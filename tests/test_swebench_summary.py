from __future__ import annotations

import json
from pathlib import Path

from experiments.swebench.summarize import summarize_results


def _write_record(
    root: Path,
    instance_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    elapsed_seconds: float,
) -> None:
    path = root / "base" / "seed-7" / "instances" / instance_id / "record.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "arm_tag": "base",
                "method": "base",
                "seed": 7,
                "status": "completed",
                "submission": "patch",
                "usage": {
                    "api_requests": 2,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "raw_output_tokens": output_tokens + 1,
                    "dropped_hidden_tokens": 1,
                    "tool_calls": 3,
                    "api_failures": 1,
                    "tool_failures": 0,
                    "state_snapshots": 2,
                    "snapshot_failures": 0,
                    "api_seconds": 1.5,
                    "tool_seconds": 2.5,
                    "snapshot_seconds": 0.5,
                    "elapsed_seconds": elapsed_seconds,
                },
            }
        ),
        encoding="utf-8",
    )


def test_summary_records_natural_resource_totals(tmp_path: Path) -> None:
    _write_record(
        tmp_path,
        "one",
        input_tokens=100,
        output_tokens=10,
        elapsed_seconds=4.0,
    )
    _write_record(
        tmp_path,
        "two",
        input_tokens=300,
        output_tokens=30,
        elapsed_seconds=8.0,
    )

    group = summarize_results(tmp_path)["groups"][0]
    assert group["total_api_requests"] == 4
    assert group["total_input_tokens"] == 400
    assert group["mean_input_tokens"] == 200
    assert group["total_output_tokens"] == 40
    assert group["total_raw_output_tokens"] == 42
    assert group["total_dropped_hidden_tokens"] == 2
    assert group["total_api_tokens"] == 442
    assert group["total_tool_calls"] == 6
    assert group["total_state_snapshots"] == 4
    assert group["total_api_failures"] == 2
    assert group["total_api_seconds"] == 3.0
    assert group["total_tool_seconds"] == 5.0
    assert group["total_snapshot_seconds"] == 1.0
    assert group["total_wall_seconds"] == 12.0
