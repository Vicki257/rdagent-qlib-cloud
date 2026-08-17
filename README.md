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
| **跑一次普通实验(只要记这一条命令)** | [第 2 节](#2-怎么跑一次新实验) |
| **搞懂 V2 的研究可信性层在管什么** | [第 0.5 节](#05-v2-研究可信性层2026-08-17) |
| **在 Frozen Test 上做最终校验** | [第 0.5 节](#frozen-test--唯一能碰它的入口) |
| 电脑重启/隔了几周,想接着用 | [第 1 节](#1-重启电脑后怎么恢复) |
| 跑一次新实验 | [第 2 节](#2-怎么跑一次新实验) |
| 打开 UI 看某一轮历史实验 | [第 3 节](#3-怎么打开-ui-看历史实验) |
| 想知道数据/日志/配置分别存哪 | [第 4 节](#4-数据日志配置分别存在哪) |
| 以后要换成 J-Quants 日股数据 | [第 5 节](#5-以后换成-j-quants-日股数据要改哪里) |
| 自己验证"环境还在不在" | [第 6 节](#6-验证命令重启后自查) |
| 每次新结果怎么写进知识地图 | [`knowledge_map/TEMPLATE.md`](knowledge_map/TEMPLATE.md) |

---

## 0.5 V2 研究可信性层(2026-08-17)

到 V1 为止解决的是「能不能跑」。V2 解决的是**「跑出来的数字能不能信」**。

### 新的流程

```
J-Quants / Qlib Data
        ↓
RD-Agent            提出假设 + 写因子       ← 负责「想」
        ↓
Qlib                计算实验结果            ← 负责「算」
        ↓
Validation Gate     独立判断结果能不能信      ← 负责「判断」(新增)
        ↓
    PASS / FAIL
     ↓       ↓
Candidate   失败原因 → RD-Agent 下一轮
     ↓
Frozen Test  (独立入口,RD-Agent 看不到)
     ↓
最终结论
     ↓
Knowledge Map       人理解学到了什么         ← 六视角,原样保留
```

**Validation Gate 不替代 knowledge_map,两者职责不同**:
Gate 是机器判断「实验可不可信」,knowledge_map 是人理解「这次学到了什么」。
顺序是:实验 → Gate → 拿到可信结果 → 再进 `knowledge_map/TEMPLATE.md` 的六视角。

### 数据切成四段(单一真源:`validation/config.yaml`)

| 段 | RD-Agent 能不能看 | JP 实际区间 | 交易日 |
|---|---|---|---|
| Train | ✅ 可反复用 | 2022-01-04 .. 2023-06-30 | 366 |
| Validation | ✅ 可反复用 | 2023-07-03 .. 2023-12-29 | 124 |
| Research OOS | ✅ 可反复用(就是 Qlib 配置里的 `test`) | 2024-01-04 .. 2024-12-30 | 245 |
| **Frozen Test** | ❌ **看不到** | **2025-01-06 .. 2025-12-30** | **243** |

CN 的四段见 `validation/config.yaml`(Frozen Test = `2022-08-02 .. 2026-08-14`,
起点排在 2022-08-01 之后是因为官方模板的取数窗口到 2022-08-01,
必须让 Frozen Test「从未被任何一轮加载过」这条性质在程序上成立)。

日期全部来自实测,不是猜的。换数据以后 `health_check` 会检查 `config.yaml`
里的 `data_available` 和真实日历是否一致,不一致直接 STOP。

### Frozen Test —— 唯一能碰它的入口

```bash
bash scripts/run_frozen_test.sh EXP-0004
```

> **一旦 Frozen Test 被用于调参数、改因子、选择因子,它就不再是 Frozen Test。**

这不是免责声明,是操作纪律。`run_frozen_test.py` 每次运行都会在
`experiments/<EXP>/frozen_test/frozen_test.json` 里累加 `times_used`,
就是为了让「这段被用过几次」留下痕迹 —— 用 1 次是最终校验,
用 5 次说明它已经变成又一个被训练过的 test 集。

**RD-Agent 看不到 Frozen Test,靠三层保证,不靠自觉**:

1. **物理层(最硬)**:research 模式下 Qlib 配置里 `data_handler_config.end_time`
   和 `backtest.end_time` 都止步于 Research OOS 末尾。Frozen 区间的数据
   **根本没被加载进内存**,不是「加载了但不看」。
2. **模式层**:两个 Qlib yaml 顶部有 `# RDAGENT_QLIB_CLOUD_MODE: research|frozen`
   标记。`run_one_loop.sh` 开跑前强制 `research_check.py --require-mode research`,
   frozen 模式下直接 ❌ STOP。
3. **反馈层**:`run_frozen_test.sh` **不启动 RD-Agent**,只调 `qrun`,
   结果只写 `experiments/`,不写 RD-Agent 的 `log/` 或 session 状态,
   所以下一轮不可能把它当反馈读到。

这三层都有对应的否定测试,见 `bash scripts/selftest_gates.sh`。

### Validation Gate 检查什么

`validation/validate.py`,读 Qlib 的真实结果,**全部确定性判定,不调用任何 LLM**。
**PASS/FAIL 不由 RD-Agent 决定** —— 它自己的 `decision` 会被原样记录,但不参与判定。

| Gate | 管什么 | 判定 |
|---|---|---|
| 1 数据/时间安全 | 段间重叠、切分越界、市场说明 vs `provider_uri`、因子源数据 vs 行情数据、标签是否只用未来价格、归一化窗口是否偷看未来、research 模式有没有伸进 frozen、patch 是否真生效 | 结构性错误 → **FAIL** |
| 2 因子有没有信息 | IC / Rank IC / ICIR / Rank ICIR | 第一版只记录,不判定 |
| 3 有没有增量价值 | baseline vs baseline+新因子:IC、Rank IC、年化、超额、IR、回撤、换手、成本 | Rank IC 无增量 → **FAIL** |
| 4 稳定性 | 按年切片的收益 / Sharpe / 回撤;去掉贡献最大的那一年还剩不剩正收益 | 全靠单一年份 → **FAIL** |

第一版**刻意不设** `IC > 0.03` 这类武断阈值。只有「一定是错」的才 FAIL,
「好不好」交给人看 knowledge_map。原则:**宁可结果少,也不要产生假的量化结论。**

Gate 3 判据用 **Rank IC** 而不是年化收益 —— 年化收益容易被少数右尾赢家支配
(私有仓库的 TOPIX Small 实验实测过:分组平均收益和 Rank IC 可以指向相反方向)。

**Gate 上线第一天就抓到一个真问题**:2026-08-16 那轮 RD-Agent 判定为「新 SOTA」
的实验(`EXP-0004`),它自己看的是 IC(0.027387 → 0.030954,确实涨了),
但 **Rank IC 其实是下降的**(0.039512 → **0.033299**),Rank ICIR 从
0.332 掉到 0.254。Gate 3 判 FAIL。

### 每轮自动存档(Codespace 删了也还在)

`log/` 在容器里,删掉就没了。每轮结束自动抽出核心证据(几百 KB,不是几百 MB):

```
experiments/EXP-0001/
    metadata.json        实验ID/时间/市场/数据范围/三段范围/因子名/Gate判定与失败原因/
                         RD-Agent意见/下一步方向/frozen_test_used/已知缺陷/对应log路径
    hypothesis.md        RD-Agent 提的假设 + 理由 + 因子任务和公式
    factor.py            它写出来并跑通的因子代码,原样保存
    config.yaml          Qlib 真正用的配置(含 provider_uri 和三段区间)
    metrics.json         本轮指标 + 上一个 SOTA 指标 + token 花费 + 墙上时间
    validation.json      Validation Gate 四组检查的完整结果
    conclusion.md        RD-Agent 的判定/观察/下一步 + 关键指标对比表
    backtest_curve.csv   逐日净值/换手/成本曲线
```

`experiments/INDEX.md` 是总索引,一行一个实验,**Gate 判定**和 RD-Agent 意见分两列。

⚠️ **公开/私有分流**:这个仓库是 Public。日股产出是 J-Quants 授权数据的衍生物,
按 `knowledge_map/AI交接手册.md` 的规定不进公开仓库。抽取器按每轮实际用的
`provider_uri` 自动分流:`cn_data` → `experiments/`(进 Git);
`jp_smallcap*` 或认不出来的 → `experiments_private/`(被 gitignore)。
**漏判成私有只是麻烦,漏判成公开是泄露**,所以默认按最保守处理。

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

**只需要记这一条命令**(先选好市场,`jp` 或 `cn`):

```bash
gh codespace ssh -c <CODESPACE_NAME> -- 'bash -lc "cd /workspaces/rdagent-qlib-cloud && source scripts/switch_market.sh jp && bash scripts/run_one_loop.sh"'
```

`run_one_loop.sh` 现在自己会做完整四步,不用你再记别的命令:

```
[1/4] 研究环境体检      配置错位 → ❌ STOP,不让你带着假配置跑
                        并强制 research 模式(碰不到 Frozen Test)
[2/4] 跑 RD-Agent       提假设 → 写因子 → Qlib 训练回测
[3/4] Validation Gate   独立判断能不能信 → PASS / FAIL
[4/4] 抽核心证据存档     写进 experiments/EXP-NNNN/
```

第 3、4 步挂在 `trap EXIT` 上,所以**即使 RD-Agent 中途卡死**(已知 bug,见下面),
这一轮的假设、代码、失败原因也会被存档,不会跑挂了就什么都没留下。

跑多轮把轮数当参数传:`bash scripts/run_one_loop.sh 5`。
实测单个 loop 约 **9-10 分钟**,DeepSeek 花费约 **$0.02 以内**。

跑完看结果:

```bash
cat experiments/INDEX.md                    # 全部历史实验一览(含 Gate 判定)
cat experiments/EXP-0005/metadata.json      # 某一轮测了什么、通过没通过、为什么
```

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

### 5b. 接入 RD-Agent 场景层(部分完成,2026-08-17 更新)

⚠️ 数据层通了,不代表 RD-Agent 自动因子生成这一层全通了。`fin_factor` 场景的配置模板原本**照着 A 股写死**(2026-08-16 实测查证):`conf_baseline.yaml` 硬编码 `market: csi300`、`benchmark: SH000300`、`provider_uri: ~/.qlib/qlib_data/cn_data`、`region: cn`(Qlib 官方 `region` 参数只有 `REG_CN`/`REG_US` 两个预设,没有日本——[官方文档](https://qlib.readthedocs.io/en/latest/start/initialization.html))。

**已经修好的部分**:
1. **数据源配置**(`conf_baseline.yaml`/`conf_combined_factors.yaml` 的 `provider_uri`)——可切换
2. **AI 场景描述文字错位的 bug**——原本这段文字(显示在网页报告的 Config 表格里,也讲给 LLM 听)是写死的 `CSI300 / 2008-2020`,跟实际用的数据完全无关。2026-08-16 晚上真实踩过这个坑:切了日股数据但报告还显示"CSI300"。已修复,补丁在 `.devcontainer/patch_market_switch.py`,原理是把这段文字改成读环境变量的模板,默认值不变(不影响中国股票那套)。

**怎么切换市场**(一条命令,两件事一起改,不会再错位):
```bash
source scripts/switch_market.sh jp   # 切到日本小盘股
source scripts/switch_market.sh cn   # 切回官方默认(中国 CSI300)
```
必须用 `source` 执行(不能 `bash` 直接跑),因为要在当前 shell 设置环境变量。

### 5c. 2026-08-17 发现:JP 那条线之前**从来没跑出过有意义的数字**

V2 改造过程中查出两个会**静默产生假数字**的错配。两个都不报错、都会给出漂亮的
指标,只是指标没有意义 —— 这也正是为什么需要一个独立的可信性层。

**错配 1:`switch_market.sh` 只换了 provider_uri 一行。**
老版本就一句 `sed -i 's|~/.qlib/qlib_data/[a-z_0-9]*"|...jp_smallcap_300"|'`。
结果 JP 模式下 Qlib 实际拿到的是:

| 字段 | 实际值 | 问题 |
|---|---|---|
| `provider_uri` | `jp_smallcap_300` | ✅ 换了 |
| `market` | `csi300` | ❌ JP 数据目录里只有 `all.txt`,没有 `csi300.txt` |
| `benchmark` | `SH000300` | ❌ JP 数据里没有这个指数 |
| `segments` | train 2008-2014 / valid 2015-2016 / test 2017-2020 | ❌ **JP 数据 2022-01-04 才开始,三段全在数据存在之前** |
| `limit_threshold` | `0.095` | ❌ A 股涨跌停 |

更糟的是:`patch_market_switch.py` 把「讲给 LLM 听的说明文字」改成读环境变量、
显示成 2022-2023,而 yaml 里的日期还是 2008-2014 —— **修好了文字,没修 yaml**,
反而把错位藏得更深。

**修法**:所有市场字段统一由 `validation/config.yaml` 定义,
`scripts/apply_market_config.py` 一次性全部写进去,不可能只改一半。
`switch_market.sh` 现在只是这个脚本的薄封装。

**错配 2:因子源数据和行情数据不是同一个市场。**
RD-Agent 把 Qlib 行情导出成
`git_ignore_folder/factor_implementation_source_data/daily_pv.h5`,
因子代码全部基于它计算。**这个文件会被缓存,切 provider 之后不会自动重新生成。**
实测当时的状态:

```
daily_pv.h5    6075 只股票, 2008-12-29 .. 2026-08-14   ← A 股
provider_uri   jp_smallcap_300, 300 只, 2022-01-04 ..  ← 日股
股票代码重叠   0 只（0.0%）
```

也就是「因子在 A 股数据上算,回测在日股数据上跑」,合并后基本全是 NaN,但不报错。
**修法**:Gate 1 现在会算这个重叠率,低于 50% 直接 FAIL,并给出
「删掉 `factor_implementation_source_data/` 让它按当前 provider 重新生成」的指示。

### 5d. JP 回测**还剩**哪些未解决的问题(不要当已经解决)

| 问题 | 状态 | 已经做了什么 |
|---|---|---|
| **股票池不是时点正确的** | ❌ 未解决 | 实测 `instruments/all.txt` 里 300 只有 291 只起始日统一是数据起点 2022-01-04,没有任何一只带「晚于起点才进入股票池」的记录 → 这是「2022-2025 任意月末属于 TOPIX Small 1/2 的并集」,不是逐月成分股。2024 年才被降级进 Small 的股票在 2022 年就已经在池子里。**退市侧是好的**(25/300 有提前结束日期,退市股票会自然消失),**进入侧有前视偏差**。已在 `validation/config.yaml` 显式标记 `point_in_time_universe: false` / `universe_membership_lookahead: true`,并且这个标记会跟着写进每一条 `experiments/*/metadata.json` 的 `known_risks`,**不会出现「数字记住了、前提忘了」**。严谨做法的代码已存在于私有仓库,但还没接进 `.bin` 生成流程。参考量级:私有仓库实测简化并集 + 无流动性过滤的信号强度只有严谨版的 **39%**(Rank IC 0.0113 vs 0.0292)。 |
| **benchmark** | ✅ 已解决 | 不再用「随便找一只股票」。改成**等权市场组合**:Qlib 原生支持 `benchmark` 传 list,语义是「列表内股票的日均涨跌」(`qlib/backtest/report.py` 第 62-64 行),明确、可重复计算。`apply_market_config.py` 会把它展开成显式的 300 个代码写进 yaml,所以翻旧实验时基准是什么一目了然。Gate 1 还会检查 benchmark 不是「池子里的一只普通成分股」(那就是被禁止的占位做法)。 |
| **`market: all`** | ✅ 已解决 | JP 数据目录里确实只有 `all.txt`,`all` 是正确值而不是占位。Gate 1 会检查 `market` 对应的 `instruments/<market>.txt` 真的存在。 |
| **涨跌停没模拟** | ❌ 未解决 | 日本涨跌停是按股价区间的**阶梯绝对值表**,不是固定比例,Qlib 的单一 `limit_threshold` 表达不了。现在显式**不设**这一项(而不是留一个错的比例值),并标记 `price_limit_simulation: false`。 |
| **没有流动性过滤** | ❌ 未解决 | 这份 `.bin` 没套任何最小成交额门槛。私有仓库实测:去掉 3000 万日元/日的中位成交额门槛后,同一个因子的多空毛年化从 **+2.78% 掉到 −2.96%** —— 被门槛挡掉的股票只贡献噪声和成本。已标记 `liquidity_filter: false`。 |
| **分时段 IC 拿不到** | ❌ 未解决 | RD-Agent 在 Docker 容器里跑 `qrun`,只把汇总指标和回测曲线带出来,**没有持久化逐日预测值**(`pred.pkl` / `mlruns`)。所以 Gate 2 的「分时段 IC」显式报「不可得」并说明原因,**没有用别的东西糊弄成 IC**。Gate 4 的分年收益/Sharpe/回撤来自真实回测曲线,那部分是实数据。 |
| **RD-Agent 循环偶发卡死** | ❌ 未解决 | 处理完新因子数据、正式开始回测之前进程会被无声终止,原因还没查到(不是内存不够、不是崩溃、不是多进程冲突,已逐一排除)。CN / JP 都会碰到,是 RD-Agent 自身问题。**缓解**:`run_one_loop.sh` 把 Gate 和存档挂在 `trap EXIT` 上,卡死也会留下假设/代码/失败原因。 |
| **日股数据自动拉取** | ❌ 未解决 | `.devcontainer/setup_env.sh` 只会下载中国股数据;日股要手动照 `~/jquants/qlib_bridge/README.md` 的步骤灌。 |

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
