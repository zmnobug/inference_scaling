from __future__ import annotations

from pathlib import Path

import pytest

from inference_scaling.swebench.config import (
    MINI_SWE_AGENT_COMMIT,
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
model_name = "openai/model"
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
