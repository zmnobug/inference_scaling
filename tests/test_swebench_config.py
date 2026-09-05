from __future__ import annotations

from pathlib import Path

import pytest

from inference_scaling.swebench.config import (
    MINI_SWE_AGENT_COMMIT,
    build_experiment_arms,
    load_experiment_config,
)


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
model_name = "openai/qwen3.8-27b"
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

[conditional_is]
alphas = [1.0, 1.5]
candidate_counts = [2, 4]
chunk_tokens = [128, 256]
rollout_counts = [1, 2]
reference_alpha = 1.5
reference_candidate_count = 4
reference_chunk_tokens = 256
reference_rollout_count = 2

[mh]
alphas = [1.0, 1.5]
updates_per_chain = [1, 4]
max_suffix_actions = [1, "all"]
suffix_schedules = ["full", "multiscale"]
chains = [1, 2]
reference_alpha = 1.5
reference_updates_per_chain = 4
reference_max_suffix_actions = "all"
reference_suffix_schedule = "multiscale"
reference_chains = 1
chunk_tokens = 256

[shortlist]
is_alpha = 1.5
is_candidate_count = 2
is_chunk_tokens = 256
is_rollout_count = 1
mh_alpha = 1.5
mh_updates_per_chain = 4
mh_max_suffix_actions = 1
mh_suffix_schedule = "multiscale"
mh_chains = 1
"""


def _write_config(tmp_path: Path, content: str = CONFIG) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_config_and_builds_registered_profiles(tmp_path: Path) -> None:
    config = load_experiment_config(_write_config(tmp_path))
    assert config.run.seeds == (7,)
    assert config.agent.max_trajectory_output_tokens == 8192
    assert config.run.dataset_revision == "dataset-commit"
    assert config.mh.max_suffix_actions == (1, None)
    assert [arm.method for arm in build_experiment_arms(config, "smoke")] == [
        "base",
        "is",
        "is",
        "mh",
        "mh",
    ]
    screen = build_experiment_arms(config, "screen")
    assert len({arm.fingerprint for arm in screen}) == len(screen)
    assert {arm.method for arm in screen} == {"base", "is", "mh"}


def test_production_stage_arm_counts() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "swebench_qwen38_27b_api.toml"
    )
    config = load_experiment_config(path)
    assert config.run.instance_plan_seed == 20260901
    assert config.api.logprob_mode == "visible_tokens"
    assert config.agent.max_trajectory_output_tokens == 8192
    assert config.conditional_is.chunk_tokens == (410, 819, 1229)
    assert config.conditional_is.chunk_tokens == tuple(
        round(config.agent.max_trajectory_output_tokens * fraction)
        for fraction in (0.05, 0.10, 0.15)
    )
    assert config.conditional_is.reference_chunk_tokens == round(
        config.agent.max_trajectory_output_tokens * 0.10
    )
    assert config.mh.chunk_tokens == config.conditional_is.reference_chunk_tokens
    expected = {
        "smoke": 5,
        "calibrate": 13,
        "stress": 10,
        "screen": 7,
        "seed_check": 3,
        "confirm": 3,
        "ofat": 28,
    }
    assert {
        profile: len(build_experiment_arms(config, profile))
        for profile in expected
    } == expected


def test_rejects_non_on_policy_sampling(tmp_path: Path) -> None:
    path = _write_config(tmp_path, CONFIG.replace("temperature = 1.0", "temperature = 0.7"))
    with pytest.raises(ValueError, match="temperature=1"):
        load_experiment_config(path)


def test_api_runtime_requires_environment_secrets(tmp_path: Path) -> None:
    config = load_experiment_config(_write_config(tmp_path))
    with pytest.raises(ValueError, match="QWEN_API_BASE"):
        config.api.resolve_runtime({})
    runtime = config.api.resolve_runtime(
        {"QWEN_API_BASE": "http://model/v1", "QWEN_API_KEY": "secret"}
    )
    assert runtime["base_url"] == "http://model/v1"
    assert runtime["api_key"] == "secret"


def test_rejects_unpinned_dataset(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, CONFIG.replace('dataset_revision = "dataset-commit"', 'dataset_revision = ""')
    )
    with pytest.raises(ValueError, match="dataset_revision"):
        load_experiment_config(path)


def test_rejects_chunk_larger_than_trajectory_limit(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        CONFIG.replace(
            "max_trajectory_output_tokens = 8192",
            "max_trajectory_output_tokens = 128",
        ).replace("chunk_tokens = [128, 256]", "chunk_tokens = [256]")
    )
    with pytest.raises(ValueError, match="at least every.*chunk_tokens"):
        load_experiment_config(path)
