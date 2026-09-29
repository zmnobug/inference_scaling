from __future__ import annotations

from pathlib import Path
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from inference_scaling.swebench.config import (
    MINI_SWE_AGENT_COMMIT,
    ExperimentArm,
    load_experiment_config,
)


def test_disabled_guards_preserve_historical_fingerprints():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_pilot20.toml")
    experiment = replace(experiment, agent=replace(
        experiment.agent, finalization_reserve_steps=0, audit_patch_timeout_seconds=0,
    ))
    payload = asdict(experiment)
    payload["path"] = str(experiment.path)
    payload["run"]["output_root"] = str(experiment.run.output_root)
    for name in ("finalization_reserve_seconds", "finalization_reserve_steps", "audit_patch_timeout_seconds", "verification_reminder"):
        payload["agent"].pop(name)
    for arm in payload["arms"]:
        for name in ("max_steps_per_round", "max_round_seconds", "max_rollout_tokens", "fallback_to_plain"):
            arm.pop(name)
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert experiment.fingerprint == expected
    legacy_arm = payload["arms"][0]
    expected_arm = hashlib.sha256(json.dumps(legacy_arm, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert experiment.arms[0].fingerprint == expected_arm


def test_runtime_safety_defaults_are_explicit_and_fingerprinted():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_envfix_failed27.toml")
    assert experiment.agent.finalization_reserve_steps == 5
    assert experiment.agent.audit_patch_timeout_seconds == 10
    disabled = replace(experiment, agent=replace(
        experiment.agent, finalization_reserve_steps=0, audit_patch_timeout_seconds=0,
    ))
    assert experiment.fingerprint != disabled.fingerprint
    with pytest.raises(ValueError, match="non-negative"):
        replace(experiment.agent, finalization_reserve_steps=-1)


@pytest.mark.parametrize("options", [
    {"max_steps_per_round": -1}, {"max_round_seconds": float("nan")},
    {"max_rollout_tokens": 100}, {"method": "base", "fallback_to_plain": True},
])
def test_invalid_guard_config_is_rejected(options):
    settings = dict(method="is_thinking", chunk_tokens=100, candidate_count=4, rollout_count=2)
    settings.update(options)
    with pytest.raises(ValueError):
        ExperimentArm(**settings)


def test_guarded_protocol_has_explicit_identity_and_unchanged_main_limits():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_guarded_smoke.toml")
    arm = experiment.arms[0]
    assert (arm.max_steps_per_round, arm.max_round_seconds, arm.max_rollout_tokens) == (4, 60, 1024)
    assert arm.fallback_to_plain
    assert arm.tag.endswith("s4-t60-rt1024-plain")
    assert experiment.agent.finalization_reserve_seconds == 60
    assert experiment.agent.max_trajectory_output_tokens == 131072
    assert experiment.agent.context_window == 133120
    assert experiment.agent.verification_reminder
    with pytest.raises(ValueError):
        replace(experiment.agent, finalization_reserve_seconds=1800)
    with pytest.raises(ValueError):
        replace(experiment.agent, audit_patch_timeout_seconds=61)


def test_zero_case_and_ledger_time_limits_are_explicitly_unlimited():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_pilot20.toml")
    unlimited = replace(experiment.agent, wall_time_limit_seconds=0)
    assert unlimited.wall_time_limit_seconds == 0
    assert replace(experiment.budget, max_wall_seconds=0).max_wall_seconds == 0
    with pytest.raises(ValueError):
        replace(experiment.agent, wall_time_limit_seconds=-1)
    with pytest.raises(ValueError):
        replace(experiment.budget, max_wall_seconds=-1)
    with pytest.raises(ValueError):
        replace(unlimited, finalization_reserve_seconds=60)


def test_failed30_config_disables_only_case_time_budgets():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_failed30_unlimited.toml")
    original = load_experiment_config("configs/qwen38_swebench_thinking_is_pilot20.toml")
    assert experiment.agent == replace(original.agent, wall_time_limit_seconds=0)
    assert experiment.budget == replace(original.budget, max_wall_seconds=0)
    assert experiment.api == original.api
    assert experiment.arms == original.arms
    assert experiment.fingerprint != original.fingerprint
    instances = Path("configs/qwen38_swebench_baseline_failed30_instances.txt").read_text().splitlines()
    assert len(instances) == len(set(instances)) == 30
    import re
    assert all(re.fullmatch(experiment.run.instance_filter, instance) for instance in instances)
    assert not re.fullmatch(experiment.run.instance_filter, "astropy__astropy-8872")


def test_baseline_rerun2_matches_unlimited_is_protocol_except_sampling():
    import re

    baseline = load_experiment_config("configs/qwen38_swebench_baseline_unlimited_rerun2.toml")
    thinking_is = load_experiment_config("configs/qwen38_swebench_thinking_is_failed30_unlimited.toml")
    assert baseline.agent == thinking_is.agent
    assert baseline.api == thinking_is.api
    assert baseline.budget == thinking_is.budget
    assert replace(baseline.run, tag=thinking_is.run.tag, instance_filter=thinking_is.run.instance_filter) == thinking_is.run
    assert len(baseline.arms) == 1
    assert baseline.arms[0].method == "base"
    assert baseline.arms[0].chunk_tokens == baseline.agent.max_trajectory_output_tokens
    assert baseline.arms[0].candidate_count is None
    assert baseline.arms[0].rollout_count is None
    instances = Path("configs/qwen38_swebench_baseline_failed30_instances.txt").read_text().splitlines()
    assert {name for name in instances if re.fullmatch(baseline.run.instance_filter, name)} == {
        "django__django-15098", "scikit-learn__scikit-learn-14894",
    }


CONFIG = f"""
[run]
tag = "test"
output_root = "results/swebench"
subset = "verified"
split = "test"
dataset_revision = "dataset-commit"
workers = 1
seeds = [7]
miniagent_commit = "{MINI_SWE_AGENT_COMMIT}"
miniagent_config = "swebench_xml.yaml"
environment_class = "docker"

[api]
model_name = "openai/model"
deployment_id = "test-deployment-v1"
temperature = 1.0
top_p = 1.0

[agent]
step_limit = 20
cost_limit = 0
wall_time_limit_seconds = 100
action_mode = "text"
max_trajectory_output_tokens = 8192

[budget]
max_api_requests = 100
max_input_tokens = 1000
max_output_tokens = 1000
max_tool_calls = 100
max_wall_seconds = 100

[[arms]]
method = "base"
chunk_tokens = 256

[[arms]]
method = "is"
alpha = 1.5
candidate_count = 4
chunk_tokens = 256
rollout_count = 2

[[arms]]
method = "mh"
alpha = 1.5
updates_per_chain = 4
max_suffix_actions = "all"
suffix_schedule = "multiscale"
chains = 1
chunk_tokens = 256
"""


def _write_config(tmp_path: Path, content: str = CONFIG) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_explicit_base_is_and_mh_arms(tmp_path: Path) -> None:
    config = load_experiment_config(_write_config(tmp_path))

    assert config.run.seeds == (7,)
    assert config.run.dataset_revision == "dataset-commit"
    assert [arm.method for arm in config.arms] == ["base", "is", "mh"]
    assert [arm.tag for arm in config.arms] == [
        "base",
        "is-a1.5-b4-c256-r2",
        "mh-a1.5-u4-sall-dmultiscale-n1-c256",
    ]
    assert config.arms[-1].max_suffix_actions is None


def test_example_config_loads(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / "swebench_api.example.toml"
    config = load_experiment_config(path)

    assert {arm.method for arm in config.arms} == {"base", "is", "mh"}
    assert config.api.base_url_env == "OPENAI_API_BASE"
    assert config.agent.max_trajectory_output_tokens == 8192


def test_rejects_non_on_policy_sampling(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, CONFIG.replace("temperature = 1.0", "temperature = 0.7")
    )
    with pytest.raises(ValueError, match="temperature=1"):
        load_experiment_config(path)


def test_api_runtime_requires_environment_secrets(tmp_path: Path) -> None:
    config = load_experiment_config(_write_config(tmp_path))
    with pytest.raises(ValueError, match="OPENAI_API_BASE"):
        config.api.resolve_runtime({})
    runtime = config.api.resolve_runtime(
        {"OPENAI_API_BASE": "http://model/v1", "OPENAI_API_KEY": "secret"}
    )
    assert runtime["base_url"] == "http://model/v1"
    assert runtime["api_key"] == "secret"


def test_runtime_fingerprint_tracks_endpoint_but_not_api_key(tmp_path: Path) -> None:
    config = load_experiment_config(_write_config(tmp_path))
    first = config.api.resolve_runtime(
        {"OPENAI_API_BASE": "http://model/v1/", "OPENAI_API_KEY": "first"}
    )
    same = config.api.resolve_runtime(
        {"OPENAI_API_BASE": "http://model/v1", "OPENAI_API_KEY": "second"}
    )
    different = config.api.resolve_runtime(
        {"OPENAI_API_BASE": "http://other/v1", "OPENAI_API_KEY": "first"}
    )

    assert first["fingerprint"] == same["fingerprint"]
    assert first["fingerprint"] != different["fingerprint"]


def test_rejects_missing_deployment_identity(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, CONFIG.replace('deployment_id = "test-deployment-v1"\n', "")
    )
    with pytest.raises(ValueError, match="deployment_id"):
        load_experiment_config(path)


def test_rejects_structured_tool_action_mode(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, CONFIG.replace('action_mode = "text"', 'action_mode = "tool"')
    )
    with pytest.raises(ValueError, match="structured tool-call logprobs"):
        load_experiment_config(path)


def test_rejects_unpinned_dataset(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        CONFIG.replace('dataset_revision = "dataset-commit"', 'dataset_revision = ""'),
    )
    with pytest.raises(ValueError, match="dataset_revision"):
        load_experiment_config(path)


def test_rejects_chunk_larger_than_trajectory_limit(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        CONFIG.replace(
            "max_trajectory_output_tokens = 8192",
            "max_trajectory_output_tokens = 128",
        ),
    )
    with pytest.raises(ValueError, match="at least every.*chunk_tokens"):
        load_experiment_config(path)


def test_rejects_duplicate_arm_tags(tmp_path: Path) -> None:
    duplicate = (
        CONFIG
        + """

[[arms]]
method = "base"
chunk_tokens = 256
"""
    )
    with pytest.raises(ValueError, match="arm tags must be unique"):
        load_experiment_config(_write_config(tmp_path, duplicate))
