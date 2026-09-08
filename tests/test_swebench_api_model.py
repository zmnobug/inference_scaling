from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from inference_scaling.swebench.config import BudgetConfig
from inference_scaling.swebench.miniagent import (
    BudgetedEnvironment,
    BudgetLedger,
    _LogprobModelMixin,
    MiniAgentSession,
    extract_logprob_metadata,
)


def _response(
    content: str = "ok", *, reasoning_content: str = ""
) -> dict[str, Any]:
    message: dict[str, Any] = {"content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "stop",
                "logprobs": {
                    "content": [
                        {
                            "token": content,
                            "bytes": list(content.encode("utf-8")),
                            "logprob": -0.25,
                        }
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }


def _ledger() -> BudgetLedger:
    return BudgetLedger(
        BudgetConfig(
            max_api_requests=10,
            max_input_tokens=100,
            max_output_tokens=100,
            max_tool_calls=10,
            max_wall_seconds=60,
        )
    )


class _SessionModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        metadata = extract_logprob_metadata(_response(), "session-request")
        return {
            "role": "assistant",
            "content": "ok",
            "extra": {"inference_scaling": metadata},
        }


class _SessionAgent:
    def __init__(self, model: _SessionModel) -> None:
        self.model = model
        self.messages = [{"role": "user", "content": "task"}]
        self.config = SimpleNamespace(
            step_limit=100,
            cost_limit=0,
            wall_time_limit_seconds=60,
        )
        self.n_calls = 0
        self.cost = 0.0
        self._start_time = time.time()

    def add_messages(self, *messages) -> None:
        self.messages.extend(messages)


def _bare_session(
    model: _SessionModel, *, chunk_tokens: int, max_tokens: int
) -> MiniAgentSession:
    session = MiniAgentSession.__new__(MiniAgentSession)
    session.agent = cast(Any, _SessionAgent(model))
    session.environment = cast(Any, SimpleNamespace())
    session.chunk_tokens = chunk_tokens
    session.max_trajectory_output_tokens = max_tokens
    session.executed = []
    session.closed = False
    session.initial_digest = "test"
    return session


def test_session_caps_each_request_by_remaining_trajectory_tokens() -> None:
    model = _SessionModel()
    session = _bare_session(model, chunk_tokens=64, max_tokens=100)
    session.executed = cast(Any, [
        SimpleNamespace(decision=SimpleNamespace(output_tokens=80))
    ])

    session.sample_decision()

    assert model.calls[-1]["max_tokens"] == 20


def test_session_records_trajectory_limit_as_terminal_reason() -> None:
    model = _SessionModel()
    session = _bare_session(model, chunk_tokens=64, max_tokens=100)
    session.executed = cast(Any, [
        SimpleNamespace(decision=SimpleNamespace(output_tokens=100))
    ])

    assert session.can_query() is False
    assert session.exit_status == "TrajectoryTokenLimitExceeded"


class _RetryingBase:
    def __init__(self, **kwargs) -> None:
        self.calls: list[dict[str, Any]] = []

    def _query(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("retryable transport failure")
        return _response()

    def query(self, messages, **kwargs):
        try:
            response = self._query(messages, **kwargs)
        except RuntimeError:
            response = self._query(messages, **kwargs)
        return {"content": "ok", "extra": {"response": response}}

    def serialize(self):
        return {}


class _RetryingLogprobModel(_LogprobModelMixin, _RetryingBase):
    pass


def test_retry_uses_stable_seed_and_accounts_failed_attempt() -> None:
    ledger = _ledger()
    model = _RetryingLogprobModel(
        ledger=ledger,
        base_seed=7,
        request_namespace="test",
        seed_supported=True,
    )
    message = model.query([{"role": "user", "content": "hello"}])

    assert model.calls[0]["seed"] == model.calls[1]["seed"]
    assert message["extra"]["inference_scaling"]["request_id"].startswith("test:0:")
    usage = ledger.snapshot()
    assert usage.api_requests == 2
    assert usage.api_failures == 1
    assert usage.input_tokens == 3
    assert usage.output_tokens == 1


def test_logprob_tokens_must_reconstruct_content() -> None:
    response = _response()
    response["choices"][0]["logprobs"]["content"][0]["bytes"] = None
    response["choices"][0]["logprobs"]["content"][0]["token"] = "different"
    with pytest.raises(ValueError, match="cannot be reconstructed"):
        extract_logprob_metadata(response, "request")


def test_hidden_reasoning_is_rejected() -> None:
    with pytest.raises(ValueError, match="hidden reasoning"):
        extract_logprob_metadata(
            _response(reasoning_content="unscored thought"), "request"
        )


def test_unscored_output_tokens_are_rejected() -> None:
    response = _response()
    response["usage"]["completion_tokens"] = 2
    with pytest.raises(ValueError, match="without matching logprobs"):
        extract_logprob_metadata(response, "request")


def test_proxy_raw_and_normalized_usage_are_recorded_separately() -> None:
    response = _response()
    response["usage"].update(
        {
            "raw_completion_tokens": 2,
            "normalized_completion_tokens": 1,
            "dropped_hidden_tokens": 1,
            "raw_total_tokens": 5,
        }
    )
    metadata = extract_logprob_metadata(response, "request")
    assert metadata["output_tokens"] == 1
    assert metadata["raw_output_tokens"] == 2
    assert metadata["dropped_hidden_tokens"] == 1

    ledger = _ledger()
    ledger.start_api_request()
    ledger.finish_api_request(
        metadata["input_tokens"],
        metadata["output_tokens"],
        0.1,
        failed=False,
        raw_output_tokens=metadata["raw_output_tokens"],
        dropped_hidden_tokens=metadata["dropped_hidden_tokens"],
    )
    usage = ledger.snapshot()
    assert usage.output_tokens == 1
    assert usage.raw_output_tokens == 2
    assert usage.dropped_hidden_tokens == 1


def test_proxy_usage_counter_drift_is_rejected() -> None:
    response = _response()
    response["usage"].update(
        {
            "raw_completion_tokens": 3,
            "normalized_completion_tokens": 1,
            "dropped_hidden_tokens": 1,
        }
    )
    with pytest.raises(ValueError, match="raw_completion_tokens"):
        extract_logprob_metadata(response, "request")


def test_power_target_requires_termination_probability() -> None:
    response = _response()
    with pytest.raises(ValueError, match="scored stop/EOS"):
        extract_logprob_metadata(
            response,
            "request",
            logprob_mode="power_target_exact",
        )

    response["choices"][0]["termination_logprob"] = -0.5
    metadata = extract_logprob_metadata(
        response,
        "request",
        logprob_mode="power_target_exact",
    )
    assert metadata["sampled_logprob"] == pytest.approx(-0.75)
    assert metadata["power_target_exact"] is True


def test_visible_token_mode_records_unscored_termination() -> None:
    metadata = extract_logprob_metadata(_response(), "request")
    assert metadata["sampled_logprob"] == pytest.approx(-0.25)
    assert metadata["visible_sampled_logprob"] == pytest.approx(-0.25)
    assert metadata["termination_status"] == "unscored"
    assert metadata["power_target_exact"] is False
    assert metadata["logprob_mode"] == "visible_tokens"


def test_zero_token_limits_record_without_truncating() -> None:
    ledger = BudgetLedger(
        BudgetConfig(
            max_api_requests=10,
            max_input_tokens=0,
            max_output_tokens=0,
            max_tool_calls=10,
            max_wall_seconds=60,
        )
    )
    ledger.start_api_request()
    ledger.finish_api_request(10**9, 10**8, 0.25, failed=False)
    usage = ledger.snapshot()
    assert usage.input_tokens == 10**9
    assert usage.output_tokens == 10**8


def test_docker_environment_checkpoint_is_audited(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1] == "inspect":
            return SimpleNamespace(returncode=0, stdout="[]\n")
        if command[1] == "commit":
            return SimpleNamespace(returncode=0, stdout="sha256:checkpoint\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.subprocess.run", fake_run
    )
    raw = SimpleNamespace(
        container_id="container-id",
        config=SimpleNamespace(
            executable="docker", run_args=["--rm"], cwd="/testbed"
        ),
        serialize=lambda: {"info": {}},
    )
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger)

    assert environment.snapshot() == "sha256:checkpoint"
    environment.cleanup()

    assert commands[0][:3] == ["docker", "inspect", "--format"]
    assert commands[1][:2] == ["docker", "commit"]
    assert (
        "LABEL org.inference-scaling.swebench.checkpoint=true" in commands[1]
    )
    assert commands[2] == ["docker", "rm", "-f", "container-id"]
    usage = ledger.snapshot()
    assert usage.state_snapshots == 1
    assert usage.snapshot_failures == 0


def test_docker_environment_checkpoint_rejects_mounts(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        assert command[1] == "inspect"
        return SimpleNamespace(
            returncode=0,
            stdout='[{"Type":"bind","Destination":"/testbed"}]\n',
        )

    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.subprocess.run", fake_run
    )
    raw = SimpleNamespace(
        container_id="container-id",
        config=SimpleNamespace(
            executable="docker", run_args=["--rm"], cwd="/testbed"
        ),
    )
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger)

    with pytest.raises(RuntimeError, match="without mounts"):
        environment.snapshot()
    usage = ledger.snapshot()
    assert usage.state_snapshots == 1
    assert usage.snapshot_failures == 1
