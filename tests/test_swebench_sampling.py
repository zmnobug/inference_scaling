from __future__ import annotations

import math
import random

import pytest

from inference_scaling.swebench.sampling import (
    conditional_is_log_weights,
    effective_sample_size,
    mh_log_acceptance,
    normalize_log_weights,
    select_is_candidate,
    suffix_cut_probabilities,
)


def test_alpha_one_gives_equal_is_weights() -> None:
    log_weights = conditional_is_log_weights(
        1.0,
        ((-2.0, -20.0), (-5.0, -6.0), (-100.0, -1.0)),
    )
    assert log_weights == pytest.approx((0.0, 0.0, 0.0))
    weights = normalize_log_weights(log_weights)
    assert weights == pytest.approx((1 / 3, 1 / 3, 1 / 3))
    assert effective_sample_size(weights) == pytest.approx(3.0)


def test_is_uses_alpha_minus_one_once() -> None:
    log_weights = conditional_is_log_weights(2.0, ((-2.0,), (-4.0, -4.0)))
    assert log_weights == pytest.approx((-2.0, -4.0))


def test_is_selection_is_deterministic_for_seed() -> None:
    first = select_is_candidate(1.5, ((-1.0,), (-2.0,)), random.Random(7))
    second = select_is_candidate(1.5, ((-1.0,), (-2.0,)), random.Random(7))
    assert first == second
    assert 1 <= first[2] <= 2


@pytest.mark.parametrize(
    "schedule", ("uniform", "inverse_length", "multiscale")
)
def test_suffix_cut_probabilities_have_full_declared_support(schedule: str) -> None:
    probabilities = suffix_cut_probabilities(8, 4, schedule)
    assert set(probabilities) == {4, 5, 6, 7}
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert all(value > 0 for value in probabilities.values())


def test_full_suffix_always_cuts_at_start() -> None:
    assert suffix_cut_probabilities(8, 2, "full") == {0: 1.0}


def test_mh_alpha_one_accepts_symmetric_proposal() -> None:
    assert mh_log_acceptance(
        alpha=1.0,
        old_suffix_logprob=-100.0,
        new_suffix_logprob=-1.0,
        forward_cut_probability=0.25,
        reverse_cut_probability=0.25,
    ) == pytest.approx(0.0)


def test_mh_includes_reverse_schedule_probability() -> None:
    actual = mh_log_acceptance(
        alpha=2.0,
        old_suffix_logprob=-3.0,
        new_suffix_logprob=-2.0,
        forward_cut_probability=0.5,
        reverse_cut_probability=0.25,
    )
    assert actual == pytest.approx(min(0.0, 1.0 + math.log(0.5)))


def test_mh_rejects_when_reverse_cut_has_no_support() -> None:
    assert mh_log_acceptance(
        alpha=2.0,
        old_suffix_logprob=-3.0,
        new_suffix_logprob=-2.0,
        forward_cut_probability=1.0,
        reverse_cut_probability=0.0,
    ) == -math.inf
