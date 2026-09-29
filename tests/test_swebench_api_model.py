from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from inference_scaling.swebench.config import BudgetConfig
from inference_scaling.swebench.miniagent import (
    BudgetedEnvironment,
    BudgetLedger,
    _LogprobModelMixin,
    LogprobLitellmTextbasedModel,
    MiniAgentSession,
    MiniAgentSessionFactory,
    SessionCheckpoint,
    extract_logprob_metadata,
)


def _response(content: str = "ok", *, reasoning_content: str = "") -> dict[str, Any]:
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
    session.finalization_reserve_steps = 0
    session.executed = []
    session.closed = False
    session.initial_digest = "test"
    return session


def test_session_caps_each_request_by_remaining_trajectory_tokens() -> None:
    model = _SessionModel()
    session = _bare_session(model, chunk_tokens=64, max_tokens=100)
    session.executed = cast(
        Any, [SimpleNamespace(decision=SimpleNamespace(output_tokens=80))]
    )

    session.sample_decision()

    assert model.calls[-1]["max_tokens"] == 20


def test_session_records_trajectory_limit_as_terminal_reason() -> None:
    model = _SessionModel()
    session = _bare_session(model, chunk_tokens=64, max_tokens=100)
    session.executed = cast(
        Any, [SimpleNamespace(decision=SimpleNamespace(output_tokens=100))]
    )

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


def test_qwen_embedded_im_end_is_recorded_as_termination_logprob() -> None:
    response = _response("ok")
    response["choices"][0]["logprobs"]["content"].append(
        {
            "token": "<|im_end|>",
            "bytes": list(b"<|im_end|>"),
            "logprob": -0.5,
        }
    )
    response["usage"]["completion_tokens"] = 2

    metadata = extract_logprob_metadata(response, "request")

    assert metadata["sampled_tokens"] == ["ok"]
    assert metadata["termination_logprob"] == -0.5
    assert metadata["termination_status"] == "scored"
    assert metadata["scored_output_tokens"] == 2


def test_unrecognized_logprob_suffix_is_not_treated_as_termination() -> None:
    response = _response("ok")
    response["choices"][0]["logprobs"]["content"].append(
        {"token": "extra", "bytes": list(b"extra"), "logprob": -0.5}
    )
    response["usage"]["completion_tokens"] = 2
    with pytest.raises(ValueError, match="do not reconstruct"):
        extract_logprob_metadata(response, "request")


def test_hidden_reasoning_is_rejected() -> None:
    with pytest.raises(ValueError, match="hidden reasoning"):
        extract_logprob_metadata(
            _response(reasoning_content="unscored thought"), "request"
        )


def _reasoning_response(
    *, opening: bool = False, finish_reason: str = "stop", content: str | None = "ok"
) -> dict[str, Any]:
    response = _response(content or "", reasoning_content="THOUGHT: 检查代码\n")
    response["choices"][0]["message"]["content"] = content
    tokens = (["<think>"] if opening else []) + ["THOUGHT: 检查代码\n"]
    if content is not None:
        tokens.extend(["</think>", content])
    if finish_reason == "stop":
        tokens.append("<|im_end|>")
    response["choices"][0]["finish_reason"] = finish_reason
    response["choices"][0]["logprobs"]["content"] = [
        {"token": token, "bytes": list(token.encode()), "logprob": -0.25}
        for token in tokens
    ]
    response["usage"]["completion_tokens"] = len(tokens)
    return response


@pytest.mark.parametrize("opening", [False, True])
@pytest.mark.parametrize("reasoning_field", ["reasoning_content", "reasoning"])
@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_scored_reasoning_is_restored_losslessly(opening, reasoning_field, finish_reason):
    response = _reasoning_response(opening=opening, finish_reason=finish_reason)
    message = response["choices"][0]["message"]
    original_reasoning = message.pop("reasoning_content")
    message["reasoning_content"] = None
    message[reasoning_field] = original_reasoning

    metadata = extract_logprob_metadata(response, "request", logprob_mode="power_target_exact")

    expected = ("<think>" if opening else "") + original_reasoning + "</think>ok"
    assert metadata["normalized_content"] == expected
    assert "".join(metadata["sampled_tokens"]) == expected
    assert metadata["reasoning_normalization"] == "qwen3_full_stream"
    assert metadata["unscored_output_tokens"] == 0
    assert metadata["scored_output_tokens"] == response["usage"]["completion_tokens"]
    assert metadata["sampled_logprob"] == -0.25 * metadata["scored_output_tokens"]
    assert message["content"] == "ok"
    assert message[reasoning_field] == original_reasoning


def test_reasoning_aliases_must_agree():
    response = _reasoning_response()
    response["choices"][0]["message"]["reasoning"] = "different reasoning"
    with pytest.raises(ValueError, match="conflicting reasoning"):
        extract_logprob_metadata(response, "request")


def test_reasoning_normalization_does_not_ignore_unscored_tokens():
    response = _reasoning_response()
    response["usage"]["completion_tokens"] += 1
    with pytest.raises(ValueError, match="without matching logprobs"):
        extract_logprob_metadata(response, "request")


def test_reasoning_normalization_rejects_unknown_markers():
    response = _reasoning_response()
    response["choices"][0]["logprobs"]["content"][1].update(
        token="<unknown>", bytes=list(b"<unknown>")
    )
    with pytest.raises(ValueError, match="hidden reasoning"):
        extract_logprob_metadata(response, "request")


def test_length_truncated_reasoning_is_scored_without_fabricating_closing_marker():
    response = _reasoning_response(finish_reason="length", content=None)
    metadata = extract_logprob_metadata(response, "request")
    assert metadata["normalized_content"] == "THOUGHT: 检查代码\n"
    assert metadata["termination_status"] == "deterministic_length"
    assert metadata["unscored_output_tokens"] == 0


def test_reasoning_bytes_can_cross_utf8_boundaries():
    response = _reasoning_response()
    entries = response["choices"][0]["logprobs"]["content"]
    encoded = "THOUGHT: 检查代码\n".encode()
    entries[:1] = [
        {"token": "partial", "bytes": list(encoded[:10]), "logprob": -0.25},
        {"token": "partial", "bytes": list(encoded[10:]), "logprob": -0.25},
    ]
    response["usage"]["completion_tokens"] += 1
    metadata = extract_logprob_metadata(response, "request")
    assert metadata["normalized_content"] == "THOUGHT: 检查代码\n</think>ok"


def test_scored_prefix_discarded_by_qwen_parser_is_preserved():
    response = _reasoning_response(opening=True)
    response["choices"][0]["logprobs"]["content"].insert(
        0, {"token": "THO", "bytes": list(b"THO"), "logprob": -0.5}
    )
    response["usage"]["completion_tokens"] += 1
    metadata = extract_logprob_metadata(response, "request")
    assert metadata["normalized_content"] == "THO<think>THOUGHT: 检查代码\n</think>ok"
    assert metadata["sampled_token_logprobs"][0] == -0.5
    assert metadata["unscored_output_tokens"] == 0


def test_empty_reasoning_with_scored_markers_is_preserved():
    response = _reasoning_response(opening=True)
    response["choices"][0]["message"]["reasoning_content"] = ""
    del response["choices"][0]["logprobs"]["content"][1]
    response["usage"]["completion_tokens"] -= 1
    metadata = extract_logprob_metadata(response, "request")
    assert metadata["normalized_content"] == "<think></think>ok"
    assert metadata["reasoning_normalization"] == "qwen3_full_stream"


def _reasoning_model(monkeypatch, response):
    import litellm

    for entry in response["choices"][0]["logprobs"]["content"]:
        entry["top_logprobs"] = []
    monkeypatch.setenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "1")
    model_response = litellm.ModelResponse(**response)
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: model_response)
    return LogprobLitellmTextbasedModel(
        ledger=_ledger(),
        base_seed=7,
        request_namespace="reasoning-test",
        seed_supported=True,
        model_name="openai/test",
        cost_tracking="ignore_errors",
        action_regex=r"<mswea_bash_command>(.*?)</mswea_bash_command>",
    )


def test_model_preserves_raw_reasoning_and_uses_scored_content_for_history(monkeypatch):
    content = "<mswea_bash_command>echo ok</mswea_bash_command>"
    model = _reasoning_model(monkeypatch, _reasoning_response(content=content))
    message = model.query([{"role": "user", "content": "task"}])

    assert message["content"] == "THOUGHT: 检查代码\n</think>" + content
    assert not message.get("reasoning_content")
    assert not message.get("reasoning")
    assert message["extra"]["actions"] == [{"command": "echo ok"}]
    raw_message = message["extra"]["response"]["choices"][0]["message"]
    assert raw_message["content"] == content
    assert raw_message["reasoning_content"] == "THOUGHT: 检查代码\n"
    assert model._ledger.snapshot().output_tokens == 4


def test_rejected_response_is_preserved_without_weakening_validation(monkeypatch):
    raw = _response()
    raw["choices"][0]["message"]["content"] = "different"
    model = _reasoning_model(monkeypatch, raw)
    with pytest.raises(ValueError, match="reconstruct"):
        model._query([{"role": "user", "content": "task"}])
    assert len(model.rejected_responses) == 1
    saved = model.rejected_responses[0]
    assert saved["response"]["choices"][0]["message"]["content"] == "different"
    assert saved["response"]["choices"][0]["logprobs"]["content"][0]["token"] == "ok"
    assert model._ledger.snapshot().api_failures == 1
    assert model._ledger.snapshot().output_tokens == 1


def test_real_session_format_errors_count_budget_and_reset_after_action():
    from dataclasses import replace
    from inference_scaling.swebench.miniagent import decision_from_message

    model = _SessionModel()
    session = _bare_session(model, chunk_tokens=64, max_tokens=100)
    session.agent.n_consecutive_format_errors = 0
    session.agent.config.max_consecutive_format_errors = 3
    session.agent.execute_actions = lambda message: None
    action = decision_from_message(model.query([]))
    malformed = replace(action, kind="format_error", messages=({"role": "user", "content": "format error"},))
    session.apply_decision(malformed)
    session.apply_decision(malformed)
    assert not session.terminal
    assert session.agent.n_consecutive_format_errors == 2
    session.apply_decision(action)
    assert session.agent.n_consecutive_format_errors == 0
    for _ in range(3):
        session.apply_decision(malformed)
    assert session.exit_status == "RepeatedFormatError"
    assert session.agent.n_calls == 6
    assert session.trajectory_output_tokens == 6


def test_parser_checks_actions_in_the_complete_scored_stream(monkeypatch):
    from minisweagent.exceptions import FormatError

    response = _reasoning_response(content="<mswea_bash_command>echo ok</mswea_bash_command>")
    reasoning = "<mswea_bash_command>echo extra</mswea_bash_command>"
    response["choices"][0]["message"]["reasoning_content"] = reasoning
    response["choices"][0]["logprobs"]["content"][0].update(
        token=reasoning, bytes=list(reasoning.encode())
    )
    model = _reasoning_model(monkeypatch, response)
    with pytest.raises(FormatError) as failure:
        model.query([{"role": "user", "content": "task"}])
    assert failure.value.messages[0]["extra"]["n_actions"] == 2
    assert failure.value.messages[0]["extra"]["inference_scaling"]["unscored_output_tokens"] == 0


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


def test_zero_wall_budget_keeps_elapsed_time_and_request_limit(monkeypatch) -> None:
    ledger = BudgetLedger(BudgetConfig(1, 0, 0, 10, 0))
    monkeypatch.setattr(ledger, "_elapsed", lambda: 100_000.0)
    ledger.start_api_request()
    ledger.finish_api_request(100, 10, 2.5, failed=False)
    assert ledger.snapshot().elapsed_seconds == 100_000.0
    assert ledger.snapshot().api_seconds == 2.5
    from inference_scaling.swebench.miniagent import ExperimentBudgetExceeded
    with pytest.raises(ExperimentBudgetExceeded, match="request budget"):
        ledger.start_api_request()


def test_positive_wall_budget_still_expires(monkeypatch) -> None:
    ledger = _ledger()
    monkeypatch.setattr(ledger, "_elapsed", lambda: 61.0)
    from inference_scaling.swebench.miniagent import ExperimentBudgetExceeded
    with pytest.raises(ExperimentBudgetExceeded, match="wall budget"):
        ledger.check()


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

    monkeypatch.setattr("inference_scaling.swebench.miniagent.subprocess.run", fake_run)
    raw = SimpleNamespace(
        container_id="container-id",
        config=SimpleNamespace(executable="docker", run_args=["--rm"], cwd="/testbed"),
        serialize=lambda: {"info": {}},
    )
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger)

    image_ref = "inference-scaling-swebench-checkpoint:test-000001"
    assert environment.snapshot(image_ref) == "sha256:checkpoint"
    environment.cleanup()

    assert commands[0][:3] == ["docker", "inspect", "--format"]
    assert commands[1][:2] == ["docker", "commit"]
    assert "LABEL org.inference-scaling.swebench.checkpoint=true" in commands[1]
    assert commands[1][-1] == image_ref
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

    monkeypatch.setattr("inference_scaling.swebench.miniagent.subprocess.run", fake_run)
    raw = SimpleNamespace(
        container_id="container-id",
        config=SimpleNamespace(executable="docker", run_args=["--rm"], cwd="/testbed"),
    )
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger)

    with pytest.raises(RuntimeError, match="without mounts"):
        environment.snapshot("inference-scaling-swebench-checkpoint:test-000001")
    usage = ledger.snapshot()
    assert usage.state_snapshots == 1
    assert usage.snapshot_failures == 1


def test_checkpoint_restore_rejects_a_missing_tag_and_records_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Error response from daemon: No such image",
        ),
    )
    factory = MiniAgentSessionFactory.__new__(MiniAgentSessionFactory)
    factory.experiment = cast(
        Any, SimpleNamespace(run=SimpleNamespace(environment_class="docker"))
    )
    factory.mini_config = {"environment": {"executable": "docker"}}
    factory.ledger = _ledger()
    checkpoint = cast(
        SessionCheckpoint,
        SimpleNamespace(
            image_ref="inference-scaling-swebench-checkpoint:test-000001",
            image_id="sha256:missing",
        ),
    )

    with pytest.raises(RuntimeError, match="unavailable before restore"):
        factory.create_from_checkpoint(checkpoint, "test", 7, 64)

    usage = factory.ledger.snapshot()
    assert usage.state_restores == 1
    assert usage.restore_failures == 1


def test_checkpoint_restore_starts_from_the_protected_image_tag(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="[]", stderr=""),
    )
    captured: dict[str, Any] = {}

    def fake_environment(config, instance):
        captured["config"] = config
        captured["instance"] = instance
        return object()

    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.get_sb_environment",
        fake_environment,
    )
    restored: list[tuple[SessionCheckpoint, bool]] = []
    session = SimpleNamespace(
        restore_checkpoint=lambda checkpoint, restore_model_request_index: (
            restored.append((checkpoint, restore_model_request_index))
        )
    )
    factory = MiniAgentSessionFactory.__new__(MiniAgentSessionFactory)
    factory.experiment = cast(
        Any, SimpleNamespace(run=SimpleNamespace(environment_class="docker"))
    )
    factory.instance = {"instance_id": "test"}
    factory.mini_config = {
        "environment": {"executable": "docker"},
        "run": {"env_startup_command": "initialize"},
    }
    factory.ledger = _ledger()
    monkeypatch.setattr(factory, "_create_session", lambda *args, **kwargs: session)
    checkpoint = cast(
        SessionCheckpoint,
        SimpleNamespace(
            image_ref="inference-scaling-swebench-checkpoint:test-000001",
            image_id="sha256:checkpoint",
        ),
    )

    result = factory.create_from_checkpoint(checkpoint, "test", 7, 64)

    assert result is session
    assert captured["instance"]["image_name"] == checkpoint.image_ref
    assert "env_startup_command" not in captured["config"]["run"]
    assert restored == [(checkpoint, False)]
    usage = factory.ledger.snapshot()
    assert usage.state_restores == 1
    assert usage.restore_failures == 0


def test_discard_checkpoint_removes_its_tag_not_the_bare_image_id(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("inference_scaling.swebench.miniagent.subprocess.run", fake_run)
    image_ref = "inference-scaling-swebench-checkpoint:test-000001"
    checkpoint = cast(
        SessionCheckpoint,
        SimpleNamespace(image_ref=image_ref, image_id="sha256:checkpoint"),
    )
    factory = MiniAgentSessionFactory.__new__(MiniAgentSessionFactory)
    factory._snapshot_images = [("docker", image_ref, "sha256:checkpoint")]

    factory.discard_checkpoints([checkpoint])

    assert commands == [["docker", "image", "rm", image_ref]]
    assert factory._snapshot_images == []


@pytest.mark.parametrize("wall_limit", [60, 0])
def test_factory_applies_configured_retry_count(monkeypatch, wall_limit) -> None:
    monkeypatch.setenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "99")
    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.get_config_from_spec",
        lambda *args: {"agent": {}},
    )
    experiment = SimpleNamespace(
        api=SimpleNamespace(
            max_retries=2,
            resolve_runtime=lambda environ: {
                "base_url": "http://model/v1",
                "api_key": "secret",
                "extra_headers": {},
                "fingerprint": "runtime",
            },
        ),
        run=SimpleNamespace(
            miniagent_config="swebench_xml.yaml", environment_class="docker"
        ),
        agent=SimpleNamespace(
            step_limit=20,
            cost_limit=0,
            wall_time_limit_seconds=wall_limit,
        ),
    )

    factory = MiniAgentSessionFactory(
        cast(Any, experiment), {"instance_id": "instance"}, _ledger(), environ={}
    )

    assert os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "3"
    assert factory.mini_config["agent"]["wall_time_limit_seconds"] == wall_limit
    assert "automatically activates" in factory.mini_config["agent"]["system_template"]
    assert factory.mini_config["environment"].get("container_timeout", "2h") == (
        "2h" if wall_limit else "infinity"
    )


def test_close_all_reports_cleanup_failures_and_continues(monkeypatch) -> None:
    class FailingSession:
        environment = SimpleNamespace(container_id="container")

        def close(self) -> None:
            raise RuntimeError("container cleanup failed")

    monkeypatch.setattr(
        "inference_scaling.swebench.miniagent.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="image is still in use"
        ),
    )
    factory = MiniAgentSessionFactory.__new__(MiniAgentSessionFactory)
    factory._sessions = [FailingSession()]
    factory._snapshot_images = [("docker", "checkpoint:test", "sha256:test")]

    errors = factory.close_all()

    assert [error["resource"] for error in errors] == [
        "container",
        "checkpoint_image",
    ]
    assert factory._sessions == []
    assert factory._snapshot_images == []


def test_session_is_marked_closed_when_cleanup_fails() -> None:
    class FailingEnvironment:
        def cleanup(self) -> None:
            raise RuntimeError("cleanup failed")

    session = MiniAgentSession.__new__(MiniAgentSession)
    session.environment = cast(Any, FailingEnvironment())
    session.closed = False

    with pytest.raises(RuntimeError, match="cleanup failed"):
        session.close()

    assert session.closed is True
