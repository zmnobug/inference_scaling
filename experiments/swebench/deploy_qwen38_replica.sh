#!/usr/bin/env bash
set -euo pipefail

export PATH="${HOME}/bin:${PATH}"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
container_name=qwen38-27b-v100-replica
image_id=sha256:41ea41cbd04a6ff6252e7918ab538cc4d6807a9dec2c5e39d733ae7718202e22

if docker container inspect "${container_name}" >/dev/null 2>&1; then
  printf 'Container already exists; refusing to replace it: %s\n' "${container_name}" >&2
  exit 1
fi
docker image inspect "${image_id}" >/dev/null
for gpu in 0 1 2 3; do
  used="$(nvidia-smi --id="${gpu}" --query-gpu=memory.used --format=csv,noheader,nounits)"
  if [[ ! "${used}" =~ ^[[:space:]]*[0-9]+[[:space:]]*$ ]] || (( used > 512 )); then
    printf 'GPU %s is not free: %s MiB\n' "${gpu}" "${used}" >&2
    exit 1
  fi
done
if [[ -n "$(ss -H -ltn 'sport = :8001')" ]]; then
  printf 'Port 8001 is already in use.\n' >&2
  exit 1
fi

docker run -d \
  --name "${container_name}" \
  --restart unless-stopped \
  --ipc host --shm-size 32g --security-opt label=disable \
  --device nvidia.com/gpu=0 --device nvidia.com/gpu=1 \
  --device nvidia.com/gpu=2 --device nvidia.com/gpu=3 \
  -p 127.0.0.1:8001:8000 \
  -v /data/users/jenkins/qwen38-models/Qwen3.8-27B:/models/model:ro \
  -e PYTORCH_ALLOC_CONF=expandable_segments:True \
  "${image_id}" \
  --model /models/model \
  --served-model-name qwen3.8-27b \
  --trust-remote-code \
  --dtype half \
  --attention-backend FLASH_ATTN_V100 \
  --gdn-prefill-backend triton \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.85 \
  --max-model-len 133120 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 8192 \
  --enable-prefix-caching \
  --generation-config vllm \
  --logprobs-mode processed_logprobs \
  --max-logprobs 5 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --language-model-only \
  --disable-custom-all-reduce \
  --host 0.0.0.0 \
  --port 8000
