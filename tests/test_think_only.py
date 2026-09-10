from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from inference_scaling.arllm.algorithms.think_only import (
    NoValidReasoningRollout,
    normalize_reasoning_log_weights,
    run_strict_think_only_conditional_is,
)
from inference_scaling.arllm.config import ConditionalISConfig, SamplingConfig
from inference_scaling.arllm.rewards import SequenceLogProbabilityReward
from inference_scaling.arllm.types import (
    GenerationRequest,
    ScoreRequest,
    SequenceSample,
)
from inference_scaling.shared.rng import SeedStream


class _ScriptedBackend:
    model_id = "scripted"

    def __init__(
        self, *, valid_rollouts: bool = True, mixed_rollouts: bool = False
    ) -> None:
        self.valid_rollouts = valid_rollouts
        self.mixed_rollouts = mixed_rollouts
        self.generation_requests: list[GenerationRequest] = []
        self.scored: list[tuple[int, ...]] = []

    def sample_batch(
        self, requests: Sequence[GenerationRequest]
    ) -> list[SequenceSample]:
        outputs = []
        for request in requests:
            self.generation_requests.append(request)
            if request.request_id == "think-only:answer":
                tokens = (4, 5)
            elif ":rollout:" in request.request_id:
                valid = self.valid_rollouts and not (
                    self.mixed_rollouts and request.request_id.endswith(":1")
                )
                tokens = (3,) if valid else (5,)
            elif len(request.prefix) > 1:
                tokens = (3,)
            else:
                tokens = (1,) * request.max_new_tokens
            tokens = tokens[: request.max_new_tokens]
            final = tokens[-1]
            if final == request.sampling.eos_token_id:
                finish_reason = "eos"
            elif final in request.stop_token_ids:
                finish_reason = "stop"
            else:
                finish_reason = "length"
            outputs.append(
                SequenceSample(
                    prefix=request.prefix,
                    token_ids=tokens,
                    token_logprobs=tuple(-0.1 for _ in tokens),
                    policy_id=request.sampling.policy_id,
                    model_id=self.model_id,
                    request_id=request.request_id,
                    finish_reason=finish_reason,
                    termination_token_id=(
                        final if finish_reason in {"eos", "stop"} else None
                    ),
                )
            )
        return outputs

    def score_batch(self, requests: Sequence[ScoreRequest]) -> list[tuple[float, ...]]:
        scores = []
        for request in requests:
            for continuation in request.continuations:
                self.scored.append(continuation)
                scores.append(tuple(-0.1 for _ in continuation))
        return scores


class _DirectEndBackend(_ScriptedBackend):
    def sample_batch(
        self, requests: Sequence[GenerationRequest]
    ) -> list[SequenceSample]:
        outputs = []
        for request in requests:
            self.generation_requests.append(request)
            tokens = (4, 5) if request.request_id == "think-only:answer" else (3,)
            final = tokens[-1]
            finish_reason = (
                "eos"
                if final == request.sampling.eos_token_id
                else "stop"
            )
            outputs.append(
                SequenceSample(
                    prefix=request.prefix,
                    token_ids=tokens,
                    token_logprobs=tuple(-0.1 for _ in tokens),
                    policy_id=request.sampling.policy_id,
                    model_id=self.model_id,
                    request_id=request.request_id,
                    finish_reason=finish_reason,
                    termination_token_id=final,
                )
            )
        return outputs


def _config() -> ConditionalISConfig:
    return ConditionalISConfig(
        candidate_count=2,
        rollout_count=2,
        block_size=2,
        total_length=8,
        reward_temperature=10.0,
        rollout_evaluation_batch_size=2,
    )


def test_strict_think_only_scores_reasoning_then_samples_one_answer() -> None:
    backend = _ScriptedBackend()
    sampling = SamplingConfig(eos_token_id=5)
    reward = SequenceLogProbabilityReward(backend, sampling)

    result = run_strict_think_only_conditional_is(
        backend,
        (),
        _config(),
        reward,
        SeedStream(17),
        reasoning_end_token_id=3,
        sampling=sampling,
    )

    assert result.failure_reason is None
    assert result.reasoning_token_ids == (1, 1, 3)
    assert result.answer_token_ids == (4, 5)
    assert len(result.token_ids) <= _config().total_length
    assert backend.scored
    assert all(completion == (1, 1, 3) for completion in backend.scored)
    assert all(4 not in completion and 5 not in completion for completion in backend.scored)
    assert sum(result.reasoning_token_logprobs) == pytest.approx(-0.3)
    assert all(
        rollout.reward == pytest.approx(-0.3)
        for step in result.steps
        for candidate in step.candidates
        for rollout in candidate.rollouts
    )
    reasoning_requests = [
        request
        for request in backend.generation_requests
        if request.request_id != "think-only:answer"
    ]
    answer_requests = [
        request
        for request in backend.generation_requests
        if request.request_id == "think-only:answer"
    ]
    assert reasoning_requests
    assert all(request.stop_token_ids == (3,) for request in reasoning_requests)
    assert len(answer_requests) == 1
    assert answer_requests[0].stop_token_ids == ()
    assert answer_requests[0].max_new_tokens == 5


def test_all_invalid_reasoning_rollouts_fail_without_answer_fallback() -> None:
    backend = _ScriptedBackend(valid_rollouts=False)
    sampling = SamplingConfig(eos_token_id=5)

    result = run_strict_think_only_conditional_is(
        backend,
        (),
        _config(),
        SequenceLogProbabilityReward(backend, sampling),
        SeedStream(19),
        reasoning_end_token_id=3,
        sampling=sampling,
    )

    assert result.failure_reason == "no_valid_reasoning_rollout"
    assert result.answer_token_ids == ()
    assert backend.scored == []
    assert not any(
        request.request_id == "think-only:answer"
        for request in backend.generation_requests
    )
    assert result.steps[0].probabilities == (0.0, 0.0)


def test_direct_reasoning_end_is_valid_and_skips_future_rollouts() -> None:
    backend = _DirectEndBackend()
    sampling = SamplingConfig(eos_token_id=5)

    result = run_strict_think_only_conditional_is(
        backend,
        (),
        _config(),
        SequenceLogProbabilityReward(backend, sampling),
        SeedStream(29),
        reasoning_end_token_id=3,
        sampling=sampling,
    )

    assert result.reasoning_token_ids == (3,)
    assert result.answer_token_ids == (4, 5)
    assert backend.scored == [(3,), (3,)]
    assert all(
        candidate.planned_rollout_count == 0
        and len(candidate.rollouts) == 1
        for candidate in result.steps[0].candidates
    )
    assert not any(
        ":rollout:" in request.request_id
        for request in backend.generation_requests
    )


def test_reasoning_weight_normalization_keeps_exact_zero_mass() -> None:
    assert normalize_reasoning_log_weights((0.0, float("-inf"))) == (1.0, 0.0)
    with pytest.raises(NoValidReasoningRollout):
        normalize_reasoning_log_weights((float("-inf"), float("-inf")))


def test_invalid_rollout_remains_in_fixed_monte_carlo_denominator() -> None:
    backend = _ScriptedBackend(mixed_rollouts=True)
    sampling = SamplingConfig(eos_token_id=5)

    result = run_strict_think_only_conditional_is(
        backend,
        (),
        _config(),
        SequenceLogProbabilityReward(backend, sampling),
        SeedStream(31),
        reasoning_end_token_id=3,
        sampling=sampling,
    )

    first_step = result.steps[0]
    expected = -0.3 / _config().reward_temperature - math.log(2)
    assert all(
        candidate.log_weight == pytest.approx(expected)
        and candidate.valid_rollout_count == 1
        and candidate.planned_rollout_count == 2
        for candidate in first_step.candidates
    )


def test_strict_think_only_rejects_reasoning_end_equal_to_eos() -> None:
    backend = _ScriptedBackend()
    sampling = SamplingConfig(eos_token_id=3)
    with pytest.raises(ValueError, match="differ from model EOS"):
        run_strict_think_only_conditional_is(
            backend,
            (),
            _config(),
            SequenceLogProbabilityReward(backend, sampling),
            SeedStream(23),
            reasoning_end_token_id=3,
            sampling=sampling,
        )
