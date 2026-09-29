from __future__ import annotations

import json
import os
import signal
import subprocess

import pytest

from experiments.swebench import split_running_pilot20 as split
from experiments.swebench.io import atomic_write_json
from inference_scaling.swebench.config import load_experiment_config


def test_process_handle_can_signal_child_even_without_python_wrappers():
    process = subprocess.Popen(["sleep", "30"])
    descriptor = split.open_process_handle(process.pid)
    try:
        split.signal_process_handle(descriptor, signal.SIGSTOP)
        _, status = os.waitpid(process.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status)
        split.signal_process_handle(descriptor, signal.SIGCONT)
        split.signal_process_handle(descriptor, signal.SIGTERM)
        assert process.wait(timeout=5) == -signal.SIGTERM
    finally:
        os.close(descriptor)
        process.kill()
        process.wait()


def test_stop_original_queue_uses_compatible_systemctl_option(monkeypatch):
    calls = []
    monkeypatch.setattr(split.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    split.stop_original_queue()
    assert calls == [(["systemctl", "--user", "kill", "--kill-who=all", "--signal=SIGKILL", split.UNIT], {"check": True})]


def test_fixed_partition_rejects_overlap_and_changed_selection():
    instances = [f"case-{number:02}" for number in range(20)]
    split.validate_partition(instances, instances[10:])
    with pytest.raises(ValueError):
        split.validate_partition(instances, instances[9:19])
    with pytest.raises(ValueError):
        split.validate_partition(instances[:19] + instances[:1], instances[10:])


def test_boundary_only_triggers_on_atomic_record_commit(tmp_path):
    watcher = split.CaseBoundaryWatch(tmp_path)
    try:
        atomic_write_json(tmp_path / "trajectory.json", {"partial": True})
        assert not watcher.committed(0.1)
        (tmp_path / "record.json.tmp").write_text("{}")
        assert not watcher.committed(0.1)
        (tmp_path / "record.json.tmp").replace(tmp_path / "record.json")
        assert watcher.committed(0.1)
    finally:
        watcher.close()


@pytest.fixture
def shards(tmp_path, monkeypatch):
    all_ids = [f"case-{number:02}" for number in range(20)]
    config = load_experiment_config(split.CONFIG)
    original, replica = tmp_path / "original", tmp_path / "replica"
    for directory, ids, fingerprint in (
        (original, all_ids, "original-runtime"),
        (replica, all_ids[10:], "replica-runtime"),
    ):
        atomic_write_json(directory / "manifest.json", {
            "dataset": {"instance_ids": ids},
            "config_fingerprint": config.fingerprint,
            "model": {"runtime_fingerprint": fingerprint},
        })
        owned = all_ids[:10] if directory == original else all_ids[10:]
        for instance_id in owned:
            atomic_write_json(directory / split.RELATIVE_INSTANCES / instance_id / "record.json", {
                "instance_id": instance_id, "seed": split.SEED, "arm_tag": split.ARM,
                "config_fingerprint": config.fingerprint, "runtime_fingerprint": fingerprint,
                "finished_at": 1, "status": "error", "model_name_or_path": "model",
                "submission": "", "usage": {},
            })
    (original / "dataset.parquet").write_bytes(b"fixture")
    monkeypatch.setattr(split, "summarize_results", lambda root: {"fixture": True})
    return original, replica, tmp_path / "merged", all_ids


def test_merge_preserves_error_records_and_per_service_provenance(shards):
    original, replica, destination, all_ids = shards
    split.merge_shards(*shards)
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["aggregation_only"] is True
    assert manifest["model"]["runtime_fingerprint"] is None
    assert len(manifest["execution_shards"]) == 2
    predictions = json.loads((destination / split.ARM / f"seed-{split.SEED}" / "preds.json").read_text())
    assert set(predictions) == set(all_ids)
    for source, instance_id in ((original, all_ids[0]), (replica, all_ids[-1])):
        relative = split.RELATIVE_INSTANCES / instance_id / "record.json"
        assert (destination / relative).read_bytes() == (source / relative).read_bytes()


@pytest.mark.parametrize("problem", ["overlap", "missing", "runtime"])
def test_merge_refuses_invalid_shards_before_writing(shards, problem):
    original, replica, destination, all_ids = shards
    if problem == "overlap":
        atomic_write_json(original / split.RELATIVE_INSTANCES / all_ids[-1] / "record.json", {})
    elif problem == "missing":
        (replica / split.RELATIVE_INSTANCES / all_ids[-1] / "record.json").unlink()
    else:
        path = replica / split.RELATIVE_INSTANCES / all_ids[-1] / "record.json"
        record = json.loads(path.read_text())
        record["runtime_fingerprint"] = "wrong-service"
        atomic_write_json(path, record)
    with pytest.raises(ValueError):
        split.merge_shards(*shards)
    assert not destination.exists()
    assert not destination.with_suffix(".tmp").exists()
