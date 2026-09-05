"""Validated configuration and arm generation for SWE-bench experiments."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence


MINI_SWE_AGENT_COMMIT = "25941c89cfbc91eb40b3f8756348c91d9977d57e"
SWE_BENCH_VERSION = "5.0.1"


def _positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _positive_int_tuple(name: str, values: Sequence[Any]) -> tuple[int, ...]:
    parsed = tuple(int(value) for value in values)
    if not parsed:
        raise ValueError(f"{name} must not be empty")
    if any(value <= 0 for value in parsed):
        raise ValueError(f"{name} values must be positive")
    return parsed


def _alpha_tuple(name: str, values: Sequence[Any]) -> tuple[float, ...]:
    parsed = tuple(float(value) for value in values)
    if not parsed:
        raise ValueError(f"{name} must not be empty")
    if any(value < 1 for value in parsed):
        raise ValueError(f"{name} values must be at least one")
    return parsed


@dataclass(frozen=True, slots=True)
class RunConfig:
    tag: str
    output_root: Path
    subset: str
    split: str
    dataset_revision: str
    workers: int
    seeds: tuple[int, ...]
    miniagent_commit: str
    miniagent_config: str
    environment_class: str
    instance_filter: str
    instance_slice: str
    instance_plan_seed: int

    def __post_init__(self) -> None:
        if not self.tag.strip():
            raise ValueError("run.tag must not be empty")
        if not self.dataset_revision.strip():
            raise ValueError("run.dataset_revision must be a pinned revision")
        _positive("run.workers", self.workers)
        if not self.seeds:
            raise ValueError("run.seeds must not be empty")
        if self.miniagent_commit != MINI_SWE_AGENT_COMMIT:
            raise ValueError(
                "run.miniagent_commit must match the integration-tested commit "
                f"{MINI_SWE_AGENT_COMMIT}"
            )
        if self.environment_class not in {"docker", "singularity"}:
            raise ValueError("run.environment_class must be docker or singularity")


@dataclass(frozen=True, slots=True)
class APIConfig:
    model_name: str
    base_url_env: str
    api_key_env: str
    temperature: float
    top_p: float
    timeout_seconds: int
    max_retries: int
    seed_supported: bool
    extra_headers_env: str | None
    logprob_mode: str

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("api.model_name must not be empty")
        if not self.base_url_env.strip() or not self.api_key_env.strip():
            raise ValueError("api base URL and key environment names must not be empty")
        if self.temperature != 1.0 or self.top_p != 1.0:
            raise ValueError(
                "on-policy IS/MH requires api.temperature=1 and api.top_p=1"
            )
        _positive("api.timeout_seconds", self.timeout_seconds)
        if self.max_retries < 0:
            raise ValueError("api.max_retries must be non-negative")
        if self.logprob_mode not in {"visible_tokens", "power_target_exact"}:
            raise ValueError(
                "api.logprob_mode must be visible_tokens or power_target_exact"
            )

    def resolve_runtime(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
        values = os.environ if environ is None else environ
        base_url = values.get(self.base_url_env, "").strip()
        api_key = values.get(self.api_key_env, "").strip()
        if not base_url:
            raise ValueError(f"missing API base URL environment variable {self.base_url_env}")
        if not api_key:
            raise ValueError(f"missing API key environment variable {self.api_key_env}")
        headers: dict[str, str] = {}
        if self.extra_headers_env:
            raw_headers = values.get(self.extra_headers_env, "").strip()
            if raw_headers:
                loaded = json.loads(raw_headers)
                if not isinstance(loaded, dict) or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in loaded.items()
                ):
                    raise ValueError(
                        f"{self.extra_headers_env} must contain a JSON string map"
                    )
                headers = loaded
        return {"base_url": base_url, "api_key": api_key, "extra_headers": headers}


@dataclass(frozen=True, slots=True)
class AgentConfig:
    step_limit: int
    cost_limit: float
    wall_time_limit_seconds: int
    action_mode: str
    max_trajectory_output_tokens: int = 8192

    def __post_init__(self) -> None:
        _positive("agent.step_limit", self.step_limit)
        if self.cost_limit < 0:
            raise ValueError("agent.cost_limit must be non-negative")
        _positive("agent.wall_time_limit_seconds", self.wall_time_limit_seconds)
        _positive(
            "agent.max_trajectory_output_tokens",
            self.max_trajectory_output_tokens,
        )
        if self.action_mode not in {"text", "tool"}:
            raise ValueError("agent.action_mode must be text or tool")


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    max_api_requests: int
    max_input_tokens: int
    max_output_tokens: int
    max_tool_calls: int
    max_wall_seconds: int

    def __post_init__(self) -> None:
        for name in ("max_api_requests", "max_tool_calls", "max_wall_seconds"):
            _positive(f"budget.{name}", getattr(self, name))
        for name in ("max_input_tokens", "max_output_tokens"):
            if getattr(self, name) < 0:
                raise ValueError(f"budget.{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class ISConfig:
    alphas: tuple[float, ...]
    candidate_counts: tuple[int, ...]
    chunk_tokens: tuple[int, ...]
    rollout_counts: tuple[int, ...]
    reference_alpha: float
    reference_candidate_count: int
    reference_chunk_tokens: int
    reference_rollout_count: int

    def __post_init__(self) -> None:
        if self.reference_alpha < 1:
            raise ValueError("is.reference_alpha must be at least one")
        for name in (
            "reference_candidate_count",
            "reference_chunk_tokens",
            "reference_rollout_count",
        ):
            _positive(f"is.{name}", getattr(self, name))


@dataclass(frozen=True, slots=True)
class MHConfig:
    alphas: tuple[float, ...]
    updates_per_chain: tuple[int, ...]
    max_suffix_actions: tuple[int | None, ...]
    suffix_schedules: tuple[str, ...]
    chains: tuple[int, ...]
    reference_alpha: float
    reference_updates_per_chain: int
    reference_max_suffix_actions: int | None
    reference_suffix_schedule: str
    reference_chains: int
    chunk_tokens: int

    def __post_init__(self) -> None:
        if self.reference_alpha < 1:
            raise ValueError("mh.reference_alpha must be at least one")
        for name in (
            "reference_updates_per_chain",
            "reference_chains",
            "chunk_tokens",
        ):
            _positive(f"mh.{name}", getattr(self, name))
        allowed = {"full", "uniform", "inverse_length", "multiscale"}
        if not self.suffix_schedules or any(
            schedule not in allowed for schedule in self.suffix_schedules
        ):
            raise ValueError("mh.suffix_schedules contains an unknown schedule")
        if self.reference_suffix_schedule not in allowed:
            raise ValueError("mh.reference_suffix_schedule is unknown")
        if any(value is not None and value <= 0 for value in self.max_suffix_actions):
            raise ValueError("mh.max_suffix_actions values must be positive or 'all'")
        if (
            self.reference_max_suffix_actions is not None
            and self.reference_max_suffix_actions <= 0
        ):
            raise ValueError(
                "mh.reference_max_suffix_actions must be positive or 'all'"
            )


@dataclass(frozen=True, slots=True)
class ShortlistConfig:
    """Runner-up configurations promoted from calibration into screening."""

    is_alpha: float
    is_candidate_count: int
    is_chunk_tokens: int
    is_rollout_count: int
    mh_alpha: float
    mh_updates_per_chain: int
    mh_max_suffix_actions: int | None
    mh_suffix_schedule: str
    mh_chains: int

    def __post_init__(self) -> None:
        if self.is_alpha < 1 or self.mh_alpha < 1:
            raise ValueError("shortlist alpha values must be at least one")
        for name in (
            "is_candidate_count",
            "is_chunk_tokens",
            "is_rollout_count",
            "mh_updates_per_chain",
            "mh_chains",
        ):
            _positive(f"shortlist.{name}", getattr(self, name))
        if self.mh_max_suffix_actions is not None and self.mh_max_suffix_actions <= 0:
            raise ValueError(
                "shortlist.mh_max_suffix_actions must be positive or 'all'"
            )
        if self.mh_suffix_schedule not in {
            "full",
            "uniform",
            "inverse_length",
            "multiscale",
        }:
            raise ValueError("shortlist.mh_suffix_schedule is unknown")


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    path: Path
    run: RunConfig
    api: APIConfig
    agent: AgentConfig
    budget: BudgetConfig
    conditional_is: ISConfig
    mh: MHConfig
    shortlist: ShortlistConfig

    def __post_init__(self) -> None:
        total = self.agent.max_trajectory_output_tokens
        chunk_values = (
            *self.conditional_is.chunk_tokens,
            self.conditional_is.reference_chunk_tokens,
            self.mh.chunk_tokens,
            self.shortlist.is_chunk_tokens,
        )
        if any(value > total for value in chunk_values):
            raise ValueError(
                "agent.max_trajectory_output_tokens must be at least every "
                "IS/MH chunk_tokens value"
            )

    @property
    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["run"]["output_root"] = str(self.run.output_root)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentArm:
    method: str
    alpha: float = 1.0
    candidate_count: int | None = None
    chunk_tokens: int | None = None
    rollout_count: int | None = None
    updates_per_chain: int | None = None
    max_suffix_actions: int | None = None
    suffix_schedule: str | None = None
    chains: int | None = None

    @property
    def tag(self) -> str:
        if self.method == "base":
            return "base"
        values = [self.method, f"a{self.alpha:g}"]
        if self.method == "is":
            values.extend(
                [
                    f"b{self.candidate_count}",
                    f"c{self.chunk_tokens}",
                    f"r{self.rollout_count}",
                ]
            )
        elif self.method == "mh":
            suffix = self.max_suffix_actions
            values.extend(
                [
                    f"u{self.updates_per_chain}",
                    f"s{suffix if suffix is not None else 'all'}",
                    f"d{self.suffix_schedule}",
                    f"n{self.chains}",
                    f"c{self.chunk_tokens}",
                ]
            )
        return "-".join(values)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def instance_fingerprint(instance: Mapping[str, Any]) -> str:
    """Hash the complete dataset row used to create and evaluate an instance."""

    encoded = json.dumps(
        dict(instance), sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_section(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = payload.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"missing [{name}] section")
    return section


def _parse_suffix_values(values: Sequence[Any]) -> tuple[int | None, ...]:
    parsed: list[int | None] = []
    for value in values:
        if isinstance(value, str) and value.lower() == "all":
            parsed.append(None)
        else:
            number = int(value)
            if number <= 0:
                raise ValueError("mh.max_suffix_actions must be positive or 'all'")
            parsed.append(number)
    if not parsed:
        raise ValueError("mh.max_suffix_actions must not be empty")
    return tuple(parsed)


def _parse_suffix_value(value: Any) -> int | None:
    if isinstance(value, str) and value.lower() == "all":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("MH suffix value must be positive or 'all'")
    return parsed


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path).resolve()
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    run = _required_section(payload, "run")
    api = _required_section(payload, "api")
    agent = _required_section(payload, "agent")
    budget = _required_section(payload, "budget")
    conditional_is = _required_section(payload, "conditional_is")
    mh = _required_section(payload, "mh")
    shortlist = _required_section(payload, "shortlist")

    output_root = Path(str(run.get("output_root", "results/swebench")))
    if not output_root.is_absolute():
        output_root = (config_path.parent.parent / output_root).resolve()

    return ExperimentConfig(
        path=config_path,
        run=RunConfig(
            tag=str(run.get("tag", "swebench-qwen38-27b")),
            output_root=output_root,
            subset=str(run.get("subset", "verified")),
            split=str(run.get("split", "test")),
            dataset_revision=str(run.get("dataset_revision", "")),
            workers=int(run.get("workers", 1)),
            seeds=tuple(int(value) for value in run.get("seeds", [20260901])),
            miniagent_commit=str(
                run.get("miniagent_commit", MINI_SWE_AGENT_COMMIT)
            ),
            miniagent_config=str(run.get("miniagent_config", "swebench_xml.yaml")),
            environment_class=str(run.get("environment_class", "docker")),
            instance_filter=str(run.get("instance_filter", "")),
            instance_slice=str(run.get("instance_slice", "")),
            instance_plan_seed=int(run.get("instance_plan_seed", 20260901)),
        ),
        api=APIConfig(
            model_name=str(api["model_name"]),
            base_url_env=str(api.get("base_url_env", "QWEN_API_BASE")),
            api_key_env=str(api.get("api_key_env", "QWEN_API_KEY")),
            temperature=float(api.get("temperature", 1.0)),
            top_p=float(api.get("top_p", 1.0)),
            timeout_seconds=int(api.get("timeout_seconds", 300)),
            max_retries=int(api.get("max_retries", 3)),
            seed_supported=bool(api.get("seed_supported", True)),
            extra_headers_env=(
                str(api["extra_headers_env"])
                if api.get("extra_headers_env")
                else None
            ),
            logprob_mode=str(api.get("logprob_mode", "visible_tokens")),
        ),
        agent=AgentConfig(
            step_limit=int(agent.get("step_limit", 100)),
            cost_limit=float(agent.get("cost_limit", 0)),
            wall_time_limit_seconds=int(
                agent.get("wall_time_limit_seconds", 7200)
            ),
            action_mode=str(agent.get("action_mode", "text")),
            max_trajectory_output_tokens=int(
                agent.get("max_trajectory_output_tokens", 8192)
            ),
        ),
        budget=BudgetConfig(
            max_api_requests=int(budget.get("max_api_requests", 5000)),
            max_input_tokens=int(budget.get("max_input_tokens", 50_000_000)),
            max_output_tokens=int(budget.get("max_output_tokens", 2_000_000)),
            max_tool_calls=int(budget.get("max_tool_calls", 10_000)),
            max_wall_seconds=int(budget.get("max_wall_seconds", 86_400)),
        ),
        conditional_is=ISConfig(
            alphas=_alpha_tuple("conditional_is.alphas", conditional_is["alphas"]),
            candidate_counts=_positive_int_tuple(
                "conditional_is.candidate_counts",
                conditional_is["candidate_counts"],
            ),
            chunk_tokens=_positive_int_tuple(
                "conditional_is.chunk_tokens", conditional_is["chunk_tokens"]
            ),
            rollout_counts=_positive_int_tuple(
                "conditional_is.rollout_counts",
                conditional_is["rollout_counts"],
            ),
            reference_alpha=float(conditional_is.get("reference_alpha", 1.5)),
            reference_candidate_count=int(
                conditional_is.get("reference_candidate_count", 4)
            ),
            reference_chunk_tokens=int(
                conditional_is.get("reference_chunk_tokens", 256)
            ),
            reference_rollout_count=int(
                conditional_is.get("reference_rollout_count", 2)
            ),
        ),
        mh=MHConfig(
            alphas=_alpha_tuple("mh.alphas", mh["alphas"]),
            updates_per_chain=_positive_int_tuple(
                "mh.updates_per_chain", mh["updates_per_chain"]
            ),
            max_suffix_actions=_parse_suffix_values(mh["max_suffix_actions"]),
            suffix_schedules=tuple(str(value) for value in mh["suffix_schedules"]),
            chains=_positive_int_tuple("mh.chains", mh["chains"]),
            reference_alpha=float(mh.get("reference_alpha", 1.5)),
            reference_updates_per_chain=int(
                mh.get("reference_updates_per_chain", 4)
            ),
            reference_max_suffix_actions=_parse_suffix_value(
                mh.get("reference_max_suffix_actions", "all")
            ),
            reference_suffix_schedule=str(
                mh.get("reference_suffix_schedule", "multiscale")
            ),
            reference_chains=int(mh.get("reference_chains", 1)),
            chunk_tokens=int(mh.get("chunk_tokens", 256)),
        ),
        shortlist=ShortlistConfig(
            is_alpha=float(shortlist.get("is_alpha", 1.5)),
            is_candidate_count=int(shortlist.get("is_candidate_count", 2)),
            is_chunk_tokens=int(shortlist.get("is_chunk_tokens", 256)),
            is_rollout_count=int(shortlist.get("is_rollout_count", 1)),
            mh_alpha=float(shortlist.get("mh_alpha", 1.5)),
            mh_updates_per_chain=int(
                shortlist.get("mh_updates_per_chain", 4)
            ),
            mh_max_suffix_actions=_parse_suffix_value(
                shortlist.get("mh_max_suffix_actions", 2)
            ),
            mh_suffix_schedule=str(
                shortlist.get("mh_suffix_schedule", "multiscale")
            ),
            mh_chains=int(shortlist.get("mh_chains", 1)),
        ),
    )


def _is_arm(config: ISConfig, **overrides: Any) -> ExperimentArm:
    arm = ExperimentArm(
        method="is",
        alpha=config.reference_alpha,
        candidate_count=config.reference_candidate_count,
        chunk_tokens=config.reference_chunk_tokens,
        rollout_count=config.reference_rollout_count,
    )
    return replace(arm, **overrides)


def _mh_arm(config: MHConfig, **overrides: Any) -> ExperimentArm:
    arm = ExperimentArm(
        method="mh",
        alpha=config.reference_alpha,
        updates_per_chain=config.reference_updates_per_chain,
        max_suffix_actions=config.reference_max_suffix_actions,
        suffix_schedule=config.reference_suffix_schedule,
        chains=config.reference_chains,
        chunk_tokens=config.chunk_tokens,
    )
    return replace(arm, **overrides)


def _unique_arms(arms: Sequence[ExperimentArm]) -> tuple[ExperimentArm, ...]:
    unique: dict[str, ExperimentArm] = {}
    for arm in arms:
        unique.setdefault(arm.fingerprint, arm)
    return tuple(unique.values())


def build_experiment_arms(
    config: ExperimentConfig,
    profile: str,
) -> tuple[ExperimentArm, ...]:
    """Build arms for a pre-registered funnel stage or manual OFAT diagnostics."""

    base = ExperimentArm(method="base")
    if profile == "smoke":
        return _unique_arms(
            (
                base,
                _is_arm(
                    config.conditional_is,
                    alpha=1.0,
                    candidate_count=2,
                    rollout_count=1,
                ),
                _is_arm(config.conditional_is),
                _mh_arm(
                    config.mh,
                    alpha=1.0,
                    updates_per_chain=1,
                    max_suffix_actions=None,
                    suffix_schedule="full",
                    chains=1,
                ),
                _mh_arm(config.mh),
            )
        )
    if profile in {"seed_check", "confirm"}:
        return (base, _is_arm(config.conditional_is), _mh_arm(config.mh))

    if profile == "calibrate":
        return _unique_arms(
            (
                base,
                _is_arm(config.conditional_is),
                _is_arm(config.conditional_is, alpha=1.0),
                _is_arm(config.conditional_is, alpha=2.0),
                _is_arm(config.conditional_is, candidate_count=2),
                _is_arm(config.conditional_is, chunk_tokens=410),
                _is_arm(config.conditional_is, rollout_count=1),
                _mh_arm(config.mh),
                _mh_arm(config.mh, alpha=1.0),
                _mh_arm(config.mh, alpha=2.0),
                _mh_arm(config.mh, updates_per_chain=1),
                _mh_arm(config.mh, max_suffix_actions=2),
                _mh_arm(config.mh, suffix_schedule="full"),
            )
        )

    if profile == "stress":
        return _unique_arms(
            (
                _is_arm(config.conditional_is, alpha=4.0),
                _is_arm(config.conditional_is, candidate_count=8),
                _is_arm(config.conditional_is, chunk_tokens=1229),
                _is_arm(config.conditional_is, rollout_count=4),
                _mh_arm(config.mh, alpha=4.0),
                _mh_arm(config.mh, updates_per_chain=8),
                _mh_arm(config.mh, max_suffix_actions=1),
                _mh_arm(config.mh, suffix_schedule="uniform"),
                _mh_arm(config.mh, suffix_schedule="inverse_length"),
                _mh_arm(config.mh, chains=4),
            )
        )

    if profile == "screen":
        shortlist = config.shortlist
        return _unique_arms(
            (
                base,
                _is_arm(config.conditional_is, alpha=1.0),
                _is_arm(config.conditional_is),
                ExperimentArm(
                    method="is",
                    alpha=shortlist.is_alpha,
                    candidate_count=shortlist.is_candidate_count,
                    chunk_tokens=shortlist.is_chunk_tokens,
                    rollout_count=shortlist.is_rollout_count,
                ),
                _mh_arm(config.mh, alpha=1.0),
                _mh_arm(config.mh),
                ExperimentArm(
                    method="mh",
                    alpha=shortlist.mh_alpha,
                    updates_per_chain=shortlist.mh_updates_per_chain,
                    max_suffix_actions=shortlist.mh_max_suffix_actions,
                    suffix_schedule=shortlist.mh_suffix_schedule,
                    chains=shortlist.mh_chains,
                    chunk_tokens=config.mh.chunk_tokens,
                ),
            )
        )

    if profile != "ofat":
        raise ValueError(
            "profile must be smoke, calibrate, stress, screen, seed_check, "
            "confirm, or ofat"
        )

    arms: list[ExperimentArm] = [base]
    is_config = config.conditional_is
    arms.extend(_is_arm(is_config, alpha=value) for value in is_config.alphas)
    arms.extend(
        _is_arm(is_config, candidate_count=value)
        for value in is_config.candidate_counts
    )
    arms.extend(
        _is_arm(is_config, chunk_tokens=value) for value in is_config.chunk_tokens
    )
    arms.extend(
        _is_arm(is_config, rollout_count=value) for value in is_config.rollout_counts
    )

    mh_config = config.mh
    arms.extend(_mh_arm(mh_config, alpha=value) for value in mh_config.alphas)
    arms.extend(
        _mh_arm(mh_config, updates_per_chain=value)
        for value in mh_config.updates_per_chain
    )
    arms.extend(
        _mh_arm(mh_config, max_suffix_actions=value)
        for value in mh_config.max_suffix_actions
    )
    arms.extend(
        _mh_arm(mh_config, suffix_schedule=value)
        for value in mh_config.suffix_schedules
    )
    arms.extend(_mh_arm(mh_config, chains=value) for value in mh_config.chains)
    return _unique_arms(arms)
