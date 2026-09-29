"""Freeze a two-service partition and aggregate official results with case timings."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from statistics import mean, median

from experiments.swebench.io import atomic_write_json
from inference_scaling.swebench.config import load_experiment_config


def partition(instance_ids: list[str], expected_count: int = 30) -> dict[str, list[str]]:
    if expected_count < 2:
        raise ValueError("expected count must be at least 2")
    if len(instance_ids) != expected_count or len(set(instance_ids)) != expected_count:
        raise ValueError(f"expected exactly {expected_count} distinct instances")
    ordered = sorted(instance_ids)
    return {"shard_a": ordered[::2], "shard_b": ordered[1::2]}


def prepare(output: Path, config: Path, selection: Path, expected_count: int = 30) -> None:
    experiment = load_experiment_config(config)
    instance_ids = selection.read_text().splitlines()
    shards = partition(instance_ids, expected_count)
    if experiment.agent.wall_time_limit_seconds or experiment.budget.max_wall_seconds:
        raise ValueError("dual-service run must not have a case wall-time limit")
    if not all(re.fullmatch(experiment.run.instance_filter, name) for name in instance_ids):
        raise ValueError("selection does not match the configured filter")
    if (output / "assignment.json").exists():
        raise FileExistsError("refusing to overwrite existing shard assignments")
    output.mkdir(parents=True, exist_ok=True)
    for name, assigned in shards.items():
        with (output / f"{name}_instances.txt").open("x") as handle:
            handle.write("\n".join(assigned) + "\n")
    atomic_write_json(output / "assignment.json", {
        "started_at": time.time(),
        "expected_count": expected_count,
        "config_fingerprint": experiment.fingerprint,
        "instance_ids": sorted(instance_ids),
        "shards": {
            name: {"instance_ids": assigned, "base_url": f"http://127.0.0.1:{port}/v1"}
            for (name, assigned), port in zip(shards.items(), (8000, 8001), strict=True)
        },
    })


def timing_stats(rows: list[dict]) -> dict:
    agent_times = [row["agent_seconds"] for row in rows if row["agent_seconds"] is not None]
    return {
        "cases": len(rows),
        "recorded_agent_times": len(agent_times),
        "mean_agent_seconds": mean(agent_times) if agent_times else None,
        "median_agent_seconds": median(agent_times) if agent_times else None,
        "max_agent_seconds": max(agent_times) if agent_times else None,
        "cases_over_30_minutes": sum(value > 1800 for value in agent_times),
        "total_runner_seconds": sum(row["runner_seconds"] for row in rows),
    }


def summarize(output: Path, config: Path) -> dict:
    experiment = load_experiment_config(config)
    assignment = json.loads((output / "assignment.json").read_text())
    expected = partition(assignment["instance_ids"], assignment.get("expected_count", 30))
    if assignment["config_fingerprint"] != experiment.fingerprint:
        raise ValueError("configuration changed after launch")
    arm = experiment.arms[0]
    seed = experiment.run.seeds[0]
    relative = Path(arm.tag) / f"seed-{seed}"
    rows, sources = [], []
    for name, assigned in expected.items():
        if assignment["shards"][name]["instance_ids"] != assigned:
            raise ValueError("shard assignment changed")
        root = output / name / experiment.run.tag
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["dataset"]["instance_ids"] != assigned or manifest["config_fingerprint"] != experiment.fingerprint:
            raise ValueError(f"unexpected manifest in {name}")
        report_path = root / "evaluation" / "reports" / arm.tag / f"seed-{seed}.json"
        report = json.loads(report_path.read_text())
        if set(report["submitted_ids"]) != set(assigned) or not set(report["resolved_ids"]) <= set(assigned):
            raise ValueError(f"official report does not cover exactly {name}")
        paths = sorted((root / relative / "instances").glob("*/record.json"))
        if sorted(path.parent.name for path in paths) != assigned:
            raise ValueError(f"missing or unexpected records in {name}")
        sources.append({"shard": name, "report": str(report_path),
                        "runtime_fingerprint": manifest["model"]["runtime_fingerprint"],
                        "evaluator_errors": report["error_instances"]})
        for path in paths:
            record = json.loads(path.read_text())
            if (record["instance_id"] != path.parent.name or record["seed"] != seed
                    or record["arm_tag"] != arm.tag or record["arm_fingerprint"] != arm.fingerprint
                    or record["config_fingerprint"] != experiment.fingerprint
                    or record["runtime_fingerprint"] != manifest["model"]["runtime_fingerprint"]
                    or not record.get("finished_at")):
                raise ValueError(f"record provenance mismatch: {path}")
            usage = record["usage"]
            rows.append({
                "instance_id": record["instance_id"], "shard": name,
                "resolved": record["instance_id"] in report["resolved_ids"],
                "status": record["status"], "exit_status": record["exit_status"],
                "agent_seconds": record.get("diagnostics", {}).get("limits", {}).get("agent_seconds"),
                "runner_seconds": usage["elapsed_seconds"],
                "api_seconds": usage["api_seconds"], "tool_seconds": usage["tool_seconds"],
                "api_requests": usage["api_requests"], "tool_calls": usage["tool_calls"],
                "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            })
    rows.sort(key=lambda row: row["instance_id"])
    temporary = output / "case_timings.csv.tmp"
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output / "case_timings.csv")
    passed = [row for row in rows if row["resolved"]]
    failed = [row for row in rows if not row["resolved"]]
    summary = {
        "aggregation_only": True, "instances": len(rows), "resolved": len(passed),
        "resolved_rate": len(passed) / len(rows), "sources": sources,
        "inference_errors": sum(row["status"] == "error" for row in rows),
        "evaluator_errors": sum(source["evaluator_errors"] for source in sources),
        "all": timing_stats(rows), "passed": timing_stats(passed), "failed": timing_stats(failed),
        "batch_wall_seconds": time.time() - assignment["started_at"],
        "finished_at": time.time(),
    }
    atomic_write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "summarize"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--expected-count", type=int, default=30)
    args = parser.parse_args()
    if args.operation == "prepare":
        if args.selection is None:
            parser.error("prepare requires --selection")
        prepare(args.output, args.config, args.selection, args.expected_count)
    else:
        print(json.dumps(summarize(args.output, args.config), indent=2))


if __name__ == "__main__":
    main()
