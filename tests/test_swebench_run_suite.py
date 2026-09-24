from __future__ import annotations

import sys
import json
from dataclasses import replace

import pytest
from pathlib import Path
from types import SimpleNamespace

from inference_scaling.swebench.config import (
    ExperimentArm,
    instance_fingerprint,
    load_experiment_config,
)
from inference_scaling.swebench.runner import RESULT_SCHEMA_VERSION

from experiments.swebench import run_suite
from experiments.swebench.run_suite import _select_incomplete_instance_batch


def test_instance_batch_advances_past_completed_instances() -> None:
    instances = [
        {"instance_id": "one"},
        {"instance_id": "two"},
        {"instance_id": "three"},
        {"instance_id": "four"},
    ]

    selected = _select_incomplete_instance_batch(
        instances,
        batch_size=2,
        is_complete=lambda instance: instance["instance_id"] in {"one", "three"},
    )

    assert [instance["instance_id"] for instance in selected] == ["two", "four"]


@pytest.mark.parametrize("previous_schema", [None, "swebench-is-mh-v5"])
@pytest.mark.parametrize("redo", [False, True])
def test_dry_run_does_not_write_result_artifacts(
    tmp_path: Path, monkeypatch, previous_schema, redo
) -> None:
    experiment = SimpleNamespace(
        path=tmp_path / "config.toml",
        fingerprint="config",
        run=SimpleNamespace(
            output_root=tmp_path / "unused",
            tag="dry-run",
            subset="verified",
            split="test",
            dataset_revision="revision",
            instance_filter="",
            instance_slice="",
            seeds=(7,),
            workers=1,
            environment_class="docker",
        ),
        arms=(ExperimentArm(method="base", chunk_tokens=64),),
    )
    output = tmp_path / "results"
    monkeypatch.setattr(run_suite, "load_experiment_config", lambda *args: experiment)
    monkeypatch.setattr(
        run_suite,
        "_load_instances",
        lambda *args: [{"instance_id": "instance", "problem_statement": "problem"}],
    )
    monkeypatch.setattr(run_suite, "validate_evaluator_instances", lambda *args: None)
    monkeypatch.setattr(
        run_suite,
        "build_manifest",
        lambda **kwargs: {
            "schema_version": "swebench-is-mh-v7",
            "config_fingerprint": "config",
            "dataset": {},
            "arms": [],
            "seeds": [7],
            "model": {"runtime_fingerprint": kwargs["runtime_fingerprint"]},
        },
    )
    monkeypatch.setattr(
        run_suite,
        "_write_dataset_snapshot",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected snapshot write")),
    )
    monkeypatch.setattr(
        run_suite,
        "atomic_write_json",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected JSON write")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_suite",
            "--config",
            str(tmp_path / "config.toml"),
            "--output",
            str(output),
            "--dry-run",
            *(["--redo"] if redo else []),
        ],
    )

    if previous_schema:
        (output / experiment.run.tag).mkdir(parents=True)
        previous = {
            "schema_version": previous_schema, "config_fingerprint": "config",
            "dataset": {}, "arms": [], "seeds": [7],
        }
        manifest_path = output / experiment.run.tag / "manifest.json"
        manifest_path.write_text(json.dumps(previous))
        with pytest.raises(RuntimeError, match="choose a new tag or output directory"):
            run_suite.main()
        assert json.loads(manifest_path.read_text()) == previous
    else:
        run_suite.main()
        assert not output.exists()


@pytest.mark.parametrize("scenario", ["changed_config", "stale_record", "same_run"])
def test_redo_batch_preserves_experiment_identity(tmp_path, monkeypatch, scenario):
    from experiments.swebench.io import atomic_write_json, build_manifest

    original = load_experiment_config("configs/swebench_api.example.toml")
    experiment = replace(
        original,
        run=replace(original.run, output_root=tmp_path, instance_slice="", seeds=(7,)),
        arms=(original.arms[0],),
    )
    monkeypatch.setenv(experiment.api.base_url_env, "http://localhost:8000/v1")
    monkeypatch.setenv(experiment.api.api_key_env, "test")
    monkeypatch.delenv(experiment.api.extra_headers_env, raising=False)
    runtime_fingerprint = experiment.api.resolve_runtime()["fingerprint"]
    instances = [{"instance_id": "case-a"}, {"instance_id": "case-b"}]
    arm = experiment.arms[0]
    root = tmp_path / experiment.run.tag
    manifest = build_manifest(
        repository_root=run_suite.REPOSITORY_ROOT, experiment=experiment,
        arms=experiment.arms, seeds=(7,), instances=instances,
        dataset_name=run_suite.resolve_dataset_name(experiment.run.subset),
        runtime_fingerprint=runtime_fingerprint,
    )
    if scenario == "changed_config":
        manifest["config_fingerprint"] = "old-config"
    atomic_write_json(root / "manifest.json", manifest)
    (root / "dataset.parquet").write_bytes(b"old snapshot")

    def record(instance, submission):
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "instance_id": instance["instance_id"],
            "instance_fingerprint": instance_fingerprint(instance),
            "arm_fingerprint": arm.fingerprint,
            "config_fingerprint": experiment.fingerprint,
            "runtime_fingerprint": runtime_fingerprint,
            "seed": 7, "status": "completed",
            "model_name_or_path": experiment.api.model_name,
            "submission": submission,
        }

    for instance in instances:
        previous = record(instance, "old patch")
        if scenario == "stale_record" and instance["instance_id"] == "case-b":
            previous["runtime_fingerprint"] = "other-server"
        atomic_write_json(root / "base/seed-7/instances" / instance["instance_id"] / "record.json", previous)
    monkeypatch.setattr(run_suite, "load_experiment_config", lambda path: experiment)
    monkeypatch.setattr(run_suite, "_load_instances", lambda *args: instances)
    monkeypatch.setattr(run_suite, "validate_evaluator_instances", lambda *args: None)
    monkeypatch.setattr(run_suite, "_write_dataset_snapshot", lambda path, rows: path.write_bytes(b"new snapshot"))
    calls = []

    def run_job(config, instance, selected_arm, seed):
        calls.append(instance["instance_id"])
        return record(instance, "new patch")

    monkeypatch.setattr("inference_scaling.swebench.runner.run_experiment_arm", run_job)
    monkeypatch.setattr("experiments.swebench.summarize.summarize_results", lambda root: {})
    monkeypatch.setattr(sys, "argv", ["run_suite", "--config", str(original.path), "--redo", "--batch-instances", "1"])

    if scenario == "changed_config":
        with pytest.raises(RuntimeError, match="choose a new tag or output directory"):
            run_suite.main()
        assert calls == []
        assert json.loads((root / "manifest.json").read_text()) == manifest
        assert (root / "dataset.parquet").read_bytes() == b"old snapshot"
        return

    run_suite.main()
    predictions = json.loads((root / "base/seed-7/preds.json").read_text())
    assert calls == ["case-a"]
    assert predictions["case-a"]["model_patch"] == "new patch"
    if scenario == "stale_record":
        assert "case-b" not in predictions
    else:
        assert predictions["case-b"]["model_patch"] == "old patch"
