"""Strict reasoning-only conditional importance sampling.

The scaled phase ends at one explicit reasoning delimiter.  Candidate rewards
never observe answer tokens; after selecting a complete reasoning sequence, the
base policy samples the answer exactly once from the remaining shared budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Callable

from inference_scaling.arllm.config import ConditionalISConfig, SamplingConfig
from inference_scaling.arllm.types import (
    AutoregressiveBackend,
    GenerationRequest,
    SequenceSample,
    TokenSequence,
)
from inference_scaling.shared.rng import SeedStream
from inference_scaling.shared.stepwise import categorical_index_from_uniform
from inference_scaling.shared.verifier import TokenReward


class NoValidReasoningRollout(RuntimeError):
    """Every candidate at one IS step received zero target mass."""


@dataclass(frozen=True, slots=True)
class ThinkOnlyRolloutEvaluation:
    token_ids: TokenSequence
    finish_reason: str
    valid_reasoning: bool
    reward: float | None
    log_weight: float
    reward_token_count: int


@dataclass(frozen=True, slots=True)
class ThinkOnlyCandidate:
    token_ids: TokenSequence
    token_logprobs: tuple[float, ...]
    finish_reason: str
    rollouts: tuple[ThinkOnlyRolloutEvaluation, ...]
    log_weight: float
    valid_rollout_count: int
    planned_rollout_count: int


@dataclass(frozen=True, slots=True)
class ThinkOnlyISStep:
    generated_length_before: int
    candidates: tuple[ThinkOnlyCandidate, ...]
    probabilities: tuple[float, ...]
    selected_index: int | None

    @property
    def selected(self) -> ThinkOnlyCandidate:
        if self.selected_index is None:
            raise NoValidReasoningRollout(
                "the failed reasoning step has no selected candidate"
            )
        return self.candidates[self.selected_index]


@dataclass(frozen=True, slots=True)
class ThinkOnlyISResult:
    prompt: TokenSequence
    reasoning_token_ids: TokenSequence
    reasoning_token_logprobs: tuple[float, ...]
    answer_token_ids: TokenSequence
    answer_token_logprobs: tuple[float, ...]
    answer_finish_reason: str | None
    steps: tuple[ThinkOnlyISStep, ...]
    failure_reason: str | None = None

    @property
    def token_ids(self) -> TokenSequence:
        return self.reasoning_token_ids + self.answer_token_ids

    @property
    def reasoning_complete(self) -> bool:
        return self.failure_reason not in {
            "no_valid_reasoning_rollout",
            "reasoning_length",
        }


RewardFunction = TokenReward


def _validate_inputs(
    config: ConditionalISConfig,
    sampling: SamplingConfig,
    reasoning_end_token_id: int,
) -> None:
    if reasoning_end_token_id < 0:
        raise ValueError("reasoning_end_token_id must be non-negative")
    if sampling.eos_token_id is None:
        raise ValueError("strict think-only sampling requires a model EOS token")
    if reasoning_end_token_id == sampling.eos_token_id:
        raise ValueError("reasoning end token must differ from model EOS")
    if sampling.top_p < 1 or sampling.top_k is not None:
        raise ValueError(
            "strict think-only candidates require top_p=1 and top_k=None"
        )
    if config.rollout_design != "iid":
        raise ValueError("strict think-only v1 supports only iid rollouts")
    if config.importance_log_ratio_clip is not None:
        raise ValueError("strict think-only on-policy IS does not support ratio clipping")
    if not config.apply_importance_correction:
        raise ValueError("strict think-only v1 requires on-policy identity correction")
    if config.exact_rollout_early_stop:
        raise ValueError("strict think-only v1 does not support rollout early stopping")


def _validate_sample(
    sample: SequenceSample,
    request: GenerationRequest,
    backend: AutoregressiveBackend,
) -> None:
    if sample.prefix != request.prefix:
        raise RuntimeError("backend returned a sample for the wrong prefix")
    if sample.request_id != request.request_id:
        raise RuntimeError("backend returned a sample for the wrong request")
    if sample.model_id != backend.model_id:
        raise RuntimeError("backend returned a sample from the wrong model")
    if sample.policy_id != request.sampling.policy_id:
        raise RuntimeError("backend returned a sample from the wrong policy")
    if not sample.token_ids:
        raise RuntimeError("reasoning generation returned no sampled token")
    if len(sample.token_ids) > request.max_new_tokens:
        raise RuntimeError("reasoning generation exceeded its token budget")
    if len(sample.token_ids) != len(sample.token_logprobs):
        raise RuntimeError("reasoning token/logprob lengths differ")
    if any(not isfinite(value) for value in sample.token_logprobs):
        raise RuntimeError("reasoning generation returned a non-finite logprob")
    if any(token in request.terminal_token_ids for token in sample.token_ids[:-1]):
        raise RuntimeError("backend generated tokens after a terminal token")
    terminal = sample.token_ids[-1] in request.terminal_token_ids
    if terminal != (sample.finish_reason in {"eos", "stop"}):
        raise RuntimeError("reasoning finish reason disagrees with its final token")
    if not terminal and len(sample.token_ids) != request.max_new_tokens:
        raise RuntimeError("a non-terminal reasoning sample ended before its limit")


def _sample_reasoning_batch(
    backend: AutoregressiveBackend,
    requests: Sequence[GenerationRequest],
) -> tuple[SequenceSample, ...]:
    samples = tuple(backend.sample_batch(requests))
    if len(samples) != len(requests):
        raise RuntimeError("backend returned the wrong number of reasoning samples")
    for sample, request in zip(samples, requests, strict=True):
        _validate_sample(sample, request, backend)
    return samples


def _reward_batch(
    reward: RewardFunction,
    prompt: TokenSequence,
    reasonings: Sequence[TokenSequence],
    batch_size: int,
) -> tuple[float, ...]:
    if not reasonings:
        return ()
    callback = getattr(reward, "batch", None)
    parsed_values: list[float] = []
    for start in range(0, len(reasonings), batch_size):
        batch = tuple(reasonings[start : start + batch_size])
        values = (
            callback(prompt, batch)
            if callable(callback)
            else tuple(reward(prompt, reasoning) for reasoning in batch)
        )
        parsed_values.extend(float(value) for value in values)
    parsed = tuple(parsed_values)
    if len(parsed) != len(reasonings):
        raise ValueError("reasoning reward returned the wrong number of values")
    if any(not isfinite(value) for value in parsed):
        raise ValueError("reasoning reward must be finite for a valid reasoning")
    return parsed


def _logmeanexp_with_zero_mass(log_weights: Sequence[float]) -> float:
    if not log_weights:
        raise ValueError("at least one rollout weight is required")
    if any(value == float("inf") or value != value for value in log_weights):
        raise ValueError("rollout log weights must be finite or negative infinity")
    finite = [value for value in log_weights if value != float("-inf")]
    if not finite:
        return float("-inf")
    maximum = max(finite)
    return maximum + log(sum(exp(value - maximum) for value in finite)) - log(
        len(log_weights)
    )


def normalize_reasoning_log_weights(
    log_weights: Sequence[float],
) -> tuple[float, ...]:
    if not log_weights:
        raise ValueError("at least one candidate weight is required")
    if any(value == float("inf") or value != value for value in log_weights):
        raise ValueError("candidate log weights must be finite or negative infinity")
    finite = [value for value in log_weights if value != float("-inf")]
    if not finite:
        raise NoValidReasoningRollout("all reasoning candidates have zero target mass")
    maximum = max(finite)
    masses = [
        0.0 if value == float("-inf") else exp(value - maximum)
        for value in log_weights
    ]
    total = sum(masses)
    return tuple(value / total for value in masses)


def _termination_kind(
    sample: SequenceSample,
    reasoning_end_token_id: int,
    model_eos_token_id: int,
) -> str:
    final = sample.token_ids[-1]
    if final == reasoning_end_token_id:
        return "reasoning_end"
    if final == model_eos_token_id:
        return "model_eos"
    return "length"


def _evaluate_candidates(
    *,
    backend: AutoregressiveBackend,
    prompt: TokenSequence,
    generated_prefix: TokenSequence,
    candidates: Sequence[SequenceSample],
    config: ConditionalISConfig,
    sampling: SamplingConfig,
    reasoning_end_token_id: int,
    reward: RewardFunction,
    seeds: SeedStream,
    step_index: int,
) -> tuple[ThinkOnlyCandidate, ...]:
    eos = sampling.eos_token_id
    assert eos is not None
    pending_requests: list[GenerationRequest] = []
    pending_candidates: list[int] = []
    direct: dict[int, tuple[str, TokenSequence]] = {}

    for candidate_index, candidate in enumerate(candidates):
        full = generated_prefix + candidate.token_ids
        termination = _termination_kind(candidate, reasoning_end_token_id, eos)
        if termination != "length" or len(full) >= config.total_length:
            direct[candidate_index] = (termination, full)
            continue
        remaining = config.total_length - len(full)
        for rollout_index in range(config.rollout_count):
            pending_requests.append(
                GenerationRequest(
                    prefix=prompt + full,
                    max_new_tokens=remaining,
                    sampling=sampling,
                    seed=seeds.derive(
                        "think_only",
                        step_index,
                        "candidate",
                        candidate_index,
                        "rollout",
                        rollout_index,
                    ),
                    request_id=(
                        "think-only:"
                        f"step:{step_index}:candidate:{candidate_index}:"
                        f"rollout:{rollout_index}"
                    ),
                    stop_token_ids=(reasoning_end_token_id,),
                )
            )
            pending_candidates.append(candidate_index)

    rollout_samples = _sample_reasoning_batch(backend, pending_requests)
    grouped: list[list[tuple[SequenceSample | None, str, TokenSequence]]] = [
        [] for _ in candidates
    ]
    for candidate_index, (termination, full) in direct.items():
        grouped[candidate_index].append((None, termination, full))
    for candidate_index, sample in zip(
        pending_candidates, rollout_samples, strict=True
    ):
        full = (
            generated_prefix
            + candidates[candidate_index].token_ids
            + sample.token_ids
        )
        grouped[candidate_index].append(
            (sample, _termination_kind(sample, reasoning_end_token_id, eos), full)
        )

    valid_sequences = [
        full
        for group in grouped
        for _, termination, full in group
        if termination == "reasoning_end"
    ]
    rewards = iter(
        _reward_batch(
            reward,
            prompt,
            valid_sequences,
            config.rollout_evaluation_batch_size,
        )
    )
    evaluated: list[ThinkOnlyCandidate] = []
    for candidate_index, candidate in enumerate(candidates):
        rollout_evaluations: list[ThinkOnlyRolloutEvaluation] = []
        for sample, termination, full in grouped[candidate_index]:
            valid = termination == "reasoning_end"
            reward_value = next(rewards) if valid else None
            log_weight = (
                reward_value / config.reward_temperature
                if reward_value is not None
                else float("-inf")
            )
            rollout_evaluations.append(
                ThinkOnlyRolloutEvaluation(
                    token_ids=() if sample is None else sample.token_ids,
                    finish_reason=termination,
                    valid_reasoning=valid,
                    reward=reward_value,
                    log_weight=log_weight,
                    reward_token_count=len(full) if valid else 0,
                )
            )
        if not rollout_evaluations:
            raise RuntimeError("a reasoning candidate received no weight contribution")
        candidate_log_weight = _logmeanexp_with_zero_mass(
            [item.log_weight for item in rollout_evaluations]
        )
        terminal = _termination_kind(candidate, reasoning_end_token_id, eos)
        evaluated.append(
            ThinkOnlyCandidate(
                token_ids=candidate.token_ids,
                token_logprobs=candidate.token_logprobs,
                finish_reason=terminal,
                rollouts=tuple(rollout_evaluations),
                log_weight=candidate_log_weight,
                valid_rollout_count=sum(
                    item.valid_reasoning for item in rollout_evaluations
                ),
                planned_rollout_count=(
                    0 if candidate_index in direct else config.rollout_count
                ),
            )
        )
    try:
        next(rewards)
    except StopIteration:
        pass
    else:
        raise RuntimeError("reasoning rewards were not consumed exactly once")
    return tuple(evaluated)


def run_strict_think_only_conditional_is(
    backend: AutoregressiveBackend,
    prompt: TokenSequence,
    config: ConditionalISConfig,
    reward: RewardFunction,
    seeds: SeedStream,
    *,
    reasoning_end_token_id: int,
    sampling: SamplingConfig | None = None,
) -> ThinkOnlyISResult:
    """Scale only explicit reasoning, then sample one unweighted answer."""

    policy = sampling or SamplingConfig()
    _validate_inputs(config, policy, reasoning_end_token_id)
    reasoning: TokenSequence = ()
    reasoning_logprobs: tuple[float, ...] = ()
    steps: list[ThinkOnlyISStep] = []
    step_index = 0

    while len(reasoning) < config.total_length:
        candidate_length = min(config.block_size, config.total_length - len(reasoning))
        requests = [
            GenerationRequest(
                prefix=prompt + reasoning,
                max_new_tokens=candidate_length,
                sampling=policy,
                seed=seeds.derive(
                    "think_only", step_index, "candidate", candidate_index
                ),
                request_id=(
                    f"think-only:step:{step_index}:candidate:{candidate_index}"
                ),
                stop_token_ids=(reasoning_end_token_id,),
            )
            for candidate_index in range(config.candidate_count)
        ]
        sampled = _sample_reasoning_batch(backend, requests)
        candidates = _evaluate_candidates(
            backend=backend,
            prompt=prompt,
            generated_prefix=reasoning,
            candidates=sampled,
            config=config,
            sampling=policy,
            reasoning_end_token_id=reasoning_end_token_id,
            reward=reward,
            seeds=seeds,
            step_index=step_index,
        )
        try:
            probabilities = normalize_reasoning_log_weights(
                [candidate.log_weight for candidate in candidates]
            )
        except NoValidReasoningRollout:
            steps.append(
                ThinkOnlyISStep(
                    generated_length_before=len(reasoning),
                    candidates=candidates,
                    probabilities=tuple(0.0 for _ in candidates),
                    selected_index=None,
                )
            )
            return ThinkOnlyISResult(
                prompt=prompt,
                reasoning_token_ids=reasoning,
                reasoning_token_logprobs=reasoning_logprobs,
                answer_token_ids=(),
                answer_token_logprobs=(),
                answer_finish_reason=None,
                steps=tuple(steps),
                failure_reason="no_valid_reasoning_rollout",
            )
        selected_index = categorical_index_from_uniform(
            probabilities,
            float(
                seeds.generator("think_only", step_index, "select").random()
            ),
        )
        selected = candidates[selected_index]
        steps.append(
            ThinkOnlyISStep(
                generated_length_before=len(reasoning),
                candidates=candidates,
                probabilities=probabilities,
                selected_index=selected_index,
            )
        )
        reasoning += selected.token_ids
        reasoning_logprobs += selected.token_logprobs
        if selected.finish_reason == "reasoning_end":
            break
        step_index += 1

    if not reasoning or reasoning[-1] != reasoning_end_token_id:
        return ThinkOnlyISResult(
            prompt=prompt,
            reasoning_token_ids=reasoning,
            reasoning_token_logprobs=reasoning_logprobs,
            answer_token_ids=(),
            answer_token_logprobs=(),
            answer_finish_reason=None,
            steps=tuple(steps),
            failure_reason="reasoning_length",
        )

    answer_budget = config.total_length - len(reasoning)
    if answer_budget <= 0:
        return ThinkOnlyISResult(
            prompt=prompt,
            reasoning_token_ids=reasoning,
            reasoning_token_logprobs=reasoning_logprobs,
            answer_token_ids=(),
            answer_token_logprobs=(),
            answer_finish_reason=None,
            steps=tuple(steps),
            failure_reason="answer_budget_exhausted",
        )
    answer_request = GenerationRequest(
        prefix=prompt + reasoning,
        max_new_tokens=answer_budget,
        sampling=policy,
        seed=seeds.derive("think_only", "answer"),
        request_id="think-only:answer",
    )
    answers = backend.sample_batch([answer_request])
    if len(answers) != 1:
        raise RuntimeError("backend returned the wrong number of answer samples")
    answer = answers[0]
    _validate_sample(answer, answer_request, backend)
    return ThinkOnlyISResult(
        prompt=prompt,
        reasoning_token_ids=reasoning,
        reasoning_token_logprobs=reasoning_logprobs,
        answer_token_ids=answer.token_ids,
        answer_token_logprobs=answer.token_logprobs,
        answer_finish_reason=answer.finish_reason,
        steps=tuple(steps),
    )


__all__ = [
    "NoValidReasoningRollout",
    "normalize_reasoning_log_weights",
    "run_strict_think_only_conditional_is",
    "ThinkOnlyCandidate",
    "ThinkOnlyISResult",
    "ThinkOnlyISStep",
    "ThinkOnlyRolloutEvaluation",
]
