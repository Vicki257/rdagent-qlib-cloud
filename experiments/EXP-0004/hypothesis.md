# EXP-0004 · 假设

> 这是 RD-Agent 自己提出的假设,原文照抄,没有润色。

## 假设

Simple price-volume based factors such as 5-day momentum, 5-day volatility, and 5-day volume change can capture short-term trends and risk, potentially predicting future returns.

## 它给的理由

These factors are simple, easy to compute, and have economic rationale: momentum captures trend persistence, volatility captures risk premium, and volume change captures liquidity and trading activity. They use only price and volume data, making them robust and interpretable. Starting with these will establish a baseline for further refinement.

## 拆成了几个因子任务

### 1. `5_day_momentum`

[Momentum Factor] 5-day momentum captures short-term price trend persistence. It is calculated as the ratio of the current close price to the close price 5 days ago minus 1.

公式：

```latex
\text{Momentum}_{t} = \frac{P_{t}}{P_{t-5}} - 1
```

变量：

- `P_t`: Close price at day t
- `P_{t-5}`: Close price at day t-5

### 2. `5_day_volatility`

[Volatility Factor] 5-day volatility measures the dispersion of daily returns over the past 5 days, capturing short-term risk. It is computed as the standard deviation of daily log returns over the 5-day window.

公式：

```latex
\text{Volatility}_{t} = \sqrt{\frac{1}{4} \sum_{i=0}^{4} (r_{t-i} - \bar{r}_t)^2}
```

变量：

- `r_t`: Daily log return at day t, defined as ln(P_t / P_{t-1})
- `\bar{r}_t`: Mean of the 5 daily log returns ending at day t

### 3. `5_day_volume_change`

[Volume Factor] 5-day volume change measures the relative change in trading volume over the past 5 days, capturing shifts in liquidity and trading activity. It is computed as the ratio of the average volume over the last 5 days to the average volume over the preceding 5 days minus 1.

公式：

```latex
\text{VolumeChange}_{t} = \frac{\text{AvgVol}_{t-4,t}}{\text{AvgVol}_{t-9,t-5}} - 1
```

变量：

- `\text{AvgVol}_{a,b}`: Average daily volume from day a to day b inclusive
