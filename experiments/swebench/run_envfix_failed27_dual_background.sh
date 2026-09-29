#!/usr/bin/env bash
set -uo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repository_root}" || exit 1
export PATH="${HOME}/bin:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export SWEBENCH_VENV=/tmp/inference-scaling-swebench-core-venv
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=true
export OPENAI_API_KEY=EMPTY PYTHONUNBUFFERED=1

output_link="${SWEBENCH_OUTPUT_LINK:-${repository_root}/results/swebench/qwen38-thinking-is-c100-envfix-failed27-20260923-dual}"
config=configs/qwen38_swebench_thinking_is_envfix_failed27.toml
selection=configs/qwen38_swebench_thinking_is_envfix_failed27_instances.txt
tag=qwen38-thinking-is-c100-envfix-failed27-20260923
python="${SWEBENCH_VENV}/bin/python"
if [[ ! -L "${output_link}" || ! -d "${output_link}" ]]; then
  printf 'Expected pre-created result symlink on the data disk: %s\n' "${output_link}" >&2
  exit 1
fi
output="$(readlink -f "${output_link}")"
exec 8>"${output}/launch.lock"
flock -n 8 || exit 1
if [[ -e "${output}/source_snapshot.tar.gz" || -e "${output}/assignment.json" || -e "${output}/source" ]]; then
  printf 'Refusing implicit restart of fixed envfix failed27 experiment.\n' >&2
  exit 1
fi
trap 'status=$?; printf "exit_code=%s\nfinished_at=%s\n" "${status}" "$(date --iso-8601=seconds)" > "${output}/launcher_exit.txt"' EXIT
printf '%s\n' "$$" > "${output}/launcher.pid"
date --iso-8601=seconds > "${output}/started_at.txt"
git rev-parse HEAD > "${output}/source_head.txt" || exit 1
git status --short > "${output}/source_status.txt" || exit 1
git diff --binary HEAD > "${output}/source_worktree.patch" || exit 1
tar -czf "${output}/source_snapshot.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
  src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh \
  pyproject.toml configs tests || exit 1
runtime_root="${output}/source"
git worktree add --detach "${runtime_root}" "$(cat "${output}/source_head.txt")" || exit 1
tar -xzf "${output}/source_snapshot.tar.gz" -C "${runtime_root}" || exit 1
cd "${runtime_root}" || exit 1
export PYTHONPATH="${runtime_root}/src:${runtime_root}"
export TMPDIR="${output}/tmp"
mkdir -p "${TMPDIR}" || exit 1
"${python}" -m experiments.swebench.failed30_dual prepare \
  --config "${config}" --selection "${selection}" --expected-count 27 --output "${output}" || exit 1
sha256sum "${config}" "${selection}" "${output}"/shard_*_instances.txt \
  src/inference_scaling/swebench/{thinking_is,miniagent,task_environment,runner}.py \
  > "${output}/inputs.sha256" || exit 1
"${python}" -c 'from importlib.metadata import distributions; print("\n".join(sorted("{}=={}".format(package.metadata["Name"], package.version) for package in distributions())))' \
  > "${output}/packages.txt" || exit 1
for port in 8000 8001; do
  OPENAI_API_BASE="http://127.0.0.1:${port}/v1" "${python}" -m experiments.swebench.preflight \
    --config "${config}" > "${output}/preflight_${port}.log" 2>&1 || exit 1
done

run_shard() {
  local shard="$1" port="$2" generation_status evaluation_status
  export OPENAI_API_BASE="http://127.0.0.1:${port}/v1"
  date --iso-8601=seconds
  RUN_PREFLIGHT=0 bash ./run_swebench.sh "${config}" --instance-file "${output}/${shard}_instances.txt" \
    --output "${output}/${shard}" --min-free-gib 4 --disk-guard-path "${repository_root}"
  generation_status=$?
  printf 'GENERATION_EXIT=%s\n' "${generation_status}"
  if (( generation_status != 0 )) || [[ ! -e "${output}/${shard}/${tag}/manifest.json" ]]; then
    printf 'generation=%s evaluation=not_started\n' "${generation_status}" > "${output}/${shard}_exit.txt"
    return 1
  fi
  (
    flock -x 9 || exit 1
    "${python}" -c \
      'import sys; from pathlib import Path; from experiments.swebench.run_suite import _wait_for_disk_space; _wait_for_disk_space(Path(sys.argv[1]), 4, (Path(sys.argv[2]),))' \
      "${output}" "${repository_root}" || exit 1
    date --iso-8601=seconds
    bash ./evaluate_swebench.sh "${output}/${shard}/${tag}" --arm is_thinking-a1-b4-c100-r2 \
      --seed 20260916 --max-workers 1 --run-prefix "qwen38-envfix-failed27-20260923-${shard}"
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
printf 'shard_a_pid=%s\nshard_b_pid=%s\n' "${pid_a}" "${pid_b}" > "${output}/shard_pids.txt"
cat "${output}/shard_pids.txt"
wait "${pid_a}"
status_a=$?
wait "${pid_b}"
status_b=$?
summary_status=1
if (( status_a == 0 && status_b == 0 )); then
  "${python}" -m experiments.swebench.failed30_dual summarize --config "${config}" --output "${output}"
  summary_status=$?
fi
printf 'shard_a=%s shard_b=%s summary=%s\n' "${status_a}" "${status_b}" "${summary_status}" > "${output}/pipeline_exit.txt"
date --iso-8601=seconds
if (( status_a != 0 || status_b != 0 || summary_status != 0 )); then
  exit 1
fi
