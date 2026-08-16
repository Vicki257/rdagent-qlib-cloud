#!/usr/bin/env bash
# ============================================================
# 一键切换 RD-Agent fin_factor 场景要研究的市场
#
# 解决的问题:之前改数据源(provider_uri)和改"AI 自己以为在研究
# 什么"的说明文字是两件分开的事,容易漏改导致错位(2026-08-16 晚
# 上真实踩过这个坑)。现在这一个脚本把两件事绑在一起改,保证一致。
#
# 用法:
#   source switch_market.sh jp    # 切到日股小盘股
#   source switch_market.sh cn    # 切回中国 CSI300(官方默认)
#
# ⚠️ 必须用 source 执行(不能直接 bash 执行),因为要在当前 shell
#    里设置环境变量,子进程执行完就没用了。
# ============================================================
set -e

PKG=/opt/conda/envs/rdagent/lib/python3.10/site-packages/rdagent/scenarios/qlib
BASELINE=$PKG/experiment/factor_template/conf_baseline.yaml
COMBINED=$PKG/experiment/factor_template/conf_combined_factors.yaml
BACKUP=/workspaces/rdagent-qlib-cloud/cn_config_backup

MARKET="$1"

if [ "$MARKET" = "cn" ]; then
  echo "==> 切回中国 CSI300(官方默认配置)"
  cp "$BACKUP/conf_baseline.yaml" "$BASELINE"
  cp "$BACKUP/conf_combined_factors.yaml" "$COMBINED"
  unset RD_AGENT_MARKET_NAME RD_AGENT_TRAIN_RANGE RD_AGENT_VALID_RANGE RD_AGENT_TEST_RANGE
  echo "    provider_uri: ~/.qlib/qlib_data/cn_data"
  echo "    说明文字: 默认值(CSI300, 2008-2020)"

elif [ "$MARKET" = "jp" ]; then
  echo "==> 切到日本小盘股(JP Small-Cap)"
  sed -i 's|~/.qlib/qlib_data/[a-z_0-9]*"|~/.qlib/qlib_data/jp_smallcap_300"|' "$BASELINE" "$COMBINED"
  export RD_AGENT_MARKET_NAME="JP Small-Cap (TOPIX Small1/2, 300只精简版)"
  export RD_AGENT_TRAIN_RANGE="2022-01-01 to 2023-12-31"
  export RD_AGENT_VALID_RANGE="2024-01-01 to 2024-06-30"
  export RD_AGENT_TEST_RANGE="2024-07-01 to 2025-12-20"
  echo "    provider_uri: ~/.qlib/qlib_data/jp_smallcap_300"
  echo "    说明文字: $RD_AGENT_MARKET_NAME"

else
  echo "用法: source switch_market.sh [jp|cn]"
  return 1 2>/dev/null || exit 1
fi

echo
echo "现在 conf_baseline.yaml / conf_combined_factors.yaml 用的数据源,"
echo "和 RD-Agent 讲给 AI 听、显示在网页报告上的说明文字,已经保证一致。"
