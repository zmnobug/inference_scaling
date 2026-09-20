"""Context-aware generation with elapsed-time tracking and optional hard deadline."""

from __future__ import annotations

import json
import signal
import threading
import time
import urllib.request
from typing import Any

from minisweagent.exceptions import FormatError

from inference_scaling.swebench.miniagent import (
    decision_from_format_error,
    decision_from_message,
)


class BaselineDeadline(BaseException):
    """Interrupt API retries and tool execution at the case deadline."""


class SamplingStopped(Exception):
    """Stop an arm without substituting another sampling method."""


def _deadline_reached(signum, frame) -> None:
    raise BaselineDeadline()


def count_prompt_tokens(messages, model_name, runtime, timeout: float) -> int:
    payload = {
        "model": model_name.removeprefix("openai/"),
        "messages": [
            {key: message[key] for key in ("role", "content") if key in message}
            for message in messages
        ],
        "add_generation_prompt": True,
    }
    base_url = runtime["base_url"].rstrip("/")
    request = urllib.request.Request(
        base_url.removesuffix("/v1") + "/tokenize",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runtime['api_key']}",
            **runtime.get("extra_headers", {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        count = json.load(response)["count"]
    if not isinstance(count, int) or count < 0:
        raise ValueError("tokenizer returned an invalid token count")
    return count


def run_budgeted_baseline(session, experiment, runtime, *, decision_sampler=None) -> dict[str, Any]:
    config = experiment.agent
    timed = config.wall_time_limit_seconds > 0
    if timed:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("hard baseline deadline requires main-thread workers=1")
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise RuntimeError("cannot replace an existing process deadline")
    reserve = getattr(config, "finalization_reserve_seconds", 0)
    started = time.monotonic()
    deadline = started + config.wall_time_limit_seconds if timed else float("inf")
    session.agent._start_time = time.time()
    diagnostics: dict[str, Any] = {
        "requests": [], "termination_reason": "", "wall_time_limit_seconds": config.wall_time_limit_seconds,
    }
    if getattr(config, "verification_reminder", False):
        session.agent.add_messages({
            "role": "user",
            "content": (
                "Before final submission, run a focused reproducer or relevant test that checks the requested "
                "behavior, including the reported edge case. Inspect its actual output; a plausible diff alone "
                "does not verify correctness. Keep time for verification and submission. If tests cannot run, "
                "state that limitation instead of claiming they passed."
            ),
        })
        diagnostics["verification_reminder"] = True
    previous_handler = None
    if timed:
        previous_handler = signal.signal(signal.SIGALRM, _deadline_reached)
        signal.setitimer(signal.ITIMER_REAL, config.wall_time_limit_seconds)

    def stop(reason: str) -> None:
        diagnostics["termination_reason"] = reason
        session._append_limit_exit(reason)

    try:
        while not session.terminal:
            remaining_time = deadline - time.monotonic()
            remaining_output = (
                config.max_trajectory_output_tokens - session.trajectory_output_tokens
            )
            if remaining_time <= 0:
                raise BaselineDeadline()
            finalizing = bool(reserve and remaining_time <= reserve)
            if finalizing and not diagnostics.get("finalization"):
                diagnostics["finalization"] = {"remaining_seconds": remaining_time, "mode": "ordinary_generation"}
                session.agent.add_messages({
                    "role": "user",
                    "content": (
                        f"Only {remaining_time:.0f} seconds remain for this task. Stop broad exploration. "
                        "Perform only essential focused verification if time permits, then submit your current patch "
                        "using COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT. Do not claim tests passed unless they ran."
                    ),
                })
            if remaining_output <= 0:
                stop("trajectory_output_limit")
                break
            prompt_tokens = count_prompt_tokens(
                session.agent.messages,
                experiment.api.model_name,
                runtime,
                min(30.0, remaining_time),
            )
            remaining_context = (
                config.context_window - prompt_tokens - config.context_safety_tokens
            )
            if remaining_context <= 0:
                stop("context_budget_exhausted")
                break
            if session.agent.n_calls >= config.step_limit:
                stop("agent_step_limit")
                break
            max_tokens = min(session.chunk_tokens, remaining_output, remaining_context)
            request_record = {
                "prompt_tokens": prompt_tokens,
                "max_tokens": max_tokens,
                "context_remaining": remaining_context,
                "trajectory_remaining": remaining_output,
                "remaining_seconds": deadline - time.monotonic() if timed else None,
                "elapsed_seconds": time.monotonic() - started,
            }
            diagnostics["requests"].append(request_record)
            sampling_deadline = deadline - reserve if decision_sampler is not None and not finalizing else deadline
            try:
                if decision_sampler is not None and not finalizing:
                    decision = decision_sampler(session.agent.messages, max_tokens, sampling_deadline)
                else:
                    decision = decision_from_message(
                        session.agent.model.query(
                            session.agent.messages,
                            max_tokens=max_tokens,
                            timeout=min(experiment.api.timeout_seconds, deadline - time.monotonic()),
                            num_retries=0,
                            extra_body={"top_k": -1},
                        )
                    )
            except FormatError as exc:
                decision = decision_from_format_error(exc)
            except BaselineDeadline:
                if reserve and decision_sampler is not None and not finalizing and sampling_deadline <= time.monotonic() < deadline:
                    request_record["interrupted_for_finalization"] = True
                    continue
                raise
            request_record.update(
                finish_reason=decision.finish_reason,
                actual_prompt_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                parser_valid=decision.kind == "action",
            )
            if time.monotonic() >= deadline:
                raise BaselineDeadline()
            projected_output = session.trajectory_output_tokens + decision.output_tokens
            if projected_output >= config.max_trajectory_output_tokens:
                diagnostics["unexecuted_decision"] = decision.to_dict()
                diagnostics["selected_output_tokens"] = projected_output
                session.agent.add_messages(*decision.messages)
                stop("trajectory_output_limit")
                break
            if decision.input_tokens != prompt_tokens:
                diagnostics["unexecuted_decision"] = decision.to_dict()
                session.agent.add_messages(*decision.messages)
                stop("prompt_token_count_mismatch")
                break
            if prompt_tokens + decision.output_tokens + config.context_safety_tokens >= config.context_window:
                diagnostics["unexecuted_decision"] = decision.to_dict()
                session.agent.add_messages(*decision.messages)
                stop("context_budget_exhausted")
                break
            if decision.kind == "format_error" and getattr(config, "max_consecutive_format_errors", 1) == 1:
                diagnostics["unexecuted_decision"] = decision.to_dict()
                session.agent.add_messages(*decision.messages)
                stop("format_error")
                break
            session.apply_decision(decision)
        if not diagnostics["termination_reason"]:
            diagnostics["termination_reason"] = session.exit_status
    except SamplingStopped as exc:
        stop(str(exc))
    except BaselineDeadline:
        stop("generation_timeout")
    except Exception as exc:
        diagnostics["error"] = {"type": type(exc).__name__, "message": str(exc)}
        stop("baseline_runtime_error")
    finally:
        if timed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
        diagnostics["agent_seconds"] = time.monotonic() - started
        rejected = getattr(session.agent.model, "rejected_responses", [])
        if rejected:
            diagnostics["rejected_responses"] = rejected
    return diagnostics
