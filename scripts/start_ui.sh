#!/usr/bin/env bash
# ============================================================
# 打开 RD-Agent 官方 UI,回看 log/ 目录下的任意一轮历史实验
#
# 用法:
#   bash scripts/start_ui.sh
#   然后浏览器打开 http://localhost:19899
#   (在 Codespaces 里,VS Code 会自动弹出"在浏览器打开"的提示,
#    因为 19899 端口已经在 devcontainer.json 里声明了转发)
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

echo "==> UI 端口: 19899"
echo "==> 日志目录: $(pwd)/log"
rdagent ui --port 19899 --log-dir "$(pwd)/log"
