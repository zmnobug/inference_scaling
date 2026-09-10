"""Pinned mini-SWE-agent integration with audited sampled-token logprobs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from inference_scaling.swebench.config import ExperimentConfig

try:
    from minisweagent import __version__ as miniagent_version
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.config import get_config_from_spec
    from minisweagent.exceptions import FormatError, InterruptAgentFlow
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel
    from minisweagent.run.benchmarks.swebench import get_sb_environment
except ImportError as exc:  # pragma: no cover - exercised by target-machine preflight
    raise ImportError(
        "SWE-bench support is not installed. Run "
        "experiments/swebench/bootstrap.sh with Python 3.11+."
    ) from exc


class ExperimentBudgetExceeded(RuntimeError):
    """Raised when any pre-registered per-arm budget is exhausted."""


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    api_requests: int
    api_failures: int
    input_tokens: int
    output_tokens: int
    raw_output_tokens: int
    dropped_hidden_tokens: int
    tool_calls: int
    tool_failures: int
    state_snapshots: int
    snapshot_failures: int
    state_restores: int
    restore_failures: int
    api_seconds: float
    tool_seconds: float
    snapshot_seconds: float
    restore_seconds: float
    elapsed_seconds: float


class BudgetLedger:
    """Thread-safe accounting shared by every branch of one arm run."""

    def __init__(self, config) -> None:
        self.config = config
        self._api_requests = 0
        self._api_failures = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._raw_output_tokens = 0
        self._dropped_hidden_tokens = 0
        self._tool_calls = 0
        self._tool_failures = 0
        self._state_snapshots = 0
        self._snapshot_failures = 0
        self._state_restores = 0
        self._restore_failures = 0
        self._api_seconds = 0.0
        self._tool_seconds = 0.0
        self._snapshot_seconds = 0.0
        self._restore_seconds = 0.0
        self._started = time.monotonic()
        self._lock = threading.Lock()

    def _elapsed(self) -> float:
        return time.monotonic() - self._started

    def _check_locked(self) -> None:
        checks = (
            ("API requests", self._api_requests, self.config.max_api_requests),
            ("input tokens", self._input_tokens, self.config.max_input_tokens),
            (
                "raw output tokens",
                self._raw_output_tokens,
                self.config.max_output_tokens,
            ),
            ("tool calls", self._tool_calls, self.config.max_tool_calls),
        )
        for label, actual, maximum in checks:
            if maximum > 0 and actual > maximum:
                raise ExperimentBudgetExceeded(
                    f"{label} budget exceeded: {actual} > {maximum}"
                )
        if self._elapsed() > self.config.max_wall_seconds:
            raise ExperimentBudgetExceeded(
                f"wall budget exceeded: {self._elapsed():.3f} > "
                f"{self.config.max_wall_seconds}"
            )

    def start_api_request(self) -> None:
        with self._lock:
            self._check_locked()
            if self._api_requests >= self.config.max_api_requests:
                raise ExperimentBudgetExceeded("API request budget exhausted")
            self._api_requests += 1

    def finish_api_request(
        self,
        input_tokens: int,
        output_tokens: int,
        elapsed_seconds: float,
        *,
        failed: bool,
        raw_output_tokens: int | None = None,
        dropped_hidden_tokens: int = 0,
    ) -> None:
        raw_output_tokens = (
            output_tokens if raw_output_tokens is None else raw_output_tokens
        )
        if (
            input_tokens < 0
            or output_tokens < 0
            or raw_output_tokens < 0
            or dropped_hidden_tokens < 0
        ):
            raise ValueError("API token counts must be non-negative")
        if raw_output_tokens != output_tokens + dropped_hidden_tokens:
            raise ValueError(
                "raw output tokens must equal normalized output tokens plus "
                "dropped hidden tokens"
            )
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._raw_output_tokens += raw_output_tokens
            self._dropped_hidden_tokens += dropped_hidden_tokens
            self._api_seconds += max(0.0, elapsed_seconds)
            self._api_failures += int(failed)
            self._check_locked()

    def start_tool_call(self) -> None:
        with self._lock:
            self._check_locked()
            if self._tool_calls >= self.config.max_tool_calls:
                raise ExperimentBudgetExceeded("tool-call budget exhausted")
            self._tool_calls += 1

    def finish_tool_call(self, elapsed_seconds: float, *, failed: bool) -> None:
        with self._lock:
            self._tool_seconds += max(0.0, elapsed_seconds)
            self._tool_failures += int(failed)
            self._check_locked()

    def finish_state_snapshot(
        self, elapsed_seconds: float, *, failed: bool
    ) -> None:
        with self._lock:
            self._state_snapshots += 1
            self._snapshot_failures += int(failed)
            self._snapshot_seconds += max(0.0, elapsed_seconds)

    def finish_state_restore(
        self, elapsed_seconds: float, *, failed: bool
    ) -> None:
        with self._lock:
            self._state_restores += 1
            self._restore_failures += int(failed)
            self._restore_seconds += max(0.0, elapsed_seconds)

    def check(self) -> None:
        with self._lock:
            self._check_locked()

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return UsageSnapshot(
                api_requests=self._api_requests,
                api_failures=self._api_failures,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                raw_output_tokens=self._raw_output_tokens,
                dropped_hidden_tokens=self._dropped_hidden_tokens,
                tool_calls=self._tool_calls,
                tool_failures=self._tool_failures,
                state_snapshots=self._state_snapshots,
                snapshot_failures=self._snapshot_failures,
                state_restores=self._state_restores,
                restore_failures=self._restore_failures,
                api_seconds=self._api_seconds,
                tool_seconds=self._tool_seconds,
                snapshot_seconds=self._snapshot_seconds,
                restore_seconds=self._restore_seconds,
                elapsed_seconds=self._elapsed(),
            )


class BudgetedEnvironment:
    """Transparent MiniAgent environment wrapper that accounts for commands."""

    def __init__(self, environment, ledger: BudgetLedger) -> None:
        self._environment = environment
        self._ledger = ledger
        self.config = environment.config

    def execute(
        self, action: dict[str, Any], cwd: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        self._ledger.start_tool_call()
        started = time.monotonic()
        try:
            result = self._environment.execute(action, cwd=cwd, **kwargs)
        except InterruptAgentFlow:
            self._ledger.finish_tool_call(
                time.monotonic() - started, failed=False
            )
            raise
        except Exception:
            self._ledger.finish_tool_call(
                time.monotonic() - started, failed=True
            )
            raise
        self._ledger.finish_tool_call(time.monotonic() - started, failed=False)
        return result

    def get_template_vars(self, **kwargs):
        return self._environment.get_template_vars(**kwargs)

    def serialize(self):
        payload = self._environment.serialize()
        container_id = getattr(self._environment, "container_id", None)
        executable = getattr(self.config, "executable", "docker")
        if container_id:
            result = subprocess.run(
                [executable, "inspect", "--format", "{{.Image}}", container_id],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                payload.setdefault("info", {}).setdefault("runtime", {})[
                    "container_image_id"
                ] = result.stdout.strip()
        return payload

    @property
    def container_id(self) -> str | None:
        return getattr(self._environment, "container_id", None)

    @property
    def executable(self) -> str:
        return str(getattr(self.config, "executable", "docker"))

    def snapshot(self, image_ref: str) -> str:
        """Commit an immutable Docker root-filesystem checkpoint."""

        container_id = self.container_id
        if not container_id:
            raise RuntimeError(
                "exact IS/MH state branching requires a Docker environment"
            )
        run_args = tuple(str(value) for value in getattr(self.config, "run_args", ()))
        if any(
            value in {"-v", "--volume", "--mount"}
            or value.startswith("--volume=")
            or value.startswith("--mount=")
            for value in run_args
        ):
            raise RuntimeError(
                "Docker checkpoint branching does not support bind mounts or volumes"
            )
        started = time.monotonic()
        failed = True
        try:
            mounts = subprocess.run(
                [
                    self.executable,
                    "inspect",
                    "--format",
                    "{{json .Mounts}}",
                    container_id,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            if json.loads(mounts.stdout or "[]"):
                raise RuntimeError(
                    "Docker checkpoint branching requires a container without "
                    "mounts because docker commit excludes mounted data"
                )
            result = subprocess.run(
                [
                    self.executable,
                    "commit",
                    "--change",
                    "LABEL org.inference-scaling.swebench.checkpoint=true",
                    container_id,
                    image_ref,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            output_lines = [
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ]
            image_id = output_lines[-1] if output_lines else ""
            if not image_id.startswith("sha256:"):
                raise RuntimeError("Docker commit did not return a valid image ID")
            failed = False
            return image_id
        finally:
            self._ledger.finish_state_snapshot(
                time.monotonic() - started, failed=failed
            )

    def cleanup(self) -> None:
        container_id = self.container_id
        if container_id:
            result = subprocess.run(
                [self.executable, "rm", "-f", container_id],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0 or "No such container" in getattr(
                result, "stderr", ""
            ):
                try:
                    self._environment.container_id = None
                except Exception:
                    pass
            else:
                cleanup = getattr(self._environment, "cleanup", None)
                if cleanup is not None:
                    cleanup()
            return
        cleanup = getattr(self._environment, "cleanup", None)
        if cleanup is not None:
            cleanup()


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if dump is not None:
        return dump(mode="json")
    raise TypeError(f"cannot serialize API response of type {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ApiUsage:
    input_tokens: int
    output_tokens: int
    raw_output_tokens: int
    dropped_hidden_tokens: int


def _usage_details(response: Any) -> ApiUsage:
    usage = _get(response, "usage")
    if usage is None:
        raise ValueError("API response is missing usage token counts")
    input_tokens = _get(usage, "prompt_tokens", _get(usage, "input_tokens"))
    output_tokens = _get(
        usage, "completion_tokens", _get(usage, "output_tokens")
    )
    normalized_output_tokens = _get(
        usage, "normalized_completion_tokens", output_tokens
    )
    raw_output_tokens = _get(
        usage, "raw_completion_tokens", normalized_output_tokens
    )
    dropped_hidden_tokens = _get(
        usage,
        "dropped_hidden_tokens",
        int(raw_output_tokens) - int(normalized_output_tokens)
        if raw_output_tokens is not None and normalized_output_tokens is not None
        else 0,
    )
    if input_tokens is None or output_tokens is None:
        raise ValueError("API response usage is missing input/output token counts")
    details = ApiUsage(
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        raw_output_tokens=int(raw_output_tokens),
        dropped_hidden_tokens=int(dropped_hidden_tokens),
    )
    if min(
        details.input_tokens,
        details.output_tokens,
        details.raw_output_tokens,
        details.dropped_hidden_tokens,
    ) < 0:
        raise ValueError("API usage token counts must be non-negative")
    if int(normalized_output_tokens) != details.output_tokens:
        raise ValueError(
            "normalized_completion_tokens differs from completion_tokens"
        )
    if (
        details.raw_output_tokens
        != details.output_tokens + details.dropped_hidden_tokens
    ):
        raise ValueError(
            "raw_completion_tokens must equal completion_tokens plus "
            "dropped_hidden_tokens"
        )
    raw_total_tokens = _get(usage, "raw_total_tokens")
    if raw_total_tokens is not None and int(raw_total_tokens) != (
        details.input_tokens + details.raw_output_tokens
    ):
        raise ValueError("raw_total_tokens is inconsistent with raw token counts")
    return details


def _usage_counts(response: Any) -> tuple[int, int]:
    details = _usage_details(response)
    return details.input_tokens, details.output_tokens


def extract_logprob_metadata(
    response: Any,
    request_id: str,
    *,
    logprob_mode: str = "visible_tokens",
) -> dict[str, Any]:
    """Extract and validate OpenAI-compatible chat completion logprobs."""

    choices = _get(response, "choices") or []
    if len(choices) != 1:
        raise ValueError("IS/MH sampling requires exactly one API choice per request")
    choice = choices[0]
    message = _get(choice, "message")
    content = _get(message, "content") or ""
    hidden_reasoning = _get(
        message, "reasoning_content", _get(message, "reasoning", "")
    )
    if hidden_reasoning:
        raise ValueError(
            "API returned separately sampled reasoning without matching logprobs; "
            "disable hidden reasoning for logprob-based IS/MH"
        )
    logprobs = _get(choice, "logprobs")
    entries = _get(logprobs, "content") if logprobs is not None else None
    if not entries:
        raise ValueError(
            "API response does not contain sampled-token logprobs; use the official "
            "MiniAgent text/XML config or enable tool-call argument logprobs server-side"
        )

    tokens: list[str] = []
    token_logprobs: list[float] = []
    token_bytes: list[list[int] | None] = []
    for index, entry in enumerate(entries):
        token = _get(entry, "token")
        logprob = float(_get(entry, "logprob"))
        raw_bytes = _get(entry, "bytes")
        if token is None or not math.isfinite(logprob):
            raise ValueError(f"invalid sampled-token logprob at index {index}")
        tokens.append(str(token))
        token_logprobs.append(logprob)
        token_bytes.append(list(raw_bytes) if raw_bytes is not None else None)

    reconstructed: str | None = None
    if all(value is not None for value in token_bytes):
        reconstructed = bytes(
            byte for value in token_bytes for byte in (value or [])
        ).decode("utf-8", errors="strict")
    elif "".join(tokens) == content:
        reconstructed = "".join(tokens)
    if reconstructed is None:
        raise ValueError(
            "sampled logprob tokens cannot be reconstructed from token bytes or text"
        )
    if reconstructed != content:
        raise ValueError("sampled logprob tokens do not reconstruct response content")

    usage = _usage_details(response)
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    finish_reason = str(_get(choice, "finish_reason", "") or "")
    if finish_reason not in {"stop", "length"}:
        raise ValueError(f"unsupported API finish_reason for logprob reward: {finish_reason!r}")
    logprob_payload = logprobs if logprobs is not None else {}
    raw_termination_logprob = _get(
        choice,
        "termination_logprob",
        _get(logprob_payload, "termination_logprob"),
    )
    termination_logprob: float | None = None
    if raw_termination_logprob is not None:
        termination_logprob = float(raw_termination_logprob)
        if not math.isfinite(termination_logprob):
            raise ValueError("API returned a non-finite termination logprob")

    scored_output_tokens = len(token_logprobs) + int(termination_logprob is not None)
    unscored_output_tokens = output_tokens - scored_output_tokens
    if unscored_output_tokens < 0:
        # Some servers report a separate termination score without counting the
        # stop token in completion_tokens.
        if termination_logprob is not None and output_tokens == len(token_logprobs):
            unscored_output_tokens = 0
        else:
            raise ValueError(
                "API output token count is smaller than scored logprob token count"
            )
    if unscored_output_tokens:
        raise ValueError(
            "API response contains output tokens without matching logprobs: "
            f"{unscored_output_tokens} unscored"
        )

    termination_status = (
        "deterministic_length"
        if finish_reason == "length"
        else "scored"
        if termination_logprob is not None
        else "unscored"
    )
    termination_covered = termination_status != "unscored"
    if logprob_mode == "power_target_exact" and not termination_covered:
        raise ValueError(
            "power_target_exact requires a scored stop/EOS probability; configure "
            "the API to return termination_logprob or use visible_tokens explicitly"
        )
    if logprob_mode not in {"visible_tokens", "power_target_exact"}:
        raise ValueError("unknown logprob mode")
    power_target_exact = logprob_mode == "power_target_exact"
    visible_logprob = float(sum(token_logprobs))
    sampled_logprob = visible_logprob
    if logprob_mode == "power_target_exact" and termination_logprob is not None:
        sampled_logprob += termination_logprob
    return {
        "request_id": request_id,
        "sampled_tokens": tokens,
        "sampled_token_bytes": token_bytes,
        "sampled_token_logprobs": token_logprobs,
        "sampled_logprob": sampled_logprob,
        "visible_sampled_logprob": visible_logprob,
        "termination_logprob": termination_logprob,
        "termination_status": termination_status,
        "power_target_exact": power_target_exact,
        "logprob_mode": logprob_mode,
        "scored_output_tokens": scored_output_tokens,
        "unscored_output_tokens": unscored_output_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "raw_output_tokens": usage.raw_output_tokens,
        "dropped_hidden_tokens": usage.dropped_hidden_tokens,
        "finish_reason": finish_reason,
        "response_id": str(_get(response, "id", "") or ""),
        "response_model": str(_get(response, "model", "") or ""),
        "system_fingerprint": str(
            _get(response, "system_fingerprint", "") or ""
        ),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {
                "api_key",
                "api_base",
                "authorization",
                "base_url",
                "extra_headers",
                "headers",
            }:
                result[key] = "<redacted>"
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class _LogprobModelMixin:
    def __init__(
        self,
        *,
        ledger: BudgetLedger,
        base_seed: int,
        request_namespace: str,
        seed_supported: bool,
        logprob_mode: str = "visible_tokens",
        **kwargs,
    ) -> None:
        self._ledger = ledger
        self._base_seed = int(base_seed)
        self._request_namespace = request_namespace
        self._seed_supported = seed_supported
        self._logprob_mode = logprob_mode
        self._request_index = 0
        self._request_lock = threading.Lock()
        self._active_request: tuple[str, int] | None = None
        super().__init__(**kwargs)

    def _next_request(self, messages: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
        with self._request_lock:
            index = self._request_index
            self._request_index += 1
        payload = json.dumps(messages, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(
            f"{self._base_seed}|{self._request_namespace}|{index}|{payload}".encode()
        ).hexdigest()
        return f"{self._request_namespace}:{index}:{digest[:12]}", int(
            digest[:8], 16
        ) & 0x7FFFFFFF

    def _query(self, messages, **kwargs):
        self._ledger.start_api_request()
        request_id, seed = self._active_request or self._next_request(messages)
        call_kwargs = {"logprobs": True, **kwargs}
        if self._seed_supported:
            call_kwargs["seed"] = seed
        started = time.monotonic()
        response = None
        try:
            response = super()._query(messages, **call_kwargs)  # type: ignore[misc]
            metadata = extract_logprob_metadata(
                response, request_id, logprob_mode=self._logprob_mode
            )
        except Exception:
            try:
                usage = (
                    _usage_details(response)
                    if response is not None
                    else ApiUsage(0, 0, 0, 0)
                )
            except Exception:
                usage = ApiUsage(0, 0, 0, 0)
            self._ledger.finish_api_request(
                usage.input_tokens,
                usage.output_tokens,
                time.monotonic() - started,
                failed=True,
                raw_output_tokens=usage.raw_output_tokens,
                dropped_hidden_tokens=usage.dropped_hidden_tokens,
            )
            raise
        self._ledger.finish_api_request(
            metadata["input_tokens"],
            metadata["output_tokens"],
            time.monotonic() - started,
            failed=False,
            raw_output_tokens=metadata["raw_output_tokens"],
            dropped_hidden_tokens=metadata["dropped_hidden_tokens"],
        )
        try:
            response._inference_scaling_metadata = metadata
        except Exception:
            pass
        return response

    def query(self, messages, **kwargs):
        if self._active_request is not None:
            raise RuntimeError("nested model query is not supported")
        request_id, seed = self._next_request(messages)
        self._active_request = (request_id, seed)
        try:
            try:
                message = super().query(messages, **kwargs)  # type: ignore[misc]
            except FormatError as exc:
                response = exc.messages[0].get("extra", {}).get("response")
                if response is None:
                    raise ValueError(
                        "format error did not preserve the API response"
                    ) from exc
                metadata = extract_logprob_metadata(
                    response, request_id, logprob_mode=self._logprob_mode
                )
                exc.messages[0].setdefault("extra", {})[
                    "inference_scaling"
                ] = metadata
                raise
            raw_response = message.get("extra", {}).get("response")
            if raw_response is None:
                raise ValueError("MiniAgent model response was not preserved")
            message["extra"]["inference_scaling"] = extract_logprob_metadata(
                raw_response, request_id, logprob_mode=self._logprob_mode
            )
            return message
        finally:
            self._active_request = None

    def serialize(self):
        return _redact(super().serialize())  # type: ignore[misc]


class LogprobLitellmTextbasedModel(_LogprobModelMixin, LitellmTextbasedModel):
    """Official MiniAgent text model with strict sampled-token logprobs."""


class LogprobLitellmToolModel(_LogprobModelMixin, LitellmModel):
    """Official tool model; requires API logprobs covering the emitted content."""


@dataclass(frozen=True, slots=True)
class SampledDecision:
    kind: str
    messages: tuple[dict[str, Any], ...]
    logprob: float
    token_logprobs: tuple[float, ...]
    tokens: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    raw_output_tokens: int
    dropped_hidden_tokens: int
    request_id: str
    response_id: str
    response_model: str
    system_fingerprint: str
    finish_reason: str
    scored_output_tokens: int
    unscored_output_tokens: int
    termination_logprob: float | None
    termination_status: str
    power_target_exact: bool
    logprob_mode: str
    cost: float

    def __post_init__(self) -> None:
        if self.kind not in {"action", "format_error"}:
            raise ValueError("unknown decision kind")
        if not math.isfinite(self.logprob):
            raise ValueError("decision logprob must be finite")
        if not self.messages:
            raise ValueError("a decision requires at least one message")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "logprob": self.logprob,
            "token_logprobs": list(self.token_logprobs),
            "tokens": list(self.tokens),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "raw_output_tokens": self.raw_output_tokens,
            "dropped_hidden_tokens": self.dropped_hidden_tokens,
            "request_id": self.request_id,
            "response_id": self.response_id,
            "response_model": self.response_model,
            "system_fingerprint": self.system_fingerprint,
            "finish_reason": self.finish_reason,
            "scored_output_tokens": self.scored_output_tokens,
            "unscored_output_tokens": self.unscored_output_tokens,
            "termination_logprob": self.termination_logprob,
            "termination_status": self.termination_status,
            "power_target_exact": self.power_target_exact,
            "logprob_mode": self.logprob_mode,
            "cost": self.cost,
        }


@dataclass(frozen=True, slots=True)
class ExecutedDecision:
    decision: SampledDecision
    context_digest: str
    delta_digest: str
    terminal: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.decision.to_dict(),
            "context_digest": self.context_digest,
            "delta_digest": self.delta_digest,
            "terminal": self.terminal,
        }


@dataclass(frozen=True, slots=True)
class SessionCheckpoint:
    """Agent state plus an immutable Docker root-filesystem image."""

    image_id: str
    image_ref: str
    messages: tuple[dict[str, Any], ...]
    executed: tuple[ExecutedDecision, ...]
    n_calls: int
    cost: float
    n_consecutive_format_errors: int
    initial_digest: str
    model_request_index: int
    agent_elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "image_ref": self.image_ref,
            "message_digest": message_digest(self.messages),
            "decision_count": len(self.executed),
            "trajectory_output_tokens": sum(
                item.decision.output_tokens for item in self.executed
            ),
        }


def _metadata_from_messages(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    for message in messages:
        metadata = message.get("extra", {}).get("inference_scaling")
        if metadata:
            return metadata
    raise ValueError("sampled MiniAgent decision is missing logprob metadata")


def decision_from_message(message: dict[str, Any]) -> SampledDecision:
    metadata = _metadata_from_messages((message,))
    return SampledDecision(
        kind="action",
        messages=(copy.deepcopy(message),),
        logprob=float(metadata["sampled_logprob"]),
        token_logprobs=tuple(float(value) for value in metadata["sampled_token_logprobs"]),
        tokens=tuple(str(value) for value in metadata["sampled_tokens"]),
        input_tokens=int(metadata["input_tokens"]),
        output_tokens=int(metadata["output_tokens"]),
        raw_output_tokens=int(metadata["raw_output_tokens"]),
        dropped_hidden_tokens=int(metadata["dropped_hidden_tokens"]),
        request_id=str(metadata["request_id"]),
        response_id=str(metadata["response_id"]),
        response_model=str(metadata["response_model"]),
        system_fingerprint=str(metadata["system_fingerprint"]),
        finish_reason=str(metadata["finish_reason"]),
        scored_output_tokens=int(metadata["scored_output_tokens"]),
        unscored_output_tokens=int(metadata["unscored_output_tokens"]),
        termination_logprob=(
            float(metadata["termination_logprob"])
            if metadata["termination_logprob"] is not None
            else None
        ),
        termination_status=str(metadata["termination_status"]),
        power_target_exact=bool(metadata["power_target_exact"]),
        logprob_mode=str(metadata["logprob_mode"]),
        cost=float(message.get("extra", {}).get("cost", 0.0)),
    )


def decision_from_format_error(exc: FormatError) -> SampledDecision:
    messages = tuple(copy.deepcopy(message) for message in exc.messages)
    metadata = _metadata_from_messages(messages)
    return SampledDecision(
        kind="format_error",
        messages=messages,
        logprob=float(metadata["sampled_logprob"]),
        token_logprobs=tuple(float(value) for value in metadata["sampled_token_logprobs"]),
        tokens=tuple(str(value) for value in metadata["sampled_tokens"]),
        input_tokens=int(metadata["input_tokens"]),
        output_tokens=int(metadata["output_tokens"]),
        raw_output_tokens=int(metadata["raw_output_tokens"]),
        dropped_hidden_tokens=int(metadata["dropped_hidden_tokens"]),
        request_id=str(metadata["request_id"]),
        response_id=str(metadata["response_id"]),
        response_model=str(metadata["response_model"]),
        system_fingerprint=str(metadata["system_fingerprint"]),
        finish_reason=str(metadata["finish_reason"]),
        scored_output_tokens=int(metadata["scored_output_tokens"]),
        unscored_output_tokens=int(metadata["unscored_output_tokens"]),
        termination_logprob=(
            float(metadata["termination_logprob"])
            if metadata["termination_logprob"] is not None
            else None
        ),
        termination_status=str(metadata["termination_status"]),
        power_target_exact=bool(metadata["power_target_exact"]),
        logprob_mode=str(metadata["logprob_mode"]),
        cost=float(messages[0].get("extra", {}).get("cost", 0.0)),
    )


def _semantic_message(message: Mapping[str, Any]) -> dict[str, Any]:
    extra = message.get("extra", {})
    return {
        "role": message.get("role"),
        "content": message.get("content"),
        "actions": [
            {"command": action.get("command", "")}
            for action in extra.get("actions", [])
        ],
        "raw_output": extra.get("raw_output"),
        "returncode": extra.get("returncode"),
        "exception_info": extra.get("exception_info"),
        "exit_status": extra.get("exit_status"),
        "submission": extra.get("submission"),
        "interrupt_type": extra.get("interrupt_type"),
    }


def message_digest(messages: Sequence[Mapping[str, Any]]) -> str:
    payload = [_semantic_message(message) for message in messages]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class MiniAgentSession:
    """One live official MiniAgent plus its isolated SWE-bench environment."""

    def __init__(
        self,
        agent: DefaultAgent,
        environment: BudgetedEnvironment,
        task: str,
        *,
        chunk_tokens: int = 256,
        max_trajectory_output_tokens: int = 8192,
    ) -> None:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be positive")
        if max_trajectory_output_tokens <= 0:
            raise ValueError("max_trajectory_output_tokens must be positive")
        self.agent = agent
        self.environment = environment
        self.chunk_tokens = int(chunk_tokens)
        self.max_trajectory_output_tokens = int(max_trajectory_output_tokens)
        self.executed: list[ExecutedDecision] = []
        self.closed = False
        self.agent.extra_template_vars |= {"task": task}
        self.agent.messages = []
        self.agent.add_messages(
            self.agent.model.format_message(
                role="system",
                content=self.agent._render_template(self.agent.config.system_template),
            ),
            self.agent.model.format_message(
                role="user",
                content=self.agent._render_template(self.agent.config.instance_template),
            ),
        )
        self.initial_digest = message_digest(self.agent.messages)

    @property
    def terminal(self) -> bool:
        return bool(self.agent.messages) and self.agent.messages[-1].get("role") == "exit"

    @property
    def trajectory_logprob(self) -> float:
        return float(sum(item.decision.logprob for item in self.executed))

    @property
    def submission(self) -> str:
        if not self.agent.messages:
            return ""
        return str(self.agent.messages[-1].get("extra", {}).get("submission", ""))

    @property
    def trajectory_output_tokens(self) -> int:
        return sum(item.decision.output_tokens for item in self.executed)

    @property
    def exit_status(self) -> str:
        if not self.agent.messages:
            return ""
        return str(self.agent.messages[-1].get("extra", {}).get("exit_status", ""))

    def _append_limit_exit(self, label: str) -> None:
        self.agent.add_messages(
            {
                "role": "exit",
                "content": label,
                "extra": {"exit_status": label, "submission": ""},
            }
        )

    def can_query(self) -> bool:
        if self.terminal:
            return False
        if self.trajectory_output_tokens >= self.max_trajectory_output_tokens:
            self._append_limit_exit("TrajectoryTokenLimitExceeded")
            return False
        if 0 < self.agent.config.step_limit <= self.agent.n_calls:
            self._append_limit_exit("LimitsExceeded")
            return False
        if 0 < self.agent.config.cost_limit <= self.agent.cost:
            self._append_limit_exit("LimitsExceeded")
            return False
        elapsed = int(time.time() - self.agent._start_time)
        if (
            0 < self.agent.config.wall_time_limit_seconds <= elapsed
        ):
            self._append_limit_exit("TimeExceeded")
            return False
        return True

    def sample_decision(self) -> SampledDecision:
        if not self.can_query():
            raise RuntimeError("cannot sample from a terminal or limited session")
        remaining_tokens = (
            self.max_trajectory_output_tokens - self.trajectory_output_tokens
        )
        request_max_tokens = min(self.chunk_tokens, remaining_tokens)
        if request_max_tokens <= 0:
            raise RuntimeError("trajectory output token budget is exhausted")
        try:
            return decision_from_message(
                self.agent.model.query(
                    self.agent.messages,
                    max_tokens=request_max_tokens,
                )
            )
        except FormatError as exc:
            return decision_from_format_error(exc)

    def apply_decision(
        self,
        decision: SampledDecision,
    ) -> ExecutedDecision:
        if self.terminal:
            raise RuntimeError("cannot apply a decision to a terminal session")
        projected_tokens = self.trajectory_output_tokens + decision.output_tokens
        if projected_tokens > self.max_trajectory_output_tokens:
            raise ExperimentBudgetExceeded(
                "trajectory output token limit exceeded: "
                f"{projected_tokens} > {self.max_trajectory_output_tokens}"
            )
        context_digest = message_digest(self.agent.messages)

        start = len(self.agent.messages)
        self.agent.n_calls += 1
        self.agent.cost += decision.cost
        if decision.kind == "format_error":
            self.agent.n_consecutive_format_errors += 1
            self.agent.add_messages(*copy.deepcopy(decision.messages))
            maximum = self.agent.config.max_consecutive_format_errors
            if 0 < maximum <= self.agent.n_consecutive_format_errors:
                self._append_limit_exit("RepeatedFormatError")
        else:
            self.agent.n_consecutive_format_errors = 0
            message = copy.deepcopy(decision.messages[0])
            self.agent.add_messages(message)
            try:
                self.agent.execute_actions(message)
            except InterruptAgentFlow as exc:
                self.agent.add_messages(*exc.messages)
            except Exception as exc:
                self.agent.handle_uncaught_exception(exc)
                raise

        delta_digest = message_digest(self.agent.messages[start:])
        executed = ExecutedDecision(
            decision=decision,
            context_digest=context_digest,
            delta_digest=delta_digest,
            terminal=self.terminal,
        )
        self.executed.append(executed)
        return executed

    def run_to_end(self) -> "MiniAgentSession":
        while self.can_query():
            self.apply_decision(self.sample_decision())
        return self

    def make_checkpoint(
        self, image_id: str, image_ref: str
    ) -> SessionCheckpoint:
        return SessionCheckpoint(
            image_id=image_id,
            image_ref=image_ref,
            messages=tuple(copy.deepcopy(self.agent.messages)),
            executed=tuple(copy.deepcopy(self.executed)),
            n_calls=int(self.agent.n_calls),
            cost=float(self.agent.cost),
            n_consecutive_format_errors=int(
                self.agent.n_consecutive_format_errors
            ),
            initial_digest=self.initial_digest,
            model_request_index=int(
                getattr(self.agent.model, "_request_index", 0)
            ),
            agent_elapsed_seconds=max(
                0.0, time.time() - float(self.agent._start_time)
            ),
        )

    def restore_checkpoint(
        self,
        checkpoint: SessionCheckpoint,
        *,
        restore_model_request_index: bool,
    ) -> None:
        if self.executed:
            raise RuntimeError("cannot restore over a non-empty session")
        self.agent.messages = list(copy.deepcopy(checkpoint.messages))
        self.executed = list(copy.deepcopy(checkpoint.executed))
        self.agent.n_calls = checkpoint.n_calls
        self.agent.cost = checkpoint.cost
        self.agent.n_consecutive_format_errors = (
            checkpoint.n_consecutive_format_errors
        )
        self.initial_digest = checkpoint.initial_digest
        self.agent._start_time = time.time() - checkpoint.agent_elapsed_seconds
        if restore_model_request_index:
            setattr(
                self.agent.model,
                "_request_index",
                checkpoint.model_request_index,
            )
        if message_digest(self.agent.messages) != message_digest(
            checkpoint.messages
        ):
            raise RuntimeError("restored MiniAgent messages changed")

    def serialize(self) -> dict[str, Any]:
        return self.agent.serialize(
            {
                "inference_scaling": {
                    "initial_prompt_sha256": self.initial_digest,
                    "chunk_tokens": self.chunk_tokens,
                    "max_trajectory_output_tokens": (
                        self.max_trajectory_output_tokens
                    ),
                    "trajectory_output_tokens": self.trajectory_output_tokens,
                    "trajectory_logprob": self.trajectory_logprob,
                    "decisions": [item.to_dict() for item in self.executed],
                }
            }
        )

    def close(self) -> None:
        if not self.closed:
            self.environment.cleanup()
            self.closed = True


class MiniAgentSessionFactory:
    """Construct pinned official MiniAgent sessions for one SWE-bench instance."""

    def __init__(
        self,
        experiment: ExperimentConfig,
        instance: Mapping[str, Any],
        ledger: BudgetLedger,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if miniagent_version != "2.4.6":
            raise RuntimeError(
                f"expected mini-swe-agent 2.4.6, found {miniagent_version}"
            )
        self.experiment = experiment
        self.instance = dict(instance)
        self.ledger = ledger
        self._sessions: list[MiniAgentSession] = []
        self._snapshot_namespace = uuid.uuid4().hex
        self._snapshot_counter = 0
        self._snapshot_images: list[tuple[str, str, str]] = []
        self.runtime = experiment.api.resolve_runtime(environ)
        self.mini_config = get_config_from_spec(experiment.run.miniagent_config)
        self.mini_config = copy.deepcopy(self.mini_config)
        self.mini_config.setdefault("environment", {})[
            "environment_class"
        ] = experiment.run.environment_class
        agent_config = self.mini_config.setdefault("agent", {})
        agent_config["step_limit"] = experiment.agent.step_limit
        agent_config["cost_limit"] = experiment.agent.cost_limit
        agent_config["wall_time_limit_seconds"] = (
            experiment.agent.wall_time_limit_seconds
        )
        agent_config["output_path"] = None

    def make_model(self, namespace: str, seed: int, chunk_tokens: int):
        section = copy.deepcopy(self.mini_config.get("model", {}))
        section.pop("model_class", None)
        section["model_name"] = self.experiment.api.model_name
        section["cost_tracking"] = "ignore_errors"
        kwargs = section.setdefault("model_kwargs", {})
        kwargs.update(
            {
                "api_base": self.runtime["base_url"],
                "api_key": self.runtime["api_key"],
                "temperature": self.experiment.api.temperature,
                "top_p": self.experiment.api.top_p,
                "max_tokens": chunk_tokens,
                "timeout": self.experiment.api.timeout_seconds,
                "stream": False,
            }
        )
        if self.runtime["extra_headers"]:
            kwargs["extra_headers"] = self.runtime["extra_headers"]
        model_class = (
            LogprobLitellmTextbasedModel
            if self.experiment.agent.action_mode == "text"
            else LogprobLitellmToolModel
        )
        return model_class(
            ledger=self.ledger,
            base_seed=seed,
            request_namespace=namespace,
            seed_supported=self.experiment.api.seed_supported,
            logprob_mode=self.experiment.api.logprob_mode,
            **section,
        )

    def _create_session(
        self,
        raw_environment,
        namespace: str,
        seed: int,
        chunk_tokens: int,
    ) -> MiniAgentSession:
        environment = BudgetedEnvironment(raw_environment, self.ledger)
        model = self.make_model(namespace, seed, chunk_tokens)
        agent = DefaultAgent(model, environment, **self.mini_config.get("agent", {}))
        session = MiniAgentSession(
            agent,
            environment,
            str(self.instance["problem_statement"]),
            chunk_tokens=chunk_tokens,
            max_trajectory_output_tokens=(
                self.experiment.agent.max_trajectory_output_tokens
            ),
        )
        self._sessions.append(session)
        return session

    def create(self, namespace: str, seed: int, chunk_tokens: int) -> MiniAgentSession:
        raw_environment = get_sb_environment(self.mini_config, self.instance)
        return self._create_session(
            raw_environment, namespace, seed, chunk_tokens
        )

    def checkpoint(self, session: MiniAgentSession) -> SessionCheckpoint:
        if session.closed:
            raise RuntimeError("cannot checkpoint a closed MiniAgent session")
        self._snapshot_counter += 1
        image_ref = (
            "inference-scaling-swebench-checkpoint:"
            f"{self._snapshot_namespace}-{self._snapshot_counter:06d}"
        )
        image_id = session.environment.snapshot(image_ref)
        self._snapshot_images.append(
            (session.environment.executable, image_ref, image_id)
        )
        return session.make_checkpoint(image_id, image_ref)

    def create_from_checkpoint(
        self,
        checkpoint: SessionCheckpoint,
        namespace: str,
        seed: int,
        chunk_tokens: int,
        *,
        restore_model_request_index: bool = False,
    ) -> MiniAgentSession:
        if self.experiment.run.environment_class != "docker":
            raise RuntimeError(
                "exact IS/MH checkpoint branching currently requires Docker"
            )
        started = time.monotonic()
        failed = True
        try:
            executable = str(
                self.mini_config.get("environment", {}).get(
                    "executable", "docker"
                )
            )
            inspected = subprocess.run(
                [executable, "image", "inspect", checkpoint.image_ref],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if inspected.returncode != 0:
                raise RuntimeError(
                    "checkpoint image is unavailable before restore: "
                    f"ref={checkpoint.image_ref} id={checkpoint.image_id}; "
                    f"docker_error={inspected.stderr.strip()!r}"
                )
            instance = dict(self.instance)
            instance["image_name"] = checkpoint.image_ref
            config = copy.deepcopy(self.mini_config)
            config.setdefault("run", {}).pop("env_startup_command", None)
            raw_environment = get_sb_environment(config, instance)
            session = self._create_session(
                raw_environment, namespace, seed, chunk_tokens
            )
            session.restore_checkpoint(
                checkpoint,
                restore_model_request_index=restore_model_request_index,
            )
            failed = False
            return session
        finally:
            self.ledger.finish_state_restore(
                time.monotonic() - started, failed=failed
            )

    def discard_checkpoints(
        self, checkpoints: Sequence[SessionCheckpoint]
    ) -> None:
        for checkpoint in reversed(checkpoints):
            matches = [
                item
                for item in self._snapshot_images
                if item[1] == checkpoint.image_ref
            ]
            if not matches:
                continue
            executable, image_ref, image_id = matches[-1]
            result = subprocess.run(
                [executable, "image", "rm", image_ref],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0 or "No such image" in getattr(
                result, "stderr", ""
            ):
                self._snapshot_images.remove(
                    (executable, image_ref, image_id)
                )

    def close_all(self) -> None:
        for session in self._sessions:
            session.close()
        for executable, image_ref, _image_id in reversed(self._snapshot_images):
            subprocess.run(
                [executable, "image", "rm", image_ref],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self._snapshot_images.clear()


def miniagent_manifest(experiment: ExperimentConfig) -> dict[str, Any]:
    return {
        "miniagent_version": miniagent_version,
        "miniagent_commit": experiment.run.miniagent_commit,
        "miniagent_config": experiment.run.miniagent_config,
        "action_mode": experiment.agent.action_mode,
        "max_trajectory_output_tokens": (
            experiment.agent.max_trajectory_output_tokens
        ),
        "branch_state_mode": "docker_tagged_commit_checkpoint_v2",
        "api": _redact(asdict(experiment.api)),
    }
