"""Deterministic repository-stratified instance plans for SWE-bench stages."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


SELECTION_PLAN_VERSION = "repo_stratified_v1"
STAGE_INSTANCE_COUNTS = {
    "smoke": 3,
    "calibrate": 5,
    "stress": 2,
    "screen": 15,
    "seed_check": 20,
    "confirm": 50,
}


def _hash_key(seed: int, *parts: object) -> str:
    payload = "|".join((str(seed), *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _repo(instance: Mapping[str, Any]) -> str:
    repo = str(instance.get("repo", "")).strip()
    if not repo:
        raise ValueError(
            f"instance {instance.get('instance_id', '<unknown>')} is missing repo"
        )
    return repo


def _quotas(
    capacities: Mapping[str, int],
    count: int,
    *,
    seed: int,
    stage: str,
) -> dict[str, int]:
    available = {
        repo: capacity for repo, capacity in capacities.items() if capacity > 0
    }
    if count <= 0 or count > sum(available.values()):
        raise ValueError("stratified sample count exceeds available instances")

    quotas = {repo: 0 for repo in available}
    if count >= len(available):
        for repo in available:
            quotas[repo] = 1
    else:
        selected_repos = sorted(
            available,
            key=lambda repo: (
                -available[repo],
                _hash_key(seed, stage, "repo", repo),
            ),
        )[:count]
        for repo in selected_repos:
            quotas[repo] = 1

    remaining = count - sum(quotas.values())
    if remaining == 0:
        return quotas

    residual = {repo: available[repo] - quotas[repo] for repo in available}
    total_residual = sum(residual.values())
    ideals = {repo: remaining * residual[repo] / total_residual for repo in available}
    for repo, ideal in ideals.items():
        quotas[repo] += min(residual[repo], int(ideal))

    leftover = count - sum(quotas.values())
    order = sorted(
        available,
        key=lambda repo: (
            -(ideals[repo] - int(ideals[repo])),
            _hash_key(seed, stage, "remainder", repo),
        ),
    )
    while leftover:
        progressed = False
        for repo in order:
            if quotas[repo] >= available[repo]:
                continue
            quotas[repo] += 1
            leftover -= 1
            progressed = True
            if leftover == 0:
                break
        if not progressed:
            raise RuntimeError("failed to allocate stratified instance quotas")
    return quotas


def _take(
    available: dict[str, list[dict[str, Any]]],
    count: int,
    *,
    seed: int,
    stage: str,
) -> list[dict[str, Any]]:
    quotas = _quotas(
        {repo: len(rows) for repo, rows in available.items()},
        count,
        seed=seed,
        stage=stage,
    )
    selected: list[dict[str, Any]] = []
    for repo in sorted(available):
        take = quotas.get(repo, 0)
        selected.extend(available[repo][:take])
        del available[repo][:take]
    return sorted(selected, key=lambda item: str(item["instance_id"]))


def build_stage_instance_plan(
    instances: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, list[dict[str, Any]]]:
    """Build the fixed six-stage plan while reserving a broad confirm set."""

    required = (
        STAGE_INSTANCE_COUNTS["smoke"]
        + STAGE_INSTANCE_COUNTS["calibrate"]
        + STAGE_INSTANCE_COUNTS["screen"]
        + STAGE_INSTANCE_COUNTS["confirm"]
    )
    if len(instances) < required:
        raise ValueError(f"selection plan requires at least {required} instances")

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for raw in instances:
        instance = dict(raw)
        instance_id = str(instance.get("instance_id", "")).strip()
        if not instance_id:
            raise ValueError("every instance must have a non-empty instance_id")
        if instance_id in seen:
            raise ValueError(f"duplicate instance_id {instance_id}")
        seen.add(instance_id)
        grouped[_repo(instance)].append(instance)

    available = {
        repo: sorted(
            rows,
            key=lambda item: _hash_key(seed, "instance", item["instance_id"]),
        )
        for repo, rows in grouped.items()
    }
    confirm = _take(
        available,
        STAGE_INSTANCE_COUNTS["confirm"],
        seed=seed,
        stage="confirm",
    )
    screen = _take(
        available,
        STAGE_INSTANCE_COUNTS["screen"],
        seed=seed,
        stage="screen",
    )
    calibrate = _take(
        available,
        STAGE_INSTANCE_COUNTS["calibrate"],
        seed=seed,
        stage="calibrate",
    )
    smoke = _take(
        available,
        STAGE_INSTANCE_COUNTS["smoke"],
        seed=seed,
        stage="smoke",
    )
    return {
        "smoke": smoke,
        "calibrate": calibrate,
        "stress": calibrate[: STAGE_INSTANCE_COUNTS["stress"]],
        "screen": screen,
        "seed_check": sorted(
            [*calibrate, *screen], key=lambda item: str(item["instance_id"])
        ),
        "confirm": confirm,
    }


def selection_metadata(
    plan: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    profile: str,
    seed: int,
) -> dict[str, Any]:
    selected = plan[profile]
    return {
        "name": SELECTION_PLAN_VERSION,
        "seed": seed,
        "profile": profile,
        "repo_counts": dict(sorted(Counter(_repo(item) for item in selected).items())),
    }
