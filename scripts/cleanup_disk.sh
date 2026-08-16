#!/usr/bin/env bash
# ============================================================
# 磁盘清理(长期跑多轮实验时的例行维护)
#
# 背景(2026-08-16 实测踩到): Codespaces 免费机型固定 32GB 磁盘,
# 且 basicLinux32gb / standardLinux32gb 两档机型磁盘大小其实一样,
# 换机型解决不了磁盘问题,只能靠定期清理。
#
# 两个大头:
#   1. RD-Agent 每次因子代码验证会开一个新 Docker 容器,失败/中断时
#      容器不一定被清理干净,会越堆越多。
#   2. RD-Agent 的 CoSTEER 环境管理器会在验证用的 conda 环境里装
#      torch,如果不干预,pip 可能解析到带 CUDA 的 GPU 版本(几个GB),
#      但 Codespaces 没有 GPU,纯属浪费。
#
# 用法:
#   bash scripts/cleanup_disk.sh          # 建议每次长跑前先跑一次
# ============================================================
set -euo pipefail

echo "=== 清理前磁盘状态 ==="
df -h / | tail -1

echo "==> 清理已停止的 Docker 容器(不影响正在跑的容器)"
docker container prune -f

echo "==> 清理未被引用的 Docker 镜像"
docker image prune -f

echo "==> 清理 pip / conda 缓存(纯缓存,不影响已装的包)"
source "$(conda info --base)/etc/profile.d/conda.sh"
for env in rdagent rdagent4qlib; do
  if conda env list | awk '{print $1}' | grep -qx "${env}"; then
    conda activate "${env}"
    python -m pip cache purge 2>/dev/null || true
    conda deactivate
  fi
done
conda clean -a -y

echo
echo "=== 清理后磁盘状态 ==="
df -h / | tail -1

echo
echo "提示: 如果 rdagent4qlib 这个验证环境需要重装 torch,"
echo "强烈建议用 CPU-only 版本(这台机器没有 GPU,装 GPU 版纯属浪费磁盘):"
echo '  conda activate rdagent4qlib'
echo '  python -m pip install torch --index-url https://download.pytorch.org/whl/cpu'
