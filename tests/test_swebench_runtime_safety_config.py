from dataclasses import replace
from pathlib import Path

import pytest

from inference_scaling.swebench.config import load_experiment_config


EXAMPLE = Path(__file__).resolve().parents[1] / "configs/swebench_api.example.toml"


def test_safety_defaults_and_explicit_disable_are_fingerprinted(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE.read_text())
    default = load_experiment_config(path)
    assert default.agent.finalization_reserve_steps == 5
    assert default.agent.audit_patch_timeout_seconds == 10
    path.write_text(EXAMPLE.read_text().replace(
        "[agent]", "[agent]\nfinalization_reserve_steps = 0\naudit_patch_timeout_seconds = 0",
    ))
    disabled = load_experiment_config(path)
    assert disabled.agent.finalization_reserve_steps == 0
    assert disabled.agent.audit_patch_timeout_seconds == 0
    assert disabled.fingerprint != default.fingerprint
    assert disabled.arms == default.arms


def test_step_reserve_supports_unlimited_time_and_rejects_negative():
    experiment = load_experiment_config(EXAMPLE)
    unlimited = replace(experiment.agent, wall_time_limit_seconds=0)
    assert unlimited.finalization_reserve_steps == 5
    with pytest.raises(ValueError, match="non-negative"):
        replace(unlimited, finalization_reserve_steps=-1)
    with pytest.raises(ValueError, match="between 0 and 60"):
        replace(unlimited, audit_patch_timeout_seconds=61)
