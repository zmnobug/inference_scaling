"""Compare chat content with sampled logprob bytes without storing responses.

Export OPENAI_API_BASE and OPENAI_API_KEY, then run
python3 -m experiments.swebench.diagnose_chat_logprobs --model deepseek-v4-flash
from the repository root. Sends one bounded request; never prints credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from itertools import zip_longest
from typing import Any


def diagnose_response(response: dict[str, Any]) -> dict[str, Any]:
    choice = response["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    entries = choice["logprobs"]["content"]
    missing_bytes = sum(entry.get("bytes") is None for entry in entries)
    usage = response.get("usage") or {}
    report: dict[str, Any] = {
        "finish_reason": choice.get("finish_reason"),
        "usage": {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "reasoning_length": len(message.get("reasoning_content") or ""),
        "content_length": len(content),
        "logprob_entries": len(entries),
        "missing_bytes": missing_bytes,
        "last_logprob_tokens": [
            {
                "token": str(entry.get("token"))[:80],
                "bytes": (entry.get("bytes") or [])[:32],
                "bytes_length": len(entry.get("bytes") or []),
            }
            for entry in entries[-3:]
        ],
    }
    if missing_bytes:
        return report
    raw = bytes(byte for entry in entries for byte in entry["bytes"])
    try:
        rebuilt = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        report["bytes_utf8_error_at"] = exc.start
        return report
    difference = next(
        (index for index, (left, right) in enumerate(zip_longest(content, rebuilt)) if left != right),
        None,
    )
    report.update(rebuilt_length=len(rebuilt), first_difference=difference)
    if difference is not None:
        start = max(0, difference - 20)
        report["content_near_difference"] = content[start:difference + 60]
        report["bytes_near_difference"] = rebuilt[start:difference + 60]
        report["content_tail"] = content[-80:]
        report["bytes_tail"] = rebuilt[-80:]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    args = parser.parse_args()
    base_url = os.environ.get("OPENAI_API_BASE", "").rstrip("/")
    if not base_url.endswith("/v1"):
        parser.error("OPENAI_API_BASE must point to the vLLM /v1 endpoint")
    payload = {
        "model": args.model.removeprefix("openai/"),
        "messages": [
            {"role": "system", "content": "Return one short bash command."},
            {"role": "user", "content": "Reply with <mswea_bash_command>echo ready</mswea_bash_command>."},
        ],
        "max_tokens": 64,
        "temperature": 1.0,
        "top_p": 1.0,
        "seed": 20260916,
        "logprobs": True,
        "stream": False,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "EMPTY"),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as result:
            response = json.load(result)
    except urllib.error.HTTPError as exc:
        parser.exit(1, f"Chat completions request failed: HTTP {exc.code}\n")
    print(json.dumps(diagnose_response(response), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
