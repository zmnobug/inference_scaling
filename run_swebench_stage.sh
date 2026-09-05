#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stage="${1:?usage: run_swebench_stage.sh STAGE [CONFIG] [extra args]}"
config_path="${2:-${repository_root}/configs/swebench_qwen38_27b_api.toml}"
shift $(( $# >= 1 ? 1 : 0 ))
shift $(( $# >= 1 ? 1 : 0 ))

case "${stage}" in
  smoke)
    profile="smoke"
    stage_args=(--selection-plan repo_stratified_v1)
    ;;
  calibrate)
    profile="calibrate"
    stage_args=(--selection-plan repo_stratified_v1)
    ;;
  stress)
    profile="stress"
    stage_args=(--selection-plan repo_stratified_v1)
    ;;
  screen)
    profile="screen"
    stage_args=(--selection-plan repo_stratified_v1)
    ;;
  seed_check)
    profile="seed_check"
    stage_args=(--selection-plan repo_stratified_v1 --seed 20260902)
    ;;
  confirm)
    profile="confirm"
    stage_args=(
      --selection-plan repo_stratified_v1
      --seed 20260901
      --seed 20260902
    )
    ;;
  *)
    echo "Unknown stage: ${stage}" >&2
    echo "Expected smoke, calibrate, stress, screen, seed_check, or confirm" >&2
    exit 2
    ;;
esac

exec "${repository_root}/run_swebench_ablation.sh" \
  "${config_path}" "${profile}" "${stage_args[@]}" "$@"
