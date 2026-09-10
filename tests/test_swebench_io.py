from __future__ import annotations

import json
from pathlib import Path

from experiments.swebench.io import rebuild_predictions
from inference_scaling.swebench.config import ExperimentArm


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
