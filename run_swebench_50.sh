#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_path="${1:-${repository_root}/configs/swebench_qwen38_27b_api.toml}"
shift $(( $# >= 1 ? 1 : 0 ))

exec "${repository_root}/run_swebench_stage.sh" \
  confirm "${config_path}" "$@"
