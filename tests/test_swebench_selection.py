from __future__ import annotations

from inference_scaling.swebench.selection import (
    STAGE_INSTANCE_COUNTS,
    build_stage_instance_plan,
    selection_metadata,
)


def _instances() -> list[dict[str, str]]:
    counts = {"large/repo": 80, "medium/repo": 30, "small/repo": 10}
    return [
        {"repo": repo, "instance_id": f"{repo.replace('/', '__')}-{index}"}
        for repo, count in counts.items()
        for index in range(count)
    ]


def _ids(rows: list[dict[str, str]]) -> set[str]:
    return {row["instance_id"] for row in rows}


def test_stage_plan_is_deterministic_stratified_and_disjoint() -> None:
    first = build_stage_instance_plan(_instances(), seed=7)
    second = build_stage_instance_plan(list(reversed(_instances())), seed=7)
    assert {
        stage: [item["instance_id"] for item in rows] for stage, rows in first.items()
    } == {
        stage: [item["instance_id"] for item in rows] for stage, rows in second.items()
    }
    assert {stage: len(rows) for stage, rows in first.items()} == STAGE_INSTANCE_COUNTS

    assert _ids(first["stress"]) <= _ids(first["calibrate"])
    assert _ids(first["seed_check"]) == (
        _ids(first["calibrate"]) | _ids(first["screen"])
    )
    unique_stages = ("smoke", "calibrate", "screen", "confirm")
    for index, left in enumerate(unique_stages):
        for right in unique_stages[index + 1 :]:
            assert _ids(first[left]).isdisjoint(_ids(first[right]))
    assert len({row["repo"] for row in first["confirm"]}) == 3
    assert len({row["repo"] for row in first["calibrate"]}) == 3


def test_selection_metadata_records_repository_counts() -> None:
    plan = build_stage_instance_plan(_instances(), seed=9)
    metadata = selection_metadata(plan, profile="confirm", seed=9)
    assert metadata["name"] == "repo_stratified_v1"
    assert metadata["seed"] == 9
    assert sum(metadata["repo_counts"].values()) == 50
