"""Deterministic OpenAI-compatible server for local SWE-bench smoke tests."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CONTENT = (
    "<mswea_bash_command>printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n"
    "mock-patch\\n'</mswea_bash_command>"
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._send({"object": "list", "data": [{"id": "mock", "object": "model"}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._send(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": CONTENT},
                        "finish_reason": "stop",
                        "logprobs": {
                            "content": [
                                {
                                    "token": CONTENT,
                                    "bytes": list(CONTENT.encode("utf-8")),
                                    "logprob": -1.0,
                                    "top_logprobs": [],
                                }
                            ]
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            }
        )

    def _send(self, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
