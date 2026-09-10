"""Pinned Omni-MATH-Rule loading, partitioning, and official grading adapter."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable, Literal, Sequence


OMNIMATH_RULE_REPOSITORY = "https://github.com/KbsdJames/omni-math-rule.git"
OMNIMATH_RULE_REVISION = "4793415ef37d31c9cdb4e5b82dbe172f76f8cf08"
OMNIMATH_RULE_DATA_FILE = "omni_math_rule.jsonl"
OMNIMATH_RULE_DATA_SHA256 = (
    "d566d5b5a9865a04b507fdc4c0669cf0ff391748e13f190ecc925e78b584b172"
)
OMNIMATH_RULE_ROWS = 2821

OMNIMATH_PROMPT_SUFFIX = (
    "\n\nSolve the problem step by step. Put only the final answer in "
    "\\boxed{...} at the end of your response."
)
OMNIMATH_DOMAIN_BUCKETS = (
    "algebra",
    "number_theory",
    "geometry",
    "discrete_mathematics",
)

PartitionName = Literal["probe", "screen", "confirm"]


@dataclass(frozen=True, slots=True)
class OmniMathProblem:
    index: int
    problem_id: str
    question: str
    solution: str
    answer: str
    difficulty: float
    domains: tuple[str, ...]
    source: str
    domain_bucket: str | None


@dataclass(frozen=True, slots=True)
class OmniMathGrade:
    prediction: str
    reference: str
    correct: bool


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def omnimath_problem_id(index: int, question: str) -> str:
    question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
    return f"omnimath-rule-{index:04d}-{question_hash[:12]}"


def omnimath_domain_bucket(domains: Iterable[str]) -> str | None:
    joined = " | ".join(str(domain) for domain in domains)
    if "Algebra" in joined or "Precalculus" in joined:
        return "algebra"
    if "Number Theory" in joined:
        return "number_theory"
    if "Geometry" in joined:
        return "geometry"
    if "Discrete Mathematics" in joined or "Combinatorics" in joined:
        return "discrete_mathematics"
    return None


def load_omnimath_rule(
    path: str | Path,
    *,
    verify_pinned: bool = True,
) -> tuple[OmniMathProblem, ...]:
    """Load the official rule-evaluable subset and optionally enforce its identity."""

    source = Path(path)
    if verify_pinned:
        actual_sha256 = file_sha256(source)
        if actual_sha256 != OMNIMATH_RULE_DATA_SHA256:
            raise ValueError(
                "Omni-MATH-Rule checksum mismatch: "
                f"expected {OMNIMATH_RULE_DATA_SHA256}, got {actual_sha256}"
            )
    problems: list[OmniMathProblem] = []
    with source.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            item = json.loads(line)
            domains = tuple(str(value) for value in item["domain"])
            question = str(item["problem"])
            problems.append(
                OmniMathProblem(
                    index=index,
                    problem_id=omnimath_problem_id(index, question),
                    question=question,
                    solution=str(item["solution"]),
                    answer=str(item["answer"]),
                    difficulty=float(item["difficulty"]),
                    domains=domains,
                    source=str(item["source"]),
                    domain_bucket=omnimath_domain_bucket(domains),
                )
            )
    if verify_pinned and len(problems) != OMNIMATH_RULE_ROWS:
        raise ValueError(
            f"expected {OMNIMATH_RULE_ROWS} Omni-MATH-Rule rows, "
            f"found {len(problems)}"
        )
    return tuple(problems)


def omnimath_prompt(question: str) -> str:
    return question + OMNIMATH_PROMPT_SUFFIX


def _rank_key(problem: OmniMathProblem, seed: int, namespace: str) -> str:
    value = f"{seed}|{namespace}|{problem.problem_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stratified_selection(
    problems: Sequence[OmniMathProblem],
    *,
    difficulty_band: tuple[float, float],
    per_bucket: int,
    seed: int,
    namespace: str,
    excluded_ids: set[str],
) -> tuple[OmniMathProblem, ...]:
    lower, upper = difficulty_band
    if lower > upper:
        raise ValueError("difficulty band must be ordered")
    if per_bucket <= 0:
        raise ValueError("per_bucket must be positive")
    selected_by_bucket: dict[str, tuple[OmniMathProblem, ...]] = {}
    for bucket in OMNIMATH_DOMAIN_BUCKETS:
        candidates = [
            problem
            for problem in problems
            if problem.domain_bucket == bucket
            and lower <= problem.difficulty <= upper
            and problem.problem_id not in excluded_ids
        ]
        candidates.sort(key=lambda item: _rank_key(item, seed, namespace))
        if len(candidates) < per_bucket:
            raise ValueError(
                f"difficulty {difficulty_band} has only {len(candidates)} "
                f"eligible {bucket} problems; need {per_bucket}"
            )
        selected_by_bucket[bucket] = tuple(candidates[:per_bucket])

    # Interleave domains so every prefix used for a smoke run remains diverse.
    return tuple(
        selected_by_bucket[bucket][offset]
        for offset in range(per_bucket)
        for bucket in OMNIMATH_DOMAIN_BUCKETS
    )


def select_omnimath_partitions(
    problems: Sequence[OmniMathProblem],
    *,
    difficulty_band: tuple[float, float],
    seed: int,
    probe_per_bucket: int = 2,
    screen_per_bucket: int = 3,
    confirm_per_bucket: int = 2,
) -> dict[PartitionName, tuple[OmniMathProblem, ...]]:
    """Build the preregistered disjoint probe, screen, and confirm partitions."""

    probe = _stratified_selection(
        problems,
        difficulty_band=(8.0, 10.0),
        per_bucket=probe_per_bucket,
        seed=seed,
        namespace="probe",
        excluded_ids=set(),
    )
    excluded = {problem.problem_id for problem in probe}
    screen = _stratified_selection(
        problems,
        difficulty_band=difficulty_band,
        per_bucket=screen_per_bucket,
        seed=seed,
        namespace=f"screen:{difficulty_band[0]}:{difficulty_band[1]}",
        excluded_ids=excluded,
    )
    excluded.update(problem.problem_id for problem in screen)
    confirm = _stratified_selection(
        problems,
        difficulty_band=difficulty_band,
        per_bucket=confirm_per_bucket,
        seed=seed,
        namespace=f"confirm:{difficulty_band[0]}:{difficulty_band[1]}",
        excluded_ids=excluded,
    )
    return {"probe": probe, "screen": screen, "confirm": confirm}


def difficulty_band_from_probe(correct: int, total: int = 8) -> tuple[float, float]:
    if total != 8 or not 0 <= correct <= total:
        raise ValueError("the preregistered difficulty gate requires exactly 8 probes")
    if correct <= 1:
        return (6.0, 8.0)
    if correct <= 6:
        return (8.0, 10.0)
    return (9.0, 10.0)


def verify_omnimath_rule_checkout(source_root: str | Path) -> str:
    root = Path(source_root).resolve()
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if revision != OMNIMATH_RULE_REVISION:
        raise ValueError(
            f"Omni-MATH-Rule checkout is {revision}, expected {OMNIMATH_RULE_REVISION}"
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
        raise ValueError("Omni-MATH-Rule checkout has modified tracked files")
    load_omnimath_rule(root / OMNIMATH_RULE_DATA_FILE)
    for relative in (
        "evaluation/parser.py",
        "evaluation/grader.py",
        "evaluation/utils.py",
        "evaluation/latex2sympy/latex2sympy2.py",
    ):
        if not (root / relative).is_file():
            raise FileNotFoundError(root / relative)
    return revision


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OfficialOmniMathRuleEvaluator:
    """Use the parser and grader from the pinned official repository checkout."""

    def __init__(self, source_root: str | Path) -> None:
        root = Path(source_root).resolve()
        verify_omnimath_rule_checkout(root)
        evaluation_root = root / "evaluation"
        search_paths = [evaluation_root, evaluation_root / "latex2sympy"]
        for path in reversed(search_paths):
            sys.path.insert(0, str(path))
        try:
            existing_utils = sys.modules.get("utils")
            if existing_utils is not None:
                existing_path = Path(str(getattr(existing_utils, "__file__", ""))).resolve()
                if existing_path != (evaluation_root / "utils.py").resolve():
                    raise RuntimeError(
                        "a different top-level 'utils' module is already loaded; "
                        "construct the Omni-MATH evaluator before importing that module"
                    )
            if existing_utils is None:
                _load_module("utils", evaluation_root / "utils.py")
            self._parser = _load_module(
                "_inference_scaling_omnimath_parser",
                evaluation_root / "parser.py",
            )
            self._grader = _load_module(
                "_inference_scaling_omnimath_grader",
                evaluation_root / "grader.py",
            )
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                "official Omni-MATH-Rule grading dependencies are missing; install "
                "the project's 'omnimath' extra before running the benchmark"
            ) from error
        finally:
            for path in search_paths:
                try:
                    sys.path.remove(str(path))
                except ValueError:
                    pass

    def grade(self, output: str, reference: str) -> OmniMathGrade:
        prediction = str(self._parser.extract_answer(output, "omni-math"))
        normalized_reference = str(
            self._parser.extract_answer(f"\\boxed{{{reference}}}", "omni-math")
        )
        correct = bool(
            self._grader.math_equal(
                prediction,
                normalized_reference,
                timeout=False,
            )
        )
        return OmniMathGrade(prediction, normalized_reference, correct)


__all__ = [
    "OMNIMATH_DOMAIN_BUCKETS",
    "OMNIMATH_PROMPT_SUFFIX",
    "OMNIMATH_RULE_DATA_FILE",
    "OMNIMATH_RULE_DATA_SHA256",
    "OMNIMATH_RULE_REPOSITORY",
    "OMNIMATH_RULE_REVISION",
    "OMNIMATH_RULE_ROWS",
    "OfficialOmniMathRuleEvaluator",
    "OmniMathGrade",
    "OmniMathProblem",
    "difficulty_band_from_probe",
    "file_sha256",
    "load_omnimath_rule",
    "omnimath_domain_bucket",
    "omnimath_problem_id",
    "omnimath_prompt",
    "select_omnimath_partitions",
    "verify_omnimath_rule_checkout",
]
