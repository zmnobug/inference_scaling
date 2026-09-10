"""Generate strict think-only comparison outputs for LiveCodeBench."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Mapping

import torch
import transformers

from experiments.arllm.omnimath_chunk_ablation import (
    _ablation_protocol_fingerprint,
    _atomic_json,
    _atomic_jsonl,
    _checkpoint_artifacts,
    _frozen_comparison_ratio_by_arm,
    _generation_protocol_fingerprint,
    _package_version,
    _preflight,
    _reasoning_boundary,
    _run_arm,
    comparison_chunk_arm,
    parse_ratios,
)
from experiments.shared.artifacts import (
    dataclass_snapshot_delta,
    implementation_hashes,
    json_fingerprint,
    load_jsonl,
)
from inference_scaling.arllm.backends import (
    BACKEND_CHOICES,
    close_backend,
    configured_backend,
    load_backend_from_config,
    set_backend_override,
)
from inference_scaling.arllm.config import SamplingConfig
from inference_scaling.shared.evaluation.livecodebench import (
    LIVECODEBENCH_DATASET,
    LIVECODEBENCH_EXPECTED_ROWS,
    LIVECODEBENCH_RELEASE,
    LIVECODEBENCH_REPOSITORY,
    LIVECODEBENCH_REVISION,
    LIVECODEBENCH_SYSTEM_PROMPT,
    LiveCodeBenchProblem,
    extract_livecodebench_code,
    file_sha256,
    livecodebench_user_prompt,
    load_livecodebench_snapshot,
    select_livecodebench_partitions,
)
from inference_scaling.shared.rng import SeedStream


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_FILES = (
    "experiments/arllm/livecodebench_think_only.py",
    "experiments/arllm/omnimath_chunk_ablation.py",
    "src/inference_scaling/arllm/algorithms/think_only.py",
    "src/inference_scaling/arllm/types.py",
    "src/inference_scaling/arllm/backends/transformers_backend.py",
    "src/inference_scaling/arllm/backends/vllm_backend.py",
    "src/inference_scaling/shared/evaluation/livecodebench.py",
)


def _prompt_tokens(
    backend: Any,
    problem: LiveCodeBenchProblem,
    config: Mapping[str, Any],
) -> tuple[int, ...]:
    prompt_config = dict(config.get("prompt", {}))
    system_prompt = str(
        prompt_config.pop("system_prompt", LIVECODEBENCH_SYSTEM_PROMPT)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": livecodebench_user_prompt(problem)},
    ]
    rendered = backend.tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        **prompt_config,
    )
    return backend.encode(str(rendered), add_special_tokens=False)


def _apply_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    set_backend_override(config, args.backend)
    if args.model is not None:
        config["models"]["base"] = args.model
    if args.device is not None:
        config["runtime"]["device"] = args.device
    if args.dtype is not None:
        config["runtime"]["dtype"] = args.dtype
        config.setdefault("vllm", {})["dtype"] = args.dtype
    if args.max_new_tokens is not None:
        config["generation"]["max_new_tokens"] = args.max_new_tokens
    if args.candidate_count is not None:
        config["conditional_is"]["candidate_count"] = args.candidate_count
    if args.rollout_count is not None:
        config["conditional_is"]["rollout_count"] = args.rollout_count
    if args.ratios is not None:
        config["conditional_is"]["chunk_ratios"] = list(
            parse_ratios(args.ratios)
        )


def _load_closure_gate(
    path: Path,
    *,
    dataset_sha256: str,
    model_fingerprint: str,
    generation_protocol_fingerprint: str,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"reasoning closure gate not found at {path}; run --phase probe first"
        )
    gate = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "dataset_sha256": dataset_sha256,
        "model_fingerprint": model_fingerprint,
        "generation_protocol_fingerprint": generation_protocol_fingerprint,
    }
    for field, value in expected.items():
        if gate.get(field) != value:
            raise ValueError(f"reasoning closure gate has a different {field}")
    if not gate.get("reasoning_closure_gate_passed", False):
        raise ValueError("probe reasoning closure gate did not pass")
    return gate


def _generation_summary(
    records: list[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in manifest["arms"]:
        values = [record for record in records if record["arm"] == arm]
        arms[arm] = {
            "examples": len(values),
            "mean_output_tokens": statistics.fmean(
                int(record["output_tokens"]) for record in values
            ),
            "reasoning_closure_rate": statistics.fmean(
                bool(record["diagnostics"].get("reasoning_complete", False))
                for record in values
            ),
            "length_truncation_rate": statistics.fmean(
                bool(record["length_truncated"]) for record in values
            ),
            "sum_example_seconds": sum(
                float(record["elapsed_seconds"]) for record in values
            ),
        }
    return {
        "schema_version": 1,
        "manifest_fingerprint": manifest["fingerprint"],
        "phase": manifest["phase"],
        "evaluation_status": "pending_official_code_execution",
        "arms": arms,
    }


def _partition_rows(
    problems: tuple[LiveCodeBenchProblem, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "problem_index": problem.index,
            "question_id": problem.question_id,
            "question_sha256": hashlib.sha256(
                problem.question_content.encode("utf-8")
            ).hexdigest(),
            "platform": problem.platform,
            "difficulty": problem.difficulty,
            "contest_id": problem.contest_id,
            "contest_date": problem.contest_date,
            "has_starter_code": bool(problem.starter_code),
        }
        for problem in problems
    ]


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
        "--output-root", type=Path, default=Path("results/livecodebench")
    )
    parser.add_argument("--tag", default="default")
    parser.add_argument("--closure-gate", type=Path)
    parser.add_argument("--frozen-top2", type=Path)
    parser.add_argument("--backend", choices=BACKEND_CHOICES)
    parser.add_argument("--model")
    parser.add_argument("--device")
    parser.add_argument("--dtype")
    parser.add_argument("--ratios", help="comma-separated chunk ratios")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-new-tokens", type=int)
    parser.add_argument("--candidate-count", type=int)
    parser.add_argument("--rollout-count", type=int)
    args = parser.parse_args()

    if args.limit is not None and (args.limit <= 0 or args.phase != "smoke"):
        raise ValueError("--limit must be positive and is only valid for smoke")
    with args.config.open("rb") as source:
        config = tomllib.load(source)
    _apply_overrides(config, args)
    if int(config["generation"]["max_new_tokens"]) != 1024:
        raise ValueError("strict think-only LiveCodeBench v1 fixes total output at 1024")
    if not bool(config.get("reasoning", {}).get("enabled", False)):
        raise ValueError("strict think-only comparison requires reasoning.enabled=true")
    if str(config["conditional_is"]["reward"]) != "sequence_log_probability":
        raise ValueError("this experiment requires sequence_log_probability reward")
    if (
        config["sampling"].get("top_p", 1.0) != 1.0
        or config["sampling"].get("top_k") is not None
    ):
        raise ValueError("exact on-policy IS requires top_p=1 and no top_k")
    if (
        str(config["runtime"].get("device", "cuda")).startswith("cuda")
        and not torch.cuda.is_available()
    ):
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")

    ratios = tuple(float(value) for value in config["conditional_is"]["chunk_ratios"])
    parse_ratios(",".join(str(value) for value in ratios))
    snapshot = args.snapshot.resolve()
    dataset_sha256 = file_sha256(snapshot)
    all_problems = load_livecodebench_snapshot(snapshot)
    partition_config = config["partitions"]
    partitions = select_livecodebench_partitions(
        all_problems,
        seed=int(config["run"]["dataset_seed"]),
        probe_count=int(partition_config["probe_count"]),
        screen_count=int(partition_config["screen_count"]),
        confirm_count=int(partition_config["confirm_count"]),
    )
    problems = (
        partitions["screen"][: args.limit or 1]
        if args.phase == "smoke"
        else partitions[args.phase]
    )

    model_artifacts = _checkpoint_artifacts(str(config["models"]["base"]))
    model_fingerprint = json_fingerprint(model_artifacts)
    run_root = args.output_root / str(config["run"]["name"]) / args.tag
    if args.phase in {"screen", "confirm"}:
        _load_closure_gate(
            args.closure_gate or (run_root / "reasoning_closure_gate.json"),
            dataset_sha256=dataset_sha256,
            model_fingerprint=model_fingerprint,
            generation_protocol_fingerprint=_generation_protocol_fingerprint(config),
        )

    frozen: dict[str, Any] | None = None
    if args.phase == "confirm":
        frozen_path = args.frozen_top2 or (run_root / "frozen_top2.json")
        if not frozen_path.is_file():
            raise FileNotFoundError(
                f"frozen top-2 artifact not found at {frozen_path}; evaluate screen first"
            )
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        if frozen.get("dataset_sha256") != dataset_sha256:
            raise ValueError("frozen top-2 belongs to a different dataset snapshot")
        if frozen.get("model_fingerprint") != model_fingerprint:
            raise ValueError("frozen top-2 belongs to a different model checkpoint")
        if frozen.get("ablation_protocol_fingerprint") != _ablation_protocol_fingerprint(
            config
        ):
            raise ValueError("frozen top-2 belongs to a different IS protocol")
        if frozen.get("target_definition") != "strict-think-only-is-v1":
            raise ValueError("frozen comparison artifact has the wrong target")
        if args.ratios is not None:
            raise ValueError("--ratios cannot override frozen confirm arms")
        ratio_by_arm = _frozen_comparison_ratio_by_arm(frozen)
        arms = ("base", *ratio_by_arm)
    elif args.phase == "probe":
        ratio_by_arm = {}
        arms = ("base",)
    else:
        ratio_by_arm = {
            comparison_chunk_arm(family, ratio): ratio
            for family in ("full", "think")
            for ratio in ratios
        }
        arms = ("base", *ratio_by_arm)

    run_dir = run_root / args.phase
    run_dir.mkdir(parents=True, exist_ok=True)
    records_path = run_dir / "records.jsonl"
    manifest_path = run_dir / "manifest.json"
    generation_summary_path = run_dir / "generation_summary.json"
    _atomic_jsonl(run_root / f"dataset_{args.phase}.jsonl", _partition_rows(problems))

    effective = {
        "config": config,
        "phase": args.phase,
        "tag": args.tag,
        "arms": arms,
        "ratio_by_arm": ratio_by_arm,
        "question_ids": [problem.question_id for problem in problems],
        "dataset_sha256": dataset_sha256,
        "model_artifacts": model_artifacts,
        "implementation_sha256": implementation_hashes(
            REPOSITORY_ROOT, entrypoints=IMPLEMENTATION_FILES
        ),
    }
    fingerprint = json_fingerprint(effective)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "phase": args.phase,
        "tag": args.tag,
        "seed": int(config["run"]["seed"]),
        "dataset_seed": int(config["run"]["dataset_seed"]),
        "arms": list(arms),
        "ratios": list(ratios),
        "ratio_by_arm": ratio_by_arm,
        "question_ids": [problem.question_id for problem in problems],
        "dataset": {
            "repository": LIVECODEBENCH_DATASET,
            "release": LIVECODEBENCH_RELEASE,
            "expected_rows": LIVECODEBENCH_EXPECTED_ROWS,
            "snapshot": str(snapshot),
            "snapshot_sha256": dataset_sha256,
        },
        "official_evaluator": {
            "repository": LIVECODEBENCH_REPOSITORY,
            "revision": LIVECODEBENCH_REVISION,
        },
        "model": {
            "configured_source": config["models"].get("base_source"),
            "configured_revision": config["models"].get("base_revision"),
            "artifacts": model_artifacts,
            "fingerprint": model_fingerprint,
        },
        "effective": effective,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "backend": configured_backend(config),
            "vllm": (
                _package_version("vllm")
                if configured_backend(config).startswith("vllm")
                else None
            ),
        },
    }
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["fingerprint"] != fingerprint:
            raise ValueError(
                f"{run_dir} contains a different experiment; choose a new --tag"
            )
        manifest = previous
    elif records_path.is_file():
        raise ValueError(f"{run_dir} contains records without a manifest")
    else:
        _atomic_json(manifest_path, manifest)

    existing = load_jsonl(records_path)
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for record in existing:
        key = str(record["arm"]), int(record["problem_index"])
        if key in indexed:
            raise ValueError(f"duplicate completed record {key}")
        indexed[key] = record
    pending = [
        (problem, arm)
        for problem in problems
        for arm in arms
        if (arm, problem.index) not in indexed
    ]

    backend = None
    try:
        if pending:
            backend = load_backend_from_config(str(config["models"]["base"]), config)
            manifest["model"]["parameter_count"] = int(backend.parameter_count)
            first_prompt = _prompt_tokens(backend, problems[0], config)
            boundary = _reasoning_boundary(backend, first_prompt, config)
            if frozen is not None:
                stable_fields = (
                    "start_token_ids",
                    "end_token_id",
                    "model_eos_token_id",
                    "shared_max_new_tokens",
                )
                if any(
                    frozen.get("reasoning_boundary", {}).get(field)
                    != boundary[field]
                    for field in stable_fields
                ):
                    raise ValueError(
                        "frozen reasoning boundary differs from the active model"
                    )
            manifest["reasoning_boundary"] = boundary
            reasoning_end_token_id = int(boundary["end_token_id"])
            sampling = SamplingConfig(
                temperature=float(config["sampling"]["temperature"]),
                top_p=float(config["sampling"].get("top_p", 1.0)),
                eos_token_id=backend.tokenizer.eos_token_id,
            )
            manifest["preflight"] = _preflight(
                backend,
                first_prompt,
                sampling,
                config,
                request_namespace="livecodebench",
            )
            _atomic_json(manifest_path, manifest)

            with records_path.open("a", encoding="utf-8", buffering=1) as sink:
                for ordinal, (problem, arm) in enumerate(pending, start=1):
                    prompt = _prompt_tokens(backend, problem, config)
                    problem_seed = SeedStream(int(config["run"]["seed"])).derive(
                        "livecodebench", problem.question_id
                    )
                    before = backend.snapshot()
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                    started = time.perf_counter()
                    tokens, diagnostics = _run_arm(
                        arm,
                        backend,
                        prompt,
                        problem_seed,
                        config,
                        ratio_by_arm,
                        reasoning_end_token_id,
                        request_namespace="livecodebench",
                    )
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                    elapsed = time.perf_counter() - started
                    after = backend.snapshot()
                    output = backend.decode(tokens)
                    evaluation_eligible = not (
                        arm.startswith("think-is-")
                        and diagnostics.get("failure_reason") is not None
                    )
                    eos_token_id = backend.tokenizer.eos_token_id
                    ended_with_eos = bool(
                        eos_token_id is not None and eos_token_id in tokens
                    )
                    record = {
                        "schema_version": 1,
                        "evaluation_status": "pending",
                        "phase": args.phase,
                        "tag": args.tag,
                        "arm": arm,
                        "problem_index": problem.index,
                        "question_id": problem.question_id,
                        "problem_id": problem.question_id,
                        "problem_seed": problem_seed,
                        "question_sha256": hashlib.sha256(
                            problem.question_content.encode("utf-8")
                        ).hexdigest(),
                        "platform": problem.platform,
                        "difficulty": problem.difficulty,
                        "contest_date": problem.contest_date,
                        "output": output,
                        "evaluation_eligible": evaluation_eligible,
                        "extracted_code_preview": (
                            extract_livecodebench_code(output)
                            if evaluation_eligible
                            else ""
                        ),
                        "prompt_tokens": len(prompt),
                        "output_tokens": len(tokens),
                        "ended_with_eos": ended_with_eos,
                        "length_truncated": bool(
                            len(tokens) >= int(config["generation"]["max_new_tokens"])
                            and not ended_with_eos
                        ),
                        "elapsed_seconds": elapsed,
                        "backend_delta": dataclass_snapshot_delta(before, after),
                        "diagnostics": diagnostics,
                    }
                    sink.write(
                        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    print(
                        f"[{ordinal}/{len(pending)}] phase={args.phase} arm={arm} "
                        f"question={problem.question_id} tokens={len(tokens)} "
                        f"seconds={elapsed:.3f}",
                        flush=True,
                    )
        else:
            print(
                f"all {len(existing)} generation records already complete; rebuilding summary"
            )
    finally:
        close_backend(backend)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    records = load_jsonl(records_path)
    selected_keys = {(arm, problem.index) for problem in problems for arm in arms}
    selected = [
        record
        for record in records
        if (str(record["arm"]), int(record["problem_index"])) in selected_keys
    ]
    expected_records = len(problems) * len(arms)
    if len(selected) != expected_records:
        raise RuntimeError(f"expected {expected_records} records, found {len(selected)}")
    generation_summary = _generation_summary(selected, manifest)
    _atomic_json(generation_summary_path, generation_summary)

    if args.phase == "probe":
        closed = sum(
            bool(record["diagnostics"].get("reasoning_complete"))
            for record in selected
        )
        required = int(config["reasoning"].get("closure_gate_min_count", 7))
        if not 0 < required <= len(selected):
            raise ValueError(
                "reasoning.closure_gate_min_count must be within the probe size"
            )
        gate = {
            "schema_version": 1,
            "probe_manifest_fingerprint": fingerprint,
            "dataset_sha256": dataset_sha256,
            "model_fingerprint": model_fingerprint,
            "generation_protocol_fingerprint": _generation_protocol_fingerprint(
                config
            ),
            "reasoning_closure_count": closed,
            "reasoning_closure_total": len(selected),
            "reasoning_closure_required": required,
            "reasoning_closure_gate_passed": closed >= required,
        }
        _atomic_json(run_root / "reasoning_closure_gate.json", gate)
        generation_summary["reasoning_closure_gate"] = gate
        _atomic_json(generation_summary_path, generation_summary)
    print(json.dumps(generation_summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
