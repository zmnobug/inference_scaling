"""Materialize a pinned LiveCodeBench runner and release_v6 data snapshot."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from inference_scaling.shared.evaluation.livecodebench import (
    LIVECODEBENCH_DATASET,
    LIVECODEBENCH_EXPECTED_ROWS,
    LIVECODEBENCH_RELEASE,
    LIVECODEBENCH_REPOSITORY,
    LIVECODEBENCH_REVISION,
    file_sha256,
    load_livecodebench_snapshot,
    verify_livecodebench_checkout,
)


def prepare_checkout(destination: Path) -> str:
    destination = destination.resolve()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                LIVECODEBENCH_REPOSITORY,
                str(destination),
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(destination),
                "fetch",
                "--depth",
                "1",
                "origin",
                LIVECODEBENCH_REVISION,
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(destination),
                "checkout",
                "--detach",
                LIVECODEBENCH_REVISION,
            ],
            check=True,
        )
    if not (destination / ".git").is_dir():
        raise ValueError(f"{destination} exists but is not a Git checkout")
    return verify_livecodebench_checkout(destination)


def _json_compatible(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def materialize_snapshot(destination: Path) -> dict[str, object]:
    try:
        from datasets import load_dataset
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "datasets is required to prepare LiveCodeBench; install the "
            "project's 'livecodebench' extra"
        ) from error

    destination = destination.resolve()
    if destination.exists():
        problems = load_livecodebench_snapshot(destination)
        return {
            "dataset": LIVECODEBENCH_DATASET,
            "release": LIVECODEBENCH_RELEASE,
            "snapshot": str(destination),
            "snapshot_sha256": file_sha256(destination),
            "rows": len(problems),
            "reused": True,
        }

    dataset = load_dataset(
        LIVECODEBENCH_DATASET,
        split="test",
        version_tag=LIVECODEBENCH_RELEASE,
        trust_remote_code=True,
    )
    if len(dataset) != LIVECODEBENCH_EXPECTED_ROWS:
        raise ValueError(
            f"expected {LIVECODEBENCH_EXPECTED_ROWS} rows for "
            f"{LIVECODEBENCH_RELEASE}, found {len(dataset)}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as sink:
        for row in dataset:
            sink.write(
                json.dumps(
                    _json_compatible(dict(row)),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    temporary.replace(destination)
    load_livecodebench_snapshot(destination)
    return {
        "dataset": LIVECODEBENCH_DATASET,
        "release": LIVECODEBENCH_RELEASE,
        "snapshot": str(destination),
        "snapshot_sha256": file_sha256(destination),
        "rows": len(dataset),
        "reused": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/livecodebench/official"),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("data/livecodebench/release_v6.jsonl"),
    )
    args = parser.parse_args()

    revision = prepare_checkout(args.source_root)
    report = materialize_snapshot(args.snapshot)
    report.update(
        {
            "official_repository": LIVECODEBENCH_REPOSITORY,
            "official_revision": revision,
            "official_source_root": str(args.source_root.resolve()),
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
