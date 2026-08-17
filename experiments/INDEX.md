# 实验索引

由 `scripts/archive_experiment.py` 自动生成，不要手改。

`log/` 在 Codespace 里，删掉就没了；这张表和它引用的目录是能活下来的那部分。
私有市场（日股）的条目在 `experiments_private/`，不在这个公开仓库里，
只在这里留一行记录说明它存在过。

**Gate** 列是 Validation Gate 的独立判定，**RD** 列是 RD-Agent 自己的意见。两者不一致是正常的 —— Gate 判的是「能不能信」，RD-Agent 判的是「它觉得好不好」。以 Gate 为准。

| EXP | 市场 | 存档 | **Gate** | RD | Frozen | IC | Rank IC | 年化(含成本) | 最大回撤 | 来源 log |
|---|---|---|---|---|---|---|---|---|---|---|
| （私有）EXP-0001 | unknown | partial | ➖ NOT_VALIDATED | — | 否 | — | — | — | — | `log/2026-08-16_06-01-55-220033/Loop_0` |
| （私有）EXP-0002 | unknown | partial | ❌ FAIL | 否决 | 否 | — | — | — | — | `log/2026-08-16_06-21-09-978261/Loop_0` |
| （私有）EXP-0003 | unknown | partial | ➖ NOT_VALIDATED | 否决 | 否 | — | — | — | — | `log/2026-08-16_06-26-16-989174/Loop_0` |
| EXP-0004 | cn | complete | ❌ FAIL | 接受 | 否 | 0.030954 | 0.033299 | 0.063456 | -0.136414 | `log/2026-08-16_06-35-38-526479/Loop_0` |
| （私有）EXP-0005 | unknown | partial | ➖ NOT_VALIDATED | — | 否 | — | — | — | — | `log/2026-08-16_10-43-33-152906/Loop_0` |

## 每个 EXP 目录里有什么

| 文件 | 内容 |
|---|---|
| `metadata.json` | 实验ID / 时间 / 市场 / 数据范围 / Train・Validation・Test 范围 / 因子名 / **Gate 判定与失败原因** / RD-Agent 意见 / 下一步方向 / `frozen_test_used` / 已知可信性缺陷 / 对应 log 路径 |
| `validation.json` | Validation Gate 四组检查的完整结果 |
| `hypothesis.md` | RD-Agent 提的假设、理由、拆成的因子任务和公式 |
| `factor.py` | 它写出来并跑通的因子代码，原样保存 |
| `config.yaml` | Qlib 真正用的配置（含 `provider_uri` 和训练/验证/测试区间） |
| `config_baseline.yaml` | 同一轮的基线配置，用来对照 |
| `metrics.json` | 本轮指标 + 上一个 SOTA 指标 + token 花费 + 墙上时间 |
| `conclusion.md` | RD-Agent 自己的判定/观察/下一步，附关键指标对比表 |
| `backtest_curve.csv` | 逐日净值、换手、成本曲线 |
| `MANIFEST.json` | 来源日志路径、抽取时间、**缺了哪些件** |

