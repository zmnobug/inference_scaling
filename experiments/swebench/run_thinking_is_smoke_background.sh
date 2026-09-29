#!/usr/bin/env bash
set -uo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repository_root}" || exit 1
export PATH="${HOME}/bin:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export SWEBENCH_VENV=/tmp/inference-scaling-swebench-core-venv
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=true
export OPENAI_API_BASE=http://127.0.0.1:8000/v1 OPENAI_API_KEY=EMPTY
export PYTHONUNBUFFERED=1
export PYTHONPATH="${repository_root}/src:${repository_root}${PYTHONPATH:+:${PYTHONPATH}}"

results_path=results/swebench/qwen38-thinking-is-c100-pytest7982-smoke-20260918
config_path=configs/qwen38_swebench_thinking_is_smoke.toml
mkdir -p "${results_path}" || exit 1
if [[ -e "${results_path}/source_snapshot.tar.gz" ]]; then
  printf 'Existing run detected; refusing an implicit retry.\n' >&2
  exit 1
fi
date --iso-8601=seconds
sha256sum "${config_path}" > "${results_path}/inputs.sha256" || exit 1
tar -czf "${results_path}/source_snapshot.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
  src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh "${config_path}" || exit 1
./run_swebench.sh "${config_path}" --min-free-gib 4
generation_status=$?
printf 'GENERATION_EXIT=%s\n' "${generation_status}"
"${SWEBENCH_VENV}/bin/python" -c \
  'import sys; from pathlib import Path; from experiments.swebench.run_suite import _wait_for_disk_space; _wait_for_disk_space(Path(sys.argv[1]), 4)' \
  "${results_path}" || exit 1
./evaluate_swebench.sh "${results_path}" --arm is_thinking-a1-b4-c100-r2 --seed 20260916 \
  --max-workers 1 --run-prefix qwen38-thinking-is-c100-smoke-20260918
evaluation_status=$?
printf 'EVALUATION_EXIT=%s\n' "${evaluation_status}"
printf 'generation=%s evaluation=%s\n' "${generation_status}" "${evaluation_status}" > "${results_path}/pipeline_exit.txt"
date --iso-8601=seconds
if (( generation_status != 0 || evaluation_status != 0 )); then
  exit 1
fi
