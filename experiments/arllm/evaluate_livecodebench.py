"""Evaluate generated comparison outputs with the pinned LiveCodeBench checker."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Mapping

from experiments.arllm.omnimath_chunk_ablation import (
    _ablation_protocol_fingerprint,
    _atomic_json,
    _atomic_jsonl,
    build_confirm_decision,
    build_summary,
)
from experiments.shared.artifacts import load_jsonl
from inference_scaling.shared.evaluation.livecodebench import (
    LIVECODEBENCH_RELEASE,
    LIVECODEBENCH_REVISION,
    LiveCodeBenchProblem,
    OfficialLiveCodeBenchEvaluator,
    file_sha256,
    load_livecodebench_snapshot,
)


def _metadata_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _output_for_official_evaluation(record: Mapping[str, Any]) -> str:
    if not bool(record.get("evaluation_eligible", True)):
        return ""
    return str(record["output"])


def _selected_records(
    records: list[dict[str, Any]], manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    expected = {
        (str(arm), str(question_id))
        for question_id in manifest["question_ids"]
        for arm in manifest["arms"]
    }
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = str(record["arm"]), str(record["question_id"])
        if key in indexed:
            raise ValueError(f"duplicate generation record {key}")
        indexed[key] = record
    missing = expected - set(indexed)
    extra = set(indexed) - expected
    if missing or extra:
        raise ValueError(
            f"generation records do not match manifest: missing={len(missing)} "
            f"extra={len(extra)}"
        )
    return [
        indexed[(str(arm), str(question_id))]
        for question_id in manifest["question_ids"]
        for arm in manifest["arms"]
    ]


def _problem_for_record(
    record: Mapping[str, Any],
    by_id: Mapping[str, LiveCodeBenchProblem],
) -> LiveCodeBenchProblem:
    question_id = str(record["question_id"])
    try:
        problem = by_id[question_id]
    except KeyError as error:
        raise ValueError(f"question {question_id} is absent from the snapshot") from error
    if int(record["problem_index"]) != problem.index:
        raise ValueError(f"snapshot index changed for question {question_id}")
    return problem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/livecodebench_qwen38_27b_strict_think_only_is.toml"),
    )
    parser.add_argument(
        "--phase", choices=("smoke", "probe", "screen", "confirm"), required=True
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("data/livecodebench/release_v6.jsonl"),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/livecodebench/official"),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("results/livecodebench")
    )
    parser.add_argument("--tag", default="default")
    parser.add_argument("--num-processes", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument(
        "--allow-code-execution",
        action="store_true",
        help="acknowledge that untrusted model-generated Python will be executed",
    )
    args = parser.parse_args()

    if not args.allow_code_execution:
        raise PermissionError(
            "LiveCodeBench evaluation executes untrusted generated Python; rerun in "
            "an isolated worker/container with --allow-code-execution"
        )
    with args.config.open("rb") as source:
        config = tomllib.load(source)
    evaluation_config = config.get("official_evaluation", {})
    num_processes = int(
        args.num_processes
        if args.num_processes is not None
        else evaluation_config.get("num_processes", 12)
    )
    timeout = int(
        args.timeout if args.timeout is not None else evaluation_config.get("timeout", 6)
    )

    run_root = args.output_root / str(config["run"]["name"]) / args.tag
    run_dir = run_root / args.phase
    manifest_path = run_dir / "manifest.json"
    records_path = run_dir / "records.jsonl"
    if not manifest_path.is_file() or not records_path.is_file():
        raise FileNotFoundError(
            f"generation artifacts are incomplete in {run_dir}; run generation first"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective_config = manifest.get("effective", {}).get("config")
    if not isinstance(effective_config, Mapping):
        raise ValueError("generation manifest does not contain its effective config")
    if manifest["phase"] != args.phase or manifest["tag"] != args.tag:
        raise ValueError("generation manifest phase/tag does not match the request")
    if manifest["dataset"].get("release") != LIVECODEBENCH_RELEASE:
        raise ValueError("generation manifest uses a different LiveCodeBench release")
    if manifest["official_evaluator"].get("revision") != LIVECODEBENCH_REVISION:
        raise ValueError("generation manifest pins a different official evaluator")

    snapshot = args.snapshot.resolve()
    snapshot_sha256 = file_sha256(snapshot)
    if manifest["dataset"].get("snapshot_sha256") != snapshot_sha256:
        raise ValueError("dataset snapshot checksum differs from generation")
    problems = load_livecodebench_snapshot(snapshot)
    by_id = {problem.question_id: problem for problem in problems}
    records = _selected_records(load_jsonl(records_path), manifest)
    selected_problems = [_problem_for_record(record, by_id) for record in records]

    evaluator = OfficialLiveCodeBenchEvaluator(args.source_root)
    grades = evaluator.evaluate(
        selected_problems,
        [_output_for_official_evaluation(record) for record in records],
        num_processes=num_processes,
        timeout=timeout,
    )
    evaluated: list[dict[str, Any]] = []
    for record, grade in zip(records, grades, strict=True):
        preview = str(record.get("extracted_code_preview", ""))
        if preview != grade.extracted_code:
            raise RuntimeError(
                "local code extraction preview differs from the pinned official extractor"
            )
        evaluated.append(
            {
                **record,
                "evaluation_status": "completed",
                "prediction": grade.extracted_code,
                "correct": grade.correct,
                "official_test_results": list(grade.test_results),
                "official_evaluation_metadata": _metadata_value(grade.metadata),
                "official_evaluator_revision": LIVECODEBENCH_REVISION,
                "official_timeout_seconds": timeout,
                "forced_incorrect_algorithm_failure": not bool(
                    record.get("evaluation_eligible", True)
                ),
            }
        )

    evaluated_path = run_dir / "evaluated_records.jsonl"
    summary_path = run_dir / "summary.json"
    _atomic_jsonl(evaluated_path, evaluated)
    summary = build_summary(
        evaluated,
        manifest,
        bootstrap_replicates=int(effective_config["run"]["bootstrap_replicates"]),
    )
    summary["evaluation"] = {
        "dataset_release": LIVECODEBENCH_RELEASE,
        "official_evaluator_revision": LIVECODEBENCH_REVISION,
        "num_processes": num_processes,
        "timeout_seconds": timeout,
        "evaluated_records_sha256": file_sha256(evaluated_path),
    }
    _atomic_json(summary_path, summary)

    if args.phase == "screen":
        top_by_family = summary["recommended_top2_by_family"]
        if top_by_family is None:
            raise RuntimeError("screen summary did not rank both IS families")
        ratio_by_arm = {
            str(arm): float(ratio)
            for arm, ratio in manifest["ratio_by_arm"].items()
        }
        frozen = {
            "schema_version": 2,
            "target_definition": "strict-think-only-is-v1",
            "screen_manifest_fingerprint": manifest["fingerprint"],
            "screen_summary_sha256": hashlib.sha256(
                summary_path.read_bytes()
            ).hexdigest(),
            "dataset_sha256": snapshot_sha256,
            "model_fingerprint": manifest["model"]["fingerprint"],
            "ablation_protocol_fingerprint": _ablation_protocol_fingerprint(
                effective_config
            ),
            "shared_max_new_tokens": int(
                effective_config["generation"]["max_new_tokens"]
            ),
            "reasoning_boundary": manifest["reasoning_boundary"],
            "families": {
                family: {
                    "arms": list(top_by_family[family]),
                    "ratios": [
                        ratio_by_arm[arm] for arm in top_by_family[family]
                    ],
                }
                for family in ("full", "think")
            },
        }
        frozen_path = run_root / "frozen_top2.json"
        if frozen_path.is_file():
            previous = json.loads(frozen_path.read_text(encoding="utf-8"))
            if previous != frozen:
                raise ValueError("screen evaluation produced a different frozen top-2")
        else:
            _atomic_json(frozen_path, frozen)
        summary["frozen_top2"] = frozen
    elif args.phase == "confirm":
        screen_path = run_root / "screen" / "evaluated_records.jsonl"
        if not screen_path.is_file():
            raise FileNotFoundError(
                f"evaluated screen records not found at {screen_path}"
            )
        screen_records = load_jsonl(screen_path)
        ratio_by_arm = {
            str(arm): float(ratio)
            for arm, ratio in manifest["ratio_by_arm"].items()
        }
        decisions = {
            family: build_confirm_decision(
                evaluated,
                screen_records,
                {
                    arm: ratio
                    for arm, ratio in ratio_by_arm.items()
                    if arm.startswith(f"{family}-is-")
                },
            )
            for family in ("full", "think")
        }
        summary["confirm_decision_by_family"] = decisions
        summary["confirm_winner_by_family"] = {
            family: decision["winner"] for family, decision in decisions.items()
        }
    _atomic_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
