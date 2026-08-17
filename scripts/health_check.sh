#!/usr/bin/env bash
# ============================================================
# 环境体检 —— 分两段
#
#   第一段 基础设施:conda / rdagent / LLM / Docker(原来就有的)
#   第二段 研究环境:市场、provider_uri、数据范围、股票数、三段切分、
#          benchmark、patch 是否真的生效(2026-08-17 新增)
#
# 每次新开 Codespace / 重建环境后,第一件事就跑这个。
# 每次切换市场之后,也要跑一次再开实验。
#
# ------------------------------------------------------------
# 为什么要加第二段
# ------------------------------------------------------------
# 原来的体检只回答「机器还能不能跑」,不回答「跑出来的数字能不能信」。
# 2026-08-17 实测发现两个会**静默产生假数字**的错配:
#
#   1. provider_uri 换成日股了,但 market/benchmark/三段日期还是 A 股的
#      (JP 数据 2022 才开始,三段却写着 2008/2015/2017 —— 全在数据之前)
#   2. 因子源数据 daily_pv.h5 是 A 股的 6075 只,回测却在日股 300 只上跑
#      (重叠 0 只,合并后基本全是 NaN,但不报错)
#
# 这两种情况程序都能跑完、都会给出漂亮的数字,只是数字没有意义。
# 所以现在只要出现这类错位,体检直接 ❌ STOP,退出码非 0。
#
# 用法:
#   bash scripts/health_check.sh              # 完整体检
#   bash scripts/health_check.sh --research   # 只跑研究环境那段(快)
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

RESEARCH_ONLY=0
if [ "${1:-}" = "--research" ]; then
  RESEARCH_ONLY=1
fi

if [ "$RESEARCH_ONLY" -eq 0 ]; then
  echo "############################################################"
  echo "# 第一段:基础设施"
  echo "############################################################"

  echo "=== docker ==="
  docker run --rm hello-world | tail -5

  echo
  echo "=== rdagent health_check ==="
  rdagent health_check
  echo
fi

echo "############################################################"
echo "# 第二段:研究环境(错位就 STOP,不让你带着假配置跑实验)"
echo "############################################################"
echo

# research_check.py 里任何一项 FAIL 都返回非 0,配合上面的 set -e
# 让整个体检直接失败。检查逻辑和 Validation Gate 的 Gate 1 共用
# validation/checks.py 那一份实现,不会出现两边说法不一致。
python scripts/research_check.py

echo
echo "############################################################"
echo "✅ 全部体检通过。"
echo
echo "跑一次普通实验:       bash scripts/run_one_loop.sh"
echo "在 Frozen Test 上评:  bash scripts/run_frozen_test.sh <EXP-NNNN>"
echo "############################################################"
