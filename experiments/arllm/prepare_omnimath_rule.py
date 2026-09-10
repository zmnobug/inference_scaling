"""Materialize the pinned official Omni-MATH-Rule data and evaluator checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from inference_scaling.shared.evaluation.omnimath import (
    OMNIMATH_RULE_DATA_FILE,
    OMNIMATH_RULE_DATA_SHA256,
    OMNIMATH_RULE_REPOSITORY,
    OMNIMATH_RULE_REVISION,
    OMNIMATH_RULE_ROWS,
    verify_omnimath_rule_checkout,
)


def prepare_checkout(destination: Path) -> dict[str, object]:
    destination = destination.resolve()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                OMNIMATH_RULE_REPOSITORY,
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
                OMNIMATH_RULE_REVISION,
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
                OMNIMATH_RULE_REVISION,
            ],
            check=True,
        )
    if not (destination / ".git").is_dir():
        raise ValueError(f"{destination} exists but is not a Git checkout")
    revision = verify_omnimath_rule_checkout(destination)
    return {
        "repository": OMNIMATH_RULE_REPOSITORY,
        "revision": revision,
        "source_root": str(destination),
        "data_file": str(destination / OMNIMATH_RULE_DATA_FILE),
        "data_sha256": OMNIMATH_RULE_DATA_SHA256,
        "rows": OMNIMATH_RULE_ROWS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("data/omni_math_rule/upstream"),
    )
    args = parser.parse_args()
    report = prepare_checkout(args.destination)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
