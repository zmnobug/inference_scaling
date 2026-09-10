"""Join official SWE-bench outcomes with inference cost and sampler diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return (max(0.0, center - radius), min(1.0, center + radius))


def _records(results: Path, arm_tag: str, seed: int) -> list[dict[str, Any]]:
    pattern = f"{arm_tag}/seed-{seed}/instances/*/record.json"
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(results.glob(pattern))
    ]


def _mean(values: Sequence[float]) -> float | None:
    return float(mean(values)) if values else None


def _sampler_diagnostics(
    method: str, records: Sequence[Mapping[str, Any]]
) -> dict[str, float | None]:
    normalized_ess: list[float] = []
    acceptance_rates: list[float] = []
    for record in records:
        diagnostics = record.get("diagnostics", {})
        if not isinstance(diagnostics, Mapping):
            continue
        if method == "is":
            steps = diagnostics.get("steps", ())
            if isinstance(steps, Sequence):
                for step in steps:
                    if not isinstance(step, Mapping):
                        continue
                    weights = step.get("weights", ())
                    if isinstance(weights, Sequence) and weights:
                        normalized_ess.append(float(step["ess"]) / len(weights))
        elif method == "mh" and "aggregate_acceptance_rate" in diagnostics:
            acceptance_rates.append(float(diagnostics["aggregate_acceptance_rate"]))
    return {
        "mean_normalized_ess": _mean(normalized_ess),
        "mean_mh_acceptance_rate": _mean(acceptance_rates),
    }


def _paired_bootstrap(
    arm_tag: str,
    arm_outcomes: Mapping[tuple[str, int], int],
    base_outcomes: Mapping[tuple[str, int], int],
    *,
    draws: int = 10_000,
) -> dict[str, Any]:
    common = sorted(set(arm_outcomes) & set(base_outcomes))
    clustered: defaultdict[str, list[float]] = defaultdict(list)
    for instance_id, seed in common:
        clustered[instance_id].append(
            float(
                arm_outcomes[(instance_id, seed)] - base_outcomes[(instance_id, seed)]
            )
        )
    instance_differences = [
        float(mean(values)) for _, values in sorted(clustered.items())
    ]
    if not instance_differences:
        return {
            "paired_observations": 0,
            "paired_instances": 0,
            "resolved_rate_difference": None,
            "cluster_bootstrap_95": None,
        }
    digest = hashlib.sha256(arm_tag.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    bootstrap = sorted(
        sum(rng.choice(instance_differences) for _ in instance_differences)
        / len(instance_differences)
        for _ in range(draws)
    )
    lower = bootstrap[int(0.025 * (draws - 1))]
    upper = bootstrap[int(0.975 * (draws - 1))]
    return {
        "paired_observations": len(common),
        "paired_instances": len(instance_differences),
        "resolved_rate_difference": float(mean(instance_differences)),
        "cluster_bootstrap_95": [lower, upper],
    }


def summarize_evaluations(results: Path) -> dict[str, Any]:
    manifest = json.loads((results / "manifest.json").read_text(encoding="utf-8"))
    expected_instance_ids = {
        str(instance_id) for instance_id in manifest["dataset"]["instance_ids"]
    }
    expected_record_keys = {
        (instance_id, int(seed))
        for instance_id in expected_instance_ids
        for seed in manifest["seeds"]
    }
    arm_configs = {str(arm["tag"]): dict(arm["config"]) for arm in manifest["arms"]}
    groups: list[dict[str, Any]] = []
    outcomes_by_arm: dict[str, dict[tuple[str, int], int]] = {}
    for arm_tag, arm_config in arm_configs.items():
        method = str(arm_config["method"])
        arm_records: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        missing_reports: list[int] = []
        outcomes: dict[tuple[str, int], int] = {}
        for seed in manifest["seeds"]:
            arm_records.extend(_records(results, arm_tag, int(seed)))
            report_path = (
                results / "evaluation" / "reports" / arm_tag / f"seed-{seed}.json"
            )
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                reports.append(report)
                resolved_ids = set(report.get("resolved_ids", ()))
                for instance_id in report.get("submitted_ids", ()):
                    outcomes[(str(instance_id), int(seed))] = int(
                        instance_id in resolved_ids
                    )
            else:
                missing_reports.append(int(seed))

        actual_record_keys = {
            (str(record.get("instance_id", "")), int(record.get("seed", -1)))
            for record in arm_records
        }
        missing_inference_records = len(expected_record_keys - actual_record_keys)
        unexpected_inference_records = len(actual_record_keys - expected_record_keys)
        duplicate_inference_records = len(arm_records) - len(actual_record_keys)
        resolved = sum(int(report["resolved_instances"]) for report in reports)
        total = sum(int(report["total_instances"]) for report in reports)
        evaluator_errors = sum(int(report["error_instances"]) for report in reports)
        infra_failures = sum(
            int(report.get("infra_failure_instances", 0)) for report in reports
        )
        inference_errors = sum(
            record.get("status") == "error" for record in arm_records
        )
        budget_exceeded = sum(
            record.get("status") == "budget_exceeded" for record in arm_records
        )
        total_input_tokens = sum(
            int(record.get("usage", {}).get("input_tokens", 0))
            for record in arm_records
        )
        total_output_tokens = sum(
            int(record.get("usage", {}).get("output_tokens", 0))
            for record in arm_records
        )
        total_raw_output_tokens = sum(
            int(
                record.get("usage", {}).get(
                    "raw_output_tokens",
                    record.get("usage", {}).get("output_tokens", 0),
                )
            )
            for record in arm_records
        )
        total_dropped_hidden_tokens = sum(
            int(record.get("usage", {}).get("dropped_hidden_tokens", 0))
            for record in arm_records
        )
        interval = wilson_interval(resolved, total)
        diagnostics = _sampler_diagnostics(method, arm_records)
        warnings: list[str] = []
        if (
            diagnostics["mean_normalized_ess"] is not None
            and float(diagnostics["mean_normalized_ess"]) < 0.25
        ):
            warnings.append("low_normalized_ess")
        acceptance = diagnostics["mean_mh_acceptance_rate"]
        if acceptance is not None and (
            float(acceptance) < 0.05 or float(acceptance) > 0.95
        ):
            warnings.append("degenerate_mh_acceptance")
        eligible = not (
            missing_reports
            or missing_inference_records
            or unexpected_inference_records
            or duplicate_inference_records
            or inference_errors
            or budget_exceeded
            or evaluator_errors
            or infra_failures
        )
        groups.append(
            {
                "arm_tag": arm_tag,
                "method": method,
                "arm": arm_config,
                "evaluation_reports": len(reports),
                "missing_report_seeds": missing_reports,
                "observations": total,
                "resolved": resolved,
                "resolved_rate": resolved / total if total else 0.0,
                "wilson_95": list(interval),
                "inference_errors": inference_errors,
                "inference_records": len(arm_records),
                "missing_inference_records": missing_inference_records,
                "unexpected_inference_records": unexpected_inference_records,
                "duplicate_inference_records": duplicate_inference_records,
                "budget_exceeded": budget_exceeded,
                "evaluator_errors": evaluator_errors,
                "infra_failures": infra_failures,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_raw_output_tokens": total_raw_output_tokens,
                "total_dropped_hidden_tokens": total_dropped_hidden_tokens,
                "total_api_tokens": total_input_tokens + total_raw_output_tokens,
                "mean_api_tokens_per_record": (
                    (total_input_tokens + total_raw_output_tokens) / len(arm_records)
                    if arm_records
                    else None
                ),
                **diagnostics,
                "warnings": warnings,
                "eligible": eligible,
            }
        )
        outcomes_by_arm[arm_tag] = outcomes

    base_tags = [
        arm_tag
        for arm_tag, arm_config in arm_configs.items()
        if arm_config["method"] == "base"
    ]
    if len(base_tags) == 1:
        base_outcomes = outcomes_by_arm[base_tags[0]]
        for group in groups:
            if group["method"] != "base":
                group["paired_vs_base"] = _paired_bootstrap(
                    str(group["arm_tag"]),
                    outcomes_by_arm[str(group["arm_tag"])],
                    base_outcomes,
                )

    return {
        "schema_version": "swebench-evaluation-summary-v2",
        "groups": groups,
    }
