from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from experiments.swebench.failed30_dual import prepare
from inference_scaling.swebench.config import load_experiment_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/qwen38_swebench_thinking_is_random100_v3_unlimited.toml"
SELECTION = ROOT / "configs/qwen38_swebench_random100_instances.txt"


def test_random100_v3_preserves_previous_repaired_protocol() -> None:
    previous = tomllib.loads(
        (ROOT / "configs/qwen38_swebench_thinking_is_empty9_rerun_unlimited.toml").read_text()
    )
    current = tomllib.loads(CONFIG.read_text())
    for settings in (previous, current):
        settings["run"].pop("tag")
        settings["run"].pop("instance_filter")
    assert current == previous
    experiment = load_experiment_config(CONFIG)
    assert len(experiment.arms) == 1
    assert experiment.arms[0].method == "is_thinking"
    assert experiment.arms[0].tag == "is_thinking-a1-b4-c100-r2"


def test_random100_v3_assignment_covers_fixed_hundred(tmp_path: Path) -> None:
    assert hashlib.sha256(SELECTION.read_bytes()).hexdigest() == (
        "559abe0a8499a40f0c82837f1b9cdf79ccaead21cd21555878ef1b7c5e8461eb"
    )
    output = tmp_path / "run"
    prepare(output, CONFIG, SELECTION, expected_count=100)
    assignment = json.loads((output / "assignment.json").read_text())
    first = set(assignment["shards"]["shard_a"]["instance_ids"])
    second = set(assignment["shards"]["shard_b"]["instance_ids"])
    assert len(first) == len(second) == 50
    assert not first & second
    assert first | second == set(SELECTION.read_text().splitlines())
    assert assignment["shards"]["shard_a"]["base_url"] == "http://127.0.0.1:8000/v1"
    assert assignment["shards"]["shard_b"]["base_url"] == "http://127.0.0.1:8001/v1"
