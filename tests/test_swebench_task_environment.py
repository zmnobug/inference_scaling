from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from inference_scaling.swebench import task_environment as task_env
from inference_scaling.swebench.config import BudgetConfig
from inference_scaling.swebench.miniagent import BudgetedEnvironment, BudgetLedger, MiniAgentSessionFactory


def _ledger():
    return BudgetLedger(BudgetConfig(100, 0, 0, 100, 0))


def _probe_result(*, returncode=0, errors=None, prefix=task_env.CONDA_PREFIX):
    probe = {
        "python": prefix + "/bin/python", "prefix": prefix, "cwd": "/testbed",
        "imports": {"astropy": "/testbed/astropy/__init__.py"}, "errors": errors or [],
    }
    return {"returncode": returncode, "output": task_env.PROBE_MARKER + json.dumps(probe) + "\n"}


class ProbeEnvironment:
    def __init__(self, result=None):
        self.result = result or _probe_result()
        self.actions = []
        self.cleaned = False
        self.config = SimpleNamespace()

    def execute(self, action, **kwargs):
        self.actions.append((action, kwargs))
        return self.result

    def cleanup(self):
        self.cleaned = True

    def serialize(self):
        return {"info": {}}


def test_task_probe_verifies_project_and_runner_without_running_tests():
    environment = ProbeEnvironment()
    audit = task_env.verify_task_environment(
        environment, {"instance_id": "astropy-test", "repo": "astropy/astropy"}
    )
    assert audit["status"] == "ready"
    assert audit["checked_modules"] == ["astropy", "pytest"]
    command = environment.actions[0][0]["command"]
    assert "conda activate" in command
    assert "importlib.import_module" in command
    assert "pytest.main" not in command
    assert environment.actions[0][1] == {"timeout": 120}


@pytest.mark.parametrize("result", [
    _probe_result(returncode=1, errors=["ModuleNotFoundError: erfa"]),
    _probe_result(errors=["project import does not resolve to the task checkout"]),
    _probe_result(prefix="/opt/miniconda3"),
    {"returncode": 1, "output": "conda: command not found"},
    {"returncode": -1, "output": "probe timed out"},
])
def test_bad_environment_is_an_audited_error(result):
    with pytest.raises(task_env.TaskEnvironmentError) as caught:
        task_env.verify_task_environment(
            ProbeEnvironment(result), {"instance_id": "test", "repo": "astropy/astropy"}
        )
    assert caught.value.diagnostics["status"] == "error"
    assert caught.value.diagnostics["returncode"] == result["returncode"]
    assert caught.value.diagnostics["output_tail"] == result["output"]


def test_unknown_repository_is_not_silently_claimed_ready():
    environment = ProbeEnvironment()
    with pytest.raises(task_env.TaskEnvironmentError, match="no task import probe"):
        task_env.verify_task_environment(environment, {"instance_id": "test", "repo": "unknown/repo"})
    assert not environment.actions


def test_restored_branch_does_not_import_candidate_modified_project():
    environment = ProbeEnvironment()
    audit = task_env.verify_task_environment(
        environment, {"instance_id": "test", "repo": "astropy/astropy"}, restored=True
    )
    assert audit["checked_modules"] == []
    assert audit["restored"] is True
    assert "for module_name in ()" in environment.actions[0][0]["command"]


def test_sympy_probe_uses_public_runner_not_version_specific_module():
    command = task_env.task_probe_command(task_env.PROJECT_MODULES["sympy/sympy"])
    assert "sympy.testing.runtests" not in command
    assert "sympy.test" in command


def test_shell_activation_is_repeated_and_preserves_quoting_cwd_and_exit(tmp_path, monkeypatch):
    prefix = tmp_path / "testbed"
    (prefix / "bin").mkdir(parents=True)
    executable = prefix / "bin" / "task-python"
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$CONDA_PREFIX"\n')
    executable.chmod(0o755)
    init = tmp_path / "conda.sh"
    init.write_text('conda() { export CONDA_PREFIX="$2"; export PATH="$2/bin:$PATH"; }\n')
    monkeypatch.setattr(task_env, "CONDA_INIT", str(init))
    monkeypatch.setattr(task_env, "CONDA_PREFIX", str(prefix))
    command = "task-python; printf '%s\\n' 'single quote '\"'\"' and $literal'; pwd; exit 7"
    for _attempt in range(2):
        result = subprocess.run(
            ["bash", "-c", task_env.activate_task_command(command)],
            cwd=tmp_path, text=True, capture_output=True,
        )
        assert result.returncode == 7
        assert result.stdout.splitlines() == [str(prefix), "single quote ' and $literal", str(tmp_path)]


@pytest.mark.parametrize("activation_failure", [False, True])
def test_activation_failure_never_executes_action(tmp_path, monkeypatch, activation_failure):
    init = tmp_path / "conda.sh"
    if activation_failure:
        init.write_text("conda() { return 1; }\n")
    monkeypatch.setattr(task_env, "CONDA_INIT", str(init))
    target = tmp_path / "must-not-exist"
    result = subprocess.run(
        ["bash", "-c", task_env.activate_task_command(f"touch {target}")], text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert not target.exists()


def test_wrapped_actions_preserve_assertion_failure_and_audit():
    raw = ProbeEnvironment({"returncode": 1, "output": "FAILED test_example - AssertionError"})
    audit = {"protocol": task_env.TASK_ENVIRONMENT_PROTOCOL, "status": "ready"}
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger, task_environment=audit)
    action = {"command": "python -m pytest", "other": "preserved"}
    for _attempt in range(2):
        assert environment.execute(action, cwd="/testbed", timeout=30) == raw.result
    assert action["command"] == "python -m pytest"
    assert all("conda activate" in entry[0]["command"] for entry in raw.actions)
    assert all(entry[0]["other"] == "preserved" for entry in raw.actions)
    assert raw.actions[0][1] == {"cwd": "/testbed", "timeout": 30}
    assert ledger.snapshot().tool_calls == 2
    assert ledger.snapshot().tool_failures == 0
    assert environment.serialize()["info"]["runtime"]["task_environment"] == audit


def test_failed_probe_cleans_container_before_model_creation(monkeypatch):
    raw = ProbeEnvironment({"returncode": 1, "output": "No module named erfa"})
    monkeypatch.setattr("inference_scaling.swebench.miniagent.get_sb_environment", lambda *args: raw)
    factory = MiniAgentSessionFactory.__new__(MiniAgentSessionFactory)
    factory.mini_config = {}
    factory.instance = {"instance_id": "test", "repo": "astropy/astropy"}
    factory.environment_checks = []
    factory.make_model = lambda *args: pytest.fail("must not create model after failed probe")
    with pytest.raises(task_env.TaskEnvironmentError):
        factory.create("base", 7, 100)
    assert raw.cleaned
    assert factory.environment_checks[0]["status"] == "error"


@pytest.mark.parametrize("method", ["base", "is_thinking"])
def test_runner_persists_environment_failure_without_api_calls(monkeypatch, method):
    from inference_scaling.swebench.config import ExperimentArm
    from inference_scaling.swebench.runner import run_experiment_arm

    audit = {"protocol": task_env.TASK_ENVIRONMENT_PROTOCOL, "status": "error"}

    class FailingFactory:
        def __init__(self, *args, **kwargs):
            self.runtime = {"fingerprint": "runtime"}
            self.environment_checks = [audit]

        def create(self, *args):
            raise task_env.TaskEnvironmentError(audit)

        def close_all(self):
            return []

    monkeypatch.setattr("inference_scaling.swebench.runner.MiniAgentSessionFactory", FailingFactory)
    monkeypatch.setattr("inference_scaling.swebench.runner.miniagent_manifest", lambda *args: {})
    experiment = SimpleNamespace(
        budget=BudgetConfig(100, 0, 0, 100, 0), fingerprint="config",
        api=SimpleNamespace(model_name="openai/model"),
        agent=SimpleNamespace(max_trajectory_output_tokens=100),
    )
    record = run_experiment_arm(
        experiment, {"instance_id": "test"},
        ExperimentArm(method=method, chunk_tokens=100, candidate_count=4, rollout_count=2), 7
    )
    assert record["status"] == "error"
    assert record["error"]["type"] == "TaskEnvironmentError"
    assert record["diagnostics"]["task_environment"] == [audit]
    assert record["usage"]["api_requests"] == 0
    assert record["submission"] == ""


@pytest.mark.parametrize(("command", "expected"), [
    ("printf 'failed test\\n'; exit 7", 7),
    ("(printf 'failed test\\n'; exit 7) | tail -1", 7),
    ("printf 'passed\\n' | tail -1", 0),
    ("false | tail -1; printf 'later command masks status\\n'", 0),
])
def test_activated_shell_preserves_pipeline_failure(tmp_path, monkeypatch, command, expected):
    init = tmp_path / "conda.sh"
    init.write_text("conda() { return 0; }\n")
    monkeypatch.setattr(task_env, "CONDA_INIT", str(init))
    result = subprocess.run(["bash", "-c", task_env.activate_task_command(command)], capture_output=True)
    assert result.returncode == expected


def test_invalid_submission_is_feedback_not_terminal_and_can_retry():
    from minisweagent.exceptions import Submitted

    class SubmittingEnvironment(ProbeEnvironment):
        patch = "(no patch; no source changes were safely verifiable in this environment)\n"

        def execute(self, action, **kwargs):
            raise Submitted({
                "role": "exit", "content": self.patch,
                "extra": {"exit_status": "Submitted", "submission": self.patch},
            })

    raw = SubmittingEnvironment()
    ledger = _ledger()
    environment = BudgetedEnvironment(raw, ledger, task_environment={"status": "ready"})
    result = environment.execute({"command": "submit"})
    assert result["returncode"] == 1
    assert "Submission rejected" in result["output"]
    assert "not submitted" in result["output"]
    assert environment.submission_checks[0]["valid_syntax"] is False
    raw.patch = "diff --git a/code b/code\n--- a/code\n+++ b/code\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(Submitted) as caught:
        environment.execute({"command": "submit"})
    assert caught.value.messages[0]["extra"]["submission"] == raw.patch
    assert environment.submission_checks[-1]["valid_syntax"] is True
    assert ledger.snapshot().tool_calls == 2


def test_non_submission_interrupt_is_unchanged():
    from minisweagent.exceptions import InterruptAgentFlow

    class InterruptedEnvironment(ProbeEnvironment):
        def execute(self, action, **kwargs):
            raise InterruptAgentFlow({"role": "exit", "extra": {"exit_status": "OtherExit"}})

    environment = BudgetedEnvironment(InterruptedEnvironment(), _ledger(), task_environment={})
    with pytest.raises(InterruptAgentFlow):
        environment.execute({"command": "anything"})
    assert not environment.submission_checks
