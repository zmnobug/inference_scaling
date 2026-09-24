from __future__ import annotations

import subprocess

import pytest

from inference_scaling.swebench.submission import submission_error


VALID_PATCH = """diff --git a/example.py b/example.py
index 3367afd..3e75765 100644
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


@pytest.mark.parametrize("patch", [
    "", "   ", "(no patch; no source changes were safely verifiable in this environment)\n",
    "Tests passed; task complete.", "diff --git a/example.py b/example.py\nnot a patch\n",
    VALID_PATCH.replace("@@ -1 +1 @@", "@@ -12,99 +12,99 @@"),
])
def test_rejects_empty_prose_and_malformed_patch(patch):
    assert submission_error(patch)


def test_valid_patch_is_syntax_checked_without_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = tmp_path / "example.py"
    original.write_text("different checkout\n")
    assert submission_error(VALID_PATCH) is None
    assert original.read_text() == "different checkout\n"


@pytest.mark.parametrize("kind", ["rename", "delete", "binary"])
def test_accepts_real_git_diff_variants(tmp_path, kind):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    original = tmp_path / "original"
    original.write_bytes(b"\0original\n" if kind == "binary" else b"original\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture",
    ], check=True)
    if kind == "rename":
        original.rename(tmp_path / "renamed")
    elif kind == "delete":
        original.unlink()
    else:
        original.write_bytes(b"\0modified\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    patch = subprocess.check_output(
        ["git", "-C", str(tmp_path), "diff", "--binary", "HEAD"], text=True,
    )
    assert submission_error(patch) is None
