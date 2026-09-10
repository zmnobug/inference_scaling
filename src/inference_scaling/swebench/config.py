"""Validated, explicit configuration for SWE-bench inference scaling."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


MINI_SWE_AGENT_COMMIT = "25941c89cfbc91eb40b3f8756348c91d9977d57e"
SWE_BENCH_VERSION = "5.0.1"
SUFFIX_SCHEDULES = frozenset({"full", "uniform", "inverse_length", "multiscale"})


def _positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _required_section(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = payload.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"missing [{name}] section")
    return section


def _parse_suffix_value(value: Any) -> int | None:
    if isinstance(value, str) and value.lower() == "all":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("MH suffix value must be positive or 'all'")
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

    def resolve_runtime(
        self, environ: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        values = os.environ if environ is None else environ
        base_url = values.get(self.base_url_env, "").strip()
        api_key = values.get(self.api_key_env, "").strip()
        if not base_url:
            raise ValueError(
                f"missing API base URL environment variable {self.base_url_env}"
            )
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
    max_trajectory_output_tokens: int

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

    def __post_init__(self) -> None:
        if self.method not in {"base", "is", "mh"}:
            raise ValueError("arm method must be base, is, or mh")
        if self.alpha < 1:
            raise ValueError("arm alpha must be at least one")
        if self.chunk_tokens is None:
            raise ValueError("every arm requires chunk_tokens")
        _positive("arm.chunk_tokens", self.chunk_tokens)
        if self.method == "is":
            if self.candidate_count is None or self.rollout_count is None:
                raise ValueError("IS arm requires candidate_count and rollout_count")
            _positive("arm.candidate_count", self.candidate_count)
            _positive("arm.rollout_count", self.rollout_count)
        if self.method == "mh":
            if (
                self.updates_per_chain is None
                or self.suffix_schedule is None
                or self.chains is None
            ):
                raise ValueError(
                    "MH arm requires updates_per_chain, suffix_schedule, and chains"
                )
            _positive("arm.updates_per_chain", self.updates_per_chain)
            _positive("arm.chains", self.chains)
            if self.max_suffix_actions is not None:
                _positive("arm.max_suffix_actions", self.max_suffix_actions)
            if self.suffix_schedule not in SUFFIX_SCHEDULES:
                raise ValueError("MH arm suffix_schedule is unknown")

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


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    path: Path
    run: RunConfig
    api: APIConfig
    agent: AgentConfig
    budget: BudgetConfig
    arms: tuple[ExperimentArm, ...]

    def __post_init__(self) -> None:
        if not self.arms:
            raise ValueError("config requires at least one [[arms]] entry")
        if any(
            int(arm.chunk_tokens or 0) > self.agent.max_trajectory_output_tokens
            for arm in self.arms
        ):
            raise ValueError(
                "agent.max_trajectory_output_tokens must be at least every "
                "arm chunk_tokens value"
            )
        tags = [arm.tag for arm in self.arms]
        if len(tags) != len(set(tags)):
            raise ValueError("arm tags must be unique")

    @property
    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["run"]["output_root"] = str(self.run.output_root)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def instance_fingerprint(instance: Mapping[str, Any]) -> str:
    """Hash the complete dataset row used to create and evaluate an instance."""

    encoded = json.dumps(
        dict(instance), sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_arms(payload: Mapping[str, Any]) -> tuple[ExperimentArm, ...]:
    raw_arms = payload.get("arms")
    if not isinstance(raw_arms, Sequence) or isinstance(raw_arms, (str, bytes)):
        raise ValueError("config requires [[arms]] entries")
    arms: list[ExperimentArm] = []
    for index, raw_arm in enumerate(raw_arms):
        if not isinstance(raw_arm, Mapping):
            raise ValueError(f"arms[{index}] must be a table")
        method = str(raw_arm.get("method", ""))
        arms.append(
            ExperimentArm(
                method=method,
                alpha=float(raw_arm.get("alpha", 1.0)),
                candidate_count=(
                    int(raw_arm["candidate_count"])
                    if raw_arm.get("candidate_count") is not None
                    else None
                ),
                chunk_tokens=(
                    int(raw_arm["chunk_tokens"])
                    if raw_arm.get("chunk_tokens") is not None
                    else None
                ),
                rollout_count=(
                    int(raw_arm["rollout_count"])
                    if raw_arm.get("rollout_count") is not None
                    else None
                ),
                updates_per_chain=(
                    int(raw_arm["updates_per_chain"])
                    if raw_arm.get("updates_per_chain") is not None
                    else None
                ),
                max_suffix_actions=(
                    _parse_suffix_value(raw_arm["max_suffix_actions"])
                    if raw_arm.get("max_suffix_actions") is not None
                    else None
                ),
                suffix_schedule=(
                    str(raw_arm["suffix_schedule"])
                    if raw_arm.get("suffix_schedule") is not None
                    else None
                ),
                chains=(
                    int(raw_arm["chains"])
                    if raw_arm.get("chains") is not None
                    else None
                ),
            )
        )
    return tuple(arms)


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path).resolve()
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    run = _required_section(payload, "run")
    api = _required_section(payload, "api")
    agent = _required_section(payload, "agent")
    budget = _required_section(payload, "budget")

    output_root = Path(str(run.get("output_root", "results/swebench")))
    if not output_root.is_absolute():
        output_root = (config_path.parent.parent / output_root).resolve()

    return ExperimentConfig(
        path=config_path,
        run=RunConfig(
            tag=str(run.get("tag", "swebench")),
            output_root=output_root,
            subset=str(run.get("subset", "verified")),
            split=str(run.get("split", "test")),
            dataset_revision=str(run.get("dataset_revision", "")),
            workers=int(run.get("workers", 1)),
            seeds=tuple(int(value) for value in run.get("seeds", [0])),
            miniagent_commit=str(run.get("miniagent_commit", MINI_SWE_AGENT_COMMIT)),
            miniagent_config=str(run.get("miniagent_config", "swebench_xml.yaml")),
            environment_class=str(run.get("environment_class", "docker")),
            instance_filter=str(run.get("instance_filter", "")),
            instance_slice=str(run.get("instance_slice", "")),
        ),
        api=APIConfig(
            model_name=str(api["model_name"]),
            base_url_env=str(api.get("base_url_env", "OPENAI_API_BASE")),
            api_key_env=str(api.get("api_key_env", "OPENAI_API_KEY")),
            temperature=float(api.get("temperature", 1.0)),
            top_p=float(api.get("top_p", 1.0)),
            timeout_seconds=int(api.get("timeout_seconds", 300)),
            max_retries=int(api.get("max_retries", 3)),
            seed_supported=bool(api.get("seed_supported", True)),
            extra_headers_env=(
                str(api["extra_headers_env"]) if api.get("extra_headers_env") else None
            ),
            logprob_mode=str(api.get("logprob_mode", "visible_tokens")),
        ),
        agent=AgentConfig(
            step_limit=int(agent.get("step_limit", 100)),
            cost_limit=float(agent.get("cost_limit", 0)),
            wall_time_limit_seconds=int(agent.get("wall_time_limit_seconds", 7200)),
            action_mode=str(agent.get("action_mode", "text")),
            max_trajectory_output_tokens=int(
                agent.get("max_trajectory_output_tokens", 8192)
            ),
        ),
        budget=BudgetConfig(
            max_api_requests=int(budget.get("max_api_requests", 5000)),
            max_input_tokens=int(budget.get("max_input_tokens", 0)),
            max_output_tokens=int(budget.get("max_output_tokens", 0)),
            max_tool_calls=int(budget.get("max_tool_calls", 10_000)),
            max_wall_seconds=int(budget.get("max_wall_seconds", 86_400)),
        ),
        arms=_load_arms(payload),
    )
