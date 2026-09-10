from __future__ import annotations

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
