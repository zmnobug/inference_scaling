"""Validate Python, pinned MiniAgent, Docker, dataset, and API logprobs."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from experiments.swebench.dataset import (
    resolve_dataset_name,
    validate_evaluator_instances,
)
from inference_scaling.swebench.config import (
    MINI_SWE_AGENT_COMMIT,
    SWE_BENCH_VERSION,
    load_experiment_config,
)


def _direct_url_commit(distribution_name: str) -> str | None:
    distribution = importlib.metadata.distribution(distribution_name)
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return None
    payload = json.loads(raw)
    return payload.get("vcs_info", {}).get("commit_id")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--skip-docker", action="store_true")
    parser.add_argument("--skip-dataset", action="store_true")
    parser.add_argument(
        "--task-instance", action="append", default=[],
        help="probe a real task container's interpreter and imports; repeat for multiple IDs",
    )
    args = parser.parse_args()
    if args.task_instance and (args.skip_dataset or args.skip_docker):
        parser.error("--task-instance requires dataset and container checks")

    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required")
    experiment = load_experiment_config(args.config)
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "config_fingerprint": experiment.fingerprint,
    }

    mini_version = importlib.metadata.version("mini-swe-agent")
    if mini_version != "2.4.6":
        raise RuntimeError(f"expected mini-swe-agent 2.4.6, found {mini_version}")
    installed_commit = _direct_url_commit("mini-swe-agent")
    if installed_commit is not None and installed_commit != MINI_SWE_AGENT_COMMIT:
        raise RuntimeError(
            f"mini-swe-agent commit mismatch: {installed_commit} != {MINI_SWE_AGENT_COMMIT}"
        )
    checks["mini_swe_agent"] = {
        "version": mini_version,
        "commit": installed_commit or "package-metadata-unavailable",
    }
    swebench_version = importlib.metadata.version("swebench")
    if swebench_version != SWE_BENCH_VERSION:
        raise RuntimeError(
            f"expected swebench {SWE_BENCH_VERSION}, found {swebench_version}"
        )
    checks["swebench"] = swebench_version

    if not args.skip_docker:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        checks["docker_server"] = result.stdout.strip()

    if not args.skip_dataset:
        from datasets import load_dataset  # type: ignore[import-untyped]

        dataset_name = resolve_dataset_name(experiment.run.subset)
        dataset = load_dataset(
            dataset_name,
            split=experiment.run.split,
            revision=experiment.run.dataset_revision,
        )
        instances = [dict(instance) for instance in dataset]
        validate_evaluator_instances(
            instances,
            {str(instance["instance_id"]) for instance in instances},
        )
        checks["dataset"] = {
            "name": dataset_name,
            "split": experiment.run.split,
            "revision": experiment.run.dataset_revision,
            "rows": len(dataset),
            "fingerprint": getattr(dataset, "_fingerprint", ""),
        }

    checks["task_environments"] = []
    if args.task_instance:
        from minisweagent.config import get_config_from_spec
        from minisweagent.run.benchmarks.swebench import get_sb_environment

        from inference_scaling.swebench.task_environment import verify_task_environment

        selected = {item["instance_id"]: item for item in instances}
        missing = set(args.task_instance) - selected.keys()
        if missing:
            parser.error(f"unknown task instance IDs: {sorted(missing)}")
        config = get_config_from_spec(experiment.run.miniagent_config)
        config.setdefault("environment", {})["environment_class"] = experiment.run.environment_class
        for instance_id in dict.fromkeys(args.task_instance):
            instance = selected[instance_id]
            environment = get_sb_environment(config, instance)
            try:
                checks["task_environments"].append(verify_task_environment(environment, instance))
            finally:
                environment.cleanup()

    if not args.skip_api:
        from inference_scaling.swebench.miniagent import (
            BudgetLedger,
            MiniAgentSessionFactory,
            extract_logprob_metadata,
        )

        ledger = BudgetLedger(experiment.budget)
        factory = MiniAgentSessionFactory(
            experiment,
            {"instance_id": "preflight", "problem_statement": "preflight"},
            ledger,
        )
        model = factory.make_model("preflight", experiment.run.seeds[0], 64)
        response = model._query(
            [
                {"role": "system", "content": "Return one short bash command."},
                {
                    "role": "user",
                    "content": "Reply with <mswea_bash_command>echo ready</mswea_bash_command>.",
                },
            ]
        )
        metadata = extract_logprob_metadata(
            response,
            "preflight",
            logprob_mode=experiment.api.logprob_mode,
        )
        checks["api"] = {
            "model": experiment.api.model_name,
            "deployment_id": experiment.api.deployment_id,
            "runtime_fingerprint": factory.runtime["fingerprint"],
            "sampled_logprob": metadata["sampled_logprob"],
            "logprob_tokens": len(metadata["sampled_token_logprobs"]),
            "input_tokens": metadata["input_tokens"],
            "output_tokens": metadata["output_tokens"],
            "raw_output_tokens": metadata["raw_output_tokens"],
            "dropped_hidden_tokens": metadata["dropped_hidden_tokens"],
            "scored_output_tokens": metadata["scored_output_tokens"],
            "unscored_output_tokens": metadata["unscored_output_tokens"],
            "termination_status": metadata["termination_status"],
            "power_target_exact": metadata["power_target_exact"],
            "logprob_mode": metadata["logprob_mode"],
            "response_model": metadata["response_model"],
            "system_fingerprint": metadata["system_fingerprint"],
        }
        thinking_arms = [arm for arm in experiment.arms if arm.method == "is_thinking"]
        if thinking_arms:
            from inference_scaling.swebench.thinking_is import ThinkingISSampler

            probe = ThinkingISSampler(factory, thinking_arms[0], experiment.run.seeds[0]).preflight()
            checks["thinking_is"] = {key: value for key, value in probe.items() if key != "requests"}

    print(json.dumps({"status": "ok", "checks": checks}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
