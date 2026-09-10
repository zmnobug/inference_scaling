#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_path="${1:?usage: ./run_swebench.sh CONFIG [runner args]}"
shift

venv_path="${SWEBENCH_VENV:-${repository_root}/.venv-swebench}"
if [[ ! -x "${venv_path}/bin/python" ]]; then
  echo "Missing ${venv_path}; run experiments/swebench/bootstrap.sh ${config_path} first" >&2
  exit 2
fi
if [[ -n "${SWEBENCH_ENV_FILE:-}" ]]; then
  if [[ ! -f "${SWEBENCH_ENV_FILE}" ]]; then
    echo "SWEBENCH_ENV_FILE does not exist: ${SWEBENCH_ENV_FILE}" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "${SWEBENCH_ENV_FILE}"
fi

cd "${repository_root}"
if [[ "${RUN_PREFLIGHT:-1}" == "1" ]]; then
  "${venv_path}/bin/python" -m experiments.swebench.preflight \
    --config "${config_path}"
fi
exec "${venv_path}/bin/python" -m experiments.swebench.run_suite \
  --config "${config_path}" "$@"
