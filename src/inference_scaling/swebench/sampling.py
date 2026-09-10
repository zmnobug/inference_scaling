"""Numerically stable logprob IS and MH primitives for SWE-bench trajectories."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def logmeanexp(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("logmeanexp requires at least one value")
    numbers = tuple(_finite("logmeanexp value", value) for value in values)
    maximum = max(numbers)
    return maximum + math.log(
        sum(math.exp(value - maximum) for value in numbers) / len(numbers)
    )


def normalize_log_weights(log_weights: Sequence[float]) -> tuple[float, ...]:
    if not log_weights:
        raise ValueError("at least one log weight is required")
    numbers = tuple(_finite("log weight", value) for value in log_weights)
    maximum = max(numbers)
    raw = tuple(math.exp(value - maximum) for value in numbers)
    total = sum(raw)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("log weights cannot be normalized")
    return tuple(value / total for value in raw)


def effective_sample_size(weights: Sequence[float]) -> float:
    if not weights:
        raise ValueError("at least one weight is required")
    numbers = tuple(_finite("weight", value) for value in weights)
    if any(value < 0 for value in numbers):
        raise ValueError("weights must be non-negative")
    total = sum(numbers)
    if total <= 0:
        raise ValueError("weights must have positive mass")
    normalized = tuple(value / total for value in numbers)
    return 1.0 / sum(value * value for value in normalized)


def conditional_is_log_weights(
    alpha: float,
    rollout_trajectory_logprobs: Sequence[Sequence[float]],
) -> tuple[float, ...]:
    """Return one finite log weight per candidate.

    Candidate and continuation logprobs must already be summed into each
    trajectory value. Since candidates and rollouts come from ``p``, the
    correction from the base proposal to ``p**alpha`` is
    ``exp((alpha - 1) * log_p_trajectory)``.
    """

    exponent = _finite("alpha", alpha) - 1.0
    if exponent < 0:
        raise ValueError("alpha must be at least one")
    if not rollout_trajectory_logprobs:
        raise ValueError("at least one candidate is required")
    result = []
    for candidate_index, rollout_values in enumerate(
        rollout_trajectory_logprobs
    ):
        if not rollout_values:
            raise ValueError(
                f"candidate {candidate_index} requires at least one rollout"
            )
        result.append(
            logmeanexp(
                [
                    exponent * _finite("trajectory logprob", value)
                    for value in rollout_values
                ]
            )
        )
    return tuple(result)


def categorical_index(weights: Sequence[float], rng: random.Random) -> int:
    if not weights:
        raise ValueError("at least one categorical weight is required")
    numbers = tuple(_finite("categorical weight", value) for value in weights)
    if any(value < 0 for value in numbers):
        raise ValueError("categorical weights must be non-negative")
    total = sum(numbers)
    if total <= 0:
        raise ValueError("categorical weights must have positive mass")
    threshold = rng.random() * total
    cumulative = 0.0
    for index, value in enumerate(numbers):
        cumulative += value
        if threshold < cumulative:
            return index
    return len(numbers) - 1


def select_is_candidate(
    alpha: float,
    rollout_trajectory_logprobs: Sequence[Sequence[float]],
    rng: random.Random,
) -> tuple[int, tuple[float, ...], float]:
    log_weights = conditional_is_log_weights(
        alpha, rollout_trajectory_logprobs
    )
    weights = normalize_log_weights(log_weights)
    return categorical_index(weights, rng), weights, effective_sample_size(weights)


def suffix_cut_probabilities(
    trajectory_length: int,
    max_suffix_actions: int | None,
    schedule: str,
) -> dict[int, float]:
    """Map eligible cut indices to probabilities for a trajectory.

    A cut ``c`` retains decisions ``[:c]`` and regenerates ``[c:]``. The empty
    suffix is never proposed. ``max_suffix_actions`` limits how far the cut may
    be from the current end; a regenerated suffix may have a different length.
    """

    if trajectory_length <= 0:
        raise ValueError("trajectory_length must be positive")
    if max_suffix_actions is not None and max_suffix_actions <= 0:
        raise ValueError("max_suffix_actions must be positive or None")
    if schedule == "full":
        return {0: 1.0}
    if schedule not in {"uniform", "inverse_length", "multiscale"}:
        raise ValueError("unknown suffix schedule")

    maximum = min(trajectory_length, max_suffix_actions or trajectory_length)
    suffix_lengths = tuple(range(1, maximum + 1))
    if schedule == "uniform":
        raw = {length: 1.0 for length in suffix_lengths}
    elif schedule == "inverse_length":
        raw = {length: 1.0 / length for length in suffix_lengths}
    else:
        favored = {1, maximum}
        value = 1
        while value < maximum:
            favored.add(value)
            value *= 2
        raw = {
            length: 0.1 / maximum
            + (0.9 / len(favored) if length in favored else 0.0)
            for length in suffix_lengths
        }
    total = sum(raw.values())
    return {
        trajectory_length - suffix_length: value / total
        for suffix_length, value in raw.items()
    }


def sample_suffix_cut(
    probabilities: Mapping[int, float], rng: random.Random
) -> int:
    cuts = tuple(sorted(probabilities))
    index = categorical_index([probabilities[cut] for cut in cuts], rng)
    return cuts[index]


def mh_log_acceptance(
    *,
    alpha: float,
    old_suffix_logprob: float,
    new_suffix_logprob: float,
    forward_cut_probability: float,
    reverse_cut_probability: float,
) -> float:
    exponent = _finite("alpha", alpha) - 1.0
    if exponent < 0:
        raise ValueError("alpha must be at least one")
    old_value = _finite("old suffix logprob", old_suffix_logprob)
    new_value = _finite("new suffix logprob", new_suffix_logprob)
    forward = _finite("forward cut probability", forward_cut_probability)
    reverse = _finite("reverse cut probability", reverse_cut_probability)
    if forward <= 0:
        raise ValueError("forward cut probability must be positive")
    if reverse < 0:
        raise ValueError("reverse cut probability must be non-negative")
    if reverse == 0:
        return -math.inf
    ratio = exponent * (new_value - old_value) + math.log(reverse) - math.log(
        forward
    )
    return min(0.0, ratio)


def metropolis_accept(log_acceptance: float, rng: random.Random) -> bool:
    if log_acceptance == -math.inf:
        return False
    value = _finite("log_acceptance", log_acceptance)
    if value > 0:
        raise ValueError("log_acceptance must be non-positive")
    uniform = max(rng.random(), float.fromhex("0x1.0p-1022"))
    return math.log(uniform) <= value
