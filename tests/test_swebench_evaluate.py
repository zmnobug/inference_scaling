from __future__ import annotations

import json
import sys
from pathlib import Path

from experiments.swebench import evaluate


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_evaluator_normalizes_report_and_writes_summary(
    tmp_path: Path, monkeypatch
) -> None:
    _write(
        tmp_path / "manifest.json",
        {
            "dataset": {
                "subset": "verified",
                "split": "test",
                "revision": "dataset-revision",
                "instance_ids": ["instance"],
            },
            "arms": [
                {
                    "tag": "base",
                    "config": {
                        "method": "base",
                        "alpha": 1.0,
                        "candidate_count": None,
                        "chunk_tokens": 256,
                        "rollout_count": None,
                        "updates_per_chain": None,
                        "max_suffix_actions": None,
                        "suffix_schedule": None,
                        "chains": None,
                    },
                }
            ],
            "seeds": [7],
        },
    )
    _write(
        tmp_path / "base" / "seed-7" / "preds.json",
        {
            "instance": {
                "instance_id": "instance",
                "model_name_or_path": "openai/model",
                "model_patch": "patch",
            }
        },
    )
    (tmp_path / "dataset.parquet").write_bytes(b"snapshot")

    monkeypatch.setattr(
        evaluate,
        "prepare_evaluation_dataset",
        lambda **kwargs: (
            tmp_path / "dataset.parquet",
            {"mode": "native_swebench_5_dataset"},
        ),
    )
    _write(
        tmp_path / "base" / "seed-7" / "instances" / "instance" / "record.json",
        {
            "arm_tag": "base",
            "seed": 7,
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "diagnostics": {},
            "instance_id": "instance",
        },
    )

    def fake_run(command, *, cwd, check):
        assert check is True
        assert "swebench.harness.run_evaluation" in command
        _write(
            Path(cwd) / "openai__model.inference-scaling-base-seed7.json",
            {
                "total_instances": 1,
                "resolved_instances": 1,
                "error_instances": 0,
                "infra_failure_instances": 0,
                "submitted_ids": ["instance"],
                "resolved_ids": ["instance"],
            },
        )

    monkeypatch.setattr(evaluate.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate", "--results", str(tmp_path)],
    )
    evaluate.main()

    normalized = tmp_path / "evaluation" / "reports" / "base" / "seed-7.json"
    assert json.loads(normalized.read_text(encoding="utf-8"))["resolved_instances"] == 1
    summary = json.loads(
        (tmp_path / "evaluation_summary.json").read_text(encoding="utf-8")
    )
    assert summary["groups"][0]["resolved_rate"] == 1.0


def test_evaluator_dry_run_does_not_write_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    _write(
        tmp_path / "manifest.json",
        {
            "dataset": {
                "split": "test",
                "revision": "dataset-revision",
                "instance_ids": ["instance"],
            },
            "arms": [{"tag": "base"}],
            "seeds": [7],
        },
    )
    _write(
        tmp_path / "base" / "seed-7" / "preds.json",
        {
            "instance": {
                "instance_id": "instance",
                "model_name_or_path": "openai/model",
                "model_patch": "patch",
            }
        },
    )
    (tmp_path / "dataset.parquet").write_bytes(b"snapshot")
    monkeypatch.setattr(
        evaluate,
        "prepare_evaluation_dataset",
        lambda **kwargs: (
            tmp_path / "dataset.parquet",
            {"mode": "native_swebench_5_dataset"},
        ),
    )
    monkeypatch.setattr(
        evaluate.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected evaluator execution")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate", "--results", str(tmp_path), "--dry-run"],
    )

    evaluate.main()

    assert not (tmp_path / "evaluation").exists()
    assert not (tmp_path / "evaluation_summary.json").exists()
