from types import SimpleNamespace

import pytest

from inference_scaling.swebench.thinking_is import ThinkingISSampler, Token


def test_thinking_is_deepseek_eos_is_scored_and_excluded_from_action():
    marker = "<｜end▁of▁sentence｜>"
    text = "think</think><mswea_bash_command>echo ready</mswea_bash_command>"
    sampler = object.__new__(ThinkingISSampler)
    sampler._decode = lambda values: "".join(
        marker if token.token_id == 999 else chr(token.token_id) for token in values
    )
    sampler.factory = SimpleNamespace(mini_config={"model": {
        "action_regex": r"<mswea_bash_command>(.*?)</mswea_bash_command>",
        "format_error_template": "invalid {{actions|length}}",
    }})
    sampler.round_index = 1
    sampler.diagnostics = {"requests": [{"response": {"system_fingerprint": "test"}}]}
    sampler.model = "deepseek-v4-flash"
    full = [Token(ord(character), -0.1, 1.0) for character in text]
    full.append(Token(999, -0.2, 1.0))
    record = {}

    decision = sampler._decision(full, "stop", [1, 2], record)

    assert decision.kind == "action"
    assert decision.messages[0]["content"] == text
    assert decision.messages[0]["extra"]["actions"] == [{"command": "echo ready"}]
    assert decision.output_tokens == len(full)
    assert len(decision.token_logprobs) == len(full) - 1
    assert decision.termination_status == "scored"
    assert decision.termination_logprob == pytest.approx(-0.2)
    assert record["parser_valid"] is True
