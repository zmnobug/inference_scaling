"""Validate submission syntax without running tests or altering a task checkout."""

from __future__ import annotations

import subprocess
import tempfile


def submission_error(patch: str) -> str | None:
    if not patch.strip():
        return "The submission is empty."
    if not any(line.startswith("diff --git ") for line in patch.splitlines()):
        return "The submission is not a git diff; explanatory text is not a patch."
    try:
        with tempfile.TemporaryDirectory(prefix="swebench-patch-check-") as directory:
            result = subprocess.run(
                ["git", "apply", "--numstat", "-z", "-"],
                input=patch, text=True, capture_output=True, cwd=directory,
                timeout=10, check=False,
            )
        if result.returncode or not result.stdout:
            return "Invalid patch syntax: " + (result.stderr.strip()[:2000] or "no changes found")
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Patch syntax validation could not complete: {error}"
    return None
