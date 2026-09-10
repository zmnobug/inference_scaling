from __future__ import annotations

from pathlib import Path

import pytest

from experiments.swebench import evaluate
from experiments.swebench.dataset import (
    canonical_image_name,
    validate_evaluator_instances,
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


def test_native_snapshot_is_validated_without_rewriting(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "dataset.parquet"
    source.write_bytes(b"native")
    monkeypatch.setattr(evaluate, "_load_parquet_rows", lambda path: [_v5_row()])

    path, provenance = evaluate.prepare_evaluation_dataset(
        snapshot=source,
        source_revision="dataset-revision",
        expected_instance_ids={"django__django-12308"},
    )

    assert path == source
    assert source.read_bytes() == b"native"
    assert provenance["mode"] == "native_swebench_5_dataset"
    assert provenance["revision"] == "dataset-revision"
    assert provenance["instance_count"] == 1
