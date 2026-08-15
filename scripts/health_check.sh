#!/usr/bin/env bash
# 环境体检:确认 conda 环境、rdagent 安装、LLM 配置、Docker 都正常。
# 每次新开一个 Codespace / 重建环境后,第一件事就跑这个。
set -euo pipefail

cd "$(dirname "$0")/.."

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

echo "=== docker ==="
docker run --rm hello-world | tail -5

echo
echo "=== rdagent health_check ==="
rdagent health_check
