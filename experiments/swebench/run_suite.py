"""Run a resumable, explicitly configured Base/IS/MH SWE-bench matrix."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

from experiments.swebench.dataset import (
    resolve_dataset_name,
    validate_evaluator_instances,
)
from experiments.swebench.io import (
    atomic_write_json,
    build_manifest,
    existing_record_matches,
    rebuild_predictions,
    result_directory,
)
from inference_scaling.swebench.config import (
    ExperimentArm,
    load_experiment_config,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _slice_instances(
    instances: list[dict[str, Any]], spec: str
) -> list[dict[str, Any]]:
    if not spec:
        return instances
    values = [int(value) if value else None for value in spec.split(":")]
    if len(values) > 3:
        raise ValueError("instance slice must use Python start:stop:step syntax")
    return instances[slice(*values)]


def _load_instances(subset: str, split: str, revision: str) -> list[dict[str, Any]]:
    from datasets import load_dataset  # type: ignore[import-untyped]

    dataset_name = resolve_dataset_name(subset)
    return [
        dict(instance)
        for instance in load_dataset(dataset_name, split=split, revision=revision)
    ]


def _write_dataset_snapshot(path: Path, instances: list[dict[str, Any]]) -> None:
    from datasets import Dataset

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    Dataset.from_list(instances).to_parquet(temporary)
    temporary.replace(path)


def _select_instances(
    instances: list[dict[str, Any]],
    *,
    filter_spec: str,
    slice_spec: str,
    instance_file: Path | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = sorted(instances, key=lambda item: str(item["instance_id"]))
    if filter_spec:
        expression = re.compile(filter_spec)
        selected = [
            item for item in selected if expression.match(str(item["instance_id"]))
        ]
    if instance_file is not None:
        requested = {
            line.strip()
            for line in instance_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        available = {str(item["instance_id"]) for item in selected}
        missing = requested - available
        if missing:
            raise ValueError(f"instance file contains unknown IDs: {sorted(missing)}")
        selected = [item for item in selected if str(item["instance_id"]) in requested]
    selected = _slice_instances(selected, slice_spec)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("instance selection is empty")
    return selected


def _select_arms(
    arms: Sequence[ExperimentArm], specs: Sequence[str]
) -> tuple[ExperimentArm, ...]:
    if not specs:
        return tuple(arms)
    requested = set(specs)
    selected = tuple(
        arm for arm in arms if arm.tag in requested or arm.method in requested
    )
    matched = {
        spec for spec in requested if any(spec in {arm.tag, arm.method} for arm in arms)
    }
    missing = requested - matched
    if missing:
        raise ValueError(f"unknown arm filters: {sorted(missing)}")
    return selected


def _select_incomplete_instance_batch(
    instances: Sequence[dict[str, Any]],
    *,
    batch_size: int,
    is_complete: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for instance in instances:
        if not is_complete(instance):
            selected.append(instance)
        if len(selected) == batch_size:
            break
    return selected


def _write_result(directory: Path, record: dict[str, Any]) -> None:
    trajectory = record.pop("trajectory", None)
    if trajectory is not None:
        atomic_write_json(directory / "trajectory.json", trajectory)
        record["trajectory_path"] = "trajectory.json"
    atomic_write_json(directory / "record.json", record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--filter")
    parser.add_argument("--slice")
    parser.add_argument("--instance-file", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument(
        "--batch-instances",
        type=int,
        metavar="N",
        help=(
            "run every configured arm and seed for the first N instances with "
            "incomplete records; repeat the same command to advance"
        ),
    )
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--arm", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--redo", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.batch_instances is not None and args.batch_instances <= 0:
        parser.error("--batch-instances must be positive")

    experiment = load_experiment_config(args.config)
    runtime_fingerprint: str | None = None
    if not args.dry_run:
        runtime_fingerprint = str(
            experiment.api.resolve_runtime()["fingerprint"]
        )
    arms = _select_arms(experiment.arms, args.arm)
    if any(arm.method in {"is", "mh"} for arm in arms) and (
        experiment.run.environment_class != "docker"
    ):
        raise ValueError("IS/MH arms require Docker checkpoint branching")
    seeds = tuple(args.seeds or experiment.run.seeds)
    workers = int(args.workers or experiment.run.workers)
    if workers <= 0:
        raise ValueError("workers must be positive")

    all_instances = _load_instances(
        experiment.run.subset,
        experiment.run.split,
        experiment.run.dataset_revision,
    )
    instances = _select_instances(
        all_instances,
        filter_spec=(
            args.filter if args.filter is not None else experiment.run.instance_filter
        ),
        slice_spec=(
            args.slice if args.slice is not None else experiment.run.instance_slice
        ),
        instance_file=args.instance_file,
        limit=args.limit,
    )
    validate_evaluator_instances(
        instances, {str(instance["instance_id"]) for instance in instances}
    )

    output_root = (args.output or experiment.run.output_root) / experiment.run.tag
    manifest = build_manifest(
        repository_root=REPOSITORY_ROOT,
        experiment=experiment,
        arms=arms,
        seeds=seeds,
        instances=instances,
        dataset_name=resolve_dataset_name(experiment.run.subset),
        runtime_fingerprint=runtime_fingerprint,
    )
    manifest_path = output_root / "manifest.json"
    if manifest_path.exists() and not args.redo:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        comparable_keys = ["config_fingerprint", "dataset", "arms", "seeds"]
        if runtime_fingerprint is not None:
            comparable_keys.append("model")
        if any(previous.get(key) != manifest.get(key) for key in comparable_keys):
            raise RuntimeError(
                f"existing manifest at {manifest_path} uses a different run matrix; "
                "choose a new tag or output directory"
            )
    def record_is_complete(
        instance: dict[str, Any], arm: ExperimentArm, seed: int
    ) -> bool:
        if args.redo:
            return False
        instance_id = str(instance["instance_id"])
        record_path = (
            result_directory(output_root, arm, seed, instance_id) / "record.json"
        )
        return existing_record_matches(
            record_path,
            experiment,
            arm,
            seed,
            instance,
            runtime_fingerprint=runtime_fingerprint,
        )

    if args.batch_instances is None:
        jobs = [
            (instance, arm, seed)
            for arm in arms
            for seed in seeds
            for instance in instances
        ]
    else:
        scheduled_instances = _select_incomplete_instance_batch(
            instances,
            batch_size=args.batch_instances,
            is_complete=lambda instance: all(
                record_is_complete(instance, arm, seed)
                for arm in arms
                for seed in seeds
            ),
        )
        jobs = [
            (instance, arm, seed)
            for instance in scheduled_instances
            for arm in arms
            for seed in seeds
        ]
    scheduled_instance_ids = list(
        dict.fromkeys(str(instance["instance_id"]) for instance, _, _ in jobs)
    )
    pending_jobs = sum(
        not record_is_complete(instance, arm, seed) for instance, arm, seed in jobs
    )
    print(
        json.dumps(
            {
                "output": str(output_root),
                "instances": len(instances),
                "arms": [arm.tag for arm in arms],
                "seeds": list(seeds),
                "matrix_jobs": len(instances) * len(arms) * len(seeds),
                "jobs": len(jobs),
                "pending_jobs": pending_jobs,
                "batch_instances": args.batch_instances,
                "scheduled_instance_ids": scheduled_instance_ids,
                "workers": workers,
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    if args.dry_run:
        return

    _write_dataset_snapshot(output_root / "dataset.parquet", instances)
    atomic_write_json(manifest_path, manifest)

    from inference_scaling.swebench.runner import run_experiment_arm

    print_lock = threading.Lock()

    def run_job(job) -> dict[str, Any]:
        instance, arm, seed = job
        instance_id = str(instance["instance_id"])
        directory = result_directory(output_root, arm, seed, instance_id)
        record_path = directory / "record.json"
        if not args.redo and existing_record_matches(
            record_path,
            experiment,
            arm,
            seed,
            instance,
            runtime_fingerprint=runtime_fingerprint,
        ):
            return {
                "status": "skipped",
                "arm": arm.tag,
                "instance": instance_id,
                "seed": seed,
            }
        record = run_experiment_arm(experiment, instance, arm, seed)
        _write_result(directory, record)
        return {
            "status": record["status"],
            "arm": arm.tag,
            "instance": instance_id,
            "seed": seed,
        }

    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_job, job): job for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            with print_lock:
                print(json.dumps(result, sort_keys=True), flush=True)
            if result["status"] == "error":
                failures += 1
                if args.fail_fast:
                    for pending in futures:
                        pending.cancel()
                    break

    rebuild_predictions(
        output_root,
        arms,
        seeds,
        [str(instance["instance_id"]) for instance in instances],
    )
    from experiments.swebench.summarize import summarize_results

    atomic_write_json(
        output_root / "inference_summary.json", summarize_results(output_root)
    )
    if failures:
        raise SystemExit(
            f"{failures} experiment jobs failed; inspect record.json files"
        )


if __name__ == "__main__":
    main()
