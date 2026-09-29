"""Supervise the existing serial pilot at its tenth committed case boundary."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import select
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

from experiments.swebench.io import atomic_write_json, existing_record_matches, rebuild_predictions
from experiments.swebench.run_suite import _wait_for_disk_space
from experiments.swebench.summarize import summarize_results
from inference_scaling.swebench.config import load_experiment_config


ROOT = Path(__file__).resolve().parents[2]
TAG = "qwen38-thinking-is-c100-pilot20-20260918"
SOURCE = ROOT / "results/swebench" / TAG
OUTPUT = ROOT / "results/swebench/qwen38-thinking-is-c100-pilot20-dual-20260918"
CONFIG = ROOT / "configs/qwen38_swebench_thinking_is_pilot20.toml"
SELECTION = ROOT / "configs/qwen38_swebench_thinking_is_pilot20_instances.txt"
SHARD_B = ROOT / "configs/qwen38_swebench_thinking_is_pilot20_shard_b.txt"
UNIT = "qwen38-swebench-thinking-is-c100-pilot20-20260918.service"
ARM = "is_thinking-a1-b4-c100-r2"
SEED = 20260916
RELATIVE_INSTANCES = Path(ARM) / f"seed-{SEED}" / "instances"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_partition(all_ids: list[str], second: list[str]) -> None:
    if len(all_ids) != 20 or len(set(all_ids)) != 20 or second != all_ids[10:]:
        raise ValueError("expected the original 20 unique IDs and exact last 10")


def open_process_handle(pid: int) -> int:
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    if platform.machine() != "x86_64":
        raise RuntimeError("pidfd fallback requires Linux x86_64")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    descriptor = library.syscall(434, pid, 0)
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "pidfd_open")
    return descriptor


def signal_process_handle(descriptor: int, number: int) -> None:
    if hasattr(signal, "pidfd_send_signal"):
        signal.pidfd_send_signal(descriptor, number)
        return
    if platform.machine() != "x86_64":
        raise RuntimeError("pidfd fallback requires Linux x86_64")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    if library.syscall(424, descriptor, number, ctypes.c_void_p(), 0) < 0:
        raise OSError(ctypes.get_errno(), "pidfd_send_signal")


def stop_original_queue() -> None:
    subprocess.run(["systemctl", "--user", "kill", "--kill-who=all", "--signal=SIGKILL", UNIT], check=True)


def merge_shards(source: Path, replica: Path, destination: Path, all_ids: list[str]) -> None:
    experiment = load_experiment_config(CONFIG)
    source_manifest = read_json(source / "manifest.json")
    replica_manifest = read_json(replica / "manifest.json")
    if source_manifest["dataset"]["instance_ids"] != all_ids:
        raise ValueError("original manifest does not match fixed pilot20")
    if replica_manifest["dataset"]["instance_ids"] != all_ids[10:]:
        raise ValueError("replica manifest does not match shard B")
    if destination.exists() or destination.with_suffix(".tmp").exists():
        raise FileExistsError(destination)
    sources = [(source, all_ids[:10], source_manifest), (replica, all_ids[10:], replica_manifest)]
    validated = []
    for shard, assigned, manifest in sources:
        found = sorted(path.parent.name for path in (shard / RELATIVE_INSTANCES).glob("*/record.json"))
        if found != sorted(assigned):
            raise ValueError(f"missing, duplicate or unassigned results in {shard}: {found}")
        if manifest["config_fingerprint"] != experiment.fingerprint:
            raise ValueError(f"configuration changed in {shard}")
        for instance_id in assigned:
            directory = shard / RELATIVE_INSTANCES / instance_id
            record = read_json(directory / "record.json")
            if (record["instance_id"] != instance_id or record["seed"] != SEED
                    or record["arm_tag"] != ARM
                    or record["config_fingerprint"] != experiment.fingerprint
                    or record["runtime_fingerprint"] != manifest["model"]["runtime_fingerprint"]
                    or not record.get("finished_at")):
                raise ValueError(f"invalid record provenance: {directory}")
            validated.append(directory)
    staging = destination.with_suffix(".tmp")
    staging.mkdir(parents=True)
    for directory in validated:
        shutil.copytree(directory, staging / RELATIVE_INSTANCES / directory.name)
    shutil.copy2(source / "dataset.parquet", staging / "dataset.parquet")
    manifest = json.loads(json.dumps(source_manifest))
    manifest["tag"] = TAG + "-dual-merged"
    manifest["model"]["runtime_fingerprint"] = None
    manifest["execution_shards"] = [
        {"source": str(shard), "instance_ids": assigned,
         "runtime_fingerprint": shard_manifest["model"]["runtime_fingerprint"]}
        for shard, assigned, shard_manifest in sources
    ]
    manifest["aggregation_only"] = True
    atomic_write_json(staging / "manifest.json", manifest)
    rebuild_predictions(staging, experiment.arms, [SEED], all_ids)
    atomic_write_json(staging / "inference_summary.json", summarize_results(staging))
    staging.rename(destination)


class CaseBoundaryWatch:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        library = ctypes.CDLL(None, use_errno=True)
        library.inotify_init1.argtypes = [ctypes.c_int]
        library.inotify_init1.restype = ctypes.c_int
        library.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        library.inotify_add_watch.restype = ctypes.c_int
        self.descriptor = library.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        if self.descriptor < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        if library.inotify_add_watch(self.descriptor, os.fsencode(directory), 0x80) < 0:
            os.close(self.descriptor)
            raise OSError(ctypes.get_errno(), "inotify_add_watch")

    def committed(self, timeout: float = 5) -> bool:
        if not select.select([self.descriptor], [], [], timeout)[0]:
            return False
        events = os.read(self.descriptor, 65536)
        offset = 0
        while offset < len(events):
            _, mask, _, length = struct.unpack_from("iIII", events, offset)
            name = events[offset + 16:offset + 16 + length].rstrip(b"\0")
            offset += 16 + length
            if mask & 0x4000:
                raise RuntimeError("inotify event queue overflow")
            if mask & 0x80 and name == b"record.json":
                return True
        return False

    def close(self) -> None:
        os.close(self.descriptor)


def main() -> None:
    all_ids = SELECTION.read_text().splitlines()
    validate_partition(all_ids, SHARD_B.read_text().splitlines())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT / "assignment.json").exists():
        raise FileExistsError("refusing an implicit supervisor restart")
    main_pid = int(subprocess.check_output(
        ["systemctl", "--user", "show", UNIT, "-p", "MainPID", "--value"], text=True
    ).strip())
    children = Path(f"/proc/{main_pid}/task/{main_pid}/children").read_text().split()
    runners = [int(child) for child in children if b"experiments.swebench.run_suite"
               in Path(f"/proc/{child}/cmdline").read_bytes()]
    if len(runners) != 1:
        raise RuntimeError(f"expected one original runner, found {runners}")
    runner_pid = runners[0]
    process_descriptor = open_process_handle(runner_pid)
    boundary = SOURCE / RELATIVE_INSTANCES / all_ids[9] / "record.json"
    watcher = CaseBoundaryWatch(boundary.parent)
    if boundary.exists() or any((SOURCE / RELATIVE_INSTANCES / name / "record.json").exists()
                                for name in all_ids[10:]):
        raise RuntimeError("original runner has already reached the handoff boundary")
    atomic_write_json(OUTPUT / "assignment.json", {
        "created_at": time.time(), "original_unit": UNIT, "original_runner_pid": runner_pid,
        "shard_a": {"endpoint": "http://127.0.0.1:8000/v1", "instance_ids": all_ids[:10]},
        "shard_b": {"endpoint": "http://127.0.0.1:8001/v1", "instance_ids": all_ids[10:]},
        "boundary_record": str(boundary), "no_automatic_retry": True,
    })
    replica_parent = OUTPUT / "replica"
    environment = dict(os.environ, OPENAI_API_BASE="http://127.0.0.1:8001/v1")
    with (OUTPUT / "replica.log").open("a") as log:
        replica = subprocess.Popen(
            [str(ROOT / "run_swebench.sh"), str(CONFIG), "--instance-file", str(SHARD_B),
             "--output", str(replica_parent), "--min-free-gib", "4"],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
        )
        print(json.dumps({"status": "split_running", "replica_pid": replica.pid,
                          "original_runner_pid": runner_pid, "boundary": all_ids[9]}), flush=True)
        while not watcher.committed():
            if select.select([process_descriptor], [], [], 0)[0]:
                raise RuntimeError("original runner exited before handoff")
        signal_process_handle(process_descriptor, signal.SIGSTOP)
        try:
            missing = [name for name in all_ids[:10]
                       if not (SOURCE / RELATIVE_INSTANCES / name / "record.json").is_file()]
            if missing:
                raise RuntimeError(f"boundary reached with missing prior records: {missing}")
        except BaseException:
            signal_process_handle(process_descriptor, signal.SIGCONT)
            raise
        stop_original_queue()
        atomic_write_json(SOURCE / "queue_handoff.json", {
            "at": time.time(), "reason": "first ten records committed; remaining ten delegated",
            "supervisor": str(OUTPUT), "retained_ids": all_ids[:10], "delegated_ids": all_ids[10:],
        })
        atomic_write_json(OUTPUT / "handoff_complete.json", {"at": time.time(), "first_ten_saved": True})
        print(json.dumps({"status": "original_first_ten_finished"}), flush=True)
        watcher.close()
        os.close(process_descriptor)
        replica_status = replica.wait()
    finish_pipeline(replica_status, all_ids)


def finish_pipeline(replica_status: int, all_ids: list[str]) -> None:
    atomic_write_json(OUTPUT / "replica_exit.json", {"exit_code": replica_status})
    _wait_for_disk_space(OUTPUT, 4)
    merged = OUTPUT / "merged"
    merge_shards(SOURCE, OUTPUT / "replica" / TAG, merged, all_ids)
    evaluation = subprocess.run([
        str(ROOT / "evaluate_swebench.sh"), str(merged), "--arm", ARM, "--seed", str(SEED),
        "--max-workers", "1", "--run-prefix", "qwen38-thinking-is-pilot20-dual-20260918",
    ], cwd=ROOT)
    atomic_write_json(OUTPUT / "pipeline_exit.json", {
        "replica_generation": replica_status, "evaluation": evaluation.returncode,
        "finished_at": time.time(), "merged": str(merged),
    })
    sys.exit(evaluation.returncode)


def resume_after_handoff() -> None:
    from experiments.swebench.evaluate import _load_parquet_rows

    all_ids = SELECTION.read_text().splitlines()
    validate_partition(all_ids, SHARD_B.read_text().splitlines())
    assignment = read_json(OUTPUT / "assignment.json")
    if assignment["shard_a"]["instance_ids"] != all_ids[:10] or assignment["shard_b"]["instance_ids"] != all_ids[10:]:
        raise ValueError("saved shard assignments changed")
    main_pid = int(subprocess.check_output(
        ["systemctl", "--user", "show", UNIT, "-p", "MainPID", "--value"], text=True
    ).strip())
    if main_pid:
        raise RuntimeError("original queue must be fully stopped before recovery")
    found = sorted(path.parent.name for path in (SOURCE / RELATIVE_INSTANCES).glob("*/record.json"))
    if found != sorted(all_ids[:10]):
        raise ValueError("original shard does not contain exactly its ten records")
    if (OUTPUT / "recovery_started.json").exists():
        raise FileExistsError("refusing an implicit recovery retry")
    experiment = load_experiment_config(CONFIG)
    replica_root = OUTPUT / "replica" / TAG
    manifest = read_json(replica_root / "manifest.json")
    if manifest["dataset"]["instance_ids"] != all_ids[10:]:
        raise ValueError("replica manifest does not match shard B")
    instances = {row["instance_id"]: row for row in _load_parquet_rows(replica_root / "dataset.parquet")}
    hashes = {}
    retained = []
    for instance_id in all_ids[10:]:
        path = replica_root / RELATIVE_INSTANCES / instance_id / "record.json"
        if not path.exists():
            continue
        if not existing_record_matches(path, experiment, experiment.arms[0], SEED, instances[instance_id],
                                       runtime_fingerprint=manifest["model"]["runtime_fingerprint"]):
            raise ValueError(f"existing record would be rerun, refusing recovery: {instance_id}")
        retained.append(instance_id)
    for directory in (SOURCE, replica_root):
        for path in (directory / RELATIVE_INSTANCES).glob("*/record.json"):
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    atomic_write_json(OUTPUT / "recovery_started.json", {
        "at": time.time(), "reason": "systemd kill-whom option unavailable; resume unfinished cases only",
        "retained_shard_b": retained, "pending_shard_b": [name for name in all_ids[10:] if name not in retained],
        "preserved_record_sha256": hashes,
    })
    environment = dict(os.environ, OPENAI_API_BASE="http://127.0.0.1:8001/v1")
    with (OUTPUT / "replica.log").open("a") as log:
        log.write("\nRECOVERY: resume unfinished cases after infrastructure interruption\n")
        log.flush()
        result = subprocess.run([
            str(ROOT / "run_swebench.sh"), str(CONFIG), "--instance-file", str(SHARD_B),
            "--output", str(OUTPUT / "replica"), "--min-free-gib", "4",
        ], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    for filename, digest in hashes.items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"previous result changed during recovery: {filename}")
    finish_pipeline(result.returncode, all_ids)


if __name__ == "__main__":
    if sys.argv[1:] == ["--resume-after-handoff"]:
        resume_after_handoff()
    elif sys.argv[1:]:
        raise SystemExit("usage: split_running_pilot20 [--resume-after-handoff]")
    else:
        main()
