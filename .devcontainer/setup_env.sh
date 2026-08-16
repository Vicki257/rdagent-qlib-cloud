#!/usr/bin/env bash
# ============================================================
# RD-Agent 环境安装脚本(幂等 —— 重复运行安全)
#
# 严格按官方步骤:
#   https://github.com/microsoft/RD-Agent  README
#   conda create -n rdagent python=3.10
#   conda activate rdagent
#   pip install rdagent
#
# 云上(Codespaces)和本地(Docker Desktop)跑的是同一份脚本,
# 保证两边环境一致,避免"云上能跑本地跑不了"。
# ============================================================
set -euo pipefail

ENV_NAME="rdagent"
PY_VER="3.10"   # 官方 CI 充分测试的版本(3.10 / 3.11)

echo "==> [1/6] 定位 conda"
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda --version

echo "==> [2/6] 创建 conda 环境 ${ENV_NAME} (python=${PY_VER})"
if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "    环境 ${ENV_NAME} 已存在,跳过创建"
else
  conda create -y -n "${ENV_NAME}" "python=${PY_VER}"
fi

conda activate "${ENV_NAME}"
python --version

echo "==> [3/6] 安装 rdagent"
python -m pip install --upgrade pip
python -m pip install rdagent
rdagent --help >/dev/null 2>&1 || true
echo "    已安装 rdagent 版本: $(python -m pip show rdagent | awk '/^Version:/{print $2}')"

echo "==> [4/6] 修正依赖版本漂移: pydantic-ai-slim"
# 已知坑(2026-08-16 实测踩到): PyPI 上的 rdagent 0.8.0 包对
# pydantic-ai-slim 的版本约束比官方 GitHub 仓库自己的 requirements.txt
# 宽松,pip 会解析到最新的 pydantic-ai-slim(如 2.x),但 RD-Agent 0.8.0
# 的代码里还在用 1.x 的旧 API,导致:
#   ImportError: cannot import name 'MCPServerStreamableHTTP'
#   from 'pydantic_ai.mcp'
# 这里按官方 requirements.txt 的精确版本重新锁定,不是自己发明的绕过方案:
#   https://github.com/microsoft/RD-Agent/blob/main/requirements.txt
python -m pip install "pydantic-ai-slim[mcp,openai,prefect]==1.66.0"

# --- 另一个已知坑(2026-08-16 实测): RD-Agent 验证因子代码时会另外建一个
#     conda 环境(rdagent4qlib),按官方 requirements.txt 里 scipy==1.11.4
#     的要求装依赖。但 Qlib 回测阶段用到的 cvxpy 1.7.5 明确要求
#     scipy>=1.13.0(eye_array 这个函数 scipy 1.12 才有),
#     导致 qrun 跑到组合回测那一步必崩,报告文件生不出来,
#     整轮实验被误判为失败。这个环境是 RD-Agent 运行时自己动态建的,
#     不在这个脚本能提前干预的范围,写在这里只是留个记录 ——
#     如果重新遇到 "cannot import name 'eye_array' from 'scipy.sparse'",
#     去那个环境里手动跑:
#       conda activate rdagent4qlib && pip install "scipy>=1.13.0"

echo "==> [4b/6] 修复 generate.py 已知 bug(选股池与取数窗口不对齐,详见文件内注释)"
# 官方 issue,未修复: https://github.com/microsoft/RD-Agent/issues/619
#                     https://github.com/microsoft/RD-Agent/issues/1002
python3 "$(dirname "${BASH_SOURCE[0]}")/patch_generate_py.py"

echo "==> [5/6] 固定 Qlib 数据目录 (容器销毁后数据仍在此路径)"
mkdir -p "${HOME}/.qlib/qlib_data/cn_data"
# 已知 issue microsoft/RD-Agent#794:容器内 /root/.qlib/qlib_data 被以 ro 挂载。
# 这里先确保宿主侧目录本身可写,挂载模式在运行阶段单独处理。
chmod -R u+rwX "${HOME}/.qlib"
ls -ld "${HOME}/.qlib/qlib_data"

echo "==> [6/6] 下载 Qlib 中国股数据 (csi300 / Alpha158 用)"
# 官方 README 原话:"The official dataset is disabled temporarily."
# 官方推荐的社区替代源(microsoft/qlib README 明确指向此地址):
#   https://github.com/chenditc/investment_data/releases
if [ -f "${HOME}/.qlib/qlib_data/cn_data/.data_downloaded_ok" ]; then
  echo "    数据已存在,跳过下载"
else
  TMP_TAR="$(mktemp -d)/qlib_bin.tar.gz"
  wget -q --show-progress -O "${TMP_TAR}" \
    https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
  tar -zxf "${TMP_TAR}" -C "${HOME}/.qlib/qlib_data/cn_data" --strip-components=1
  rm -f "${TMP_TAR}"
  touch "${HOME}/.qlib/qlib_data/cn_data/.data_downloaded_ok"
  echo "    下载完成: $(du -sh "${HOME}/.qlib/qlib_data/cn_data" | cut -f1)"
fi

echo
echo "============================================================"
echo "安装完成。"
echo
echo "云端(Codespaces): DEEPSEEK_API_KEY / LITELLM_PROXY_API_KEY"
echo "  已通过 GitHub Codespaces Secrets 自动注入。"
echo "  ⚠️ 注意:这些变量只在【登录 shell】里能读到。"
echo "  用 'gh codespace ssh -- 命令' 直接跑命令是看不到它们的,"
echo "  必须包一层: gh codespace ssh -- 'bash -lc \"命令\"'"
echo
echo "本地部署时才需要:"
echo "  1) cp .env.template .env  并填入你自己的 API Key"
echo
echo "下一步(两种情况都一样):"
echo "  1) conda activate ${ENV_NAME}"
echo "  2) bash scripts/health_check.sh"
echo "============================================================"
