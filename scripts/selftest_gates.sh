#!/usr/bin/env bash
# ============================================================
# 关卡自检 —— 故意制造错误配置,确认系统真的会 STOP
#
# 用法:
#   bash scripts/selftest_gates.sh
#
# 为什么要有这个脚本:
# 一个「会挡住错误」的关卡,只有在**真的拿错误去撞过**之后才能说它有效。
# 光看代码写着 if ... fail 说明不了什么 —— 正则写窄了、缩进匹配不上、
# 检查项被跳过了,都会让关卡看起来存在、实际上放行。
#
# 每次改动 validation/checks.py 或 apply_market_config.py 之后都该跑一次。
# 脚本会自己把配置恢复原状(trap EXIT),不会留下错误配置。
#
# 三个否定测试对应 V2 验收要求的测试 3 / 4 / 5:
#   测试3  普通 loop 碰不到 Frozen Test
#   测试4  Train / Frozen Test 日期重叠 -> STOP
#   测试5  JP 说明 + CN provider_uri     -> STOP
# ============================================================
set -uo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

CONFIG="validation/config.yaml"
BACKUP="$(mktemp)"
cp "$CONFIG" "$BACKUP"

TEMPLATE="$(python -c 'import sysconfig,pathlib;print(pathlib.Path(sysconfig.get_paths()["purelib"])/"rdagent/scenarios/qlib/experiment/factor_template")')"

restore() {
  cp "$BACKUP" "$CONFIG"
  rm -f "$BACKUP"
  # 恢复成一个确定的、干净的状态
  python scripts/apply_market_config.py --market jp --mode research >/dev/null 2>&1 || true
  echo
  echo "（已恢复 validation/config.yaml 和 research 模式）"
}
trap restore EXIT

PASS=0
FAIL=0

expect_stop() {
  local label="$1"; shift
  echo "------------------------------------------------------------"
  echo "测试: $label"
  echo "期望: ❌ STOP（退出码非 0）"
  if "$@" > /tmp/selftest_out.txt 2>&1; then
    echo "结果: ⚠️  没有 STOP —— 这个关卡没起作用！"
    echo "--- 输出 ---"
    tail -20 /tmp/selftest_out.txt
    FAIL=$((FAIL + 1))
  else
    echo "结果: ✅ 正确 STOP"
    grep -E "❌|STOP" /tmp/selftest_out.txt | head -4 | sed 's/^/       /'
    PASS=$((PASS + 1))
  fi
  echo
}

expect_ok() {
  local label="$1"; shift
  echo "------------------------------------------------------------"
  echo "测试: $label"
  echo "期望: ✅ 通过（退出码 0）"
  if "$@" > /tmp/selftest_out.txt 2>&1; then
    echo "结果: ✅ 通过"
    PASS=$((PASS + 1))
  else
    echo "结果: ⚠️  意外失败"
    tail -20 /tmp/selftest_out.txt
    FAIL=$((FAIL + 1))
  fi
  echo
}

echo "############################################################"
echo "# 测试 4:Train / Frozen Test 日期重叠"
echo "############################################################"
cp "$BACKUP" "$CONFIG"
# 把 JP 的 frozen_test 起点拉到 train 区间里面 —— 直接制造重叠
python - <<'PY'
from pathlib import Path
p = Path("validation/config.yaml")
text = p.read_text(encoding="utf-8")
text = text.replace(
    'frozen_test:  ["2025-01-06", "2025-12-30"]',
    'frozen_test:  ["2022-06-01", "2025-12-30"]   # 故意重叠(自检用)',
)
p.write_text(text, encoding="utf-8")
print("已把 jp.frozen_test 起点改成 2022-06-01（落在 train 2022-01-04..2023-06-30 里）")
PY
expect_stop "apply_market_config 应该拒绝应用重叠的切分" \
  python scripts/apply_market_config.py --market jp --mode research

echo "############################################################"
echo "# 测试 5:JP 说明文字 + CN provider_uri（错位）"
echo "############################################################"
cp "$BACKUP" "$CONFIG"
python scripts/apply_market_config.py --market jp --mode research >/dev/null
eval "$(python scripts/apply_market_config.py --market jp --mode research --print-env)"
# 模拟老版本 switch_market.sh 那种「只改一半」的后果:
# 说明文字和 yaml 标记都还是 jp,只把 provider_uri 偷偷换成 CN 数据。
sed -i 's|~/.qlib/qlib_data/jp_smallcap_300|~/.qlib/qlib_data/cn_data|' \
  "$TEMPLATE/conf_baseline.yaml" "$TEMPLATE/conf_combined_factors.yaml"
echo "已把 provider_uri 偷偷换成 cn_data，但市场标记 / 说明文字仍是 JP"
expect_stop "health_check 应该发现市场说明与 provider_uri 错位" \
  python scripts/research_check.py

echo "############################################################"
echo "# 测试 3:普通 loop 碰不到 Frozen Test"
echo "############################################################"
cp "$BACKUP" "$CONFIG"

# 3a. frozen 模式下,普通 loop 的关卡必须拒绝
python scripts/apply_market_config.py --market jp --mode frozen >/dev/null
expect_stop "frozen 模式下 --require-mode research 必须 STOP" \
  python scripts/research_check.py --require-mode research

# 3b. research 模式下,取数窗口必须止步于 frozen 区间之前(物理上读不到)
python scripts/apply_market_config.py --market jp --mode research >/dev/null
eval "$(python scripts/apply_market_config.py --market jp --mode research --print-env)"
echo "------------------------------------------------------------"
echo "测试: research 模式下 Qlib 实际取数窗口"
python - <<'PY'
import re, sysconfig
from pathlib import Path

template = Path(sysconfig.get_paths()["purelib"]) / "rdagent/scenarios/qlib/experiment/factor_template"
import yaml
frozen_start = yaml.safe_load(Path("validation/config.yaml").read_text())["markets"]["jp"]["splits"]["frozen_test"][0]
bad = False
for name in ("conf_baseline.yaml", "conf_combined_factors.yaml"):
    text = (template / name).read_text()
    ends = re.findall(r"^\s*end_time:\s*(\d{4}-\d{2}-\d{2})\s*$", text, flags=re.MULTILINE)
    tests = re.findall(r"^\s*test:\s*\[(.*?)\]", text, flags=re.MULTILINE)
    print(f"  {name}: 所有 end_time={ends}  test={tests}  frozen 起点={frozen_start}")
    for end in ends:
        if end >= frozen_start:
            print(f"    ❌ end_time={end} 已经进入 frozen 区间")
            bad = True
    for segment in tests:
        if frozen_start in segment:
            print(f"    ❌ test 段引用了 frozen 区间")
            bad = True
raise SystemExit(1 if bad else 0)
PY
if [ $? -eq 0 ]; then
  echo "结果: ✅ 所有取数窗口都止步于 frozen 起点之前 —— RD-Agent 物理上读不到那段数据"
  PASS=$((PASS + 1))
else
  echo "结果: ⚠️  有窗口伸进了 frozen 区间"
  FAIL=$((FAIL + 1))
fi
echo

echo "############################################################"
echo "自检结果: ${PASS} 通过 / ${FAIL} 失败"
echo "############################################################"
[ "$FAIL" -eq 0 ]
