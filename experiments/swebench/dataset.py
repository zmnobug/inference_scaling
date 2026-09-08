"""Pinned SWE-bench dataset names and evaluator-schema compatibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DATASET_MAPPING = {
    "verified": "SWE-bench/SWE-bench_Verified",
    "lite": "SWE-bench/SWE-bench_Lite",
    "full": "SWE-bench/SWE-bench",
}

# SWE-bench 5.0 moved evaluator metadata into the dataset rows. This revision
# is the compatible 500-row Verified snapshot pinned by this experiment.
VERIFIED_V5_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"

EVALUATOR_REQUIRED_FIELDS = frozenset(
    {
        "instance_id",
        "image",
        "repo",
        "version",
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "log_parser",
        "eval_type",
        "eval_script",
    }
)

INFERENCE_IDENTITY_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "version",
)


def resolve_dataset_name(subset: str) -> str:
    return DATASET_MAPPING.get(subset, subset)


def canonical_image_name(instance_id: str) -> str:
    """Return the image name published by the SWE-bench 5.x task dataset."""

    key = f"sweb.eval.x86_64.{instance_id}:latest".lower()
    return f"swebench/{key}".replace("__", "_1776_")


def missing_evaluator_fields(instance: Mapping[str, Any]) -> set[str]:
    return {
        field
        for field in EVALUATOR_REQUIRED_FIELDS
        if field not in instance or instance[field] is None
    }


def validate_evaluator_instances(
    instances: Sequence[Mapping[str, Any]],
    expected_instance_ids: set[str],
) -> None:
    actual = [str(instance.get("instance_id", "")) for instance in instances]
    if len(actual) != len(set(actual)):
        raise ValueError("evaluation dataset contains duplicate instance IDs")
    if set(actual) != expected_instance_ids:
        raise ValueError(
            "evaluation dataset instance IDs differ from the run manifest"
        )
    for instance in instances:
        missing = missing_evaluator_fields(instance)
        if missing:
            raise ValueError(
                f"{instance.get('instance_id', '<unknown>')} is missing SWE-bench "
                f"5.x evaluator fields: {sorted(missing)}"
            )
        expected_image = canonical_image_name(str(instance["instance_id"]))
        if str(instance["image"]) != expected_image:
            raise ValueError(
                f"unexpected evaluator image for {instance['instance_id']}: "
                f"{instance['image']!r} != {expected_image!r}"
            )


def verify_inference_identity(
    original: Sequence[Mapping[str, Any]],
    compatible: Sequence[Mapping[str, Any]],
) -> None:
    """Prove that a v5 evaluation snapshot represents the inferred tasks."""

    original_by_id = {
        str(instance["instance_id"]): instance for instance in original
    }
    compatible_by_id = {
        str(instance["instance_id"]): instance for instance in compatible
    }
    if set(original_by_id) != set(compatible_by_id):
        raise ValueError(
            "compatible evaluation dataset has different instance IDs"
        )
    for instance_id, source in original_by_id.items():
        target = compatible_by_id[instance_id]
        changed = [
            field
            for field in INFERENCE_IDENTITY_FIELDS
            if str(source.get(field, "")) != str(target.get(field, ""))
        ]
        if changed:
            raise ValueError(
                f"compatible evaluation row {instance_id} changes inference "
                f"identity fields: {changed}"
            )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_rows(instances: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        [dict(instance) for instance in instances],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
