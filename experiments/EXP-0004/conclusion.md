# EXP-0004 · 结论

**RD-Agent 的判定**：接受（判定为新 SOTA）

> 以下全部是 RD-Agent 自己写的原文，不是我的解读。
> ⚠️ 它的判定只看 Qlib 的纸面指标，**没有**过成本敏感性和隐藏样本外校验
> （见 `../../../jquants/qlib_bridge/RELIABILITY_PLAN.md` 第 3 条）。

## 它观察到什么

The combined factors (5-day momentum, 5-day volatility, and 5-day volume change) yield an IC of 0.030954, which is higher than the SOTA IC of 0.027387. The annualized return with cost is 0.063456, significantly higher than the SOTA's 0.037827. However, the max drawdown is -0.136414, which is worse (more negative) than the SOTA's -0.084930.

## 它怎么评价这个假设

The hypothesis that simple price-volume based factors can capture short-term trends and risk is supported. The improvement in IC and annualized return indicates that these factors provide predictive power for future returns. The higher drawdown suggests increased risk, but the overall return improvement is substantial.

## 它给的理由

The current factors show strong predictive ability (higher IC) and return generation, but the increased drawdown indicates a need for risk management. Adding complementary technical indicators or adjusting factor weights could help balance return and risk. Since the current factors are already in the SOTA library, exploring new directions like ATR or RSI could provide additional alpha and diversification.

## 它打算下一轮做什么

Incorporating additional short-term factors such as 5-day average true range (ATR) or 5-day relative strength index (RSI) could further enhance predictive power while potentially managing drawdowns. Additionally, combining these factors with a risk overlay or volatility scaling might improve risk-adjusted returns.

## 关键指标（数字来自 `metrics.json`）

| 指标 | 这一轮 | 上一个 SOTA |
|---|---|---|
| `IC` | 0.030954 | 0.027387 |
| `Rank IC` | 0.033299 | 0.039512 |
| `ICIR` | 0.238938 | 0.226750 |
| `Rank ICIR` | 0.253985 | 0.332397 |
| `1day.excess_return_with_cost.annualized_return` | 0.063456 | 0.037827 |
| `1day.excess_return_with_cost.max_drawdown` | -0.136414 | -0.084930 |
| `1day.excess_return_with_cost.information_ratio` | 0.675281 | 0.526216 |
