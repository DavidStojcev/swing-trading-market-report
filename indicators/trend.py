"""Trend indicators: MACD (Moving Average Convergence Divergence) and ADX (Average Directional Index)."""

from typing import Tuple
import numpy as np
import pandas as pd


def compute_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD line, signal line, and histogram.
    
    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Helper to apply classic Wilder smoothing."""
    s_vals = np.full(len(series), np.nan, dtype=np.float64)
    if len(series) < period:
        return pd.Series(s_vals, index=series.index)

    vals = series.to_numpy(dtype=np.float64)
    s_vals[period - 1] = np.nansum(vals[:period])

    for i in range(period, len(series)):
        val = vals[i] if not np.isnan(vals[i]) else 0.0
        s_vals[i] = s_vals[i - 1] - (s_vals[i - 1] / period) + val

    return pd.Series(s_vals, index=series.index)


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Average Directional Index (ADX) along with +DI and -DI.
    
    Returns:
        Tuple of (adx, plus_di, minus_di).
    """
    if len(close) < (2 * period):
        nan_series = pd.Series(np.nan, index=close.index)
        return nan_series, nan_series, nan_series

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=close.index)
    minus_dm = pd.Series(0.0, index=close.index)

    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    tr_smoothed = _wilder_smooth(tr, period)
    plus_dm_smoothed = _wilder_smooth(plus_dm, period)
    minus_dm_smoothed = _wilder_smooth(minus_dm, period)

    plus_di = 100.0 * (plus_dm_smoothed / tr_smoothed)
    minus_di = 100.0 * (minus_dm_smoothed / tr_smoothed)

    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100.0 * (di_diff / di_sum.replace(0, np.nan))

    adx_vals = np.full(len(close), np.nan, dtype=np.float64)
    dx_vals = dx.to_numpy(dtype=np.float64)

    dx_valid_indices = np.where(~np.isnan(dx_vals))[0]
    if len(dx_valid_indices) >= period:
        start_idx = dx_valid_indices[period - 1]
        adx_vals[start_idx] = np.mean(dx_vals[dx_valid_indices[:period]])
        for i in range(start_idx + 1, len(close)):
            current_dx = dx_vals[i]
            if not np.isnan(current_dx):
                adx_vals[i] = (adx_vals[i - 1] * (period - 1) + current_dx) / period

    adx = pd.Series(adx_vals, index=close.index)
    return adx, plus_di, minus_di
