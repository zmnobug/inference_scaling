"""Run the Qwen conditional-IS chunk-ratio ablation on Omni-MATH-Rule."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import sys
import time
import tomllib
from dataclasses import asdict
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
import transformers

from experiments.shared.artifacts import (
    cached_file_sha256,
    checkpoint_metadata_hashes,
    dataclass_snapshot_delta,
    implementation_hashes,
    json_fingerprint,
    load_jsonl,
)
from experiments.shared.statistics import (
    clustered_paired_binary_difference,
    wilson_interval,
)
from inference_scaling.arllm.algorithms import run_conditional_is
from inference_scaling.arllm.backends import (
    BACKEND_CHOICES,
    ScoreCachingBackend,
    close_backend,
    configured_backend,
    load_backend_from_config,
    set_backend_override,
)
from inference_scaling.arllm.config import ConditionalISConfig, SamplingConfig
from inference_scaling.arllm.rewards import SequenceLogProbabilityReward
from inference_scaling.arllm.types import GenerationRequest, ScoreRequest, TokenSequence
from inference_scaling.shared.evaluation.omnimath import (
    OMNIMATH_RULE_DATA_FILE,
    OMNIMATH_RULE_DATA_SHA256,
    OMNIMATH_RULE_REPOSITORY,
    OMNIMATH_RULE_REVISION,
    OfficialOmniMathRuleEvaluator,
    OmniMathProblem,
    difficulty_band_from_probe,
    load_omnimath_rule,
    omnimath_prompt,
    select_omnimath_partitions,
    verify_omnimath_rule_checkout,
)
from inference_scaling.shared.metrics import importance_effective_sample_size
from inference_scaling.shared.rng import SeedStream
from inference_scaling.shared.stepwise import normalize_log_weights


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_FILES = (
    "experiments/arllm/omnimath_chunk_ablation.py",
    "src/inference_scaling/shared/evaluation/omnimath.py",
)
CHECKPOINT_HASH_CACHE = REPOSITORY_ROOT / ".cache" / "artifact_hashes"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful mathematical reasoning assistant. Think step by step and "
    "put your final answer within \\boxed{}."
)


def chunk_tokens(total_length: int, ratio: float, alignment: int) -> int:
    if total_length <= 0 or alignment <= 0:
        raise ValueError("total length and chunk alignment must be positive")
    if not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise ValueError("chunk ratio must lie in (0, 1]")
    return min(total_length, alignment * math.ceil(ratio * total_length / alignment))


def chunk_arm(ratio: float) -> str:
    return f"is-cr{round(ratio * 1000):04d}"


def parse_ratios(value: str) -> tuple[float, ...]:
    ratios = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not ratios:
        raise ValueError("at least one chunk ratio is required")
    if len(set(ratios)) != len(ratios):
        raise ValueError("chunk ratios must be unique")
    for ratio in ratios:
        if not math.isfinite(ratio) or not 0 < ratio <= 1:
            raise ValueError("chunk ratios must lie in (0, 1]")
    if len({chunk_arm(ratio) for ratio in ratios}) != len(ratios):
        raise ValueError("chunk ratios produce duplicate arm labels")
    return ratios


def parse_difficulty_band(value: str) -> tuple[float, float]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("difficulty band must use LOWER:UPPER")
    lower, upper = (float(item) for item in parts)
    if not 0 <= lower <= upper <= 10:
        raise ValueError("difficulty band must be ordered inside [0, 10]")
    return lower, upper


def _generation_protocol_fingerprint(config: Mapping[str, Any]) -> str:
    return json_fingerprint(
        {
            "prompt": config.get("prompt", {}),
            "generation": config["generation"],
            "sampling": config["sampling"],
        }
    )


def _ablation_protocol_fingerprint(config: Mapping[str, Any]) -> str:
    conditional = dict(config["conditional_is"])
    conditional.pop("chunk_ratios", None)
    return json_fingerprint(
        {
            "generation_protocol": _generation_protocol_fingerprint(config),
            "conditional_is_fixed_parameters": conditional,
        }
    )


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as sink:
        for row in rows:
            sink.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _checkpoint_artifacts(model_path: str) -> dict[str, Any]:
    directory = Path(model_path).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(
            f"model path must be a local checkpoint directory; use --model: {directory}"
        )
    weights = sorted(directory.glob("*.safetensors"))
    if not weights:
        raise FileNotFoundError(f"no safetensors weights found in {directory}")
    return {
        "path": str(directory),
        "weight_sha256": {
            weight.name: cached_file_sha256(
                weight,
                cache_directory=CHECKPOINT_HASH_CACHE,
            )
            for weight in weights
        },
        "metadata_sha256": checkpoint_metadata_hashes(directory),
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _prompt_tokens(backend: Any, problem: OmniMathProblem, config: Mapping[str, Any]) -> TokenSequence:
    prompt_config = dict(config.get("prompt", {}))
    system_prompt = str(prompt_config.pop("system_prompt", DEFAULT_SYSTEM_PROMPT))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": omnimath_prompt(problem.question)},
    ]
    rendered = backend.tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        **prompt_config,
    )
    return backend.encode(str(rendered), add_special_tokens=False)


def _cuda_sync() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _preflight(
    backend: Any,
    prompt: TokenSequence,
    sampling: SamplingConfig,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    options = config.get("preflight", {})
    generated_tokens = int(options.get("generated_tokens", 2))
    tolerance = float(options.get("logprob_absolute_tolerance", 1e-4))
    sample = backend.sample_batch(
        [
            GenerationRequest(
                prompt,
                generated_tokens,
                sampling,
                int(config["run"]["seed"]),
                "omnimath-preflight",
            )
        ]
    )[0]
    rescored = backend.score_batch(
        [ScoreRequest(prompt, (sample.token_ids,), sampling)]
    )[0]
    if len(rescored) != len(sample.token_ids):
        raise RuntimeError("preflight rescoring returned the wrong number of tokens")
    differences = [
        abs(generated - scored)
        for generated, scored in zip(sample.token_logprobs, rescored, strict=True)
    ]
    maximum_difference = max(differences, default=0.0)
    if any(not math.isfinite(value) for value in (*sample.token_logprobs, *rescored)):
        raise RuntimeError("preflight observed a non-finite token logprob")
    if maximum_difference > tolerance:
        raise RuntimeError(
            f"generated/rescored logprob difference {maximum_difference} exceeds {tolerance}"
        )
    return {
        "generated_tokens": len(sample.token_ids),
        "finish_reason": sample.finish_reason,
        "generated_logprob_sum": sum(sample.token_logprobs),
        "rescored_logprob_sum": sum(rescored),
        "maximum_token_logprob_absolute_difference": maximum_difference,
        "absolute_tolerance": tolerance,
        "passed": True,
    }


def _conditional_diagnostics(result: Any, candidate_count: int) -> dict[str, Any]:
    candidate_ess: list[float] = []
    candidate_ess_fraction: list[float] = []
    maximum_probabilities: list[float] = []
    weight_entropies: list[float] = []
    rollout_rewards: list[float] = []
    future_rollout_generations = 0
    reward_contributions = 0
    for step in result.steps:
        log_weights = [candidate.log_weight for candidate in step.candidates]
        probabilities = normalize_log_weights(log_weights)
        ess = importance_effective_sample_size(log_weights)
        candidate_ess.append(ess)
        candidate_ess_fraction.append(ess / candidate_count)
        maximum_probabilities.append(max(probabilities))
        weight_entropies.append(
            -sum(value * math.log(value) for value in probabilities if value > 0)
        )
        for candidate in step.candidates:
            reward_contributions += len(candidate.rollouts)
            future_rollout_generations += sum(
                bool(rollout.token_ids) for rollout in candidate.rollouts
            )
            rollout_rewards.extend(rollout.reward for rollout in candidate.rollouts)
    return {
        "guidance_steps": len(result.steps),
        "selected_block_tokens_by_step": [
            len(step.selected.token_ids) for step in result.steps
        ],
        "selected_candidate_indices": [step.selected_index for step in result.steps],
        "candidate_log_weights_by_step": [
            [candidate.log_weight for candidate in step.candidates]
            for step in result.steps
        ],
        "candidate_probabilities_by_step": [
            list(
                normalize_log_weights(
                    [candidate.log_weight for candidate in step.candidates]
                )
            )
            for step in result.steps
        ],
        "candidate_ess_by_step": candidate_ess,
        "candidate_ess_fraction_by_step": candidate_ess_fraction,
        "mean_candidate_ess_fraction": statistics.fmean(candidate_ess_fraction),
        "mean_maximum_candidate_probability": statistics.fmean(maximum_probabilities),
        "mean_candidate_weight_entropy_nats": statistics.fmean(weight_entropies),
        "reward_contributions": reward_contributions,
        "future_rollout_generations": future_rollout_generations,
        "future_rollout_tokens": sum(
            len(rollout.token_ids)
            for step in result.steps
            for candidate in step.candidates
            for rollout in candidate.rollouts
        ),
        "mean_rollout_reward": statistics.fmean(rollout_rewards),
        "minimum_rollout_reward": min(rollout_rewards),
        "maximum_rollout_reward": max(rollout_rewards),
    }


def _run_arm(
    arm: str,
    backend: Any,
    prompt: TokenSequence,
    problem_seed: int,
    config: Mapping[str, Any],
    ratio_by_arm: Mapping[str, float],
) -> tuple[TokenSequence, dict[str, Any]]:
    total_length = int(config["generation"]["max_new_tokens"])
    sampling = SamplingConfig(
        temperature=float(config["sampling"]["temperature"]),
        top_p=float(config["sampling"].get("top_p", 1.0)),
        top_k=(
            int(config["sampling"]["top_k"])
            if config["sampling"].get("top_k") is not None
            else None
        ),
        eos_token_id=backend.tokenizer.eos_token_id,
    )
    if arm == "base":
        sample = backend.sample_batch(
            [
                GenerationRequest(
                    prompt,
                    total_length,
                    sampling,
                    SeedStream(problem_seed).derive("base"),
                    f"omnimath:base:{problem_seed}",
                )
            ]
        )[0]
        return sample.token_ids, {
            "sampling_temperature": sampling.temperature,
            "finish_reason": sample.finish_reason,
            "sample_logprob": sample.logprob,
        }

    ratio = ratio_by_arm[arm]
    options = config["conditional_is"]
    alignment = int(options["chunk_alignment_tokens"])
    block_size = chunk_tokens(total_length, ratio, alignment)
    candidate_count = int(options["candidate_count"])
    cached_backend = ScoreCachingBackend(backend)
    reward = SequenceLogProbabilityReward(
        cached_backend,
        sampling,
        scale=float(options["logprob_reward_scale"]),
    )
    result = run_conditional_is(
        cached_backend,
        prompt,
        ConditionalISConfig(
            candidate_count=candidate_count,
            rollout_count=int(options["rollout_count"]),
            block_size=block_size,
            total_length=total_length,
            reward_temperature=float(options["reward_temperature"]),
            importance_log_ratio_clip=None,
            apply_importance_correction=bool(options["apply_importance_correction"]),
            rollout_design=str(options["rollout_design"]),
            exact_rollout_early_stop=bool(options["exact_rollout_early_stop"]),
            rollout_evaluation_batch_size=int(options["rollout_evaluation_batch_size"]),
        ),
        reward,
        SeedStream(problem_seed),
        base_sampling=sampling,
        rollout_backend=cached_backend,
        rollout_sampling=sampling,
    )
    diagnostics = _conditional_diagnostics(result, candidate_count)
    diagnostics.update(
        {
            "chunk_ratio": ratio,
            "chunk_tokens": block_size,
            "chunk_alignment_tokens": alignment,
            "nominal_guidance_steps": math.ceil(total_length / block_size),
            "candidate_count": candidate_count,
            "rollout_count": int(options["rollout_count"]),
            "rollout_design": str(options["rollout_design"]),
            "reward_source": "model_sequence_log_probability",
            "logprob_reward_scale": float(options["logprob_reward_scale"]),
            "reward_temperature": float(options["reward_temperature"]),
            "effective_alpha": 1.0
            + float(options["logprob_reward_scale"])
            / float(options["reward_temperature"]),
            "importance_log_ratio_clip": None,
            "on_policy_rollouts": True,
            "score_cache": asdict(cached_backend.snapshot()),
        }
    )
    return result.token_ids, diagnostics


def _arm_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    successes = sum(bool(record["correct"]) for record in records)
    elapsed = [float(record["elapsed_seconds"]) for record in records]
    output_lengths = [int(record["output_tokens"]) for record in records]
    generation_slots = sum(
        int(record["backend_delta"].get("generation_forward_token_slots", 0))
        for record in records
    )
    score_slots = sum(
        int(record["backend_delta"].get("score_forward_token_slots", 0))
        for record in records
    )
    estimated_flops = sum(
        int(record["backend_delta"].get("estimated_dense_forward_flops", 0))
        for record in records
    )
    ess_values = [
        float(record["diagnostics"]["mean_candidate_ess_fraction"])
        for record in records
        if "mean_candidate_ess_fraction" in record["diagnostics"]
    ]
    return {
        "examples": len(records),
        "correct": successes,
        "accuracy": successes / len(records),
        "accuracy_wilson_95": wilson_interval(successes, len(records)),
        "sum_example_seconds": sum(elapsed),
        "mean_example_seconds": statistics.fmean(elapsed),
        "mean_output_tokens": statistics.fmean(output_lengths),
        "eos_rate": statistics.fmean(bool(record["ended_with_eos"]) for record in records),
        "length_truncation_rate": statistics.fmean(
            bool(record["length_truncated"]) for record in records
        ),
        "parse_failure_rate": statistics.fmean(
            not bool(record["prediction"]) for record in records
        ),
        "generation_forward_token_slots": generation_slots,
        "score_forward_token_slots": score_slots,
        "total_forward_token_slots": generation_slots + score_slots,
        "estimated_dense_forward_flops": estimated_flops,
        "mean_candidate_ess_fraction": (
            statistics.fmean(ess_values) if ess_values else None
        ),
        "weight_degenerate": bool(
            ess_values and statistics.fmean(ess_values) < 0.25
        ),
    }


def build_summary(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    bootstrap_replicates: int,
) -> dict[str, Any]:
    if not records:
        raise ValueError("cannot summarize an empty experiment")
    by_arm = {
        arm: [record for record in records if record["arm"] == arm]
        for arm in manifest["arms"]
    }
    if any(not values for values in by_arm.values()):
        raise ValueError("every configured arm must contain records")
    summaries = {arm: _arm_summary(values) for arm, values in by_arm.items()}
    paired: dict[str, Any] = {}
    if "base" in by_arm:
        base_ids = {record["problem_index"] for record in by_arm["base"]}
        for arm, values in by_arm.items():
            if arm == "base":
                continue
            if {record["problem_index"] for record in values} != base_ids:
                raise ValueError("paired arms do not contain the same problems")
            paired[f"{arm}_minus_base"] = clustered_paired_binary_difference(
                values,
                by_arm["base"],
                cluster_key="problem_index",
                outcome_key="correct",
                seed=SeedStream(int(manifest["seed"])).derive("paired", arm, "base"),
                replicates=bootstrap_replicates,
            )
    is_arms = [arm for arm in by_arm if arm != "base"]
    for left, right in combinations(is_arms, 2):
        if {
            record["problem_index"] for record in by_arm[left]
        } != {record["problem_index"] for record in by_arm[right]}:
            raise ValueError("paired IS arms do not contain the same problems")
        paired[f"{left}_minus_{right}"] = clustered_paired_binary_difference(
            by_arm[left],
            by_arm[right],
            cluster_key="problem_index",
            outcome_key="correct",
            seed=SeedStream(int(manifest["seed"])).derive("paired", left, right),
            replicates=bootstrap_replicates,
        )
    ranked = sorted(
        (arm for arm in by_arm if arm != "base"),
        key=lambda arm: (
            -float(summaries[arm]["accuracy"]),
            int(summaries[arm]["total_forward_token_slots"]),
            float(summaries[arm]["sum_example_seconds"]),
            -float(summaries[arm]["mean_candidate_ess_fraction"] or 0.0),
        ),
    )
    return {
        "schema_version": 1,
        "manifest_fingerprint": manifest["fingerprint"],
        "phase": manifest["phase"],
        "arms": summaries,
        "paired_accuracy": paired,
        "ranked_is_arms": ranked,
        "recommended_top2": ranked[:2] if manifest["phase"] == "screen" else None,
        "confirm_winner": None,
        "bootstrap_replicates": bootstrap_replicates,
    }


def build_confirm_decision(
    confirm_records: Sequence[Mapping[str, Any]],
    screen_records: Sequence[Mapping[str, Any]],
    ratio_by_arm: Mapping[str, float],
) -> dict[str, Any]:
    arms = tuple(ratio_by_arm)
    if len(arms) != 2:
        raise ValueError("confirm decision requires exactly two IS arms")

    def selected(
        records: Sequence[Mapping[str, Any]], arm: str
    ) -> list[Mapping[str, Any]]:
        values = [record for record in records if record["arm"] == arm]
        if not values:
            raise ValueError(f"no records found for confirm arm {arm}")
        return values

    confirm_by_arm = {arm: selected(confirm_records, arm) for arm in arms}
    screen_by_arm = {arm: selected(screen_records, arm) for arm in arms}
    if {
        record["problem_id"] for values in confirm_by_arm.values() for record in values
    } & {
        record["problem_id"] for values in screen_by_arm.values() for record in values
    }:
        raise ValueError("screen and confirm problems must be disjoint")

    confirm_correct = {
        arm: sum(bool(record["correct"]) for record in confirm_by_arm[arm])
        for arm in arms
    }
    if len(set(confirm_correct.values())) > 1:
        winner = max(arms, key=lambda arm: confirm_correct[arm])
        basis = "confirm_correct"
    else:
        pooled_correct = {
            arm: confirm_correct[arm]
            + sum(bool(record["correct"]) for record in screen_by_arm[arm])
            for arm in arms
        }
        if len(set(pooled_correct.values())) > 1:
            winner = max(arms, key=lambda arm: pooled_correct[arm])
            basis = "screen_confirm_pooled_correct"
        else:
            pooled_slots = {
                arm: sum(
                    int(record["backend_delta"].get("generation_forward_token_slots", 0))
                    + int(record["backend_delta"].get("score_forward_token_slots", 0))
                    for record in (*confirm_by_arm[arm], *screen_by_arm[arm])
                )
                for arm in arms
            }
            lower_cost = min(pooled_slots.values())
            upper_cost = max(pooled_slots.values())
            relative_gap = (
                (upper_cost - lower_cost) / lower_cost if lower_cost > 0 else math.inf
            )
            if len(set(pooled_slots.values())) > 1 and relative_gap >= 0.10:
                winner = min(arms, key=lambda arm: pooled_slots[arm])
                basis = "screen_confirm_pooled_forward_token_slots"
            else:
                winner = min(
                    arms,
                    key=lambda arm: (abs(ratio_by_arm[arm] - 0.25), ratio_by_arm[arm]),
                )
                basis = "cost_within_10_percent_then_closest_to_0.25"
            return {
                "winner": winner,
                "basis": basis,
                "confirm_correct": confirm_correct,
                "pooled_correct": pooled_correct,
                "pooled_forward_token_slots": pooled_slots,
                "pooled_cost_relative_gap": relative_gap,
            }
        return {
            "winner": winner,
            "basis": basis,
            "confirm_correct": confirm_correct,
            "pooled_correct": pooled_correct,
        }
    return {
        "winner": winner,
        "basis": basis,
        "confirm_correct": confirm_correct,
    }


def _load_gate(
    path: Path,
    model_fingerprint: str,
    generation_protocol_fingerprint: str,
) -> tuple[float, float]:
    if not path.is_file():
        raise FileNotFoundError(
            f"difficulty gate not found at {path}; run --phase probe first"
        )
    gate = json.loads(path.read_text(encoding="utf-8"))
    if gate["dataset_sha256"] != OMNIMATH_RULE_DATA_SHA256:
        raise ValueError("difficulty gate belongs to a different dataset")
    if gate["model_fingerprint"] != model_fingerprint:
        raise ValueError("difficulty gate belongs to a different model checkpoint")
    if gate["generation_protocol_fingerprint"] != generation_protocol_fingerprint:
        raise ValueError("difficulty gate belongs to a different generation protocol")
    return tuple(float(value) for value in gate["selected_difficulty_band"])  # type: ignore[return-value]


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
        config["conditional_is"]["chunk_ratios"] = list(parse_ratios(args.ratios))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/omnimath_qwen38_27b_chunk_ablation.toml"),
    )
    parser.add_argument("--phase", choices=("smoke", "probe", "screen", "confirm"), required=True)
    parser.add_argument("--source-root", type=Path, default=Path("data/omni_math_rule/upstream"))
    parser.add_argument("--output-root", type=Path, default=Path("results/omnimath"))
    parser.add_argument("--tag", default="default")
    parser.add_argument("--difficulty-gate", type=Path)
    parser.add_argument("--frozen-top2", type=Path)
    parser.add_argument("--difficulty-band", help="explicit LOWER:UPPER override; smoke only")
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

    if args.difficulty_band is not None and args.phase != "smoke":
        raise ValueError("--difficulty-band is a smoke-only protocol override")
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        if args.phase != "smoke":
            raise ValueError("--limit is a smoke-only protocol override")

    with args.config.open("rb") as source:
        config = tomllib.load(source)
    _apply_overrides(config, args)
    ratios = tuple(float(value) for value in config["conditional_is"]["chunk_ratios"])
    parse_ratios(",".join(str(value) for value in ratios))
    if str(config["conditional_is"]["reward"]) != "sequence_log_probability":
        raise ValueError("this experiment requires sequence_log_probability reward")
    if config["sampling"].get("top_p", 1.0) != 1.0 or config["sampling"].get("top_k") is not None:
        raise ValueError("exact on-policy IS requires top_p=1 and no top_k")
    if str(config["runtime"].get("device", "cuda")).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")

    source_root = args.source_root.resolve()
    dataset_revision = verify_omnimath_rule_checkout(source_root)
    data_path = source_root / OMNIMATH_RULE_DATA_FILE
    all_problems = load_omnimath_rule(data_path)
    evaluator = OfficialOmniMathRuleEvaluator(source_root)
    model_artifacts = _checkpoint_artifacts(str(config["models"]["base"]))
    model_fingerprint = json_fingerprint(model_artifacts)
    run_root = args.output_root / str(config["run"]["name"]) / args.tag
    frozen_top2: dict[str, Any] | None = None
    if args.phase == "confirm":
        frozen_path = args.frozen_top2 or (run_root / "frozen_top2.json")
        if not frozen_path.is_file():
            raise FileNotFoundError(
                f"frozen top-2 artifact not found at {frozen_path}; run screen first"
            )
        frozen_top2 = json.loads(frozen_path.read_text(encoding="utf-8"))
        if frozen_top2["dataset_sha256"] != OMNIMATH_RULE_DATA_SHA256:
            raise ValueError("frozen top-2 belongs to a different dataset")
        if frozen_top2["model_fingerprint"] != model_fingerprint:
            raise ValueError("frozen top-2 belongs to a different model checkpoint")
        if frozen_top2["ablation_protocol_fingerprint"] != _ablation_protocol_fingerprint(config):
            raise ValueError("frozen top-2 belongs to a different fixed IS protocol")
        frozen_ratios = tuple(float(value) for value in frozen_top2["ratios"])
        if args.ratios is not None and ratios != frozen_ratios:
            raise ValueError("--ratios does not match the frozen screen top-2")
        ratios = frozen_ratios
        config["conditional_is"]["chunk_ratios"] = list(ratios)

    partition_options = config["partitions"]
    if args.phase == "probe":
        difficulty_band = (8.0, 10.0)
    elif args.phase == "smoke":
        difficulty_band = (
            parse_difficulty_band(args.difficulty_band)
            if args.difficulty_band is not None
            else (8.0, 10.0)
        )
    else:
        default_gate = (
            run_root / "difficulty_gate.json"
        )
        difficulty_band = _load_gate(
            args.difficulty_gate or default_gate,
            model_fingerprint,
            _generation_protocol_fingerprint(config),
        )
    partitions = select_omnimath_partitions(
        all_problems,
        difficulty_band=difficulty_band,
        seed=int(config["run"]["dataset_seed"]),
        probe_per_bucket=int(partition_options["probe_per_bucket"]),
        screen_per_bucket=int(partition_options["screen_per_bucket"]),
        confirm_per_bucket=int(partition_options["confirm_per_bucket"]),
    )
    if args.phase == "smoke":
        problems = partitions["screen"][: args.limit or 1]
    else:
        problems = partitions[args.phase]
        if args.limit is not None:
            problems = problems[: args.limit]

    if args.phase == "probe":
        arms = ("base",)
    else:
        arms = ("base", *(chunk_arm(ratio) for ratio in ratios))
    if args.phase == "confirm" and len(ratios) != 2:
        raise ValueError("confirm requires exactly the two frozen screen ratios")
    ratio_by_arm = {chunk_arm(ratio): ratio for ratio in ratios}

    run_dir = run_root / args.phase
    run_dir.mkdir(parents=True, exist_ok=True)
    records_path = run_dir / "records.jsonl"
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    partition_path = run_root / f"dataset_{args.phase}.jsonl"
    partition_rows = [
        {
            "problem_index": problem.index,
            "problem_id": problem.problem_id,
            "question_sha256": hashlib.sha256(problem.question.encode("utf-8")).hexdigest(),
            "difficulty": problem.difficulty,
            "domain_bucket": problem.domain_bucket,
            "domains": list(problem.domains),
            "source": problem.source,
        }
        for problem in problems
    ]
    _atomic_jsonl(partition_path, partition_rows)

    effective = {
        "config": config,
        "phase": args.phase,
        "tag": args.tag,
        "arms": arms,
        "problem_ids": [problem.problem_id for problem in problems],
        "difficulty_band": difficulty_band,
        "dataset_revision": dataset_revision,
        "dataset_sha256": OMNIMATH_RULE_DATA_SHA256,
        "model_artifacts": model_artifacts,
        "implementation_sha256": implementation_hashes(
            REPOSITORY_ROOT,
            entrypoints=IMPLEMENTATION_FILES,
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
        "difficulty_band": list(difficulty_band),
        "arms": list(arms),
        "ratios": list(ratios),
        "derived_chunk_tokens": {
            chunk_arm(ratio): chunk_tokens(
                int(config["generation"]["max_new_tokens"]),
                ratio,
                int(config["conditional_is"]["chunk_alignment_tokens"]),
            )
            for ratio in ratios
        },
        "problem_ids": [problem.problem_id for problem in problems],
        "dataset": {
            "repository": OMNIMATH_RULE_REPOSITORY,
            "revision": OMNIMATH_RULE_REVISION,
            "data_sha256": OMNIMATH_RULE_DATA_SHA256,
            "source_root": str(source_root),
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
            "vllm": _package_version("vllm") if configured_backend(config).startswith("vllm") else None,
            "sympy": _package_version("sympy"),
            "antlr4_python3_runtime": _package_version("antlr4-python3-runtime"),
        },
    }
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["fingerprint"] != fingerprint:
            raise ValueError(f"{run_dir} contains a different experiment; choose a new --tag")
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
            first_prompt = _prompt_tokens(backend, pending[0][0], config)
            sampling = SamplingConfig(
                temperature=float(config["sampling"]["temperature"]),
                top_p=float(config["sampling"].get("top_p", 1.0)),
                eos_token_id=backend.tokenizer.eos_token_id,
            )
            manifest["preflight"] = _preflight(backend, first_prompt, sampling, config)
            _atomic_json(manifest_path, manifest)

            with records_path.open("a", encoding="utf-8", buffering=1) as sink:
                for ordinal, (problem, arm) in enumerate(pending, start=1):
                    prompt = _prompt_tokens(backend, problem, config)
                    problem_seed = SeedStream(int(config["run"]["seed"])).derive(
                        "omnimath", problem.problem_id
                    )
                    before = backend.snapshot()
                    _cuda_sync()
                    started = time.perf_counter()
                    tokens, diagnostics = _run_arm(
                        arm,
                        backend,
                        prompt,
                        problem_seed,
                        config,
                        ratio_by_arm,
                    )
                    _cuda_sync()
                    elapsed = time.perf_counter() - started
                    after = backend.snapshot()
                    output = backend.decode(tokens)
                    grade = evaluator.grade(output, problem.answer)
                    eos_token_id = backend.tokenizer.eos_token_id
                    ended_with_eos = bool(eos_token_id is not None and eos_token_id in tokens)
                    record = {
                        "schema_version": 1,
                        "phase": args.phase,
                        "tag": args.tag,
                        "arm": arm,
                        "problem_index": problem.index,
                        "problem_id": problem.problem_id,
                        "problem_seed": problem_seed,
                        "question_sha256": hashlib.sha256(problem.question.encode("utf-8")).hexdigest(),
                        "difficulty": problem.difficulty,
                        "domain_bucket": problem.domain_bucket,
                        "reference": grade.reference,
                        "prediction": grade.prediction,
                        "correct": grade.correct,
                        "output": output,
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
                    sink.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    print(
                        f"[{ordinal}/{len(pending)}] phase={args.phase} arm={arm} "
                        f"problem={problem.problem_id} correct={grade.correct} "
                        f"tokens={len(tokens)} seconds={elapsed:.3f}",
                        flush=True,
                    )
        else:
            print(f"all {len(existing)} records already complete; rebuilding summary")
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
    summary = build_summary(
        selected,
        manifest,
        bootstrap_replicates=int(config["run"]["bootstrap_replicates"]),
    )
    _atomic_json(summary_path, summary)

    if args.phase == "probe":
        correct = sum(bool(record["correct"]) for record in selected)
        selected_band = difficulty_band_from_probe(correct, len(selected))
        gate = {
            "schema_version": 1,
            "probe_manifest_fingerprint": fingerprint,
            "probe_summary_sha256": hashlib.sha256(
                summary_path.read_bytes()
            ).hexdigest(),
            "dataset_sha256": OMNIMATH_RULE_DATA_SHA256,
            "model_fingerprint": model_fingerprint,
            "probe_correct": correct,
            "probe_total": len(selected),
            "selected_difficulty_band": list(selected_band),
            "generation_protocol_fingerprint": _generation_protocol_fingerprint(config),
        }
        _atomic_json(run_root / "difficulty_gate.json", gate)
        summary["difficulty_gate"] = gate
    elif args.phase == "screen":
        top_arms = list(summary["recommended_top2"])
        frozen = {
            "schema_version": 1,
            "screen_manifest_fingerprint": fingerprint,
            "screen_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "dataset_sha256": OMNIMATH_RULE_DATA_SHA256,
            "model_fingerprint": model_fingerprint,
            "ablation_protocol_fingerprint": _ablation_protocol_fingerprint(config),
            "arms": top_arms,
            "ratios": [ratio_by_arm[arm] for arm in top_arms],
        }
        frozen_path = run_root / "frozen_top2.json"
        if frozen_path.is_file():
            previous_frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
            if previous_frozen != frozen:
                raise ValueError("screen produced a different frozen top-2 artifact")
        else:
            _atomic_json(frozen_path, frozen)
        summary["frozen_top2"] = frozen
    elif args.phase == "confirm":
        screen_records_path = run_root / "screen" / "records.jsonl"
        if not screen_records_path.is_file():
            raise FileNotFoundError(
                f"screen records not found at {screen_records_path}"
            )
        decision = build_confirm_decision(
            selected,
            load_jsonl(screen_records_path),
            ratio_by_arm,
        )
        summary["confirm_decision"] = decision
        summary["confirm_winner"] = decision["winner"]
        _atomic_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
