# 给任何 AI 的交接手册

**这份文档是写给"不记得我们之前聊过什么"的 AI 看的**——不管是 Claude 额度用完了换了新对话,
还是换成别的 AI(ChatGPT、Gemini 之类的都行)。只要这个 AI 能在你 Mac 的终端里执行命令
(能用 Bash/终端工具),照着这份文档一步步做,就能接着用这套环境,不用你重新解释一遍。

---

## 第一步:让 AI 先确认这几个关键事实(把下面这段话整段发给它)

> 我在用 microsoft/RD-Agent + Qlib 做量化因子研究。请你先做这几件事确认环境状态:
> 1. 公开代码仓库是 `https://github.com/Vicki257/rdagent-qlib-cloud`,先读一下里面的 README.md
> 2. 用 `gh codespace list` 查一下我现在有没有在跑的 Codespace,叫什么名字
> 3. 如果没有,按 README.md 第 1b 节的步骤重建一个
> 4. 私有仓库在我 Mac 本地的 `~/jquants` 目录,里面有日本股票数据处理的方法论,不要往任何公开地方推送这个仓库的内容

## 第二步:告诉它这次要研究哪个市场

**我们现在有两份数据,必须先说清楚这次用哪份**:

| 市场 | 数据在哪(Codespace 容器内路径) | 切换命令 |
|---|---|---|
| 中国 CSI300(官方默认) | `~/.qlib/qlib_data/cn_data` | `source scripts/switch_market.sh cn` |
| 日本小盘股(300只精简版) | `~/.qlib/qlib_data/jp_smallcap_300` | `source scripts/switch_market.sh jp` |

跟 AI 说:

> 这次帮我研究 **[日本小盘股 / 中国 CSI300]**。先在 Codespace 里 `cd /workspaces/rdagent-qlib-cloud`,
> 然后 `source scripts/switch_market.sh [jp / cn]`,确认切换成功(这条命令会把数据源和"AI 自己
> 以为在研究什么"的说明文字绑在一起改,不会切换了数据但说明文字没跟着换)。

## 第三步:把因子想法喂给它

> 我在 [论文/文章/推特] 上看到一个说法:[把你看到的内容原样贴给它,不用自己先整理]。
> 帮我把这个想法整理成一个能测试的因子定义(写清楚公式和参数),然后用 RD-Agent 的
> `fin_factor` 场景跑一遍,数据用刚才选好的那个市场。

## 第四步:要求它诚实汇报,不许美化

> 跑完之后,把真实的原始数字给我(IC、Rank IC、收益率、最大回撤这些),不要只说"效果不错"
> 这种话。中途如果报错,把原始报错文字贴给我,不要自己悄悄绕过去,先告诉我打算怎么修再动手。

## 第五步:要求它用固定框架分析,不许只报数字

> 用 `knowledge_map/TEMPLATE.md` 里那套六视角框架(预测模型/收益模型/风险模型/赚钱方式/
> 执行模型/参数测试 → 这次的结论 → 下一步验证什么)帮我拆一遍这个结果。先问我自己怎么看,
> 不要直接把结论讲给我听。

## 第六步:存档

> 把这次的分析写进 `knowledge_map/` 目录,提交到对应的仓库(公开内容进
> `rdagent-qlib-cloud`,涉及日股具体数据/方法论的进本地 `~/jquants`,不要推送后者)。
> 另外帮我更新 Notion 里"待复盘"那个数据库当天日期的那一页(先搜"待复盘"找到)。

---

## 关键信息速查表(AI 忘了随时回来看这张表)

| 东西 | 在哪 |
|---|---|
| 公开仓库(环境、脚本、公开分析) | `https://github.com/Vicki257/rdagent-qlib-cloud` |
| 私有仓库(日股数据方法论,不公开) | 本机 `~/jquants`,没有远程仓库,只存在这台 Mac 上 |
| 恢复云端环境完整步骤 | 公开仓库 `README.md` 第 1 节 |
| 中国股票数据位置 | Codespace 内 `~/.qlib/qlib_data/cn_data` |
| 日本股票数据位置 | Codespace 内 `~/.qlib/qlib_data/jp_smallcap_300` |
| 切换研究市场 | 公开仓库 `scripts/switch_market.sh jp` 或 `cn` |
| 六视角分析模板 | 公开仓库 `knowledge_map/TEMPLATE.md` |
| 简化版工作流程图 | 公开仓库 `knowledge_map/工作流程.md` |
| Notion 复盘记录 | Notion 里搜"待复盘",数据库叫"复盘 · 复利记录" |

## 一个必须提醒新 AI 的限制

RD-Agent 自动跑因子回测这一步,目前偶尔会在"处理完新因子数据、正式开始回测"这个点上
无声无息地卡死(根源还没查出来,不是内存不够、不是崩溃,已经排除过好几种可能)。如果
新 AI 碰到这个情况:**不要瞎猜着改代码硬闯**,先老实告诉你卡在哪,可以参考的诊断记录在
公开仓库这次相关的 git 提交历史里(commit message 里写了已经排除过哪些原因)。
