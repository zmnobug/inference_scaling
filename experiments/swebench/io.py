"""Result layout, atomic writes, and reproducibility helpers."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    except (OSError, json.JSONDecodeError):
        return False
    return (
        record.get("schema_version") == RESULT_SCHEMA_VERSION
        and record.get("config_fingerprint") == experiment.fingerprint
        and record.get("arm_fingerprint") == arm.fingerprint
        and record.get("instance_fingerprint") == instance_fingerprint(instance)
        and (
            runtime_fingerprint is None
            or record.get("runtime_fingerprint") == runtime_fingerprint
        )
        and int(record.get("seed", -1)) == seed
        and record.get("status") in {"completed", "budget_exceeded"}
    )


def rebuild_predictions(
    root: Path,
    arms: Sequence[ExperimentArm],
    seeds: Sequence[int],
    instance_ids: Sequence[str],
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
