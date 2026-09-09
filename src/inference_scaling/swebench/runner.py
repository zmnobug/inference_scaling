"""Base, conditional-IS, and trajectory-MH runners for official MiniAgent."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import traceback
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from inference_scaling.swebench.config import (
    ExperimentArm,
    ExperimentConfig,
    instance_fingerprint,
)
from inference_scaling.swebench.miniagent import (
    BudgetLedger,
    ExperimentBudgetExceeded,
    MiniAgentSession,
    MiniAgentSessionFactory,
    SampledDecision,
    SessionCheckpoint,
    decision_from_format_error,
    decision_from_message,
    miniagent_manifest,
)
from inference_scaling.swebench.sampling import (
    conditional_is_log_weights,
    mh_log_acceptance,
    metropolis_accept,
    sample_suffix_cut,
    select_is_candidate,
    suffix_cut_probabilities,
)

try:
    from minisweagent.exceptions import FormatError
except ImportError as exc:  # pragma: no cover - target preflight reports this
    raise ImportError("mini-swe-agent is required for SWE-bench runs") from exc


RESULT_SCHEMA_VERSION = "swebench-is-mh-v4"


def derive_seed(seed: int, *parts: object) -> int:
    payload = "|".join([str(seed), *(str(part) for part in parts)])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) & 0x7FFFFFFF


def _sample_decision(
    model,
    messages: Sequence[Mapping[str, Any]],
    *,
    max_tokens: int | None = None,
) -> SampledDecision:
    try:
        kwargs = {} if max_tokens is None else {"max_tokens": max_tokens}
        return decision_from_message(model.query(list(messages), **kwargs))
    except FormatError as exc:
        return decision_from_format_error(exc)


def _session_summary(session: MiniAgentSession) -> dict[str, Any]:
    return {
        "exit_status": session.exit_status,
        "submission_sha256": hashlib.sha256(
            session.submission.encode("utf-8")
        ).hexdigest(),
        "submission_bytes": len(session.submission.encode("utf-8")),
        "trajectory_logprob": session.trajectory_logprob,
        "decisions": len(session.executed),
        "generated_tokens": sum(
            len(item.decision.token_logprobs) for item in session.executed
        ),
        "trajectory_output_tokens": session.trajectory_output_tokens,
        "trajectory_output_token_limit": session.max_trajectory_output_tokens,
        "trajectory_limit_reached": (
            session.exit_status == "TrajectoryTokenLimitExceeded"
        ),
        "power_target_exact": bool(session.executed)
        and all(item.decision.power_target_exact for item in session.executed),
        "termination_statuses": sorted(
            {item.decision.termination_status for item in session.executed}
        ),
    }


def _run_base(
    factory: MiniAgentSessionFactory,
    arm: ExperimentArm,
    seed: int,
) -> tuple[MiniAgentSession, dict[str, Any]]:
    session = factory.create("base", seed, arm.chunk_tokens or factory.experiment.mh.chunk_tokens)
    session.run_to_end()
    return session, {"base": _session_summary(session)}


def _run_conditional_is(
    factory: MiniAgentSessionFactory,
    arm: ExperimentArm,
    seed: int,
) -> tuple[MiniAgentSession, dict[str, Any]]:
    if (
        arm.candidate_count is None
        or arm.chunk_tokens is None
        or arm.rollout_count is None
    ):
        raise ValueError("IS arm is missing candidate/chunk/rollout parameters")

    rng = random.Random(derive_seed(seed, "is", "selection"))
    main = factory.create("is-main", seed, arm.chunk_tokens)
    steps: list[dict[str, Any]] = []
    step_index = 0
    while main.can_query():
        candidate_model = main.agent.model
        remaining_tokens = (
            main.max_trajectory_output_tokens - main.trajectory_output_tokens
        )
        candidate_max_tokens = min(arm.chunk_tokens, remaining_tokens)
        candidates = tuple(
            _sample_decision(
                candidate_model,
                main.agent.messages,
                max_tokens=candidate_max_tokens,
            )
            for _ in range(arm.candidate_count)
        )
        rollout_logprobs: list[list[float]] = []
        rollout_summaries: list[list[dict[str, Any]]] = []
        candidate_sessions: list[MiniAgentSession] = []
        candidate_checkpoints: list[SessionCheckpoint] = []
        main_checkpoint = factory.checkpoint(main)

        for candidate_index, candidate in enumerate(candidates):
            candidate_seed = derive_seed(
                seed, "is", step_index, candidate_index, "state"
            )
            candidate_session = factory.create_from_checkpoint(
                main_checkpoint,
                f"is-s{step_index}-c{candidate_index}-state",
                candidate_seed,
                arm.chunk_tokens,
            )
            candidate_session.apply_decision(candidate)
            candidate_sessions.append(candidate_session)
            candidate_checkpoint = factory.checkpoint(candidate_session)
            candidate_checkpoints.append(candidate_checkpoint)
            candidate_values: list[float] = []
            candidate_summaries: list[dict[str, Any]] = []
            for rollout_index in range(arm.rollout_count):
                branch_seed = derive_seed(
                    seed, "is", step_index, candidate_index, rollout_index
                )
                branch = factory.create_from_checkpoint(
                    candidate_checkpoint,
                    f"is-s{step_index}-c{candidate_index}-r{rollout_index}",
                    branch_seed,
                    arm.chunk_tokens,
                )
                try:
                    prefix_length = len(branch.executed)
                    branch.run_to_end()
                    suffix_logprob = float(
                        sum(
                            item.decision.logprob
                            for item in branch.executed[prefix_length:]
                        )
                    )
                    if not math.isfinite(suffix_logprob):
                        raise ValueError("IS rollout produced a non-finite logprob")
                    trajectory_logprob = float(candidate.logprob + suffix_logprob)
                    if not math.isfinite(trajectory_logprob):
                        raise ValueError(
                            "IS rollout produced a non-finite trajectory logprob"
                        )
                    candidate_values.append(trajectory_logprob)
                    candidate_summaries.append(
                        {
                            **_session_summary(branch),
                            "candidate_logprob": candidate.logprob,
                            "suffix_logprob": suffix_logprob,
                            "trajectory_logprob": trajectory_logprob,
                            "candidate_request_id": candidate.request_id,
                            "suffix_decisions": [
                                item.to_dict()
                                for item in branch.executed[prefix_length:]
                            ],
                        }
                    )
                finally:
                    branch.close()
            rollout_logprobs.append(candidate_values)
            rollout_summaries.append(candidate_summaries)

        log_weights = conditional_is_log_weights(arm.alpha, rollout_logprobs)
        selected, weights, ess = select_is_candidate(
            arm.alpha, rollout_logprobs, rng
        )
        previous_main = main
        main = candidate_sessions[selected]
        previous_main.close()
        for candidate_index, candidate_session in enumerate(candidate_sessions):
            if candidate_index != selected:
                candidate_session.close()
        factory.discard_checkpoints(candidate_checkpoints)
        steps.append(
            {
                "step": step_index,
                "branch_state_mode": "docker_tagged_commit_checkpoint_v2",
                "main_checkpoint": main_checkpoint.to_dict(),
                "candidate_request_ids": [item.request_id for item in candidates],
                "candidate_logprobs": [item.logprob for item in candidates],
                "candidates": [item.to_dict() for item in candidates],
                "rollout_logprobs": rollout_logprobs,
                "log_weights": list(log_weights),
                "weights": list(weights),
                "ess": ess,
                "max_weight": max(weights),
                "weight_entropy": -sum(
                    weight * math.log(weight) for weight in weights if weight > 0
                ),
                "selected_index": selected,
                "rollouts": rollout_summaries,
            }
        )
        step_index += 1

    return main, {
        "steps": steps,
        "mean_ess": (
            sum(float(step["ess"]) for step in steps) / len(steps) if steps else 0.0
        ),
    }


def _continue_with_checkpoints(
    factory: MiniAgentSessionFactory,
    session: MiniAgentSession,
) -> tuple[MiniAgentSession, list[SessionCheckpoint]]:
    """Finish a trajectory while making every decision boundary forkable."""

    checkpoints: list[SessionCheckpoint] = []
    while session.can_query():
        session.apply_decision(session.sample_decision())
        checkpoint = factory.checkpoint(session)
        checkpoints.append(checkpoint)
    return session, checkpoints


def _new_checkpointed_trajectory(
    factory: MiniAgentSessionFactory,
    *,
    namespace: str,
    seed: int,
    chunk_tokens: int,
) -> tuple[MiniAgentSession, list[SessionCheckpoint]]:
    initial = factory.create(namespace, seed, chunk_tokens)
    initial_checkpoint = factory.checkpoint(initial)
    current, suffix_checkpoints = _continue_with_checkpoints(
        factory,
        initial,
    )
    return current, [initial_checkpoint, *suffix_checkpoints]


def _run_mh_chain(
    factory: MiniAgentSessionFactory,
    arm: ExperimentArm,
    seed: int,
    chain_index: int,
) -> tuple[MiniAgentSession, dict[str, Any]]:
    if (
        arm.updates_per_chain is None
        or arm.suffix_schedule is None
        or arm.chunk_tokens is None
    ):
        raise ValueError("MH arm is missing update/schedule/chunk parameters")
    rng = random.Random(derive_seed(seed, "mh", "accept", chain_index))
    initial_namespace = f"mh-chain{chain_index}-initial"
    initial_seed = derive_seed(seed, "mh", "initial", chain_index)
    current, current_checkpoints = _new_checkpointed_trajectory(
        factory,
        namespace=initial_namespace,
        seed=initial_seed,
        chunk_tokens=arm.chunk_tokens,
    )
    trace: list[dict[str, Any]] = []

    for update_index in range(arm.updates_per_chain):
        if not current.executed:
            break
        if len(current_checkpoints) != len(current.executed) + 1:
            raise RuntimeError(
                "MH checkpoint table must contain one boundary per decision plus "
                "the initial state"
            )
        forward = suffix_cut_probabilities(
            len(current.executed), arm.max_suffix_actions, arm.suffix_schedule
        )
        cut = sample_suffix_cut(forward, rng)
        proposal_namespace = f"mh-chain{chain_index}-update{update_index}"
        proposal_seed = derive_seed(
            seed, "mh", "proposal", chain_index, update_index
        )
        proposal = factory.create_from_checkpoint(
            current_checkpoints[cut],
            proposal_namespace,
            proposal_seed,
            arm.chunk_tokens,
        )
        proposal_suffix_checkpoints: list[SessionCheckpoint] = []
        accepted = False
        try:
            proposal, proposal_suffix_checkpoints = _continue_with_checkpoints(
                factory,
                proposal,
            )
            old_suffix_logprob = float(
                sum(item.decision.logprob for item in current.executed[cut:])
            )
            new_suffix_logprob = float(
                sum(item.decision.logprob for item in proposal.executed[cut:])
            )
            reverse = suffix_cut_probabilities(
                len(proposal.executed),
                arm.max_suffix_actions,
                arm.suffix_schedule,
            )
            reverse_probability = float(reverse.get(cut, 0.0))
            log_acceptance = mh_log_acceptance(
                alpha=arm.alpha,
                old_suffix_logprob=old_suffix_logprob,
                new_suffix_logprob=new_suffix_logprob,
                forward_cut_probability=float(forward[cut]),
                reverse_cut_probability=reverse_probability,
            )
            accepted = metropolis_accept(log_acceptance, rng)
            trace.append(
                {
                    "update": update_index,
                    "cut": cut,
                    "branch_state_mode": "docker_tagged_commit_checkpoint_v2",
                    "cut_checkpoint": current_checkpoints[cut].to_dict(),
                    "old_trajectory_decisions": len(current.executed),
                    "new_trajectory_decisions": len(proposal.executed),
                    "old_suffix_logprob": old_suffix_logprob,
                    "new_suffix_logprob": new_suffix_logprob,
                    "forward_cut_probability": forward[cut],
                    "reverse_cut_probability": reverse_probability,
                    "log_acceptance": log_acceptance,
                    "accepted": accepted,
                    "old_suffix_tokens": sum(
                        len(item.decision.token_logprobs)
                        for item in current.executed[cut:]
                    ),
                    "new_suffix_tokens": sum(
                        len(item.decision.token_logprobs)
                        for item in proposal.executed[cut:]
                    ),
                    "old_suffix_decisions": [
                        item.to_dict() for item in current.executed[cut:]
                    ],
                    "proposal_suffix_decisions": [
                        item.to_dict() for item in proposal.executed[cut:]
                    ],
                }
            )
            if accepted:
                previous = current
                discarded = current_checkpoints[cut + 1 :]
                current = proposal
                current_checkpoints = [
                    *current_checkpoints[: cut + 1],
                    *proposal_suffix_checkpoints,
                ]
                previous.close()
                factory.discard_checkpoints(discarded)
            else:
                proposal.close()
                factory.discard_checkpoints(proposal_suffix_checkpoints)
        except Exception:
            proposal.close()
            factory.discard_checkpoints(proposal_suffix_checkpoints)
            raise

    return current, {
        "chain": chain_index,
        "branch_state_mode": "docker_tagged_commit_checkpoint_v2",
        "checkpoint_count": len(current_checkpoints),
        "trace": trace,
        "attempts": len(trace),
        "accepted": sum(bool(item["accepted"]) for item in trace),
        "acceptance_rate": (
            sum(bool(item["accepted"]) for item in trace) / len(trace)
            if trace
            else 0.0
        ),
        "final": _session_summary(current),
    }


def _run_mh(
    factory: MiniAgentSessionFactory,
    arm: ExperimentArm,
    seed: int,
) -> tuple[MiniAgentSession, dict[str, Any]]:
    if arm.chains is None:
        raise ValueError("MH arm is missing chains")
    chosen_chain = random.Random(derive_seed(seed, "mh", "output-chain")).randrange(
        arm.chains
    )
    sessions: list[MiniAgentSession] = []
    diagnostics: list[dict[str, Any]] = []
    for chain_index in range(arm.chains):
        session, chain_diagnostics = _run_mh_chain(
            factory, arm, seed, chain_index
        )
        sessions.append(session)
        diagnostics.append(chain_diagnostics)
    selected = sessions[chosen_chain]
    for index, session in enumerate(sessions):
        if index != chosen_chain:
            session.close()
    return selected, {
        "chosen_chain": chosen_chain,
        "chains": diagnostics,
        "aggregate_acceptance_rate": (
            sum(item["accepted"] for item in diagnostics)
            / sum(item["attempts"] for item in diagnostics)
            if sum(item["attempts"] for item in diagnostics)
            else 0.0
        ),
    }


def run_experiment_arm(
    experiment: ExperimentConfig,
    instance: Mapping[str, Any],
    arm: ExperimentArm,
    seed: int,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run one arm and return an auditable, JSON-compatible record."""

    started = time.time()
    ledger = BudgetLedger(experiment.budget)
    factory: MiniAgentSessionFactory | None = None
    session: MiniAgentSession | None = None
    status = "completed"
    error: dict[str, str] | None = None
    diagnostics: dict[str, Any] = {}
    trajectory: dict[str, Any] | None = None
    submission = ""
    exit_status = ""
    try:
        factory = MiniAgentSessionFactory(
            experiment, instance, ledger, environ=environ
        )
        if arm.method == "base":
            session, diagnostics = _run_base(factory, arm, seed)
        elif arm.method == "is":
            session, diagnostics = _run_conditional_is(factory, arm, seed)
        elif arm.method == "mh":
            session, diagnostics = _run_mh(factory, arm, seed)
        else:
            raise ValueError(f"unknown method {arm.method}")
        submission = session.submission
        exit_status = session.exit_status
        trajectory = session.serialize()
    except ExperimentBudgetExceeded as exc:
        status = "budget_exceeded"
        error = {"type": type(exc).__name__, "message": str(exc)}
        if session is not None:
            submission = session.submission
            exit_status = session.exit_status or "ExperimentBudgetExceeded"
            trajectory = session.serialize()
    except Exception as exc:
        status = "error"
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        if session is not None:
            submission = session.submission
            exit_status = session.exit_status or type(exc).__name__
            trajectory = session.serialize()
    finally:
        if factory is not None:
            factory.close_all()

    usage = asdict(ledger.snapshot())
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "instance_id": str(instance["instance_id"]),
        "instance_fingerprint": instance_fingerprint(instance),
        "seed": int(seed),
        "method": arm.method,
        "arm_tag": arm.tag,
        "arm_fingerprint": arm.fingerprint,
        "arm": asdict(arm),
        "config_fingerprint": experiment.fingerprint,
        "model_name_or_path": experiment.api.model_name,
        "exit_status": exit_status,
        "submission": submission,
        "usage": usage,
        "diagnostics": diagnostics,
        "error": error,
        "trajectory": trajectory,
        "manifest": miniagent_manifest(experiment),
        "started_at": started,
        "finished_at": time.time(),
    }


def compact_result(record: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("trajectory", None)
    result["submission_sha256"] = hashlib.sha256(
        str(result.get("submission", "")).encode("utf-8")
    ).hexdigest()
    return result


def result_fingerprint(record: Mapping[str, Any]) -> str:
    payload = {
        "schema_version": record.get("schema_version"),
        "instance_id": record.get("instance_id"),
        "seed": record.get("seed"),
        "arm_fingerprint": record.get("arm_fingerprint"),
        "config_fingerprint": record.get("config_fingerprint"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
