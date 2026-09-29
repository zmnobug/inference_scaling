from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Expected one occurrence: {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    reference = repository / "results/swebench/qwen38-thinking-is-c100-random100-rebased-v7-20260926-dual"
    tag = "qwen38-baseline-random100-aligned-is3-v7-20260928"
    output = Path("/data/users/jenkins/inference_scaling-results") / f"{tag}-dual"
    link = repository / "results/swebench" / output.name
    if output.exists() or link.exists() or link.is_symlink():
        raise FileExistsError("Refusing to overwrite or restart the aligned baseline")
    old_config = "configs/qwen38_swebench_thinking_is_random100_rebased_v7_20260926.toml"
    config = "configs/qwen38_swebench_baseline_aligned_is3_20260928.toml"
    archive = reference / "source_snapshot.tar.gz"
    with tarfile.open(archive) as snapshot:
        config_text = snapshot.extractfile(old_config).read().decode()
        launcher = snapshot.extractfile(
            "experiments/swebench/run_baseline_random100_second_dual_background.sh"
        ).read().decode()
    modified = replace_once(config_text, 'tag = "qwen38-thinking-is-c100-random100-rebased-v7-20260926"', f'tag = "{tag}"')
    modified = replace_once(modified, 'method = "is_thinking"\nchunk_tokens = 100\ncandidate_count = 4\nrollout_count = 2', 'method = "base"\nchunk_tokens = 131072')
    original = tomllib.loads(config_text)
    aligned = tomllib.loads(modified)
    expected = tomllib.loads(config_text)
    expected["run"]["tag"] = tag
    expected["arms"] = [{"method": "base", "chunk_tokens": 131072}]
    if aligned != expected or original["run"]["seeds"] != [20260916]:
        raise ValueError("Unexpected protocol change")
    launcher = replace_once(launcher, 'repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"', f'repository_root="{repository}"')
    launcher = launcher.replace("qwen38-baseline-random100-second-v7-20260924", tag)
    launcher = replace_once(launcher, "configs/qwen38_swebench_random100_baseline_second_20260924.toml", config)
    snapshot_start = launcher.index('git rev-parse HEAD >')
    snapshot_end = launcher.index('runtime_root="${output}/source"')
    launcher = launcher[:snapshot_start] + f'''reference="{reference.resolve()}"
for filename in source_head.txt source_status.txt source_worktree.patch source_snapshot.tar.gz; do
  cp "${{reference}}/${{filename}}" "${{output}}/${{filename}}" || exit 1
done
''' + launcher[snapshot_end:]
    launcher = replace_once(launcher, 'cd "${runtime_root}" || exit 1', f'cp "${{output}}/aligned_config.toml" "${{runtime_root}}/{config}" || exit 1\ncd "${{runtime_root}}" || exit 1')
    launcher = replace_once(launcher, "--seed 20260924", "--seed 20260916")
    launcher = replace_once(launcher, "qwen38-baseline-second-20260924-${shard}", "qwen38-baseline-aligned-is3-20260928-${shard}")
    subprocess.run(["bash", "-n"], input=launcher, text=True, check=True)
    for path in (repository, output.parent):
        if shutil.disk_usage(path).free < 4 * 1024**3:
            raise RuntimeError(f"Disk guard: {path}")
    output.mkdir()
    link.symlink_to(output, target_is_directory=True)
    (output / "aligned_config.toml").write_text(modified)
    (output / "reference_config.toml").write_text(config_text)
    (output / "launch.sh").write_text(launcher)
    (output / "protocol.json").write_text(json.dumps({
        "reference_run": str(reference.resolve()),
        "reference_source_head": (reference / "source_head.txt").read_text().strip(),
        "reference_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "seed": 20260916,
        "allowed_changes": {"run.tag": tag, "arms": aligned["arms"]},
        "agent_reward_or_environment_changes": False,
        "note": "IS3 operator-skipped django-10554; baseline runs all 100. No historical results replaced.",
    }, indent=2) + "\n")
    with (output / "launcher.log").open("ab") as log:
        process = subprocess.Popen(
            ["bash", str(output / "launch.sh")], cwd=repository,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    print(json.dumps({"output": str(output), "pid": process.pid}))


if __name__ == "__main__":
    main()
