# RD-Agent + Qlib 量化研究环境(云端 Codespaces 版)

> 状态:2026-08-16 完成第 1 个 `fin_factor` 闭环,验证通过。
> 当前架构:**跑在 GitHub Codespaces 云端,本地 Mac 还没装 Docker/conda**(按你的决定,这次先只验证云端闭环,本地化留到以后)。

---

## ⚠️ 给以后每次回来的 Claude(和我自己)的强制要求

**这套环境存在的目的不是"跑出一个能赚钱的策略",是让用户在做的过程中,持续丰富自己的量化投资知识地图。**

所以:**任何一次新的回测/实验结果出来之后,不许只报数字,必须用 [`knowledge_map/TEMPLATE.md`](knowledge_map/TEMPLATE.md) 那套六视角框架(预测模型/收益模型/风险模型/赚钱方式/执行模型/参数测试)写一篇分析,存进 `knowledge_map/` 目录,并且要以提问-回答的方式引导用户自己先给出判断,而不是直接把结论讲给他听。** 这是 2026-08-16 用户明确提出的要求,不是可选项。

---

## 0. 先看这张地图,再决定要跳到哪一节

| 你想做什么 | 看第几节 |
|---|---|
| 电脑重启/隔了几周,想接着用 | [第 1 节](#1-重启电脑后怎么恢复) |
| 跑一次新实验 | [第 2 节](#2-怎么跑一次新实验) |
| 打开 UI 看某一轮历史实验 | [第 3 节](#3-怎么打开-ui-看历史实验) |
| 想知道数据/日志/配置分别存哪 | [第 4 节](#4-数据日志配置分别存在哪) |
| 以后要换成 J-Quants 日股数据 | [第 5 节](#5-以后换成-j-quants-日股数据要改哪里) |
| 自己验证"环境还在不在" | [第 6 节](#6-验证命令重启后自查) |
| 每次新结果怎么写进知识地图 | [`knowledge_map/TEMPLATE.md`](knowledge_map/TEMPLATE.md) |

---

## 1. 重启电脑后,怎么恢复

**重要前提**:真正跑实验的环境**不在你的 Mac 上**,在 GitHub Codespaces 云端容器里。你的 Mac 只是一个"遥控器"。所以"恢复"分两种情况。

### 1a. 如果 Codespace 还活着(大概率,30 天内都在)

打开终端,依次执行:

```bash
gh auth status
```

如果显示 `Logged in to github.com account Vicki257`,说明登录还有效,跳过下一步。如果没登录:

```bash
gh auth login --web --git-protocol https
```

查现有 Codespace:

```bash
gh codespace list
```

会看到类似这样一行(`NAME` 那一列就是你要的):

```
rdagent-fin-factor-4j6gx66p65xv3jrj7   rdagent-fin-factor   Vicki257/rdagent-qlib-cloud   main   Available
```

如果状态是 `Shutdown`(自动休眠了,正常,不是坏了),直接连上去会自动唤醒。用 `NAME` 那一列的值替换下面命令里的 `<CODESPACE_NAME>`:

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && bash scripts/health_check.sh"'
```

看到这几行说明环境完好,可以直接跳到 [第 2 节](#2-怎么跑一次新实验) 开始跑实验:

```
✅ Embedding test passed.
✅ Chat test passed.
✅ All tests completed.
The docker status is normal
```

### 1b. 如果 Codespace 已经被删了(超过 30 天没碰,或者你手动删的)

不用慌,所有踩过的坑都已经写进仓库脚本里了,重建大概 10-15 分钟,**不会重新踩一遍已知的坑**:

```bash
gh auth login --web --git-protocol https
gh codespace create -R Vicki257/rdagent-qlib-cloud --branch main --machine basicLinux32gb --idle-timeout 4h --display-name rdagent-fin-factor -s
```

这条命令跑完后会打印新的 Codespace 名字,记下来,后面所有 `-c <CODESPACE_NAME>` 都用这个新名字。创建过程会自动跑 `.devcontainer/setup_env.sh`,包含:装 conda + rdagent 0.8.0、修正已知依赖版本坑、下载 Qlib 中国股数据(~842MB,官方源临时下架期间用的社区替代源)。

装完之后跑一次健康检查确认:

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && bash scripts/health_check.sh"'
```

⚠️ 如果这里报错 `cannot import name '\''MCPServerStreamableHTTP'\''` 或类似依赖问题,说明仓库脚本又漂移了,参考 [第 4 节末尾"已知坑清单"](#已知坑清单)。

---

## 2. 怎么跑一次新实验

先确认 Codespace 名字(见上一节 `gh codespace list`),然后:

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && export BACKEND=rdagent.oai.backend.LiteLLMAPIBackend && export MLFLOW_ALLOW_FILE_STORE=true && bash scripts/run_one_loop.sh 1"'
```

这会跑 **1 个 loop**(提出因子→写代码→Qlib 训练验证→出结果→反馈)。实测单个 loop 大约 **9-10 分钟**,DeepSeek 花费约 **$0.02 以内**。

要连续跑多轮(比如 5 轮),把最后的 `1` 换成想要的轮数:

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && export BACKEND=rdagent.oai.backend.LiteLLMAPIBackend && export MLFLOW_ALLOW_FILE_STORE=true && bash scripts/run_one_loop.sh 5"'
```

**长跑前建议先清一次磁盘**(Codespaces 固定 32GB,跑几轮 Docker 容器会堆积):

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && bash scripts/cleanup_disk.sh"'
```

---

## 3. 怎么打开 UI 看历史实验

RD-Agent 官方 UI 是个跑在 Codespace 容器内部的网页(Streamlit,端口 **19899**),需要先把端口转发到你 Mac 本地,再用你自己的浏览器打开。

**第一步**:在容器里启动 UI(后台运行,不会因为你关终端就退出):

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && nohup bash scripts/start_ui.sh > /tmp/ui.log 2>&1 &"'
```

**第二步**:另开一个终端窗口(这条命令会一直占着,不要用同一个窗口),把端口转发到你 Mac 本地:

```bash
gh codespace ports forward 19899:19899 -c <CODESPACE_NAME>
```

看到 `Forwarding ports: remote 19899 <=> local 19899` 就说明通了,**这个终端窗口要一直开着**,关掉就断了。

**第三步**:浏览器打开:

```
http://localhost:19899
```

**第四步**:进去之后,左侧 "Control Panel" → "Log Path" 下拉框里选你想看的那一轮(格式是 `YYYY-MM-DD_HH-MM-SS-微秒`,越晚的越新),再点 **"All Loops"** 按钮把数据渲染出来。第一次成功跑通的完整闭环记录在:

```
2026-08-16_06-35-38-526479
```

---

## 4. 数据、日志、配置分别存在哪

都在云端 Codespace 容器里,不在你的 Mac 上(本地 `~/quant/rdagent/` 目前只是配置文件的 git 仓库副本,不含数据和日志)。

| 内容 | 容器内路径 | 说明 |
|---|---|---|
| Qlib 行情数据 | `~/.qlib/qlib_data/cn_data`(即 `/home/vscode/.qlib/qlib_data/cn_data`) | csi300 + Alpha158 用,~842MB,社区替代源 |
| 实验日志(每轮一个时间戳目录) | `/workspaces/rdagent-qlib-cloud/log/` | **这是你最在意的那一层**——每次跑 `run_one_loop.sh` 都会在这里新建一个目录,不会覆盖旧的 |
| RD-Agent 工作区(生成的因子代码、中间产物) | `/workspaces/rdagent-qlib-cloud/git_ignore_folder/` | 不进 git,纯运行时产物 |
| conda 环境 | `rdagent`(主环境)、`rdagent4qlib`(Qlib 验证环境,运行时自动建) | |
| 配置(非密钥) | `.devcontainer/devcontainer.json` 里的 `remoteEnv` | CHAT_MODEL / EMBEDDING_MODEL / BACKEND / MLFLOW_ALLOW_FILE_STORE 等 |
| API Key | GitHub Codespaces Secrets(`DEEPSEEK_API_KEY`、`LITELLM_PROXY_API_KEY`) | 不在任何文件里,仓库设置页管理:`https://github.com/Vicki257/rdagent-qlib-cloud/settings/secrets/codespaces` |
| 仓库(配置+脚本的唯一真源) | `https://github.com/Vicki257/rdagent-qlib-cloud`(**Public**) | 本地 `~/quant/rdagent/` 就是这个仓库的本地克隆 |

### 已知坑清单

这次实测踩过、已经修好并写回仓库脚本的坑,供以后排查报错时对照:

1. **`pydantic-ai-slim` 版本漂移**:PyPI 上的 `rdagent==0.8.0` 解析到的版本比官方 `requirements.txt` 锁的新,导致 `ImportError: MCPServerStreamableHTTP`。已在 `setup_env.sh` 里锁定 `pydantic-ai-slim[mcp,openai,prefect]==1.66.0`。
2. **`generate.py` 选股池和取数窗口不一致**:官方代码从全历史选前100只股票,拿去筛 2018-2019 窗口的数据,退市股票会导致 `KeyError`。已用 `.devcontainer/patch_generate_py.py` 打补丁,`setup_env.sh` 会自动应用。
3. **MLflow 拒绝文件系统后端**:`qrun` 训练这一步默认报错。已设 `MLFLOW_ALLOW_FILE_STORE=true`(写在 `devcontainer.json` 的 `remoteEnv` 里)。
4. **torch 装成 GPU 版**:Codespaces 没有 GPU,但 RD-Agent 运行时装的验证环境默认可能拉 CUDA 版 torch,把 32GB 磁盘挤爆。用 `scripts/fix_qlib_verify_env.sh` 强制装 CPU-only 版。
5. **scipy 版本冲突**:官方 `requirements.txt` 锁 `scipy==1.11.4`,但 Qlib 回测用的 `cvxpy 1.7.5` 需要 `scipy>=1.13.0`(缺 `eye_array` 函数),导致组合回测阶段崩溃、整轮被误判失败。同样在 `scripts/fix_qlib_verify_env.sh` 里升级到 `>=1.13.0`。
6. **Docker 容器堆积**:失败的运行会留下停止的容器,不清理会把 32GB 磁盘占满。`scripts/cleanup_disk.sh` 处理。
7. **`gh codespace ssh -- <命令>` 读不到环境变量**:必须包一层 `bash -lc "..."` 才能读到 Codespaces Secrets 和 `remoteEnv` 配置。本 README 里所有命令都已经这样写。

---

## 5. 以后换成 J-Quants 日股数据,要改哪里

### 5a. 数据层(已验证,2026-08-16)

**J-Quants 数据 → Qlib 格式这条技术链路已经跑通并验证过**:真实的日股小盘股数据(股票代码、金额等具体内容属于私有数据,**不放在这个公开仓库里**)已经转换成 Qlib `.bin` 格式,存在 Codespace 的 `~/.qlib/qlib_data/jp_smallcap`(独立路径,不影响这个仓库用的 `cn_data`),用 `D.features()` 查询过,数值正确,还拿一个真实因子(短期反转)算出过 Rank IC,数字合理。

具体的转换脚本、数据字段映射、如何在新 Codespace 里重新灌入这份数据,记录在**另一个私有仓库**里(不公开,因为里面涉及具体数据处理方法论):`~/jquants/qlib_bridge/README.md`。

### 5b. 接入 RD-Agent 场景层(还没做,下次会话的任务)

⚠️ 数据层通了,不代表 RD-Agent 自动因子生成这一层通了——`fin_factor` 场景的配置模板和 LLM 场景描述,目前是**照着 A 股写死的**,证据(2026-08-16 实测查证,不是猜的):

- `conf_baseline.yaml` 里硬编码 `market: csi300`、`benchmark: SH000300`、`provider_uri: ~/.qlib/qlib_data/cn_data`、`region: cn`,以及 A 股特有的涨跌停阈值(9.5%)
- Qlib 官方 `region` 参数**只有 `REG_CN` 和 `REG_US` 两个预设**([官方文档](https://qlib.readthedocs.io/en/latest/start/initialization.html)),没有日本

| 要改的文件 | 改什么 |
|---|---|
| `rdagent/scenarios/qlib/experiment/factor_template/conf_baseline.yaml`(和 `conf_combined_factors.yaml`) | `provider_uri` 指向 `jp_smallcap`;去掉 `region: cn`,手动配置(日股涨跌停不是固定比例,是阶梯表,第一版可以先不模拟);`market`/`benchmark` 换成日股小盘股票池和合适的基准 |
| RD-Agent 因子场景的 prompt/scenario 描述文件(在 `rdagent/scenarios/qlib/` 下,**具体是哪个文件还没定位**) | 官方默认场景描述是针对 A 股写的,换日股需要检查这些假设是否还成立,不然 LLM 会带着"这是 A 股"的错误语境去生成因子 |
| `.devcontainer/setup_env.sh` | 加一步:每次重建 Codespace,自动从私有仓库拉取/重建 `jp_smallcap` 数据(参考 `~/jquants/qlib_bridge/README.md` 的"从头恢复步骤") |

---

## 6. 验证命令(重启后自查)

一条命令确认"环境还在、数据还在、历史日志还能打开":

```bash
gh auth status && gh codespace list && gh codespace ssh -c $(gh codespace list --json name -q '.[0].name') -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && echo \"=== conda 环境 ===\"; conda env list | grep rdagent; echo; echo \"=== Qlib 数据 ===\"; du -sh ~/.qlib/qlib_data/cn_data 2>&1; echo; echo \"=== 历史实验日志 ===\"; ls log/; echo; echo \"=== 健康检查 ===\"; bash scripts/health_check.sh"'
```

预期看到:
- `conda` 环境列表里有 `rdagent`
- Qlib 数据目录显示 `842M` 左右
- `log/` 下列出多个时间戳目录(每轮实验一个)
- 健康检查全部 `✅`

---

## 附:这次踩坑踩出来的一个重要认知

RD-Agent 官方 `requirements.txt` 里锁的几个版本(`pydantic-ai-slim==1.66.0`、`scipy==1.11.4`)彼此之间其实**不完全兼容**——`scipy==1.11.4` 满足不了 Qlib 回测用到的 `cvxpy` 的实际要求。这不是我们环境搭建的问题,是上游项目本身依赖锁定不够严谨。如果以后升级 `rdagent` 版本,这几个手动修复的版本号**大概率需要重新核实**,不要假设它们永远适用。
