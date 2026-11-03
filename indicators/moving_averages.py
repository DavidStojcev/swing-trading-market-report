"""Moving average calculations and Golden/Death cross detection."""

from typing import Tuple
import pandas as pd


def compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def check_dma_cross(dma_fast: pd.Series, dma_slow: pd.Series, lookback_bars: int = 5) -> str:
    """Determine the cross status between fast DMA (e.g. 50) and slow DMA (e.g. 200).
    
    Returns:
        'Golden Cross' if 50 crossed above 200 recently,
        'Death Cross' if 50 crossed below 200 recently,
        'Bullish (50 > 200)' if 50 remains above 200,
        'Bearish (50 < 200)' if 50 remains below 200,
        or 'Neutral' if insufficient data.
    """
    valid = (dma_fast.dropna().index).intersection(dma_slow.dropna().index)
    if len(valid) < 2:
        return "Insufficient Data"

    f = dma_fast.loc[valid]
    s = dma_slow.loc[valid]

    diff = f - s
    current_diff = diff.iloc[-1]
    
    # Check for recent crossover within lookback_bars
    window = min(lookback_bars, len(diff) - 1)
    if window >= 1:
        prev_diff = diff.iloc[-1 - window]
        if prev_diff < 0 and current_diff >= 0:
            return "Golden Cross"
        if prev_diff > 0 and current_diff <= 0:
            return "Death Cross"

    if current_diff > 0:
        return "Bullish (50 > 200)"
    elif current_diff < 0:
        return "Bearish (50 < 200)"
    else:
        return "Neutral"
