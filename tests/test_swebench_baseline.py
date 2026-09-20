from types import SimpleNamespace
import json
import math
import signal
import time

import pytest

from inference_scaling.swebench import baseline
from inference_scaling.swebench.config import load_experiment_config


class FakeSession:
    def __init__(self, output_tokens=10, kind="action", finish_reason="stop"):
        self.terminal = False
        self.exit_status = ""
        self.trajectory_output_tokens = 0
        self.chunk_tokens = 200
        self.applied = 0
        self.kwargs = {}
        self.decision = SimpleNamespace(
            output_tokens=output_tokens,
            input_tokens=100,
            kind=kind,
            finish_reason=finish_reason,
            messages=({"role": "assistant", "content": "command"},),
            to_dict=lambda: {"output_tokens": output_tokens},
        )
        self.agent = SimpleNamespace(
            n_calls=0,
            messages=[],
            add_messages=lambda *messages: self.agent.messages.extend(messages),
            model=SimpleNamespace(query=self.query),
        )

    def query(self, messages, **kwargs):
        self.kwargs = kwargs
        return self.decision

    def _append_limit_exit(self, reason):
        self.terminal = True
        self.exit_status = reason

    def apply_decision(self, decision):
        self.applied += 1
        self.trajectory_output_tokens += decision.output_tokens
        self._append_limit_exit("Submitted")


@pytest.fixture
def experiment(monkeypatch):
    monkeypatch.setattr(baseline, "count_prompt_tokens", lambda *args: 100)
    monkeypatch.setattr(baseline, "decision_from_message", lambda message: message)
    return SimpleNamespace(
        agent=SimpleNamespace(
            context_window=300,
            context_safety_tokens=20,
            max_trajectory_output_tokens=250,
            wall_time_limit_seconds=10,
            step_limit=250,
        ),
        api=SimpleNamespace(model_name="openai/test", timeout_seconds=100),
    )


def test_dynamic_limit_and_complete_length_response(experiment):
    session = FakeSession(finish_reason="length")
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert session.kwargs["max_tokens"] == 180
    assert 0 < session.kwargs["timeout"] <= 10
    assert session.applied == 1
    assert result["termination_reason"] == "Submitted"


@pytest.mark.parametrize(
    ("context_window", "output_limit", "reason"),
    [(120, 250, "context_budget_exhausted"), (300, 0, "trajectory_output_limit")],
)
def test_exhausted_budget_prevents_query(experiment, context_window, output_limit, reason):
    experiment.agent.context_window = context_window
    experiment.agent.max_trajectory_output_tokens = output_limit
    session = FakeSession()
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["termination_reason"] == reason
    assert not session.kwargs


def test_output_limit_prevents_command_execution(experiment):
    experiment.agent.max_trajectory_output_tokens = 10
    session = FakeSession(output_tokens=10)
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["termination_reason"] == "trajectory_output_limit"
    assert session.applied == 0


def test_incomplete_action_is_not_retried(experiment):
    session = FakeSession(kind="format_error", finish_reason="length")
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["termination_reason"] == "format_error"
    assert session.applied == 0
    assert len(result["requests"]) == 1


def test_format_recovery_applies_and_counts_failed_output(experiment):
    experiment.agent.max_consecutive_format_errors = 3
    session = FakeSession(kind="format_error")
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert session.applied == 1
    assert session.trajectory_output_tokens == 10
    assert result["termination_reason"] == "Submitted"


def test_injected_sampler_uses_shared_deadline_and_budget(experiment):
    session = FakeSession()
    observed = []

    def sample(messages, maximum, deadline):
        observed.append((maximum, deadline - time.monotonic()))
        return session.decision

    result = baseline.run_budgeted_baseline(session, experiment, {}, decision_sampler=sample)
    assert observed[0][0] == 180
    assert 0 < observed[0][1] <= 10
    assert result["termination_reason"] == "Submitted"
    assert not session.kwargs


def test_hard_deadline_interrupts_blocked_query(experiment):
    experiment.agent.wall_time_limit_seconds = 0.03
    session = FakeSession()
    session.agent.model.query = lambda *args, **kwargs: time.sleep(5)
    previous_handler = signal.getsignal(signal.SIGALRM)
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["termination_reason"] == "generation_timeout"
    assert result["agent_seconds"] < 1
    assert signal.getsignal(signal.SIGALRM) == previous_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert session.applied == 0


@pytest.mark.parametrize("use_sampler", [False, True])
def test_unlimited_case_records_time_without_disabling_request_timeout(experiment, monkeypatch, use_sampler):
    experiment.agent.wall_time_limit_seconds = 0
    clock = {"now": 100.0}
    monkeypatch.setattr(baseline, "time", SimpleNamespace(monotonic=lambda: clock["now"], time=time.time))

    def count_tokens(*args):
        assert args[-1] == 30.0
        clock["now"] += 8000.0
        return 100

    def unexpected_signal(*args):
        pytest.fail("unlimited generation must not change process alarms")

    monkeypatch.setattr(baseline, "count_prompt_tokens", count_tokens)
    monkeypatch.setattr(baseline.signal, "signal", unexpected_signal)
    monkeypatch.setattr(baseline.signal, "setitimer", unexpected_signal)
    session = FakeSession()

    def sampler(messages, maximum, deadline):
        assert math.isinf(deadline)
        return session.decision

    result = baseline.run_budgeted_baseline(
        session, experiment, {}, decision_sampler=sampler if use_sampler else None,
    )
    assert result["termination_reason"] == "Submitted"
    assert result["agent_seconds"] == 8000.0
    assert result["requests"][0]["remaining_seconds"] is None
    assert result["requests"][0]["elapsed_seconds"] == 8000.0
    if not use_sampler:
        assert session.kwargs["timeout"] == experiment.api.timeout_seconds
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("limit", ["context", "output", "steps"])
def test_unlimited_time_preserves_other_case_limits(experiment, limit):
    experiment.agent.wall_time_limit_seconds = 0
    session = FakeSession()
    if limit == "context":
        experiment.agent.context_window = 120
        reason = "context_budget_exhausted"
    elif limit == "output":
        experiment.agent.max_trajectory_output_tokens = 10
        reason = "trajectory_output_limit"
    else:
        session.agent.n_calls = experiment.agent.step_limit
        reason = "agent_step_limit"
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["termination_reason"] == reason
    assert session.applied == 0
    assert result["agent_seconds"] >= 0


def test_five_case_config_is_frozen():
    config = load_experiment_config("configs/qwen38_swebench_random5_baseline.toml")
    assert config.agent.context_window == 133120
    assert config.agent.max_trajectory_output_tokens == 131072
    assert config.agent.wall_time_limit_seconds == 1800
    assert config.run.workers == 1
    assert len(config.arms) == 1
    assert config.arms[0].method == "base"


def test_finalization_window_uses_ordinary_generation_within_case_deadline(experiment):
    experiment.agent.wall_time_limit_seconds = 0.2
    experiment.agent.finalization_reserve_seconds = 0.15
    session = FakeSession()
    calls = []

    def sampler(messages, maximum, deadline):
        calls.append(deadline)
        time.sleep(max(0, deadline - time.monotonic()) + 0.001)
        raise baseline.BaselineDeadline()

    result = baseline.run_budgeted_baseline(session, experiment, {}, decision_sampler=sampler)
    assert len(calls) == 1
    assert result["requests"][0]["interrupted_for_finalization"] is True
    assert result["finalization"]["mode"] == "ordinary_generation"
    assert any("submit your current patch" in message["content"] for message in session.agent.messages)
    assert session.applied == 1
    assert session.trajectory_output_tokens == 10
    assert result["termination_reason"] == "Submitted"
    assert result["agent_seconds"] < 0.2


def test_verification_reminder_is_explicit_and_does_not_claim_test_success(experiment):
    experiment.agent.verification_reminder = True
    session = FakeSession()
    result = baseline.run_budgeted_baseline(session, experiment, {})
    assert result["verification_reminder"] is True
    assert "focused reproducer" in session.agent.messages[0]["content"]
    assert "instead of claiming they passed" in session.agent.messages[0]["content"]
    assert result["termination_reason"] == "Submitted"
