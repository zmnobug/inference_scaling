#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
results_path="${1:?usage: ./evaluate_swebench.sh RESULTS_DIR [evaluator args]}"
shift
venv_path="${SWEBENCH_VENV:-${repository_root}/.venv-swebench}"
if [[ ! -x "${venv_path}/bin/python" ]]; then
  echo "Missing ${venv_path}; run experiments/swebench/bootstrap.sh CONFIG first" >&2
  exit 2
fi

cd "${repository_root}"
exec "${venv_path}/bin/python" -m experiments.swebench.evaluate \
  --results "${results_path}" "$@"
