"""Run the pinned official SWE-bench evaluator for generated prediction files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from experiments.swebench.evaluation_summary import summarize_evaluations
from experiments.swebench.io import atomic_write_json


DATASET_MAPPING = {
    "verified": "princeton-nlp/SWE-Bench_Verified",
    "lite": "princeton-nlp/SWE-Bench_Lite",
    "full": "princeton-nlp/SWE-Bench",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="Profile result directory containing manifest.json")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--arm", action="append", default=[])
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--run-prefix", default="is-mh")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((args.results / "manifest.json").read_text(encoding="utf-8"))
    dataset_spec = str(manifest["dataset"]["subset"])
    snapshot = args.results / str(
        manifest["dataset"].get("local_parquet", "dataset.parquet")
    )
    if snapshot.is_file():
        dataset_name = str(snapshot.resolve())
    else:
        dataset_name = DATASET_MAPPING.get(dataset_spec, dataset_spec)
    split = str(manifest["dataset"]["split"])
    expected_instance_ids = {
        str(instance_id) for instance_id in manifest["dataset"]["instance_ids"]
    }
    allowed_arms = set(args.arm)
    allowed_seeds = set(args.seeds or manifest["seeds"])
    evaluation_root = args.results / "evaluation"
    evaluation_root.mkdir(parents=True, exist_ok=True)

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
                raise ValueError(
                    f"{predictions} must contain exactly one model name"
                )
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
