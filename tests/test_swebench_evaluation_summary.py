from __future__ import annotations

import json
from pathlib import Path

from experiments.swebench.evaluation_summary import (
    summarize_evaluations,
    wilson_interval,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _arm(tag: str, method: str, alpha: float, candidate_count: int | None) -> dict:
    return {
        "tag": tag,
        "config": {
            "method": method,
            "alpha": alpha,
            "candidate_count": candidate_count,
            "chunk_tokens": 256,
            "rollout_count": 1,
            "updates_per_chain": None,
            "max_suffix_actions": None,
            "suffix_schedule": None,
            "chains": None,
        },
    }


def _record(tag: str, instance: str, tokens: int, ess: float) -> dict:
    return {
        "arm_tag": tag,
        "seed": 7,
        "status": "completed",
        "usage": {"input_tokens": tokens, "output_tokens": 10},
        "diagnostics": {"steps": [{"ess": ess, "weights": [0.5, 0.5]}]},
        "instance_id": instance,
    }


def _report(resolved_ids: list[str]) -> dict:
    all_ids = ["one", "two"]
    return {
        "total_instances": 2,
        "resolved_instances": len(resolved_ids),
        "error_instances": 0,
        "infra_failure_instances": 0,
        "submitted_ids": all_ids,
        "resolved_ids": resolved_ids,
    }


def test_evaluation_summary_ranks_and_emits_config_overrides(tmp_path: Path) -> None:
    arms = [
        _arm("base", "base", 1.0, None),
        _arm("is-cheap", "is", 1.25, 2),
        _arm("is-costly", "is", 1.5, 4),
    ]
    _write_json(
        tmp_path / "manifest.json",
        {
            "profile": "calibrate",
            "seeds": [7],
            "dataset": {"instance_ids": ["one", "two"]},
            "arms": arms,
        },
    )
    for tag, tokens, ess, resolved in (
        ("base", 50, 2.0, []),
        ("is-cheap", 100, 1.5, ["one"]),
        ("is-costly", 300, 2.0, ["one"]),
    ):
        for instance in ("one", "two"):
            _write_json(
                tmp_path / tag / "seed-7" / "instances" / instance / "record.json",
                _record(tag, instance, tokens, ess),
            )
        _write_json(
            tmp_path / "evaluation" / "reports" / tag / "seed-7.json",
            _report(resolved),
        )

    summary = summarize_evaluations(tmp_path)
    recommendation = summary["recommendations"]["is"]
    assert recommendation["recommended_arms"] == ["is-cheap", "is-costly"]
    assert (
        recommendation["config_overrides"]["conditional_is.reference_candidate_count"]
        == 2
    )
    assert recommendation["config_overrides"]["shortlist.is_candidate_count"] == 4
    cheap = next(group for group in summary["groups"] if group["arm_tag"] == "is-cheap")
    assert cheap["mean_normalized_ess"] == 0.75
    assert cheap["paired_vs_base"]["resolved_rate_difference"] == 0.5
    assert cheap["paired_vs_base"]["paired_instances"] == 2

    _write_json(
        tmp_path / "is-cheap" / "seed-7" / "instances" / "stale" / "record.json",
        _record("is-cheap", "stale", 1, 2.0),
    )
    summary_with_stale_record = summarize_evaluations(tmp_path)
    cheap_with_stale_record = next(
        group
        for group in summary_with_stale_record["groups"]
        if group["arm_tag"] == "is-cheap"
    )
    assert cheap_with_stale_record["unexpected_inference_records"] == 1
    assert cheap_with_stale_record["eligible"] is False


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(3, 5)
    assert lower < 0.6 < upper
