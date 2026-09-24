"""Result layout, atomic writes, and reproducibility helpers."""

from __future__ import annotations

import hashlib
import gzip
import importlib.metadata
import json
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from inference_scaling.swebench.config import (
    ExperimentArm,
    ExperimentConfig,
    instance_fingerprint,
)
from inference_scaling.swebench.runner import RESULT_SCHEMA_VERSION


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def externalize_sampling_details(directory: Path, record: dict[str, Any]) -> None:
    details = record.get("diagnostics", {}).get("thinking_is")
    if not details or "details_path" in details:
        return
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".json.gz.tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as handle:
            json.dump(details, handle, ensure_ascii=False, separators=(",", ":"))
        checksum = _file_sha256(temporary)
        filename = f"thinking_is.{checksum}.json.gz"
        temporary.replace(directory / filename)
    finally:
        temporary.unlink(missing_ok=True)
    record["diagnostics"]["thinking_is"] = {
        **{key: value for key, value in details.items() if key not in {"requests", "rounds"}},
        "request_count": len(details.get("requests", [])),
        "round_count": len(details.get("rounds", [])),
        "details_path": filename,
        "details_sha256": checksum,
        "details_encoding": "gzip-json",
    }


def _sampling_details_path(path: Path, record: Mapping[str, Any]) -> Path | None:
    details = record.get("diagnostics", {}).get("thinking_is", {})
    filename = details.get("details_path")
    if filename is None:
        return None
    if Path(filename).name != filename or details.get("details_encoding") != "gzip-json":
        raise ValueError("invalid sampling diagnostics reference")
    artifact = path.parent / filename
    if _file_sha256(artifact) != details.get("details_sha256"):
        raise ValueError("sampling diagnostics checksum mismatch")
    return artifact


def load_record(path: Path, *, include_sampling_details: bool = False) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if include_sampling_details:
        artifact = _sampling_details_path(path, record)
        if artifact is not None:
            with gzip.open(artifact, "rt", encoding="utf-8") as handle:
                record["diagnostics"]["thinking_is"] = json.load(handle)
    return record


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def result_directory(
    root: Path, arm: ExperimentArm, seed: int, instance_id: str
) -> Path:
    return root / arm.tag / f"seed-{seed}" / "instances" / instance_id


def existing_record_matches(
    path: Path,
    experiment: ExperimentConfig,
    arm: ExperimentArm,
    seed: int,
    instance: Mapping[str, Any],
    *,
    runtime_fingerprint: str | None,
) -> bool:
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        _sampling_details_path(path, record)
    except (OSError, ValueError):
        return False
    return record_matches_experiment(
        record, experiment, arm, seed, instance,
        runtime_fingerprint=runtime_fingerprint,
    ) and record.get("status") in {"completed", "budget_exceeded"}


def record_matches_experiment(
    record: Mapping[str, Any],
    experiment: ExperimentConfig,
    arm: ExperimentArm,
    seed: int,
    instance: Mapping[str, Any],
    *,
    runtime_fingerprint: str | None,
) -> bool:
    return (
        record.get("schema_version") == RESULT_SCHEMA_VERSION
        and record.get("config_fingerprint") == experiment.fingerprint
        and record.get("arm_fingerprint") == arm.fingerprint
        and record.get("instance_fingerprint") == instance_fingerprint(instance)
        and (
            runtime_fingerprint is None
            or record.get("runtime_fingerprint") == runtime_fingerprint
        )
        and record.get("seed") == seed
    )


def rebuild_predictions(
    root: Path,
    arms: Sequence[ExperimentArm],
    seeds: Sequence[int],
    instance_ids: Sequence[str],
    *,
    record_validator: Callable[[Mapping[str, Any], ExperimentArm, int], bool] | None = None,
) -> None:
    allowed_instance_ids = set(instance_ids)
    for arm in arms:
        for seed in seeds:
            seed_root = root / arm.tag / f"seed-{seed}"
            predictions: dict[str, dict[str, str]] = {}
            instance_root = seed_root / "instances"
            if instance_root.is_dir():
                for path in sorted(instance_root.glob("*/record.json")):
                    record = json.loads(path.read_text(encoding="utf-8"))
                    instance_id = str(record["instance_id"])
                    if instance_id not in allowed_instance_ids:
                        continue
                    if path.parent.name != instance_id:
                        continue
                    if record_validator is not None and not record_validator(record, arm, seed):
                        continue
                    predictions[instance_id] = {
                        "model_name_or_path": str(record["model_name_or_path"]),
                        "instance_id": instance_id,
                        "model_patch": str(record.get("submission", "")),
                    }
            atomic_write_json(seed_root / "preds.json", predictions)


def build_manifest(
    *,
    repository_root: Path,
    experiment: ExperimentConfig,
    arms: Sequence[ExperimentArm],
    seeds: Sequence[int],
    instances: Sequence[Mapping[str, Any]],
    dataset_name: str,
    runtime_fingerprint: str | None,
) -> dict[str, Any]:
    instance_ids = [str(instance["instance_id"]) for instance in instances]
    instance_fingerprints = [instance_fingerprint(instance) for instance in instances]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "git_commit": git_revision(repository_root),
        "config_path": str(experiment.path),
        "config_fingerprint": experiment.fingerprint,
        "tag": experiment.run.tag,
        "dataset": {
            "name": dataset_name,
            "subset": experiment.run.subset,
            "split": experiment.run.split,
            "revision": experiment.run.dataset_revision,
            "local_parquet": "dataset.parquet",
            "instance_count": len(instance_ids),
            "instance_ids": instance_ids,
            "instance_ids_sha256": sha256_json(instance_ids),
            "instance_payloads_sha256": sha256_json(instance_fingerprints),
        },
        "arms": [
            {"tag": arm.tag, "fingerprint": arm.fingerprint, "config": asdict(arm)}
            for arm in arms
        ],
        "seeds": list(seeds),
        "dependencies": {
            "mini-swe-agent": package_version("mini-swe-agent"),
            "swebench": package_version("swebench"),
            "datasets": package_version("datasets"),
            "litellm": package_version("litellm"),
        },
        "model": {
            "request_name": experiment.api.model_name,
            "deployment_id": experiment.api.deployment_id,
            "runtime_fingerprint": runtime_fingerprint,
            "base_url_env": experiment.api.base_url_env,
            "api_key_env": experiment.api.api_key_env,
            "seed_supported": experiment.api.seed_supported,
        },
        "reward": {
            "source": "model_sampled_sequence_log_probability",
            "version": "swebench-logprob-v2",
            "logprob_mode": experiment.api.logprob_mode,
            "requires_reference": False,
            "uses_online_verifier": False,
            "scale": "alpha_minus_one",
            "target": (
                "base_api_trajectory_probability_times_exp_"
                "alpha_minus_one_times_scored_logprob"
            ),
            "power_target_claim": (
                "required_per_response"
                if experiment.api.logprob_mode == "power_target_exact"
                else "not_claimed_visible_token_reward_tilt"
            ),
        },
        "miniagent": {
            "commit": experiment.run.miniagent_commit,
            "config": experiment.run.miniagent_config,
            "action_mode": experiment.agent.action_mode,
            "max_trajectory_output_tokens": (
                experiment.agent.max_trajectory_output_tokens
            ),
        },
    }
