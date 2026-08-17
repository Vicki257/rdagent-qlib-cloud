"""
EXP-0004 · RD-Agent 生成并跑通的因子代码（原样保存，未改动）。

多个因子按 `# ===== 因子: <名字> =====` 分段。每一段就是 RD-Agent 在自己的
工作目录里那份 factor.py 的完整内容。
"""

# ==========================================================================
# ===== 因子: 5_day_momentum =====
# 公式: \text{Momentum}_{t} = \frac{P_{t}}{P_{t-5}} - 1
# ==========================================================================

import pandas as pd
import numpy as np

def calculate_5_day_momentum():
    # Read the daily price and volume data
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # Sort the dataframe by datetime and instrument to ensure correct grouping
    df = df.sort_index(level=['datetime', 'instrument'])
    
    # Calculate the 5-day momentum factor
    # Group by instrument and shift the close price by 5 days
    df['close_5d_ago'] = df.groupby(level='instrument')['$close'].shift(5)
    df['5_day_momentum'] = df['$close'] / df['close_5d_ago'] - 1
    
    # Select only the datetime, instrument, and factor value
    result = df[['5_day_momentum']].dropna()
    
    # Save the result to result.h5
    result.to_hdf('result.h5', key='data', mode='w')
    
    return result

if __name__ == '__main__':
    calculate_5_day_momentum()



# ==========================================================================
# ===== 因子: 5_day_volatility =====
# 公式: \text{Volatility}_{t} = \sqrt{\frac{1}{4} \sum_{i=0}^{4} (r_{t-i} - \bar{r}_t)^2}
# ==========================================================================

import pandas as pd
import numpy as np

def calculate_5_day_volatility():
    # Read the price data
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # Sort index to ensure correct order
    df = df.sort_index()
    
    # Calculate daily log returns
    # Need to group by instrument to compute returns per instrument
    df['log_return'] = df.groupby(level='instrument')['$close'].transform(lambda x: np.log(x / x.shift(1)))
    
    # Calculate 5-day rolling standard deviation (sample std, ddof=1)
    # Rolling window of 5, min_periods=5 to ensure full window
    df['5_day_volatility'] = df.groupby(level='instrument')['log_return'].transform(
        lambda x: x.rolling(window=5, min_periods=5).std(ddof=1)
    )
    
    # Drop the intermediate column
    df = df.drop(columns=['log_return'])
    
    # Select only the factor column and drop rows with NaN
    result = df[['5_day_volatility']].dropna()
    
    # Save to result.h5
    result.to_hdf('result.h5', key='data', mode='w')
    
    return result

if __name__ == '__main__':
    calculate_5_day_volatility()



# ==========================================================================
# ===== 因子: 5_day_volume_change =====
# 公式: \text{VolumeChange}_{t} = \frac{\text{AvgVol}_{t-4,t}}{\text{AvgVol}_{t-9,t-5}} - 1
# ==========================================================================

import pandas as pd
import numpy as np

def calculate_5_day_volume_change():
    # Read the input data
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # Sort index to ensure correct order
    df = df.sort_index()
    
    # Compute rolling sums for the two windows using groupby with transform
    # For the last 5 days (including current day): sum of volume over days t-4 to t
    sum_last5 = df.groupby(level='instrument')['$volume'].transform(
        lambda x: x.rolling(window=5, min_periods=5).sum()
    )
    
    # For the preceding 5 days (t-9 to t-5): shift the volume by 5 days then compute rolling sum
    # First, shift volume by 5 days within each instrument
    shifted_volume = df.groupby(level='instrument')['$volume'].shift(5)
    # Then compute rolling sum of the shifted volume over 5 days (this gives sum of days t-9 to t-5)
    sum_prev5 = df.groupby(level='instrument')['$volume'].transform(
        lambda x: x.shift(5).rolling(window=5, min_periods=5).sum()
    )
    
    # Compute averages
    avg_last5 = sum_last5 / 5.0
    avg_prev5 = sum_prev5 / 5.0
    
    # Compute the factor
    factor = avg_last5 / avg_prev5 - 1.0
    
    # Convert the Series to a DataFrame with the original index
    result = factor.to_frame(name='5_day_volume_change')
    
    # Drop rows with NaN (due to insufficient data)
    result = result.dropna()
    
    # Save to result.h5
    result.to_hdf('result.h5', key='data', mode='w')
    
    return result

if __name__ == '__main__':
    calculate_5_day_volume_change()


