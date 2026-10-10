from __future__ import annotations

import unittest

from experiments.swebench.diagnose_chat_logprobs import diagnose_response


def response(content: str, tokens: list[str], *, reasoning: str = "") -> dict:
    return {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": content, "reasoning_content": reasoning},
            "logprobs": {"content": [
                {"token": token, "bytes": list(token.encode()), "logprob": -0.1}
                for token in tokens
            ]},
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": len(tokens), "total_tokens": 10 + len(tokens)},
    }


class ChatLogprobProbeTests(unittest.TestCase):
    def test_matching_bytes_have_no_difference(self):
        report = diagnose_response(response("hello", ["he", "llo"]))
        self.assertIsNone(report["first_difference"])
        self.assertEqual(report["rebuilt_length"], 5)
        self.assertNotIn("bytes_tail", report)

    def test_unrecognized_termination_suffix_is_visible(self):
        report = diagnose_response(response("ok", ["ok", "<eos>"]))
        self.assertEqual(report["first_difference"], 2)
        self.assertEqual(report["content_tail"], "ok")
        self.assertEqual(report["bytes_tail"], "ok<eos>")
        self.assertEqual(report["last_logprob_tokens"][-1]["token"], "<eos>")

    def test_different_body_and_reasoning_are_reported(self):
        report = diagnose_response(response("answer", ["thought", "answer"], reasoning="thought"))
        self.assertEqual(report["first_difference"], 0)
        self.assertEqual(report["reasoning_length"], 7)

    def test_missing_bytes_do_not_claim_valid_reconstruction(self):
        raw = response("ok", ["ok"])
        raw["choices"][0]["logprobs"]["content"][0]["bytes"] = None
        report = diagnose_response(raw)
        self.assertEqual(report["missing_bytes"], 1)
        self.assertNotIn("first_difference", report)

    def test_invalid_utf8_reports_byte_offset(self):
        raw = response("ok", ["ok"])
        raw["choices"][0]["logprobs"]["content"][0]["bytes"] = [255]
        report = diagnose_response(raw)
        self.assertEqual(report["bytes_utf8_error_at"], 0)
        self.assertNotIn("first_difference", report)


if __name__ == "__main__":
    unittest.main()
