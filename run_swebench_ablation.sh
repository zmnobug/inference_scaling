#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_path="${1:-${repository_root}/configs/swebench_qwen38_27b_api.toml}"
profile="${2:-smoke}"
shift $(( $# >= 1 ? 1 : 0 ))
shift $(( $# >= 1 ? 1 : 0 ))

venv_path="${SWEBENCH_VENV:-${repository_root}/.venv-swebench}"
env_file="${SWEBENCH_ENV_FILE:-${repository_root}/configs/swebench_qwen38_27b.env}"
if [[ ! -x "${venv_path}/bin/python" ]]; then
  echo "Missing ${venv_path}; run experiments/swebench/bootstrap.sh first" >&2
  exit 2
fi
if [[ -f "${env_file}" ]]; then
  # shellcheck disable=SC1090
  source "${env_file}"
fi

cd "${repository_root}"
if [[ "${RUN_PREFLIGHT:-1}" == "1" ]]; then
  "${venv_path}/bin/python" -m experiments.swebench.preflight --config "${config_path}"
fi
exec "${venv_path}/bin/python" -m experiments.swebench.run_suite \
  --config "${config_path}" --profile "${profile}" "$@"
