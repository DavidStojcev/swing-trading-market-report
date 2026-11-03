"""Coordinated technical indicator computation pipeline."""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

from indicators.momentum import compute_rsi
from indicators.moving_averages import check_dma_cross, compute_sma
from indicators.trend import compute_adx, compute_macd


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Structured container for all calculated technical indicator metrics."""
    symbol: str
    name: str
    as_of_date: str
    price: float
    
    # Moving Averages
    dma_20: float
    dma_50: float
    dma_200: float
    price_vs_dma20_pct: float
    price_vs_dma50_pct: float
    price_vs_dma200_pct: float
    cross_50_200: str
    
    # Momentum
    rsi: float
    prev_rsi: float
    delta_rsi: float
    rsi_flag: str  # "Overbought", "Oversold", or "Neutral"
    
    # Trend - MACD
    macd: float
    macd_signal: float
    macd_hist: float
    macd_status: str  # "Bullish (MACD > Signal)" or "Bearish (MACD < Signal)"
    prev_macd: float
    delta_macd: float
    
    # Trend - ADX
    adx: float
    plus_di: float
    minus_di: float
    prev_adx: float
    delta_adx: float
    trend_strength: str  # "Strong Trend", "Moderate Trend", "Weak / Ranging"


def compute_technicals(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    as_of_date: str,
    prev_date: Optional[str] = None,
    dma_fast: int = 20,
    dma_medium: int = 50,
    dma_slow: int = 200,
    rsi_period: int = 14,
    rsi_overbought: float = 70.0,
    rsi_oversold: float = 30.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    adx_period: int = 14,
) -> Optional[TechnicalSnapshot]:
    """Compute complete technical indicators snapshot for an asset up to as_of_date.
    
    Guarantees no lookahead bias by filtering df <= as_of_date prior to computing indicators.
    """
    if df.empty or len(df) < 30:
        return None

    # Enforce strictly no lookahead bias
    as_of_dt = pd.to_datetime(as_of_date)
    sub = df[df.index <= as_of_dt].copy()
    if sub.empty:
        return None

    close = sub["Close"]
    high = sub["High"] if "High" in sub.columns else close
    low = sub["Low"] if "Low" in sub.columns else close

    sma20 = compute_sma(close, dma_fast)
    sma50 = compute_sma(close, dma_medium)
    sma200 = compute_sma(close, dma_slow)
    cross_status = check_dma_cross(sma50, sma200)

    rsi_series = compute_rsi(close, rsi_period)
    macd_line, sig_line, hist = compute_macd(close, macd_fast, macd_slow, macd_signal)
    adx_series, plus_di_series, minus_di_series = compute_adx(high, low, close, adx_period)

    # Current bar values (at as_of_dt or latest bar available <= as_of_dt)
    curr_idx = sub.index[-1]
    curr_price = float(close.loc[curr_idx])
    v_sma20 = float(sma20.loc[curr_idx]) if not np.isnan(sma20.loc[curr_idx]) else curr_price
    v_sma50 = float(sma50.loc[curr_idx]) if not np.isnan(sma50.loc[curr_idx]) else curr_price
    v_sma200 = float(sma200.loc[curr_idx]) if not np.isnan(sma200.loc[curr_idx]) else curr_price

    p_vs_20 = ((curr_price - v_sma20) / v_sma20) * 100.0 if v_sma20 > 0 else 0.0
    p_vs_50 = ((curr_price - v_sma50) / v_sma50) * 100.0 if v_sma50 > 0 else 0.0
    p_vs_200 = ((curr_price - v_sma200) / v_sma200) * 100.0 if v_sma200 > 0 else 0.0

    v_rsi = float(rsi_series.loc[curr_idx]) if not np.isnan(rsi_series.loc[curr_idx]) else 50.0
    rsi_flag = "Neutral"
    if v_rsi >= rsi_overbought:
        rsi_flag = f"Overbought (>{rsi_overbought:.0f})"
    elif v_rsi <= rsi_oversold:
        rsi_flag = f"Oversold (<{rsi_oversold:.0f})"

    v_macd = float(macd_line.loc[curr_idx]) if not np.isnan(macd_line.loc[curr_idx]) else 0.0
    v_sig = float(sig_line.loc[curr_idx]) if not np.isnan(sig_line.loc[curr_idx]) else 0.0
    v_hist = float(hist.loc[curr_idx]) if not np.isnan(hist.loc[curr_idx]) else 0.0
    macd_status = "Bullish (MACD > Signal)" if v_macd >= v_sig else "Bearish (MACD < Signal)"

    v_adx = float(adx_series.loc[curr_idx]) if not np.isnan(adx_series.loc[curr_idx]) else 0.0
    v_pdi = float(plus_di_series.loc[curr_idx]) if not np.isnan(plus_di_series.loc[curr_idx]) else 0.0
    v_mdi = float(minus_di_series.loc[curr_idx]) if not np.isnan(minus_di_series.loc[curr_idx]) else 0.0

    # Directional Trend Assessment combining ADX with +DI / -DI
    direction = "Bullish" if v_pdi >= v_mdi else "Bearish"
    di_tag = f"(+DI {v_pdi:.1f} > -DI {v_mdi:.1f})" if v_pdi >= v_mdi else f"(-DI {v_mdi:.1f} > +DI {v_pdi:.1f})"

    if v_adx < 20.0:
        trend_strength = f"Weak / Ranging {di_tag}"
    elif v_adx < 25.0:
        trend_strength = f"Emerging {direction} Trend {di_tag}"
    elif v_adx < 40.0:
        trend_strength = f"Moderate {direction} Trend {di_tag}"
    else:
        trend_strength = f"Strong {direction} Trend {di_tag}"

    # Prior bar lookup (either specified prev_date or immediately prior trading bar)
    prev_idx = None
    if prev_date:
        p_dt = pd.to_datetime(prev_date)
        prior_slice = sub[sub.index <= p_dt]
        if not prior_slice.empty:
            prev_idx = prior_slice.index[-1]
    
    if prev_idx is None and len(sub) >= 2:
        prev_idx = sub.index[-2]

    if prev_idx is not None and prev_idx in sub.index:
        prev_rsi = float(rsi_series.loc[prev_idx]) if not np.isnan(rsi_series.loc[prev_idx]) else v_rsi
        prev_macd = float(macd_line.loc[prev_idx]) if not np.isnan(macd_line.loc[prev_idx]) else v_macd
        prev_adx = float(adx_series.loc[prev_idx]) if not np.isnan(adx_series.loc[prev_idx]) else v_adx
    else:
        prev_rsi = v_rsi
        prev_macd = v_macd
        prev_adx = v_adx

    return TechnicalSnapshot(
        symbol=symbol,
        name=name,
        as_of_date=curr_idx.strftime("%Y-%m-%d"),
        price=curr_price,
        dma_20=v_sma20,
        dma_50=v_sma50,
        dma_200=v_sma200,
        price_vs_dma20_pct=p_vs_20,
        price_vs_dma50_pct=p_vs_50,
        price_vs_dma200_pct=p_vs_200,
        cross_50_200=cross_status,
        rsi=v_rsi,
        prev_rsi=prev_rsi,
        delta_rsi=v_rsi - prev_rsi,
        rsi_flag=rsi_flag,
        macd=v_macd,
        macd_signal=v_sig,
        macd_hist=v_hist,
        macd_status=macd_status,
        prev_macd=prev_macd,
        delta_macd=v_macd - prev_macd,
        adx=v_adx,
        plus_di=v_pdi,
        minus_di=v_mdi,
        prev_adx=prev_adx,
        delta_adx=v_adx - prev_adx,
        trend_strength=trend_strength,
    )
