#!/usr/bin/env bash
# ============================================================
# 修复 RD-Agent 运行时自己动态创建的 rdagent4qlib 验证环境
#
# 这个环境不是我们的 setup_env.sh 建的 —— 是 RD-Agent 第一次跑
# fin_factor 的 "running" 步骤时,按自己内部逻辑动态创建的,
# 用来真正执行 Qlib 的 qrun(训练模型 + 回测)。
# 所以没法提前在 setup_env.sh 里预防,只能等它建完之后来修。
#
# 已知坑(2026-08-16 实测):
#   1. RD-Agent 装的 torch 默认可能解析到带 CUDA 的 GPU 版本,
#      但 Codespaces 没有 GPU,纯属浪费磁盘(GPU 版几个GB, CPU 版才 ~200MB)。
#   2. 官方 requirements.txt 里锁的 scipy==1.11.4,但 Qlib 回测用的
#      cvxpy 1.7.5 明确要求 scipy>=1.13.0(缺 eye_array 这个函数),
#      导致 qrun 跑到回测阶段必崩,报告文件生不出来,整轮被误判失败:
#        ImportError: cannot import name 'eye_array' from 'scipy.sparse'
#
# 用法(在 rdagent4qlib 环境还不存在,或者刚重跑出现上述报错时执行):
#   bash scripts/fix_qlib_verify_env.sh
# ============================================================
set -euo pipefail

ENV_NAME="rdagent4qlib"

source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "环境 ${ENV_NAME} 还不存在。它由 RD-Agent 在跑 fin_factor 时自动创建,"
  echo "先跑一次 scripts/run_one_loop.sh,失败后再回来跑这个脚本。"
  exit 1
fi

conda activate "${ENV_NAME}"

echo "==> 修复 1/2: torch 换成 CPU-only 版本(这台机器没有 GPU)"
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

echo "==> 修复 2/2: scipy 升级到 cvxpy 要求的 >=1.13.0"
python -m pip install "scipy>=1.13.0"

echo
echo "验证:"
python -c "from scipy.sparse import eye_array; import cvxpy, torch; print('scipy/cvxpy OK, torch =', torch.__version__)"
