#!/usr/bin/env bash
# ============================================================
# 跑一次 fin_factor 实验(默认只跑 1 个 loop,避免大量 API 消耗)
#
# 用法:
#   bash scripts/run_one_loop.sh          # 跑 1 个 loop(首次默认)
#   bash scripts/run_one_loop.sh 5        # 跑 5 个 loop(以后长跑时用)
#   bash scripts/run_one_loop.sh 5 <path> # 从某个 checkpoint 续跑
#
# 必须在 ~/quant/rdagent/ 目录下执行 ——
# RD-Agent 默认把日志写到 <当前工作目录>/log/<UTC时间戳>/,
# 固定在这里跑,所有历史实验才会自动堆在同一个 log/ 目录下,
# 以后才能用 `rdagent ui` 一次性回看全部历史。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."   # 保证工作目录就是 ~/quant/rdagent/

LOOP_N="${1:-1}"
RESUME_PATH="${2:-}"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

echo "==> 工作目录: $(pwd)"
echo "==> 本次 loop 数: ${LOOP_N}"

if [ -n "${RESUME_PATH}" ]; then
  echo "==> 从 checkpoint 续跑: ${RESUME_PATH}"
  rdagent fin_factor --path "${RESUME_PATH}" --loop-n "${LOOP_N}"
else
  echo "==> 全新一轮 fin_factor"
  rdagent fin_factor --loop-n "${LOOP_N}"
fi
