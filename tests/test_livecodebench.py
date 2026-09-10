from __future__ import annotations

import json
from collections import Counter

import pytest

from experiments.arllm.evaluate_livecodebench import (
    _output_for_official_evaluation,
    _selected_records,
)
from experiments.arllm.livecodebench_think_only import (
    _generation_summary,
    _load_closure_gate,
)
from inference_scaling.shared.evaluation.livecodebench import (
    LIVECODEBENCH_DIFFICULTIES,
    LIVECODEBENCH_PLATFORMS,
    LiveCodeBenchProblem,
    extract_livecodebench_code,
    livecodebench_user_prompt,
    load_livecodebench_snapshot,
    select_livecodebench_partitions,
)


def _row(platform: str, difficulty: str, offset: int) -> dict[str, object]:
    question_id = f"{platform}-{difficulty}-{offset}"
    return {
        "question_title": question_id,
        "question_content": f"Solve {question_id}.",
        "platform": platform,
        "question_id": question_id,
        "contest_id": f"contest-{offset}",
        "contest_date": "2025-01-01T00:00:00",
        "starter_code": "",
        "difficulty": difficulty,
        "public_test_cases": json.dumps(
            [{"input": "1", "output": "1", "testtype": "stdin"}]
        ),
        "private_test_cases": json.dumps(
            [{"input": "2", "output": "2", "testtype": "stdin"}]
        ),
        "metadata": json.dumps({"func_name": None}),
    }


def _fixture_problems() -> tuple[LiveCodeBenchProblem, ...]:
    rows = [
        _row(platform, difficulty, offset)
        for platform in LIVECODEBENCH_PLATFORMS
        for difficulty in LIVECODEBENCH_DIFFICULTIES
        for offset in range(5)
    ]
    return tuple(
        LiveCodeBenchProblem.from_mapping(index, row)
        for index, row in enumerate(rows)
    )


def test_livecodebench_partitions_are_balanced_deterministic_and_disjoint() -> None:
    problems = _fixture_problems()
    first = select_livecodebench_partitions(problems, seed=17)
    second = select_livecodebench_partitions(problems, seed=17)

    assert first == second
    assert {name: len(values) for name, values in first.items()} == {
        "probe": 8,
        "screen": 12,
        "confirm": 8,
    }
    identifiers = [
        {problem.question_id for problem in first[name]}
        for name in ("probe", "screen", "confirm")
    ]
    assert identifiers[0].isdisjoint(identifiers[1])
    assert identifiers[0].isdisjoint(identifiers[2])
    assert identifiers[1].isdisjoint(identifiers[2])
    screen_counts = Counter(
        (problem.platform, problem.difficulty) for problem in first["screen"]
    )
    assert max(screen_counts.values()) - min(screen_counts.values()) <= 1


def test_snapshot_loader_preserves_official_serialized_fields(tmp_path) -> None:
    path = tmp_path / "release.jsonl"
    row = _row("leetcode", "easy", 0)
    row["metadata"] = {"func_name": "solve"}
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    (problem,) = load_livecodebench_snapshot(path, expected_rows=None)

    assert json.loads(problem.metadata) == {"func_name": "solve"}
    assert problem.official_record()["private_test_cases"] == row[
        "private_test_cases"
    ]


def test_livecodebench_prompt_uses_official_generic_code_format() -> None:
    without_starter = LiveCodeBenchProblem.from_mapping(
        0, _row("atcoder", "medium", 0)
    )
    with_starter_row = _row("leetcode", "hard", 1)
    with_starter_row["starter_code"] = "class Solution:\n    pass"
    with_starter = LiveCodeBenchProblem.from_mapping(1, with_starter_row)

    stdin_prompt = livecodebench_user_prompt(without_starter)
    starter_prompt = livecodebench_user_prompt(with_starter)

    assert "reads the inputs" in stdin_prompt
    assert "# YOUR CODE HERE" in stdin_prompt
    assert "class Solution:" in starter_prompt
    assert starter_prompt.endswith(
        "### Answer: (use the provided format with backticks)\n\n"
    )


def test_code_extraction_matches_official_last_fence_rule() -> None:
    output = (
        "<think>try this</think>\n"
        "```python\nprint('wrong')\n```\n"
        "final\n```python\nprint(input())\n```\n"
    )
    assert extract_livecodebench_code(output) == "print(input())"
    assert extract_livecodebench_code("print(input())") == ""


def test_generation_records_must_exactly_match_manifest() -> None:
    manifest = {"question_ids": ["q1"], "arms": ["base", "think-is-cr0250"]}
    records = [
        {"question_id": "q1", "arm": "base"},
        {"question_id": "q1", "arm": "think-is-cr0250"},
    ]
    assert _selected_records(records, manifest) == records
    with pytest.raises(ValueError, match="missing=1"):
        _selected_records(records[:1], manifest)


def test_closure_gate_is_bound_to_data_model_and_protocol(tmp_path) -> None:
    path = tmp_path / "gate.json"
    path.write_text(
        json.dumps(
            {
                "dataset_sha256": "data",
                "model_fingerprint": "model",
                "generation_protocol_fingerprint": "protocol",
                "reasoning_closure_gate_passed": True,
            }
        ),
        encoding="utf-8",
    )

    gate = _load_closure_gate(
        path,
        dataset_sha256="data",
        model_fingerprint="model",
        generation_protocol_fingerprint="protocol",
    )
    assert gate["reasoning_closure_gate_passed"] is True
    with pytest.raises(ValueError, match="dataset_sha256"):
        _load_closure_gate(
            path,
            dataset_sha256="different",
            model_fingerprint="model",
            generation_protocol_fingerprint="protocol",
        )


def test_generation_summary_does_not_treat_pending_outputs_as_correctness() -> None:
    record = {
        "arm": "think-is-cr0250",
        "output_tokens": 10,
        "length_truncated": False,
        "elapsed_seconds": 1.0,
        "diagnostics": {
            "reasoning_complete": False,
            "failure_reason": "no_valid_reasoning_rollout",
        },
    }
    summary = _generation_summary(
        [record],
        {
            "arms": ["think-is-cr0250"],
            "fingerprint": "manifest",
            "phase": "smoke",
        },
    )

    assert summary["evaluation_status"] == "pending_official_code_execution"
    assert "accuracy" not in summary["arms"]["think-is-cr0250"]


def test_algorithm_failure_cannot_pass_from_code_inside_reasoning() -> None:
    output = "<think>```python\nprint(1)\n```"
    assert _output_for_official_evaluation(
        {"output": output, "evaluation_eligible": False}
    ) == ""
    assert _output_for_official_evaluation(
        {"output": output, "evaluation_eligible": True}
    ) == output
