from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from inference_scaling.swebench.config import ExperimentArm

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


def test_dry_run_does_not_write_result_artifacts(
    tmp_path: Path, monkeypatch
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
        ],
    )

    run_suite.main()

    assert not output.exists()
