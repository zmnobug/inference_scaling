"""Activate and audit the prepared SWE-bench task environment."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping


TASK_ENVIRONMENT_PROTOCOL = "swebench-testbed-v2"
CONDA_PREFIX = "/opt/miniconda3/envs/testbed"
CONDA_INIT = "/opt/miniconda3/etc/profile.d/conda.sh"
PROBE_MARKER = "INFERENCE_SCALING_TASK_ENVIRONMENT="
TASK_ENVIRONMENT_GUIDANCE = """
Every tool command automatically activates the prepared Conda testbed environment.
Use python/python -m pytest or the repository's documented test runner from /testbed;
do not switch to the base /opt/miniconda3/bin/python interpreter.
Validate changes against actual repository code and relevant existing tests.
A copied or simplified reimplementation is not a substitute for testing the patch.
Distinguish assertion failures from dependency/import/collection failures: an import
failure or no collected tests does not demonstrate that the patch works.
Tool shells enable pipefail: a failed test piped through tail/grep still fails.
Run tests separately from unrelated commands; a later successful command can hide
an earlier failure. Inspect the test summary, not only the shell return code.
For submission, first generate and inspect a real git diff from /testbed. Then
print COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT followed only by that diff. Never
substitute an explanation, placeholder, or claimed success for a patch.
""".strip()

PROJECT_MODULES = {
    "astropy/astropy": ("astropy", "pytest"),
    "django/django": ("django", "django.test.runner"),
    "matplotlib/matplotlib": ("matplotlib", "pytest"),
    "mwaskom/seaborn": ("seaborn", "pytest"),
    "pallets/flask": ("flask", "pytest"),
    "psf/requests": ("requests", "pytest"),
    "pydata/xarray": ("xarray", "pytest"),
    "pylint-dev/pylint": ("pylint", "pytest"),
    "pytest-dev/pytest": ("pytest",),
    "scikit-learn/scikit-learn": ("sklearn", "pytest"),
    "sphinx-doc/sphinx": ("sphinx", "pytest"),
    "sympy/sympy": ("sympy",),
}


class TaskEnvironmentError(RuntimeError):
    """A task cannot start safely in its prepared execution environment."""

    def __init__(self, diagnostics: dict[str, Any]) -> None:
        self.diagnostics = diagnostics
        super().__init__(
            f"SWE-bench task environment check failed: {json.dumps(diagnostics)}"
        )


def activate_task_command(command: str) -> str:
    return (
        f"source {shlex.quote(CONDA_INIT)} && "
        f"conda activate {shlex.quote(CONDA_PREFIX)} && "
        f"exec bash -o pipefail -c {shlex.quote(command)}"
    )


def task_probe_command(modules: tuple[str, ...]) -> str:
    script = f"""import importlib, json, os, sys
report = {{"python": sys.executable, "prefix": sys.prefix,
          "cwd": os.getcwd(), "imports": {{}}, "errors": []}}
if os.path.realpath(sys.prefix) != {CONDA_PREFIX!r}:
    report["errors"].append("python is not in the prepared testbed environment")
if os.path.realpath(os.getcwd()) != "/testbed":
    report["errors"].append("initial working directory is not /testbed")
for module_name in {modules!r}:
    try:
        module = importlib.import_module(module_name)
        report["imports"][module_name] = getattr(module, "__file__", None)
    except Exception as error:
        report["errors"].append(module_name + ": " + type(error).__name__ + ": " + str(error))
if {bool(modules)!r}:
    project_path = report["imports"].get({modules[0] if modules else ''!r})
    if not project_path or not os.path.realpath(project_path).startswith("/testbed/"):
        report["errors"].append("project import does not resolve to the task checkout")
if {modules == ('sympy',)!r}:
    if not callable(getattr(sys.modules.get("sympy"), "test", None)):
        report["errors"].append("SymPy's public test runner is unavailable")
    else:
        report["test_runner"] = "sympy.test"
print({PROBE_MARKER!r} + json.dumps(report, sort_keys=True))
sys.exit(1 if report["errors"] else 0)
"""
    return activate_task_command("python -c " + shlex.quote(script))


def verify_task_environment(
    environment: Any,
    instance: Mapping[str, Any],
    *,
    restored: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    repository = str(instance.get("repo", ""))
    diagnostics: dict[str, Any] = {
        "protocol": TASK_ENVIRONMENT_PROTOCOL,
        "instance_id": str(instance["instance_id"]),
        "repository": repository,
        "restored": restored,
        "status": "error",
    }
    try:
        if not restored and repository not in PROJECT_MODULES:
            raise ValueError(f"no task import probe registered for {repository!r}")
        modules = () if restored else PROJECT_MODULES[repository]
        diagnostics["checked_modules"] = list(modules)
        result = environment.execute(
            {"command": task_probe_command(modules)}, timeout=120
        )
        diagnostics["returncode"] = result["returncode"]
        output = str(result.get("output", ""))
        diagnostics["output_tail"] = output[-12000:]
        probe_lines = [
            line[len(PROBE_MARKER):]
            for line in output.splitlines()
            if line.startswith(PROBE_MARKER)
        ]
        if len(probe_lines) != 1:
            raise ValueError("task environment probe did not return one audit record")
        probe = json.loads(probe_lines[0])
        diagnostics["probe"] = probe
        if result["returncode"] != 0 or probe.get("errors"):
            raise ValueError("task interpreter, imports or test runner are not ready")
        if probe.get("prefix") != CONDA_PREFIX or probe.get("cwd") != "/testbed":
            raise ValueError("task environment probe reported an unexpected location")
        diagnostics["status"] = "ready"
    except Exception as error:
        diagnostics["error"] = f"{type(error).__name__}: {error}"
        diagnostics["elapsed_seconds"] = time.monotonic() - started
        raise TaskEnvironmentError(diagnostics) from error
    diagnostics["elapsed_seconds"] = time.monotonic() - started
    return diagnostics
