#!/usr/bin/env bash
# ============================================================
# 一键切换 RD-Agent fin_factor 场景要研究的市场
#
# 用法:
#   source scripts/switch_market.sh jp    # 切到日股小盘股
#   source scripts/switch_market.sh cn    # 切回中国 CSI300(官方默认)
#
# ⚠️ 必须用 source 执行(不能直接 bash 执行),因为要在当前 shell
#    里设置环境变量,子进程执行完就没用了。
#
# ------------------------------------------------------------
# 2026-08-17 改动:这个脚本不再自己用 sed 改配置
# ------------------------------------------------------------
# 老版本只 sed 了 provider_uri 一行,`market: csi300`、
# `benchmark: SH000300`、三段日期(2008/2015/2017)、A股涨跌停 0.095
# 全都没换。JP 数据 2022-01-04 才开始,三段全落在数据存在之前 ——
# 等于 JP 那条线从来没跑出过有意义的数字,而说明文字却显示 2022-2023,
# 反而把错位藏得更深(patch_market_switch.py 修好了文字,没修 yaml)。
#
# 现在所有市场相关字段都由 validation/config.yaml 统一定义,
# scripts/apply_market_config.py 一次性全部写进去,不可能只改一半。
# 这个脚本只剩两件事:调它,然后把它算出来的环境变量 export 进当前 shell。
#
# 这个脚本**永远**用 research 模式。Frozen Test 只能通过
# scripts/run_frozen_test.sh 进入,不给这里留后门。
# ============================================================
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKET="$1"

if [ "$MARKET" != "cn" ] && [ "$MARKET" != "jp" ]; then
  echo "用法: source scripts/switch_market.sh [jp|cn]"
  return 1 2>/dev/null || exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

# 第一步:把配置真正写进 RD-Agent 安装目录的 Qlib yaml(research 模式)
python "$REPO/scripts/apply_market_config.py" --market "$MARKET" --mode research

# 第二步:把 RD-Agent 讲给 LLM 听、也显示在网页报告 Config 表格里的说明文字,
# 从**同一份** splits 生成并 export 到当前 shell,所以不可能再错位。
eval "$(python "$REPO/scripts/apply_market_config.py" \
          --market "$MARKET" --mode research --print-env)"

echo
echo "已 export 到当前 shell:"
echo "  RD_AGENT_MARKET_NAME = $RD_AGENT_MARKET_NAME"
echo "  RD_AGENT_TRAIN_RANGE = $RD_AGENT_TRAIN_RANGE"
echo "  RD_AGENT_VALID_RANGE = $RD_AGENT_VALID_RANGE"
echo "  RD_AGENT_TEST_RANGE  = $RD_AGENT_TEST_RANGE   (= research_oos)"
echo "  RDAGENT_QLIB_CLOUD_MODE = $RDAGENT_QLIB_CLOUD_MODE"
echo
echo "下一步先跑研究环境体检,确认没有错位再开实验:"
echo "  bash scripts/health_check.sh"
