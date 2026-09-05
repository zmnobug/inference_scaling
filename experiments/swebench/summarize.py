"""Summarize inference status and API cost from a SWE-bench result directory."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from experiments.swebench.io import atomic_write_json


def _mean(values: Sequence[int | float]) -> float:
    return float(mean(values)) if values else 0.0


def summarize_results(results: Path) -> dict[str, Any]:
    grouped: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(results.glob("*/seed-*/instances/*/record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        grouped[(record["arm_tag"], int(record["seed"]))].append(record)

    groups: list[dict[str, Any]] = []
    for (arm_tag, seed), records in sorted(grouped.items()):
        usages = [record["usage"] for record in records]
        completed = sum(record["status"] == "completed" for record in records)
        groups.append(
            {
                "arm_tag": arm_tag,
                "method": records[0]["method"],
                "seed": seed,
                "instances": len(records),
                "completed": completed,
                "budget_exceeded": sum(
                    record["status"] == "budget_exceeded" for record in records
                ),
                "errors": sum(record["status"] == "error" for record in records),
                "submitted": sum(bool(record.get("submission")) for record in records),
                "mean_api_requests": _mean([item["api_requests"] for item in usages]),
                "total_api_requests": sum(item["api_requests"] for item in usages),
                "mean_input_tokens": _mean([item["input_tokens"] for item in usages]),
                "total_input_tokens": sum(item["input_tokens"] for item in usages),
                "mean_output_tokens": _mean([item["output_tokens"] for item in usages]),
                "total_output_tokens": sum(item["output_tokens"] for item in usages),
                "mean_tool_calls": _mean([item["tool_calls"] for item in usages]),
                "total_tool_calls": sum(item["tool_calls"] for item in usages),
                "mean_api_failures": _mean(
                    [item.get("api_failures", 0) for item in usages]
                ),
                "total_api_failures": sum(
                    item.get("api_failures", 0) for item in usages
                ),
                "mean_tool_failures": _mean(
                    [item.get("tool_failures", 0) for item in usages]
                ),
                "total_tool_failures": sum(
                    item.get("tool_failures", 0) for item in usages
                ),
                "mean_api_seconds": _mean(
                    [item.get("api_seconds", 0.0) for item in usages]
                ),
                "total_api_seconds": sum(
                    item.get("api_seconds", 0.0) for item in usages
                ),
                "mean_tool_seconds": _mean(
                    [item.get("tool_seconds", 0.0) for item in usages]
                ),
                "total_tool_seconds": sum(
                    item.get("tool_seconds", 0.0) for item in usages
                ),
                "mean_wall_seconds": _mean([item["elapsed_seconds"] for item in usages]),
                "total_wall_seconds": sum(item["elapsed_seconds"] for item in usages),
            }
        )
    return {"groups": groups, "group_count": len(groups)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = summarize_results(args.results)
    output = args.output or args.results / "inference_summary.json"
    atomic_write_json(output, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
