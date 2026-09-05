#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${PYTHON_BIN:-python3.11}"
venv_path="${SWEBENCH_VENV:-${repository_root}/.venv-swebench}"
config_path="${1:-${repository_root}/configs/swebench_qwen38_27b_api.toml}"

command -v "${python_bin}" >/dev/null
command -v git >/dev/null
command -v docker >/dev/null

"${python_bin}" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
created_with_stdlib_venv=0
if [[ ! -x "${venv_path}/bin/python" ]]; then
  if "${python_bin}" -m venv "${venv_path}"; then
    created_with_stdlib_venv=1
  else
    if command -v uv >/dev/null; then
      uv venv --seed --python "${python_bin}" "${venv_path}"
    else
      echo "Failed to create a venv. Install python3.11-venv or uv and retry." >&2
      exit 2
    fi
  fi
fi
if ! "${venv_path}/bin/python" -c 'import encodings, sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
  if [[ "${created_with_stdlib_venv}" == "1" ]] && command -v uv >/dev/null; then
    uv venv --clear --seed --python "${python_bin}" "${venv_path}"
  else
    echo "Existing venv is unusable or older than Python 3.11: ${venv_path}" >&2
    echo "Choose a fresh SWEBENCH_VENV path and retry." >&2
    exit 2
  fi
fi
if ! "${venv_path}/bin/python" -m pip --version >/dev/null 2>&1; then
  if command -v uv >/dev/null; then
    uv pip install --python "${venv_path}/bin/python" pip setuptools wheel
  else
    echo "The venv has no pip. Install python3.11-venv or uv and retry." >&2
    exit 2
  fi
fi

"${venv_path}/bin/python" -m pip install --upgrade pip setuptools wheel
"${venv_path}/bin/python" -m pip install -e "${repository_root}[dev,swebench]"
"${venv_path}/bin/python" -m pip check
"${venv_path}/bin/python" -m experiments.swebench.preflight \
  --config "${config_path}" --skip-api --skip-dataset

echo "Environment ready: ${venv_path}"
echo "Next: set QWEN_API_BASE/QWEN_API_KEY, then run ./run_swebench_ablation.sh"
