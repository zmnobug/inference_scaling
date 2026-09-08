from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.swebench import evaluate
from experiments.swebench.dataset import (
    canonical_image_name,
    validate_evaluator_instances,
    verify_inference_identity,
)


def _v5_row(instance_id: str = "django__django-12308") -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "image": canonical_image_name(instance_id),
        "repo": "django/django",
        "base_commit": "base",
        "problem_statement": "problem",
        "version": "3.0",
        "FAIL_TO_PASS": ["test_fails"],
        "PASS_TO_PASS": ["test_passes"],
        "log_parser": "pytest",
        "eval_type": "pass_and_fail",
        "eval_script": "echo test",
    }


def test_canonical_image_name_uses_published_dunder_encoding() -> None:
    assert canonical_image_name("django__django-12308") == (
        "swebench/sweb.eval.x86_64.django_1776_django-12308:latest"
    )


def test_evaluator_schema_rejects_noncanonical_image() -> None:
    row = _v5_row()
    row["image"] = "swebench/wrong:latest"
    with pytest.raises(ValueError, match="unexpected evaluator image"):
        validate_evaluator_instances([row], {"django__django-12308"})


def test_identity_check_rejects_changed_problem_statement() -> None:
    source = _v5_row()
    compatible = _v5_row()
    compatible["problem_statement"] = "different"
    with pytest.raises(ValueError, match="problem_statement"):
        verify_inference_identity([source], [compatible])


def test_legacy_snapshot_is_derived_without_overwriting_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "dataset.parquet"
    source.write_bytes(b"legacy")
    output = tmp_path / "dataset.evaluation.parquet"
    legacy_row = {
        key: value
        for key, value in _v5_row().items()
        if key not in {"image", "log_parser", "eval_type", "eval_script"}
    }
    compatible_row = _v5_row()
    monkeypatch.setattr(evaluate, "_load_parquet_rows", lambda path: [legacy_row])
    monkeypatch.setattr(
        evaluate,
        "_load_compatible_rows",
        lambda subset, split, ids: [compatible_row],
    )

    class FakeDataset:
        def __init__(self, rows) -> None:
            self.rows = rows

        @classmethod
        def from_list(cls, rows):
            return cls(rows)

        def to_parquet(self, path: Path) -> None:
            Path(path).write_bytes(b"compatible")

    monkeypatch.setitem(
        sys.modules, "datasets", SimpleNamespace(Dataset=FakeDataset)
    )
    path, provenance = evaluate.prepare_evaluation_dataset(
        snapshot=source,
        output=output,
        subset="verified",
        split="test",
        source_revision="legacy-revision",
        expected_instance_ids={"django__django-12308"},
    )

    assert path == output
    assert source.read_bytes() == b"legacy"
    assert output.read_bytes() == b"compatible"
    assert provenance["mode"] == "derived_swebench_5_evaluation_snapshot"
    assert provenance["missing_source_fields"] == [
        "eval_script",
        "eval_type",
        "image",
        "log_parser",
    ]
