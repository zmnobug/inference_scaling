import math
import time
from types import SimpleNamespace

import pytest

from inference_scaling.arllm.rewards import ConsilienceReward
from inference_scaling.swebench.baseline import SamplingStopped
from inference_scaling.swebench.baseline import BaselineDeadline
from inference_scaling.swebench.config import load_experiment_config
from inference_scaling.swebench.thinking_is import (
    OPEN_ACTION,
    ThinkingISSampler,
    Token,
    decode_completion,
    reward_weights,
)


def response():
    return {"usage": {"prompt_tokens": 2, "completion_tokens": 1}, "choices": [{
        "token_ids": [9], "prompt_token_ids": [1, 2], "finish_reason": "length",
        "logprobs": {"tokens": ["token_id:9"], "token_logprobs": [-1.0],
                     "top_logprobs": [{"token_id:9": -1.0, "b": -2.0, "c": -3.0, "d": -4.0, "e": -5.0, "f": -10.0}]},
    }]}


def test_exact_token_scoring_and_top_five_only():
    tokens = decode_completion(response(), [1, 2], 100)
    assert tokens == [Token(9, -1.0, 3.0)]


@pytest.mark.parametrize("fault", ["prompt", "count", "scores", "top5", "nan", "ids"])
def test_rejects_unverifiable_completion(fault):
    raw = response()
    choice = raw["choices"][0]
    if fault == "prompt":
        choice["prompt_token_ids"] = [2, 1]
    elif fault == "count":
        raw["usage"]["completion_tokens"] = 2
    elif fault == "scores":
        choice["logprobs"]["token_logprobs"] = []
    elif fault == "top5":
        choice["logprobs"]["top_logprobs"] = [{"token_id:9": -1.0}]
    elif fault == "nan":
        choice["logprobs"]["token_logprobs"] = [float("nan")]
    else:
        choice["logprobs"]["tokens"] = ["token_id:8"]
    with pytest.raises(ValueError):
        decode_completion(raw, [1, 2], 100)


def test_invalid_rollout_keeps_fixed_denominator():
    weights = reward_weights([[0, None], [0, 0], [None, None], [-2000, -2000]])
    assert weights == pytest.approx([1 / 3, 2 / 3, 0, 0])
    with pytest.raises(SamplingStopped, match="no_valid_thinking_rollout"):
        reward_weights([[None, None], [None, None]])


def character_sampler():
    sampler = object.__new__(ThinkingISSampler)
    sampler._decode = lambda tokens: ''.join(chr(token.token_id) for token in tokens)
    sampler.reward = ConsilienceReward(None)
    return sampler


def tokens(text):
    return [Token(ord(character), -1.0, 2.0) for character in text]


def test_boundary_handles_marker_split_between_chunks_and_excludes_action_reward():
    sampler = character_sampler()
    assert sampler._boundary(tokens("THOUGHT abc<mswea_")) is None
    full = tokens("THOUGHT abc" + OPEN_ACTION + "echo secret")
    assert sampler._boundary(full) == (11, 11 + len(OPEN_ACTION))
    score = sampler._quality(full)
    poisoned = full[:11] + [Token(token.token_id, -100.0, 9999) for token in full[11:]]
    assert sampler._quality(poisoned) == score
    assert score == -4


def test_empty_thinking_is_unscored_and_eos_before_marker_is_invalid():
    sampler = character_sampler()
    assert sampler._quality(tokens(OPEN_ACTION)) is None
    assert sampler._quality(tokens("TH<|im_end|>" + OPEN_ACTION)) is None


def test_shared_boundary_tokens_are_preserved_without_scoring_body():
    sampler = character_sampler()
    vocabulary = {1: "THOUGHT", 2: " <", 3: "mswea_bash_command", 4: ">\n", 5: "echo"}
    sampler._decode = lambda values: ''.join(vocabulary[token.token_id] for token in values)
    sample = [Token(index, -1, 2) for index in range(1, 6)]
    assert sampler._boundary(sample) == (1, 4)
    vocabulary[2] = "text<"
    vocabulary[4] = ">/"
    assert sampler._boundary(sample) == (1, 4)
    assert sampler._decode(sample[:4]).endswith(OPEN_ACTION + "/")
    assert sampler._quality(sample) == sampler.reward._trajectory_score([2])


def test_sample_rejection_keeps_raw_response_and_accounts_usage():
    from inference_scaling.swebench.config import BudgetConfig
    from inference_scaling.swebench.miniagent import BudgetLedger
    from inference_scaling.swebench.thinking_is import InvalidSample

    ledger = BudgetLedger(BudgetConfig(10, 100, 100, 10, 60))
    factory = SimpleNamespace(runtime={}, ledger=ledger,
                              experiment=SimpleNamespace(api=SimpleNamespace(model_name="openai/test")))
    arm = SimpleNamespace(chunk_tokens=100, candidate_count=4, rollout_count=2)
    sampler = ThinkingISSampler(factory, arm, 42)
    raw = response()
    raw["choices"][0]["token_ids"] = [88]
    sampler._post = lambda *args: raw
    with pytest.raises(InvalidSample):
        sampler._sample([1, 2], 100, "candidate")
    assert sampler.diagnostics["requests"][0]["response"] == raw
    assert ledger.snapshot().api_failures == 1
    assert ledger.snapshot().output_tokens == 1


def test_chunk_hundred_is_frozen_and_not_round_output_limit():
    experiment = load_experiment_config("configs/qwen38_swebench_thinking_is_smoke.toml")
    arm = experiment.arms[0]
    assert arm.method == "is_thinking"
    assert (arm.chunk_tokens, arm.candidate_count, arm.rollout_count) == (100, 4, 2)
    assert experiment.agent.max_trajectory_output_tokens == 131072
    assert experiment.agent.context_window == 133120
    assert experiment.agent.max_consecutive_format_errors == 3
    assert experiment.agent.wall_time_limit_seconds == 1800


def test_consilience_matches_existing_window_formula():
    reward = ConsilienceReward(None)
    values = [1.0] * 10 + [3.0] * 10
    assert reward._trajectory_score(values) == pytest.approx(0.0)
    assert math.isfinite(reward._trajectory_score([2.0]))


def test_multistep_selection_discards_rollouts_and_samples_action_once():
    factory = SimpleNamespace(
        runtime={}, ledger=None,
        experiment=SimpleNamespace(api=SimpleNamespace(model_name="openai/test"),
                                   agent=SimpleNamespace(context_window=1000, context_safety_tokens=10)),
        mini_config={"model": {"action_regex": r"<mswea_bash_command>(.*?)</mswea_bash_command>",
                               "format_error_template": "invalid {{actions|length}}"}},
    )
    arm = SimpleNamespace(chunk_tokens=5, candidate_count=4, rollout_count=2)
    sampler = ThinkingISSampler(factory, arm, 42)
    sampler._decode = lambda values: ''.join(chr(token.token_id) for token in values)
    sampler._post = lambda path, payload: {"tokens": [1, 2], "count": 2}
    observed = []
    terminal = tokens("xyz" + OPEN_ACTION)

    def sample(prompt, maximum, role):
        observed.append((list(prompt), maximum, role))
        if role == "candidate":
            value = tokens("think") if len(prompt) == 2 else terminal
        elif role == "rollout":
            value = tokens("DISCARD" + OPEN_ACTION)
        else:
            value = tokens("echo ok</mswea_bash_command>")
        sampler.diagnostics["requests"].append({"response": {"system_fingerprint": "test"}})
        return value, "length"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 10)
    assert decision.messages[0]["content"] == "thinkxyz" + OPEN_ACTION + "echo ok</mswea_bash_command>"
    assert "DISCARD" not in decision.messages[0]["content"]
    assert decision.messages[0]["extra"]["actions"] == [{"command": "echo ok"}]
    assert sum(role == "candidate" for _, _, role in observed) == 8
    assert sum(role == "rollout" for _, _, role in observed) == 8
    assert sum(role == "action" for _, _, role in observed) == 1
    assert observed[-1][0] == [1, 2] + [ord(character) for character in "thinkxyz" + OPEN_ACTION]
    assert len(sampler.diagnostics["rounds"][0]["steps"]) == 2
    assert decision.output_tokens == len(decision.messages[0]["content"])


def guarded_sampler(**settings):
    factory = SimpleNamespace(
        runtime={}, ledger=None,
        experiment=SimpleNamespace(api=SimpleNamespace(model_name="openai/test"),
                                   agent=SimpleNamespace(context_window=1000, context_safety_tokens=10)),
        mini_config={"model": {"action_regex": r"<mswea_bash_command>(.*?)</mswea_bash_command>",
                               "format_error_template": "invalid {{actions|length}}"}},
    )
    options = dict(chunk_tokens=100, candidate_count=4, rollout_count=2,
                   max_steps_per_round=4, max_round_seconds=60, max_rollout_tokens=8, fallback_to_plain=True)
    options.update(settings)
    sampler = ThinkingISSampler(factory, SimpleNamespace(**options), 42)
    sampler._decode = lambda values: ''.join(chr(token.token_id) for token in values)
    sampler._post = lambda path, payload: {"tokens": [1, 2], "count": 2}
    return sampler


def audit_fake_sample(sampler):
    sampler.request_index += 1
    sampler.diagnostics["requests"].append({"response": {"system_fingerprint": "test"}})


def unguarded_sampler():
    return guarded_sampler(max_steps_per_round=0, max_round_seconds=0,
                           max_rollout_tokens=0, fallback_to_plain=False)


@pytest.mark.parametrize("shared_body_prefix", ["", "/"])
def test_zero_thinking_selects_uniformly_then_samples_exact_action_once(shared_body_prefix):
    sampler = unguarded_sampler()
    command = "opt/python --version" if shared_body_prefix else "echo ok"
    vocabulary = {101: "<mswea_bash_command", 102: ">" + shared_body_prefix,
                  103: command + "</mswea_bash_command>", 104: "<|im_end|>"}
    sampler._decode = lambda values: ''.join(vocabulary[token.token_id] for token in values)
    observed = []

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        observed.append((list(prompt), maximum, role))
        assert role in {"candidate", "action"}
        ids = [101, 102] if role == "candidate" else [103, 104]
        assert len(ids) <= maximum
        return [Token(token_id, -1, 2) for token_id in ids], "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    round_record = sampler.diagnostics["rounds"][0]
    step = round_record["steps"][0]
    assert [role for _, _, role in observed] == ["candidate"] * 4 + ["action"]
    assert observed[-1] == ([1, 2, 101, 102], 498, "action")
    assert step["weights"] == [0.25] * 4
    assert step["ess"] == 4
    assert step["selection_mode"] == "empty_thinking_uniform"
    assert all(candidate["empty_thinking"] and candidate["rewards"] == [None, None]
               and not candidate["rollout_request_ids"] for candidate in step["candidates"])
    assert round_record["thinking_tokens"] == 0
    assert round_record["sampled_body_prefix"] == shared_body_prefix
    assert "fallback_reason" not in round_record
    assert decision.messages[0]["extra"]["actions"] == [{"command": shared_body_prefix + command}]
    assert decision.output_tokens == 4
    assert decision.token_logprobs == (-1, -1, -1)
    assert decision.termination_status == "scored"
    assert sampler.diagnostics["protocol"] == "thinking-is-token-prefix-v3"


def test_zero_thinking_does_not_change_weights_when_scored_candidates_exist():
    sampler = unguarded_sampler()
    contents = iter([OPEN_ACTION, "THOUGHT" + OPEN_ACTION, OPEN_ACTION, "PLAN" + OPEN_ACTION])

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        assert role in {"candidate", "action"}
        return tokens(next(contents) if role == "candidate" else "echo ok</mswea_bash_command>"), "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    step = sampler.diagnostics["rounds"][0]["steps"][0]
    assert step["weights"] == list(reward_weights([candidate["rewards"] for candidate in step["candidates"]]))
    assert step["weights"][0] == step["weights"][2] == 0
    assert step["selected"] in (1, 3)
    assert "selection_mode" not in step
    assert decision.kind == "action"


def test_zero_thinking_only_selects_valid_empty_candidates_among_invalid_proposals():
    from inference_scaling.swebench.thinking_is import InvalidSample

    sampler = unguarded_sampler()
    contents = iter([OPEN_ACTION, None, "<|im_end|>" + OPEN_ACTION, "unterminated thinking"])

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        assert role in {"candidate", "action"}
        content = next(contents) if role == "candidate" else "echo ok</mswea_bash_command>"
        if content is None:
            raise InvalidSample("completion scores do not cover all generated tokens")
        return tokens(content), "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    step = sampler.diagnostics["rounds"][0]["steps"][0]
    assert step["weights"] == [1, 0, 0, 0]
    assert step["selected"] == 0
    assert step["candidates"][1]["error"] == "completion scores do not cover all generated tokens"
    assert decision.kind == "action"


@pytest.mark.parametrize("fault", ["scores", "eos", "unfinished", "shared_thinking_token", "nonfinite_reward"])
def test_zero_thinking_policy_does_not_rescue_truly_invalid_candidates(fault):
    from inference_scaling.swebench.thinking_is import InvalidSample

    sampler = unguarded_sampler()
    if fault == "shared_thinking_token":
        sampler._decode = lambda values: "THOUGHT" + OPEN_ACTION if values else ""
    if fault == "nonfinite_reward":
        sampler.reward = SimpleNamespace(_trajectory_score=lambda values: float("nan"))

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        assert role == "candidate"
        if fault == "scores":
            raise InvalidSample("missing logprobs")
        if fault == "shared_thinking_token":
            return [Token(101, -1, 2)], "stop"
        content = "<|im_end|>" + OPEN_ACTION if fault == "eos" else "unfinished"
        if fault == "nonfinite_reward":
            content = "THOUGHT" + OPEN_ACTION
        return tokens(content), "stop"

    sampler._sample = sample
    with pytest.raises(SamplingStopped, match="no_valid_thinking_rollout"):
        sampler([], 500, time.monotonic() + 100)
    assert "selected" not in sampler.diagnostics["rounds"][0]["steps"][0]


@pytest.mark.parametrize("budget_source", ["trajectory", "context"])
def test_zero_thinking_does_not_bypass_remaining_output_budget(budget_source):
    sampler = unguarded_sampler()
    maximum = len(OPEN_ACTION)
    if budget_source == "context":
        sampler.factory.experiment.agent.context_window = 2 + 10 + maximum

    def sample(prompt, requested, role):
        audit_fake_sample(sampler)
        assert role == "candidate"
        assert requested == maximum
        return tokens(OPEN_ACTION), "stop"

    sampler._sample = sample
    with pytest.raises(SamplingStopped, match="trajectory_output_limit"):
        sampler([], maximum if budget_source == "trajectory" else 500, time.monotonic() + 100)


def test_zero_thinking_does_not_repair_malformed_action():
    sampler = unguarded_sampler()

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        assert role in {"candidate", "action"}
        return tokens(OPEN_ACTION if role == "candidate" else "echo unfinished"), "length"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert decision.kind == "format_error"
    assert sampler.diagnostics["rounds"][0]["parser_valid"] is False


def test_shared_end_token_survives_exact_action_prefix():
    sampler = guarded_sampler()
    vocabulary = {11: "THOUGHT", 12: "<mswea_bash_command", 17566: ">/",
                  13: "opt/python --version</mswea_bash_command>"}
    sampler._decode = lambda values: ''.join(vocabulary[token.token_id] for token in values)
    observed = []

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        observed.append((prompt, role))
        ids = [11, 12, 17566] if role == "candidate" else [13]
        return [Token(number, -1, 2) for number in ids], "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert observed[-1] == ([1, 2, 11, 12, 17566], "action")
    assert decision.messages[0]["extra"]["actions"] == [{"command": "/opt/python --version"}]
    assert decision.output_tokens == 4
    assert decision.token_logprobs == (-1, -1, -1, -1)
    assert sampler.diagnostics["rounds"][0]["sampled_body_prefix"] == "/"
    assert sampler.diagnostics["rounds"][0]["thinking_tokens"] == 1


def test_step_budget_continues_only_selected_prefix():
    sampler = guarded_sampler(max_steps_per_round=1)
    observed = []

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        observed.append((list(prompt), role))
        content = {"candidate": "think", "rollout": "DISCARD" + OPEN_ACTION,
                   "continuation": " done" + OPEN_ACTION + "echo ok</mswea_bash_command>"}[role]
        return tokens(content), "length"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert observed[-1] == ([1, 2] + [ord(character) for character in "think"], "continuation")
    assert "DISCARD" not in decision.messages[0]["content"]
    assert decision.kind == "action"
    assert sampler.diagnostics["rounds"][0]["fallback_reason"] == "is_step_budget"


def test_truncated_rollouts_are_not_scored_and_fallback_is_explicit():
    sampler = guarded_sampler()
    observed = []

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        observed.append((list(prompt), maximum, role))
        content = {"candidate": "think", "rollout": "longtail",
                   "continuation": "plain" + OPEN_ACTION + "echo ok</mswea_bash_command>"}[role]
        return tokens(content), "length"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert all(maximum == 8 for _, maximum, role in observed if role == "rollout")
    assert observed[-1][0] == [1, 2]
    round_record = sampler.diagnostics["rounds"][0]
    assert round_record["fallback_reason"] == "no_valid_thinking_rollout"
    assert all(candidate["rewards"] == [None, None] for candidate in round_record["steps"][0]["candidates"])
    assert "longtail" not in decision.messages[0]["content"]


@pytest.mark.parametrize("expired_at,expected", [(6, "continuation"), (101, "deadline")])
def test_round_timeout_discards_partial_block_but_case_deadline_does_not_fallback(monkeypatch, expired_at, expected):
    sampler = guarded_sampler(max_round_seconds=5)
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    observed = []

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        observed.append((list(prompt), role))
        if role == "rollout":
            clock[0] = expired_at
            raise BaselineDeadline()
        if role == "candidate":
            return tokens("unselected"), "length"
        return tokens("plain" + OPEN_ACTION + "echo ok</mswea_bash_command>"), "stop"

    sampler._sample = sample
    if expected == "deadline":
        with pytest.raises(BaselineDeadline):
            sampler([], 500, 100)
        assert not any(role == "continuation" for _, role in observed)
    else:
        decision = sampler([], 500, 100)
        assert observed[-1] == ([1, 2], "continuation")
        assert "unselected" not in decision.messages[0]["content"]
        assert sampler.diagnostics["rounds"][0]["fallback_reason"] == "is_round_time_budget"


def test_invalid_candidate_does_not_abort_other_proposals():
    from inference_scaling.swebench.thinking_is import InvalidSample

    sampler = guarded_sampler()
    counts = {"candidate": 0}

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        if role == "candidate":
            counts[role] += 1
            if counts[role] == 1:
                raise InvalidSample("corrupt score")
            return tokens("think" + OPEN_ACTION), "stop"
        return tokens("echo ok</mswea_bash_command>"), "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert decision.kind == "action"
    assert sampler.diagnostics["rounds"][0]["steps"][0]["weights"][0] == 0


@pytest.mark.parametrize("wrapped", [False, True])
def test_http_timeout_at_round_deadline_becomes_budget_signal(monkeypatch, wrapped):
    import urllib.error
    import urllib.request

    sampler = guarded_sampler()
    sampler.runtime = {"base_url": "http://localhost/v1", "api_key": "test"}
    sampler.factory.experiment.api.timeout_seconds = 100
    sampler.deadline = 5
    clock = [0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    sampler._post = ThinkingISSampler._post.__get__(sampler)

    def timeout(*args, **kwargs):
        clock[0] = 6
        error = TimeoutError("timed out")
        if wrapped:
            raise urllib.error.URLError(error)
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with pytest.raises(BaselineDeadline):
        sampler._post("/v1/completions", {})


@pytest.mark.parametrize("fails", [False, True])
def test_unlimited_case_keeps_finite_is_http_timeout(monkeypatch, fails):
    import io
    import urllib.request

    sampler = guarded_sampler()
    sampler.runtime = {"base_url": "http://localhost/v1", "api_key": "test"}
    sampler.factory.experiment.api.timeout_seconds = 100
    sampler.deadline = float("inf")

    def respond(request, *, timeout):
        assert timeout == 100
        if fails:
            raise TimeoutError("request timed out")
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    if fails:
        with pytest.raises(TimeoutError):
            ThinkingISSampler._post(sampler, "/v1/completions", {})
    else:
        assert ThinkingISSampler._post(sampler, "/v1/completions", {}) == {"ok": True}


def test_plain_fallback_does_not_execute_or_repair_incomplete_command():
    sampler = guarded_sampler()

    def sample(prompt, maximum, role):
        audit_fake_sample(sampler)
        if role == "continuation":
            return tokens("plain" + OPEN_ACTION + "echo unfinished"), "length"
        return tokens("no marker"), "stop"

    sampler._sample = sample
    decision = sampler([], 500, time.monotonic() + 100)
    assert decision.kind == "format_error"
    assert not any(message.get("extra", {}).get("actions") for message in decision.messages)
