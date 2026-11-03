"""Momentum indicators including Wilder's Relative Strength Index (RSI)."""

import numpy as np
import pandas as pd


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) using classic Wilder's smoothing.
    
    Args:
        series: Price series (e.g., Close).
        period: Lookback period, standard is 14.
        
    Returns:
        pd.Series containing RSI values between 0.0 and 100.0.
    """
    if len(series) < period + 1:
        return pd.Series(np.nan, index=series.index)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    ag_vals = np.full(len(series), np.nan, dtype=np.float64)
    al_vals = np.full(len(series), np.nan, dtype=np.float64)

    gain_vals = gain.to_numpy(dtype=np.float64)
    loss_vals = loss.to_numpy(dtype=np.float64)

    first_gain_mean = np.mean(gain_vals[1 : period + 1])
    first_loss_mean = np.mean(loss_vals[1 : period + 1])

    ag_vals[period] = first_gain_mean
    al_vals[period] = first_loss_mean

    for i in range(period + 1, len(series)):
        ag_vals[i] = (ag_vals[i - 1] * (period - 1) + gain_vals[i]) / period
        al_vals[i] = (al_vals[i - 1] * (period - 1) + loss_vals[i]) / period

    avg_gain = pd.Series(ag_vals, index=series.index)
    avg_loss = pd.Series(al_vals, index=series.index)

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where(avg_gain != 0, 0.0)

    return rsi
