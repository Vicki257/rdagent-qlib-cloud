#!/usr/bin/env bash
# ============================================================
# 在 Frozen Test 区间上评一个 candidate
#
# 用法:
#   bash scripts/run_frozen_test.sh EXP-0004
#
# 这是**唯一**能碰 Frozen Test 的入口。普通实验循环
# (scripts/run_one_loop.sh) 会被强制检查 research 模式,
# 碰不到 frozen 区间。
#
# ⚠️ 一旦 Frozen Test 被用于调参数、改因子、选择因子,
#    它就不再是 Frozen Test。
#
# 本脚本不启动 RD-Agent,只调 Qlib 的 qrun,结果只写进
# experiments/<EXP>/frozen_test/,不写 RD-Agent 的 log/ 或 session,
# 所以不会被下一轮当反馈读到。
#
# 详细说明见 scripts/run_frozen_test.py 的文档字符串。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "用法: bash scripts/run_frozen_test.sh <EXP-NNNN>"
  echo
  echo "可用的 candidate(见 experiments/INDEX.md):"
  ls -1 experiments 2>/dev/null | grep '^EXP-' || echo "  (还没有,先跑 scripts/archive_experiment.py --all)"
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

python scripts/run_frozen_test.py "$@"
