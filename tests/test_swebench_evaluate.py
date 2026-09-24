from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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
            {"mode": "native_swebench_5_dataset", "sha256": "snapshot-hash"},
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
        run_id = command[command.index("--run_id") + 1]
        assert run_id.startswith("inference-scaling-base-seed7-input-")
        _write(
            Path(cwd) / f"openai__model.{run_id}.json",
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
            {"mode": "native_swebench_5_dataset", "sha256": "snapshot-hash"},
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


@pytest.mark.parametrize("changed_input", ["patch", "dataset", "split"])
def test_evaluation_cache_is_bound_to_inputs(tmp_path, monkeypatch, changed_input):
    manifest = {
        "dataset": {"split": "test", "instance_ids": ["instance"]},
        "arms": [{"tag": "base"}],
        "seeds": [7],
    }
    predictions = {
        "instance": {
            "instance_id": "instance",
            "model_name_or_path": "openai/model",
            "model_patch": "old patch",
        }
    }
    predictions_path = tmp_path / "base/seed-7/preds.json"
    snapshot = tmp_path / "dataset.parquet"
    _write(tmp_path / "manifest.json", manifest)
    _write(predictions_path, predictions)
    snapshot.write_bytes(b"original dataset")
    monkeypatch.setattr(
        evaluate, "prepare_evaluation_dataset",
        lambda **kwargs: (snapshot, {"sha256": evaluate.sha256_file(snapshot)}),
    )
    monkeypatch.setattr(evaluate, "summarize_evaluations", lambda root: {})
    monkeypatch.setattr(sys, "argv", ["evaluate", "--results", str(tmp_path)])
    executions = []
    run_ids = []

    def fake_harness(command, *, cwd, check):
        run_id = command[command.index("--run_id") + 1]
        run_ids.append(run_id)
        report_path = Path(cwd) / f"openai__model.{run_id}.json"
        if report_path.exists():
            return
        executions.append(run_id)
        _write(report_path, {"submitted_ids": ["instance"], "execution": len(executions)})

    monkeypatch.setattr(evaluate.subprocess, "run", fake_harness)
    evaluate.main()
    evaluate.main()
    assert len(executions) == 1
    assert run_ids[0] == run_ids[1]

    if changed_input == "patch":
        predictions["instance"]["model_patch"] = "new patch"
        _write(predictions_path, predictions)
    elif changed_input == "dataset":
        snapshot.write_bytes(b"updated evaluation script")
    else:
        manifest["dataset"]["split"] = "dev"
        _write(tmp_path / "manifest.json", manifest)
    evaluate.main()

    assert len(executions) == 2
    assert run_ids[-1] != run_ids[0]
    normalized = tmp_path / "evaluation/reports/base/seed-7.json"
    assert json.loads(normalized.read_text())["execution"] == 2
