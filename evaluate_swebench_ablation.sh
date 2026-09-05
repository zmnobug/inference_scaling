#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
results_path="${1:?usage: evaluate_swebench_ablation.sh RESULTS_PROFILE_DIR [extra args]}"
shift
venv_path="${SWEBENCH_VENV:-${repository_root}/.venv-swebench}"

cd "${repository_root}"
exec "${venv_path}/bin/python" -m experiments.swebench.evaluate \
  --results "${results_path}" "$@"
