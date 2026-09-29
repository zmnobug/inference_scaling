#!/usr/bin/env bash
set -uo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repository_root}"

export PATH="${HOME}/bin:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export SWEBENCH_VENV=/tmp/inference-scaling-swebench-core-venv
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=true
export OPENAI_API_BASE=http://127.0.0.1:8000/v1 OPENAI_API_KEY=EMPTY
export PYTHONUNBUFFERED=1
export PYTHONPATH="${repository_root}/src:${repository_root}${PYTHONPATH:+:${PYTHONPATH}}"

results_path=results/swebench/qwen38-verified-random100-baseline-20260917
config_path=configs/qwen38_swebench_random100_baseline.toml
instance_file=configs/qwen38_swebench_random100_instances.txt

mkdir -p "${results_path}"
if [[ -f "${results_path}/pipeline_exit.txt" ]]; then
  mv "${results_path}/pipeline_exit.txt" "${results_path}/pipeline_exit.previous.$(date +%s).txt"
fi
date --iso-8601=seconds
printf 'Starting fixed random100 baseline; workers=1; agent deadline=1800s\n'
sha256sum "${config_path}" "${instance_file}" > "${results_path}/inputs.sha256"
tar -czf "${results_path}/source_snapshot.tar.gz" \
  --exclude='__pycache__' --exclude='*.pyc' \
  src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh \
  "${config_path}" "${instance_file}"

./run_swebench.sh "${config_path}" --instance-file "${instance_file}" --min-free-gib 4
generation_status=$?
printf 'GENERATION_EXIT=%s\n' "${generation_status}"
"${SWEBENCH_VENV}/bin/python" -c \
  'from pathlib import Path; from experiments.swebench.run_suite import _wait_for_disk_space; _wait_for_disk_space(Path("results/swebench/qwen38-verified-random100-baseline-20260917"), 4)'

./evaluate_swebench.sh "${results_path}" --arm base --seed 20260916 \
  --max-workers 1 --run-prefix qwen38-random100-baseline-20260917
evaluation_status=$?
printf 'EVALUATION_EXIT=%s\n' "${evaluation_status}"
printf 'generation=%s evaluation=%s\n' "${generation_status}" "${evaluation_status}" \
  > "${results_path}/pipeline_exit.txt"
date --iso-8601=seconds
if (( generation_status != 0 || evaluation_status != 0 )); then
  exit 1
fi
