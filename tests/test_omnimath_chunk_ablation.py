from __future__ import annotations

import json

import pytest

from experiments.arllm.omnimath_chunk_ablation import (
    build_confirm_decision,
    build_summary,
    chunk_arm,
    chunk_tokens,
    parse_ratios,
)
from inference_scaling.shared.evaluation.omnimath import (
    OMNIMATH_DOMAIN_BUCKETS,
    difficulty_band_from_probe,
    load_omnimath_rule,
    select_omnimath_partitions,
)


@pytest.mark.parametrize(
    "ratio,expected",
    [(0.125, 128), (0.25, 256), (0.5, 512), (1.0, 1024)],
)
def test_chunk_ratio_is_aligned_and_bounded(ratio, expected) -> None:
    assert chunk_tokens(1024, ratio, 8) == expected


def test_chunk_ratio_rounds_up_and_has_stable_arm_labels() -> None:
    assert chunk_tokens(100, 0.125, 8) == 16
    assert chunk_arm(0.125) == "is-cr0125"
    assert chunk_arm(1.0) == "is-cr1000"
    assert parse_ratios("0.125,0.25,1") == (0.125, 0.25, 1.0)
    with pytest.raises(ValueError, match="unique"):
        parse_ratios("0.5,0.5")


def _fixture_rows():
    domains = {
        "algebra": "Mathematics -> Algebra",
        "number_theory": "Mathematics -> Number Theory",
        "geometry": "Mathematics -> Geometry",
        "discrete_mathematics": "Mathematics -> Discrete Mathematics",
    }
    for bucket in OMNIMATH_DOMAIN_BUCKETS:
        for offset in range(8):
            yield {
                "domain": [domains[bucket]],
                "difficulty": 9.0,
                "problem": f"{bucket} problem {offset}",
                "solution": f"solution {offset}",
                "answer": str(offset),
                "source": "fixture",
            }


def test_preregistered_partitions_are_stratified_deterministic_and_disjoint(
    tmp_path,
) -> None:
    path = tmp_path / "omni.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in _fixture_rows()),
        encoding="utf-8",
    )
    problems = load_omnimath_rule(path, verify_pinned=False)

    first = select_omnimath_partitions(
        problems,
        difficulty_band=(8.0, 10.0),
        seed=17,
    )
    second = select_omnimath_partitions(
        problems,
        difficulty_band=(8.0, 10.0),
        seed=17,
    )

    assert first == second
    assert {name: len(values) for name, values in first.items()} == {
        "probe": 8,
        "screen": 12,
        "confirm": 8,
    }
    identifiers = [
        {problem.problem_id for problem in first[name]}
        for name in ("probe", "screen", "confirm")
    ]
    assert identifiers[0].isdisjoint(identifiers[1])
    assert identifiers[0].isdisjoint(identifiers[2])
    assert identifiers[1].isdisjoint(identifiers[2])
    assert all(
        [problem.domain_bucket for problem in first["screen"]].count(bucket) == 3
        for bucket in OMNIMATH_DOMAIN_BUCKETS
    )


def test_probe_gate_matches_preregistered_branches() -> None:
    assert difficulty_band_from_probe(0) == (6.0, 8.0)
    assert difficulty_band_from_probe(2) == (8.0, 10.0)
    assert difficulty_band_from_probe(6) == (8.0, 10.0)
    assert difficulty_band_from_probe(8) == (9.0, 10.0)


def _record(arm, problem_index, correct, slots, seconds, ess=None):
    diagnostics = {}
    if ess is not None:
        diagnostics["mean_candidate_ess_fraction"] = ess
    return {
        "arm": arm,
        "problem_index": problem_index,
        "correct": correct,
        "elapsed_seconds": seconds,
        "output_tokens": 8,
        "ended_with_eos": True,
        "length_truncated": False,
        "prediction": "1",
        "backend_delta": {
            "generation_forward_token_slots": slots,
            "score_forward_token_slots": 0,
            "estimated_dense_forward_flops": slots * 10,
        },
        "diagnostics": diagnostics,
    }


def test_screen_summary_uses_quality_then_natural_compute_for_top_two() -> None:
    records = [
        _record("base", 0, False, 10, 1.0),
        _record("base", 1, True, 10, 1.0),
        _record("is-cr0250", 0, True, 40, 4.0, 0.8),
        _record("is-cr0250", 1, True, 40, 4.0, 0.8),
        _record("is-cr0500", 0, True, 20, 2.0, 0.7),
        _record("is-cr0500", 1, True, 20, 2.0, 0.7),
        _record("is-cr1000", 0, False, 10, 1.0, 0.9),
        _record("is-cr1000", 1, True, 10, 1.0, 0.9),
    ]
    manifest = {
        "fingerprint": "abc",
        "phase": "screen",
        "seed": 11,
        "arms": ["base", "is-cr0250", "is-cr0500", "is-cr1000"],
    }

    summary = build_summary(records, manifest, bootstrap_replicates=100)

    assert summary["recommended_top2"] == ["is-cr0500", "is-cr0250"]
    assert summary["paired_accuracy"]["is-cr0250_minus_base"]["difference"] == 0.5


def test_confirm_decision_uses_pooled_quality_then_ten_percent_cost_rule() -> None:
    ratios = {"is-cr0250": 0.25, "is-cr0500": 0.5}
    confirm = [
        {
            **_record(arm, index + 10, index == 0, 100, 1.0, 0.8),
            "problem_id": f"confirm-{index}",
        }
        for arm in ratios
        for index in range(2)
    ]
    screen = [
        {
            **_record(arm, index, index == 0, 100 if arm == "is-cr0250" else 104, 1.0, 0.8),
            "problem_id": f"screen-{index}",
        }
        for arm in ratios
        for index in range(2)
    ]

    decision = build_confirm_decision(confirm, screen, ratios)

    assert decision["winner"] == "is-cr0250"
    assert decision["basis"] == "cost_within_10_percent_then_closest_to_0.25"
