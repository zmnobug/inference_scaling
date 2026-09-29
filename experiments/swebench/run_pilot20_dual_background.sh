#!/usr/bin/env bash
set -euo pipefail
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repository_root}"
export PATH="${HOME}/bin:${HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export SWEBENCH_VENV=/tmp/inference-scaling-swebench-core-venv
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=true
export OPENAI_API_BASE=http://127.0.0.1:8001/v1 OPENAI_API_KEY=EMPTY
export PYTHONUNBUFFERED=1
export PYTHONPATH="${repository_root}/src:${repository_root}${PYTHONPATH:+:${PYTHONPATH}}"
output=results/swebench/qwen38-thinking-is-c100-pilot20-dual-20260918
mkdir -p "${output}"
if [[ "${1:-}" == "--resume-after-handoff" ]]; then
  test ! -e "${output}/recovery_source_snapshot.tar.gz"
  sha256sum configs/qwen38_swebench_thinking_is_pilot20{.toml,_instances.txt,_shard_b.txt} > "${output}/recovery_inputs.sha256"
  tar -czf "${output}/recovery_source_snapshot.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
    src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh \
    configs/qwen38_swebench_thinking_is_pilot20{.toml,_instances.txt,_shard_b.txt}
  exec "${SWEBENCH_VENV}/bin/python" -m experiments.swebench.split_running_pilot20 --resume-after-handoff
fi
if [[ -e "${output}/source_snapshot.tar.gz" ]]; then
  printf 'Refusing implicit restart of split supervisor.\n' >&2
  exit 1
fi
sha256sum configs/qwen38_swebench_thinking_is_pilot20{.toml,_instances.txt,_shard_b.txt} > "${output}/inputs.sha256"
tar -czf "${output}/source_snapshot.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
  src/inference_scaling experiments/swebench run_swebench.sh evaluate_swebench.sh \
  configs/qwen38_swebench_thinking_is_pilot20{.toml,_instances.txt,_shard_b.txt}
exec "${SWEBENCH_VENV}/bin/python" -m experiments.swebench.split_running_pilot20
