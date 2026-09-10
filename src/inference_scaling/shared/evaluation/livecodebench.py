"""Pinned LiveCodeBench loading, partitioning, prompting, and grading adapter."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Sequence


LIVECODEBENCH_REPOSITORY = "https://github.com/LiveCodeBench/LiveCodeBench.git"
LIVECODEBENCH_REVISION = "28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24"
LIVECODEBENCH_DATASET = "livecodebench/code_generation_lite"
LIVECODEBENCH_RELEASE = "release_v6"
LIVECODEBENCH_EXPECTED_ROWS = 1055
LIVECODEBENCH_PLATFORMS = ("leetcode", "codeforces", "atcoder")
LIVECODEBENCH_DIFFICULTIES = ("easy", "medium", "hard")

LIVECODEBENCH_SYSTEM_PROMPT = (
    "You are an expert Python programmer. You will be given a question "
    "(problem specification) and will generate a correct Python program that "
    "matches the specification and passes all tests."
)

PartitionName = Literal["probe", "screen", "confirm"]


@dataclass(frozen=True, slots=True)
class LiveCodeBenchProblem:
    index: int
    question_title: str
    question_content: str
    platform: str
    question_id: str
    contest_id: str
    contest_date: str
    starter_code: str
    difficulty: str
    public_test_cases: str
    private_test_cases: str
    metadata: str

    @classmethod
    def from_mapping(
        cls, index: int, value: Mapping[str, Any]
    ) -> "LiveCodeBenchProblem":
        return cls(
            index=index,
            question_title=str(value["question_title"]),
            question_content=str(value["question_content"]),
            platform=str(value["platform"]).lower(),
            question_id=str(value["question_id"]),
            contest_id=str(value["contest_id"]),
            contest_date=str(value["contest_date"]),
            starter_code=str(value.get("starter_code") or ""),
            difficulty=str(value["difficulty"]).lower(),
            public_test_cases=_json_field(value["public_test_cases"]),
            private_test_cases=_json_field(value["private_test_cases"]),
            metadata=_json_field(value["metadata"]),
        )

    def official_record(self) -> dict[str, str]:
        return {
            "question_title": self.question_title,
            "question_content": self.question_content,
            "platform": self.platform,
            "question_id": self.question_id,
            "contest_id": self.contest_id,
            "contest_date": self.contest_date,
            "starter_code": self.starter_code,
            "difficulty": self.difficulty,
            "public_test_cases": self.public_test_cases,
            "private_test_cases": self.private_test_cases,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class LiveCodeBenchGrade:
    extracted_code: str
    correct: bool
    test_results: tuple[Any, ...]
    metadata: Any


def _json_field(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_livecodebench_snapshot(
    path: str | Path,
    *,
    expected_rows: int | None = LIVECODEBENCH_EXPECTED_ROWS,
) -> tuple[LiveCodeBenchProblem, ...]:
    problems: list[LiveCodeBenchProblem] = []
    seen_ids: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            problem = LiveCodeBenchProblem.from_mapping(index, json.loads(line))
            if problem.question_id in seen_ids:
                raise ValueError(
                    f"duplicate LiveCodeBench question_id {problem.question_id}"
                )
            if problem.platform not in LIVECODEBENCH_PLATFORMS:
                raise ValueError(f"unsupported platform {problem.platform}")
            if problem.difficulty not in LIVECODEBENCH_DIFFICULTIES:
                raise ValueError(f"unsupported difficulty {problem.difficulty}")
            seen_ids.add(problem.question_id)
            problems.append(problem)
    if expected_rows is not None and len(problems) != expected_rows:
        raise ValueError(
            f"expected {expected_rows} LiveCodeBench rows, found {len(problems)}"
        )
    return tuple(problems)


def livecodebench_user_prompt(problem: LiveCodeBenchProblem) -> str:
    prompt = f"### Question:\n{problem.question_content}\n\n"
    if problem.starter_code:
        prompt += (
            "### Format: You will use the following starter code to write the "
            "solution to the problem and enclose your code within delimiters.\n"
            f"```python\n{problem.starter_code}\n```\n\n"
        )
    else:
        prompt += (
            "### Format: Read the inputs from stdin solve the problem and write "
            "the answer to stdout (do not directly test on the sample inputs). "
            "Enclose your code within delimiters as follows. Ensure that when the "
            "python program runs, it reads the inputs, runs the algorithm and "
            "writes output to STDOUT.\n"
            "```python\n# YOUR CODE HERE\n```\n\n"
        )
    return prompt + "### Answer: (use the provided format with backticks)\n\n"


def extract_livecodebench_code(output: str) -> str:
    """Match the official generic/chat extraction rule: use the final code fence."""

    lines = output.split("\n")
    fences = [index for index, line in enumerate(lines) if "```" in line]
    if len(fences) < 2:
        return ""
    return "\n".join(lines[fences[-2] + 1 : fences[-1]])


def _rank_key(problem: LiveCodeBenchProblem, seed: int, namespace: str) -> str:
    value = f"{seed}|{namespace}|{problem.question_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _balanced_selection(
    problems: Sequence[LiveCodeBenchProblem],
    *,
    count: int,
    seed: int,
    namespace: str,
    excluded_ids: set[str],
) -> tuple[LiveCodeBenchProblem, ...]:
    if count <= 0:
        raise ValueError("partition count must be positive")
    strata = [
        (platform, difficulty)
        for platform in LIVECODEBENCH_PLATFORMS
        for difficulty in LIVECODEBENCH_DIFFICULTIES
    ]
    strata.sort(
        key=lambda value: hashlib.sha256(
            f"{seed}|{namespace}|{value[0]}|{value[1]}".encode("utf-8")
        ).hexdigest()
    )
    queues: dict[tuple[str, str], list[LiveCodeBenchProblem]] = {}
    for stratum in strata:
        candidates = [
            problem
            for problem in problems
            if (problem.platform, problem.difficulty) == stratum
            and problem.question_id not in excluded_ids
        ]
        candidates.sort(key=lambda item: _rank_key(item, seed, namespace))
        queues[stratum] = candidates

    selected: list[LiveCodeBenchProblem] = []
    while len(selected) < count:
        progress = False
        for stratum in strata:
            if queues[stratum] and len(selected) < count:
                selected.append(queues[stratum].pop(0))
                progress = True
        if not progress:
            raise ValueError(
                f"only {len(selected)} eligible LiveCodeBench problems; need {count}"
            )
    return tuple(selected)


def select_livecodebench_partitions(
    problems: Sequence[LiveCodeBenchProblem],
    *,
    seed: int,
    probe_count: int = 8,
    screen_count: int = 12,
    confirm_count: int = 8,
) -> dict[PartitionName, tuple[LiveCodeBenchProblem, ...]]:
    selected: dict[PartitionName, tuple[LiveCodeBenchProblem, ...]] = {}
    excluded: set[str] = set()
    for name, count in (
        ("probe", probe_count),
        ("screen", screen_count),
        ("confirm", confirm_count),
    ):
        partition = _balanced_selection(
            problems,
            count=count,
            seed=seed,
            namespace=name,
            excluded_ids=excluded,
        )
        selected[name] = partition
        excluded.update(problem.question_id for problem in partition)
    return selected


def verify_livecodebench_checkout(source_root: str | Path) -> str:
    root = Path(source_root).resolve()
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if revision != LIVECODEBENCH_REVISION:
        raise ValueError(
            f"LiveCodeBench checkout is {revision}, expected {LIVECODEBENCH_REVISION}"
        )
    status = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("LiveCodeBench checkout has modified tracked files")
    for relative in (
        "lcb_runner/benchmarks/code_generation.py",
        "lcb_runner/evaluation/compute_code_generation_metrics.py",
        "lcb_runner/evaluation/testing_util.py",
        "lcb_runner/utils/extraction_utils.py",
    ):
        if not (root / relative).is_file():
            raise FileNotFoundError(root / relative)
    return revision


@contextmanager
def _official_import_path(root: Path) -> Iterator[None]:
    loaded = sys.modules.get("lcb_runner")
    if loaded is not None:
        loaded_file = Path(str(getattr(loaded, "__file__", ""))).resolve()
        if root not in loaded_file.parents:
            raise RuntimeError(
                "a different lcb_runner package is already imported in this process"
            )
    sys.path.insert(0, str(root))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass


class OfficialLiveCodeBenchEvaluator:
    """Run the pinned official code extractor and code-generation checker."""

    def __init__(self, source_root: str | Path) -> None:
        self.source_root = Path(source_root).resolve()
        verify_livecodebench_checkout(self.source_root)

    def evaluate(
        self,
        problems: Sequence[LiveCodeBenchProblem],
        outputs: Sequence[str],
        *,
        num_processes: int = 12,
        timeout: int = 6,
    ) -> tuple[LiveCodeBenchGrade, ...]:
        if len(problems) != len(outputs):
            raise ValueError("problems and outputs must have equal length")
        if num_processes <= 0 or timeout <= 0:
            raise ValueError("num_processes and timeout must be positive")
        try:
            with _official_import_path(self.source_root):
                from lcb_runner.benchmarks.code_generation import (  # type: ignore
                    CodeGenerationProblem,
                )
                from lcb_runner.evaluation.compute_code_generation_metrics import (  # type: ignore
                    codegen_metrics,
                )
                from lcb_runner.lm_styles import LMStyle  # type: ignore
                from lcb_runner.utils.extraction_utils import extract_code  # type: ignore
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                "official LiveCodeBench dependencies are missing; install the pinned "
                "checkout before running code evaluation"
            ) from error

        official_problems = [
            CodeGenerationProblem(**problem.official_record()) for problem in problems
        ]
        extracted = [
            str(extract_code(output, LMStyle.OpenAIChat)) for output in outputs
        ]
        metrics, results, metadata = codegen_metrics(
            [problem.get_evaluation_sample() for problem in official_problems],
            [[code] for code in extracted],
            k_list=[1],
            num_process_evaluate=num_processes,
            timeout=timeout,
            debug=False,
        )
        if len(results) != len(problems) or "pass@1" not in metrics:
            raise RuntimeError("official LiveCodeBench evaluator returned incomplete data")
        grades = []
        for index, code in enumerate(extracted):
            instance_results = tuple(results[index][0])
            grades.append(
                LiveCodeBenchGrade(
                    extracted_code=code,
                    correct=all(value > 0 for value in instance_results),
                    test_results=instance_results,
                    metadata=metadata[index][0],
                )
            )
        return tuple(grades)


__all__ = [
    "LIVECODEBENCH_DATASET",
    "LIVECODEBENCH_DIFFICULTIES",
    "LIVECODEBENCH_EXPECTED_ROWS",
    "LIVECODEBENCH_PLATFORMS",
    "LIVECODEBENCH_RELEASE",
    "LIVECODEBENCH_REPOSITORY",
    "LIVECODEBENCH_REVISION",
    "LIVECODEBENCH_SYSTEM_PROMPT",
    "LiveCodeBenchGrade",
    "LiveCodeBenchProblem",
    "OfficialLiveCodeBenchEvaluator",
    "extract_livecodebench_code",
    "file_sha256",
    "livecodebench_user_prompt",
    "load_livecodebench_snapshot",
    "select_livecodebench_partitions",
    "verify_livecodebench_checkout",
]
