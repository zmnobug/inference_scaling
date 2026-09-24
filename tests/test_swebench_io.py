from __future__ import annotations

import json
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from experiments.swebench.io import existing_record_matches, rebuild_predictions, load_record
from experiments.swebench.run_suite import _write_result
from inference_scaling.swebench.config import (
    ExperimentArm,
    ExperimentConfig,
    instance_fingerprint,
)
from inference_scaling.swebench.runner import RESULT_SCHEMA_VERSION


def _record(path: Path, instance_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "model_name_or_path": "openai/model",
                "submission": f"patch-{instance_id}",
            }
        ),
        encoding="utf-8",
    )


def test_rebuild_predictions_excludes_records_outside_current_manifest(
    tmp_path: Path,
) -> None:
    arm = ExperimentArm(method="base", alpha=1.0, chunk_tokens=256)
    seed_root = tmp_path / arm.tag / "seed-7"
    _record(seed_root / "instances" / "current" / "record.json", "current")
    _record(seed_root / "instances" / "stale" / "record.json", "stale")

    rebuild_predictions(tmp_path, (arm,), (7,), ("current",))

    predictions = json.loads((seed_root / "preds.json").read_text(encoding="utf-8"))
    assert set(predictions) == {"current"}


def test_resume_requires_matching_runtime_fingerprint(tmp_path: Path) -> None:
    instance = {"instance_id": "instance", "problem_statement": "problem"}
    arm = ExperimentArm(method="base", alpha=1.0, chunk_tokens=256)
    experiment = cast(ExperimentConfig, SimpleNamespace(fingerprint="config"))
    path = tmp_path / "record.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "config_fingerprint": "config",
                "arm_fingerprint": arm.fingerprint,
                "instance_fingerprint": instance_fingerprint(instance),
                "runtime_fingerprint": "runtime-a",
                "seed": 7,
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )

    assert existing_record_matches(
        path,
        experiment,
        arm,
        7,
        instance,
        runtime_fingerprint="runtime-a",
    )
    assert not existing_record_matches(
        path,
        experiment,
        arm,
        7,
        instance,
        runtime_fingerprint="runtime-b",
    )
    previous = json.loads(path.read_text())
    previous["schema_version"] = "swebench-is-mh-v5"
    path.write_text(json.dumps(previous))
    assert not existing_record_matches(
        path, experiment, arm, 7, instance, runtime_fingerprint="runtime-a"
    )


def test_sampling_details_are_lossless_compressed_and_predictions_stay_lightweight(tmp_path):
    arm = ExperimentArm(method="is_thinking", chunk_tokens=100, candidate_count=4, rollout_count=2)
    directory = tmp_path / arm.tag / "seed-7" / "instances" / "case"
    details = {"protocol": "test", "requests": [{"response": {"tokens": ["token"] * 10000}}],
               "rounds": [{"ess": 2.5}], "guards": {"fallback_to_plain": False}}
    record = {"instance_id": "case", "model_name_or_path": "model", "submission": "patch",
              "diagnostics": {"thinking_is": copy.deepcopy(details), "limits": {"termination_reason": "Submitted"}},
              "trajectory": {"messages": []}}
    _write_result(directory, record)
    path = directory / "record.json"
    light = load_record(path)
    summary = light["diagnostics"]["thinking_is"]
    assert summary["request_count"] == 1 and summary["round_count"] == 1
    assert "requests" not in summary and "rounds" not in summary
    assert path.stat().st_size < 4096
    assert load_record(path, include_sampling_details=True)["diagnostics"]["thinking_is"] == details
    assert light["diagnostics"]["limits"]["termination_reason"] == "Submitted"
    rebuild_predictions(tmp_path, (arm,), (7,), ("case",))
    predictions = json.loads((tmp_path / arm.tag / "seed-7" / "preds.json").read_text())
    assert predictions["case"]["model_patch"] == "patch"
    (directory / summary["details_path"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_record(path, include_sampling_details=True)


def test_compression_failure_preserves_existing_record(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    path.write_text('{"submission": "old"}')
    record = {"diagnostics": {"thinking_is": {"requests": [], "rounds": []}}}

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("experiments.swebench.io.gzip.open", fail)
    with pytest.raises(OSError, match="disk full"):
        _write_result(tmp_path, record)
    assert json.loads(path.read_text()) == {"submission": "old"}
    assert not list(tmp_path.glob("*.tmp"))


def test_legacy_record_can_still_load_inline_details(tmp_path):
    path = tmp_path / "record.json"
    record = {"diagnostics": {"thinking_is": {"requests": [], "rounds": []}}}
    path.write_text(json.dumps(record))
    assert load_record(path, include_sampling_details=True) == record


def test_missing_sampling_details_prevent_resume(tmp_path):
    instance = {"instance_id": "case"}
    arm = ExperimentArm(method="base", chunk_tokens=64)
    experiment = cast(ExperimentConfig, SimpleNamespace(fingerprint="config"))
    record = {
        "schema_version": RESULT_SCHEMA_VERSION, "config_fingerprint": "config",
        "arm_fingerprint": arm.fingerprint, "instance_fingerprint": instance_fingerprint(instance),
        "runtime_fingerprint": "runtime", "seed": 7, "status": "completed",
        "diagnostics": {"thinking_is": {"requests": [], "rounds": []}},
    }
    _write_result(tmp_path, record)
    path = tmp_path / "record.json"
    assert existing_record_matches(path, experiment, arm, 7, instance, runtime_fingerprint="runtime")
    (tmp_path / record["diagnostics"]["thinking_is"]["details_path"]).unlink()
    assert not existing_record_matches(path, experiment, arm, 7, instance, runtime_fingerprint="runtime")
