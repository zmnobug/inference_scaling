from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from experiments.swebench.io import existing_record_matches, rebuild_predictions
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
