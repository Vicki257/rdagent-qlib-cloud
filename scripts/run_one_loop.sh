#!/usr/bin/env bash
# ============================================================
# 跑一次 fin_factor 实验(默认只跑 1 个 loop,避免大量 API 消耗)
#
# 用法:
#   bash scripts/run_one_loop.sh          # 跑 1 个 loop(首次默认)
#   bash scripts/run_one_loop.sh 5        # 跑 5 个 loop(以后长跑时用)
#   bash scripts/run_one_loop.sh 5 <path> # 从某个 checkpoint 续跑
#
# 必须在仓库根目录执行 —— RD-Agent 默认把日志写到 <当前工作目录>/log/,
# 固定在这里跑,所有历史实验才会自动堆在同一个 log/ 目录下,
# 以后才能用 `rdagent ui` 一次性回看全部历史。
#
# ------------------------------------------------------------
# 2026-08-17 起,这个脚本前后各加了一道关卡
# ------------------------------------------------------------
# 跑之前:
#   1. 研究环境体检(scripts/research_check.py) —— 市场说明和 provider_uri
#      错位、因子源数据和行情数据不是同一个市场、切分越界,直接 ❌ STOP。
#   2. 强制 research 模式。**绝不允许**在 frozen 模式下跑普通 loop。
#
# 跑之后:
#   3. Validation Gate(validation/validate.py) —— 独立、确定性地判断结果
#      能不能信,给 PASS / FAIL。不由 RD-Agent 自己说了算。
#   4. 实验持久化(scripts/archive_experiment.py) —— 把 log/ 里的核心证据抽
#      成 experiments/EXP-NNNN/,Codespace 被删了结论也还在。
#
# 3 和 4 挂在 trap EXIT 上,所以**即使 RD-Agent 中途卡死/崩溃**(已知 bug,
# 见 README),这一轮的假设、代码、失败原因也会被抽出来存档,
# 不会因为跑挂了就什么都没留下。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"

LOOP_N="${1:-1}"
RESUME_PATH="${2:-}"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate rdagent

# ------------------------------------------------------------
# 关卡 1:研究环境体检 + 强制 research 模式
# ------------------------------------------------------------
echo "==> [1/4] 研究环境体检"
python scripts/research_check.py --require-mode research

# 记录跑之前 log/ 里已有哪些目录,跑完精确定位「新产生的那一个」,
# 不用「取最新」这种在失败/并发时会认错的猜法。
BEFORE="$(mktemp)"
ls -1 log 2>/dev/null | sort > "$BEFORE" || true

archive_and_validate() {
  local status=$?
  echo
  echo "==> [3/4] Validation Gate(独立判断结果能不能信)"
  local new_dirs
  new_dirs="$(ls -1 log 2>/dev/null | sort | comm -13 "$BEFORE" - || true)"
  rm -f "$BEFORE"

  if [ -z "$new_dirs" ]; then
    echo "    这一轮没有产生新的 log 目录,跳过 Gate 和存档。"
    return $status
  fi

  local d
  for d in $new_dirs; do
    echo "    ---- log/$d"
    # Gate 判 FAIL 不能让脚本退出:FAIL 本身就是有效结论,必须被存档。
    python validation/validate.py --log-dir "log/$d" || true
  done

  echo
  echo "==> [4/4] 抽取核心证据到 experiments/(Codespace 删了也还在)"
  for d in $new_dirs; do
    python scripts/archive_experiment.py --log-dir "log/$d" || true
  done

  echo
  echo "本轮产出:"
  for d in $new_dirs; do
    echo "  log/$d"
  done
  echo "  experiments/INDEX.md   ← 从这里看全部历史实验"
  return $status
}
trap archive_and_validate EXIT

echo
echo "==> [2/4] 跑 RD-Agent"
echo "    工作目录: $REPO"
echo "    本次 loop 数: ${LOOP_N}"
echo "    生效配置:"
python scripts/apply_market_config.py --show | sed -n '3,17p' | sed 's/^/      /'
echo

if [ -n "${RESUME_PATH}" ]; then
  echo "    从 checkpoint 续跑: ${RESUME_PATH}"
  rdagent fin_factor --path "${RESUME_PATH}" --loop-n "${LOOP_N}"
else
  echo "    全新一轮 fin_factor"
  rdagent fin_factor --loop-n "${LOOP_N}"
fi
