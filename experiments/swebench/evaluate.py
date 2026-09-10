"""Run the pinned official SWE-bench evaluator for generated prediction files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiments.swebench.dataset import (
    sha256_file,
    sha256_rows,
    validate_evaluator_instances,
)
from experiments.swebench.evaluation_summary import summarize_evaluations
from experiments.swebench.io import atomic_write_json


def _load_parquet_rows(path: Path) -> list[dict[str, Any]]:
    from datasets import load_dataset  # type: ignore[import-untyped]

    return [
        dict(instance)
        for instance in load_dataset(
            "parquet", data_files=str(path.resolve()), split="train"
        )
    ]


def prepare_evaluation_dataset(
    *,
    snapshot: Path,
    source_revision: str,
    expected_instance_ids: set[str],
) -> tuple[Path, dict[str, Any]]:
    """Validate and describe the immutable dataset used during inference."""

    source_rows = _load_parquet_rows(snapshot)
    validate_evaluator_instances(source_rows, expected_instance_ids)
    return snapshot, {
        "mode": "native_swebench_5_dataset",
        "path": str(snapshot.resolve()),
        "revision": source_revision,
        "sha256": sha256_file(snapshot),
        "rows_sha256": sha256_rows(source_rows),
        "instance_count": len(source_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Result directory containing manifest.json",
    )
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--arm", action="append", default=[])
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--run-prefix", default="inference-scaling")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((args.results / "manifest.json").read_text(encoding="utf-8"))
    snapshot = args.results / str(
        manifest["dataset"].get("local_parquet", "dataset.parquet")
    )
    split = str(manifest["dataset"]["split"])
    expected_instance_ids = {
        str(instance_id) for instance_id in manifest["dataset"]["instance_ids"]
    }
    allowed_arms = set(args.arm)
    allowed_seeds = set(args.seeds or manifest["seeds"])
    evaluation_root = args.results / "evaluation"
    evaluation_root.mkdir(parents=True, exist_ok=True)
    if not snapshot.is_file():
        raise FileNotFoundError(
            f"inference dataset snapshot is required for evaluation: {snapshot}"
        )
    evaluation_snapshot, dataset_provenance = prepare_evaluation_dataset(
        snapshot=snapshot,
        source_revision=str(manifest["dataset"].get("revision", "")),
        expected_instance_ids=expected_instance_ids,
    )
    dataset_name = str(evaluation_snapshot.resolve())
    atomic_write_json(
        evaluation_root / "dataset_provenance.json",
        dataset_provenance,
    )

    jobs = []
    for arm in manifest["arms"]:
        arm_tag = str(arm["tag"])
        if allowed_arms and arm_tag not in allowed_arms:
            continue
        for seed in manifest["seeds"]:
            if int(seed) not in allowed_seeds:
                continue
            predictions = args.results / arm_tag / f"seed-{seed}" / "preds.json"
            if not predictions.is_file():
                raise FileNotFoundError(predictions)
            prediction_payload = json.loads(predictions.read_text(encoding="utf-8"))
            instance_ids = list(prediction_payload)
            if set(instance_ids) != expected_instance_ids:
                missing = sorted(expected_instance_ids - set(instance_ids))
                unexpected = sorted(set(instance_ids) - expected_instance_ids)
                raise ValueError(
                    f"{predictions} does not match manifest instance IDs; "
                    f"missing={missing}, unexpected={unexpected}"
                )
            model_names = {
                str(prediction["model_name_or_path"])
                for prediction in prediction_payload.values()
            }
            if len(model_names) != 1:
                raise ValueError(f"{predictions} must contain exactly one model name")
            model_slug = next(iter(model_names)).replace("/", "__")
            run_id = f"{args.run_prefix}-{arm_tag}-seed{seed}"
            report_path = evaluation_root / f"{model_slug}.{run_id}.json"
            normalized_report = (
                evaluation_root / "reports" / arm_tag / f"seed-{seed}.json"
            )
            command = [
                sys.executable,
                "-m",
                "swebench.harness.run_evaluation",
                "--dataset_name",
                dataset_name,
                "--split",
                split,
                "--predictions_path",
                str(predictions.resolve()),
                "--max_workers",
                str(args.max_workers),
                "--run_id",
                run_id,
                "--instance_ids",
                *instance_ids,
            ]
            jobs.append((run_id, command, report_path, normalized_report))

    for run_id, command, report_path, normalized_report in jobs:
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "command": command,
                    "report": str(normalized_report),
                }
            )
        )
        if not args.dry_run:
            subprocess.run(command, cwd=evaluation_root, check=True)
            if not report_path.is_file():
                raise FileNotFoundError(
                    f"official evaluator did not create expected report {report_path}"
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if set(report.get("submitted_ids", ())) != set(instance_ids):
                raise ValueError(f"evaluator report {report_path} has different IDs")
            atomic_write_json(normalized_report, report)

    if not args.dry_run:
        atomic_write_json(
            args.results / "evaluation_summary.json",
            summarize_evaluations(args.results),
        )


if __name__ == "__main__":
    main()
