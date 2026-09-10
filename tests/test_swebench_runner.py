from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from inference_scaling.swebench.config import ExperimentArm
from inference_scaling.swebench.miniagent import MiniAgentSessionFactory
from inference_scaling.swebench.runner import _run_conditional_is, _run_mh_chain


class FakeDecision:
    def __init__(self, logprob: float, request_id: str) -> None:
        self.logprob = logprob
        self.request_id = request_id
        self.output_tokens = 1
        self.token_logprobs = (logprob,)
        self.power_target_exact = False
        self.termination_status = "unscored"

    def to_dict(self) -> dict[str, object]:
        return {"logprob": self.logprob, "request_id": self.request_id}


class FakeExecuted:
    def __init__(self, decision: FakeDecision) -> None:
        self.decision = decision

    def to_dict(self) -> dict[str, object]:
        return self.decision.to_dict()


class FakeCheckpoint:
    def __init__(self, executed) -> None:
        self.executed = list(executed)

    def to_dict(self) -> dict[str, object]:
        return {"decision_count": len(self.executed)}


class FakeSession:
    def __init__(self, executed=(), *, terminal: bool = False) -> None:
        self.executed = list(executed)
        self._terminal = terminal
        self.closed = False
        self.agent = SimpleNamespace(model=object(), messages=[])
        self.max_trajectory_output_tokens = 8192
        self.initial_digest = "initial"

    @property
    def trajectory_output_tokens(self) -> int:
        return sum(item.decision.output_tokens for item in self.executed)

    @property
    def trajectory_logprob(self) -> float:
        return sum(item.decision.logprob for item in self.executed)

    @property
    def exit_status(self) -> str:
        return "Submitted" if self._terminal else ""

    @property
    def submission(self) -> str:
        return "patch" if self._terminal else ""

    def can_query(self) -> bool:
        return not self._terminal

    def apply_decision(self, decision) -> None:
        self.executed.append(FakeExecuted(decision))
        self._terminal = True

    def run_to_end(self) -> "FakeSession":
        return self

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self) -> None:
        self.main = FakeSession()
        self.discarded: list[FakeCheckpoint] = []

    def create(self, namespace: str, seed: int, chunk_tokens: int) -> FakeSession:
        return self.main

    def checkpoint(self, session: FakeSession) -> FakeCheckpoint:
        return FakeCheckpoint(session.executed)

    def create_from_checkpoint(
        self,
        checkpoint: FakeCheckpoint,
        namespace: str,
        seed: int,
        chunk_tokens: int,
    ) -> FakeSession:
        return FakeSession(checkpoint.executed, terminal=bool(checkpoint.executed))

    def discard_checkpoints(self, checkpoints) -> None:
        self.discarded.extend(checkpoints)


def test_is_promotes_checkpointed_candidate_without_double_counting(
    monkeypatch,
) -> None:
    decisions = iter((FakeDecision(-1.0, "one"), FakeDecision(-3.0, "two")))
    monkeypatch.setattr(
        "inference_scaling.swebench.runner._sample_decision",
        lambda *args, **kwargs: next(decisions),
    )
    monkeypatch.setattr(
        "inference_scaling.swebench.runner.select_is_candidate",
        lambda *args, **kwargs: (0, (1.0, 0.0), 1.0),
    )
    factory = FakeFactory()
    arm = ExperimentArm(
        method="is",
        alpha=2.0,
        candidate_count=2,
        chunk_tokens=64,
        rollout_count=1,
    )

    selected, diagnostics = _run_conditional_is(
        cast(MiniAgentSessionFactory, factory), arm, 7
    )

    assert selected.trajectory_logprob == -1.0
    assert diagnostics["steps"][0]["rollout_logprobs"] == [[-1.0], [-3.0]]
    assert factory.main.closed is True
    assert len(factory.discarded) == 2


class FakeMHSession(FakeSession):
    def __init__(self, executed=(), *, next_decision: FakeDecision) -> None:
        super().__init__(executed)
        self.next_decision: FakeDecision | None = next_decision

    def can_query(self) -> bool:
        return self.next_decision is not None

    def sample_decision(self) -> FakeDecision:
        assert self.next_decision is not None
        return self.next_decision

    def apply_decision(self, decision) -> None:
        self.executed.append(FakeExecuted(decision))
        self.next_decision = None


class FakeMHFactory:
    def __init__(self) -> None:
        self.initial = FakeMHSession(next_decision=FakeDecision(-3.0, "old"))
        self.proposal_checkpoint: FakeCheckpoint | None = None
        self.discarded: list[FakeCheckpoint] = []

    def create(self, namespace: str, seed: int, chunk_tokens: int):
        return self.initial

    def checkpoint(self, session: FakeMHSession) -> FakeCheckpoint:
        return FakeCheckpoint(session.executed)

    def create_from_checkpoint(
        self,
        checkpoint: FakeCheckpoint,
        namespace: str,
        seed: int,
        chunk_tokens: int,
        *,
        restore_model_request_index: bool = False,
    ) -> FakeMHSession:
        self.proposal_checkpoint = checkpoint
        return FakeMHSession(
            checkpoint.executed, next_decision=FakeDecision(-2.0, "new")
        )

    def discard_checkpoints(self, checkpoints) -> None:
        self.discarded.extend(checkpoints)


def test_mh_proposal_starts_from_cut_checkpoint_without_replay() -> None:
    factory = FakeMHFactory()
    arm = ExperimentArm(
        method="mh",
        alpha=1.0,
        chunk_tokens=64,
        updates_per_chain=1,
        max_suffix_actions=None,
        suffix_schedule="full",
        chains=1,
    )

    selected, diagnostics = _run_mh_chain(
        cast(MiniAgentSessionFactory, factory), arm, 7, 0
    )

    assert selected.trajectory_logprob == -2.0
    assert factory.proposal_checkpoint is not None
    assert factory.proposal_checkpoint.executed == []
    assert diagnostics["trace"][0]["cut"] == 0
    assert diagnostics["trace"][0]["accepted"] is True
