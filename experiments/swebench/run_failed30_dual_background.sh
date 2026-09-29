#!/usr/bin/env bash
set -uo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repository_root}" || exit 1
export PATH="${HOME}/bin:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export SWEBENCH_VENV=/tmp/inference-scaling-swebench-core-venv
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=true
export OPENAI_API_KEY=EMPTY PYTHONUNBUFFERED=1
export PYTHONPATH="${repository_root}/src:${repository_root}${PYTHONPATH:+:${PYTHONPATH}}"

output=results/swebench/qwen38-thinking-is-failed30-unlimited-dual
config=configs/qwen38_swebench_thinking_is_failed30_unlimited.toml
selection=configs/qwen38_swebench_baseline_failed30_instances.txt
tag=qwen38-thinking-is-c100-baseline-failed30-unlimited
python="${SWEBENCH_VENV}/bin/python"
mkdir -p "${output}" || exit 1
if [[ -e "${output}/source_snapshot.tar.gz" || -e "${output}/assignment.json" ]]; then
  printf 'Refusing implicit restart of fixed failed30 experiment.\n' >&2
  exit 1
fi
date --iso-8601=seconds
"${python}" -m experiments.swebench.failed30_dual prepare \
  --config "${config}" --selection "${selection}" --output "${output}" || exit 1
git rev-parse HEAD > "${output}/source_head.txt" || exit 1
git status --short > "${output}/source_status.txt" || exit 1
sha256sum "${config}" "${selection}" "${output}"/shard_*_instances.txt > "${output}/inputs.sha256" || exit 1
tar -czf "${output}/source_snapshot.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
  src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh \
  "${config}" "${selection}" "${output}"/shard_*_instances.txt || exit 1

run_shard() {
  local shard="$1" port="$2" generation_status evaluation_status
  export OPENAI_API_BASE="http://127.0.0.1:${port}/v1"
  date --iso-8601=seconds
  ./run_swebench.sh "${config}" --instance-file "${output}/${shard}_instances.txt" \
    --output "${output}/${shard}" --min-free-gib 4
  generation_status=$?
  printf 'GENERATION_EXIT=%s\n' "${generation_status}"
  if [[ ! -e "${output}/${shard}/${tag}/manifest.json" ]]; then
    printf 'generation=%s evaluation=not_started\n' "${generation_status}" > "${output}/${shard}_exit.txt"
    return 1
  fi
  (
    flock -x 9 || exit 1
    "${python}" -c \
      'import sys; from pathlib import Path; from experiments.swebench.run_suite import _wait_for_disk_space; _wait_for_disk_space(Path(sys.argv[1]), 4)' \
      "${output}" || exit 1
    date --iso-8601=seconds
    ./evaluate_swebench.sh "${output}/${shard}/${tag}" --arm is_thinking-a1-b4-c100-r2 \
      --seed 20260916 --max-workers 1 --run-prefix "qwen38-thinking-is-failed30-unlimited-${shard}"
  ) 9>"${output}/evaluation.lock"
  evaluation_status=$?
  printf 'generation=%s evaluation=%s\n' "${generation_status}" "${evaluation_status}" > "${output}/${shard}_exit.txt"
  date --iso-8601=seconds
  (( generation_status == 0 && evaluation_status == 0 ))
}

run_shard shard_a 8000 > "${output}/shard_a.log" 2>&1 &
pid_a=$!
run_shard shard_b 8001 > "${output}/shard_b.log" 2>&1 &
pid_b=$!
printf 'shard_a_pid=%s shard_b_pid=%s\n' "${pid_a}" "${pid_b}"
wait "${pid_a}"
status_a=$?
wait "${pid_b}"
status_b=$?
"${python}" -m experiments.swebench.failed30_dual summarize --config "${config}" --output "${output}"
summary_status=$?
printf 'shard_a=%s shard_b=%s summary=%s\n' "${status_a}" "${status_b}" "${summary_status}" > "${output}/pipeline_exit.txt"
date --iso-8601=seconds
if (( status_a != 0 || status_b != 0 || summary_status != 0 )); then
  exit 1
fi
