import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from experiments.swebench.failed30_dual import partition, prepare, summarize
from experiments.swebench.io import atomic_write_json
from inference_scaling.swebench.config import load_experiment_config


CONFIG = Path("configs/qwen38_swebench_thinking_is_failed30_unlimited.toml")
SELECTION = Path("configs/qwen38_swebench_baseline_failed30_instances.txt")
REMAINING_CONFIG = Path("configs/qwen38_swebench_thinking_is_remaining70_unlimited.toml")
REMAINING_SELECTION = Path("configs/qwen38_swebench_thinking_is_remaining70_instances.txt")


def test_partition_is_disjoint_complete_and_deterministic():
    names = SELECTION.read_text().splitlines()
    shards = partition(names)
    assert shards == partition(list(reversed(names)))
    assert len(shards["shard_a"]) == len(shards["shard_b"]) == 15
    assert not set(shards["shard_a"]) & set(shards["shard_b"])
    assert set(shards["shard_a"] + shards["shard_b"]) == set(names)
    with pytest.raises(ValueError):
        partition(names[:-1])
    with pytest.raises(ValueError):
        partition(names[:-1] + [names[0]])


def populate_run(tmp_path, config=CONFIG, selection=SELECTION, expected_count=30):
    prepare(tmp_path, config, selection, expected_count)
    experiment = load_experiment_config(config)
    arm = experiment.arms[0]
    for name, assigned in partition(selection.read_text().splitlines(), expected_count).items():
        root = tmp_path / name / experiment.run.tag
        atomic_write_json(root / "manifest.json", {
            "dataset": {"instance_ids": assigned}, "config_fingerprint": experiment.fingerprint,
            "model": {"runtime_fingerprint": name},
        })
        atomic_write_json(root / "evaluation" / "reports" / arm.tag / "seed-20260916.json", {
            "submitted_ids": assigned, "resolved_ids": assigned[:2], "error_instances": 0,
        })
        for instance_id in assigned:
            atomic_write_json(root / arm.tag / "seed-20260916" / "instances" / instance_id / "record.json", {
                "instance_id": instance_id, "seed": 20260916, "arm_tag": arm.tag,
                "arm_fingerprint": arm.fingerprint, "config_fingerprint": experiment.fingerprint,
                "runtime_fingerprint": name, "finished_at": 10, "status": "completed",
                "exit_status": "Submitted", "diagnostics": {"limits": {"agent_seconds": 2000}},
                "usage": {"elapsed_seconds": 2010, "api_seconds": 1900, "tool_seconds": 100,
                          "api_requests": 50, "tool_calls": 10, "input_tokens": 10000, "output_tokens": 1000},
            })
    return tmp_path


@pytest.fixture
def complete_run(tmp_path):
    return populate_run(tmp_path)


def test_remaining70_is_exact_complement_with_unchanged_protocol(tmp_path):
    full = set(Path("configs/qwen38_swebench_random100_instances.txt").read_text().splitlines())
    previous = set(SELECTION.read_text().splitlines())
    remaining = REMAINING_SELECTION.read_text().splitlines()
    assert len(full) == 100 and len(previous) == 30
    assert set(remaining) == full - previous
    shards = partition(remaining, 70)
    assert shards == partition(list(reversed(remaining)), 70)
    assert len(shards["shard_a"]) == len(shards["shard_b"]) == 35
    original = load_experiment_config(CONFIG)
    current = load_experiment_config(REMAINING_CONFIG)
    assert current.api == original.api
    assert current.agent == original.agent
    assert current.budget == original.budget
    assert current.arms == original.arms
    assert current.run == replace(
        original.run, tag=current.run.tag, instance_filter=current.run.instance_filter,
    )
    populate_run(tmp_path, REMAINING_CONFIG, REMAINING_SELECTION, 70)
    summary = summarize(tmp_path, REMAINING_CONFIG)
    assert (summary["instances"], summary["resolved"]) == (70, 4)
    assert summary["all"]["total_runner_seconds"] == 70 * 2010
    with (tmp_path / "case_timings.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 70


@pytest.mark.parametrize("count", [0, -2, 1])
def test_partition_rejects_invalid_counts(count):
    with pytest.raises(ValueError, match="at least 2"):
        partition([], count)


def test_empty_thinking_rerun9_preserves_parameters_and_covers_odd_partition(tmp_path):
    config = Path("configs/qwen38_swebench_thinking_is_empty9_rerun_unlimited.toml")
    selection = Path("configs/qwen38_swebench_thinking_is_empty9_instances.txt")
    names = selection.read_text().splitlines()
    assert set(names) == {
        "django__django-12325", "matplotlib__matplotlib-20826", "matplotlib__matplotlib-24637",
        "matplotlib__matplotlib-25960", "pallets__flask-5014", "pytest-dev__pytest-5787",
        "sympy__sympy-17139", "sympy__sympy-22456", "sympy__sympy-23413",
    }
    assert set(names) <= set(Path("configs/qwen38_swebench_random100_instances.txt").read_text().splitlines())
    shards = partition(names, 9)
    assert shards == partition(list(reversed(names)), 9)
    assert len(shards["shard_a"]) == 5 and len(shards["shard_b"]) == 4
    assert not set(shards["shard_a"]) & set(shards["shard_b"])
    original = load_experiment_config(CONFIG)
    current = load_experiment_config(config)
    assert current.api == original.api
    assert current.agent == original.agent
    assert current.budget == original.budget
    assert current.arms == original.arms
    assert current.run == replace(original.run, tag=current.run.tag, instance_filter=current.run.instance_filter)
    populate_run(tmp_path, config, selection, 9)
    summary = summarize(tmp_path, config)
    assert (summary["instances"], summary["resolved"]) == (9, 4)
    assert summary["all"]["total_runner_seconds"] == 9 * 2010
    with (tmp_path / "case_timings.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 9


def test_historical_assignment_without_expected_count_still_summarizes(complete_run):
    path = complete_run / "assignment.json"
    assignment = json.loads(path.read_text())
    assignment.pop("expected_count")
    atomic_write_json(path, assignment)
    assert summarize(complete_run, CONFIG)["instances"] == 30


def test_combined_summary_preserves_denominator_and_timings(complete_run):
    summary = summarize(complete_run, CONFIG)
    assert (summary["instances"], summary["resolved"]) == (30, 4)
    assert summary["failed"]["cases"] == 26
    assert summary["all"]["cases_over_30_minutes"] == 30
    assert summary["all"]["total_runner_seconds"] == 60300
    with (complete_run / "case_timings.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 30
    with pytest.raises(FileExistsError):
        prepare(complete_run, CONFIG, SELECTION)


@pytest.mark.parametrize("fault", ["missing", "runtime", "report"])
def test_summary_rejects_incomplete_or_wrong_provenance(complete_run, fault):
    record = next(complete_run.glob("shard_a/*/is_*/seed-*/instances/*/record.json"))
    if fault == "missing":
        record.unlink()
    elif fault == "runtime":
        payload = json.loads(record.read_text())
        payload["runtime_fingerprint"] = "wrong-service"
        atomic_write_json(record, payload)
    else:
        report = next(complete_run.glob("shard_a/*/evaluation/reports/*/*.json"))
        payload = json.loads(report.read_text())
        payload["submitted_ids"] = payload["submitted_ids"][:-1]
        atomic_write_json(report, payload)
    with pytest.raises(ValueError):
        summarize(complete_run, CONFIG)
    assert not (complete_run / "summary.json").exists()
