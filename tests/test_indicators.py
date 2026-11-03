"""Unit tests for technical indicators with spot checks against standard benchmarks."""

import numpy as np
import pandas as pd
import pytest

from indicators.engine import compute_technicals
from indicators.momentum import compute_rsi
from indicators.moving_averages import check_dma_cross, compute_sma
from indicators.trend import compute_adx, compute_macd


def test_sma_calculation():
    series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    sma3 = compute_sma(series, window=3)
    assert np.isnan(sma3.iloc[0])
    assert np.isnan(sma3.iloc[1])
    assert sma3.iloc[2] == pytest.approx(20.0)
    assert sma3.iloc[3] == pytest.approx(30.0)
    assert sma3.iloc[4] == pytest.approx(40.0)


def test_dma_cross_detection():
    # Golden cross scenario: fast crossed above slow
    fast = pd.Series([98.0, 99.0, 100.0, 102.0, 105.0])
    slow = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0])
    status = check_dma_cross(fast, slow, lookback_bars=3)
    assert "Golden Cross" in status or "Bullish" in status

    # Death cross scenario
    fast_d = pd.Series([105.0, 102.0, 100.0, 98.0, 95.0])
    slow_d = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0])
    status_d = check_dma_cross(fast_d, slow_d, lookback_bars=3)
    assert "Death Cross" in status_d or "Bearish" in status_d


def test_rsi_wilder_precision(classic_rsi_series):
    """Spot-check RSI values against classic Wilder reference values."""
    rsi = compute_rsi(classic_rsi_series, period=14)
    valid_rsi = rsi.dropna()

    # Wilder's 14th day (index 14) test textbook value: ~70.5
    val_14 = valid_rsi.iloc[0]
    assert 68.0 <= val_14 <= 72.0

    # All values must strictly reside in [0, 100]
    assert (valid_rsi >= 0.0).all()
    assert (valid_rsi <= 100.0).all()


def test_macd_calculation(sample_trend_bars):
    close = sample_trend_bars["Close"]
    macd, signal, hist = compute_macd(close, fast=12, slow=26, signal=9)

    # Output lengths must match input
    assert len(macd) == len(close)
    assert len(signal) == len(close)
    assert len(hist) == len(close)

    # Histogram equals macd - signal
    np.testing.assert_allclose(hist.values, (macd - signal).values, rtol=1e-5)


def test_adx_bounds_and_validity(sample_trend_bars):
    high = sample_trend_bars["High"]
    low = sample_trend_bars["Low"]
    close = sample_trend_bars["Close"]

    adx, plus_di, minus_di = compute_adx(high, low, close, period=14)

    valid_adx = adx.dropna()
    assert len(valid_adx) > 0
    # ADX is bounded between 0 and 100
    assert (valid_adx >= 0.0).all()
    assert (valid_adx <= 100.0).all()
    assert (plus_di.dropna() >= 0.0).all()
    assert (minus_di.dropna() >= 0.0).all()


def test_no_lookahead_bias(sample_trend_bars):
    """Ensure technicals computed at time T are identical whether future bars T+1 exist or not."""
    t_date = "2026-06-01"
    snap_full = compute_technicals(
        df=sample_trend_bars,
        symbol="TEST",
        name="Test Asset",
        as_of_date=t_date,
    )

    # Truncate bars strictly to t_date
    sub_bars = sample_trend_bars[sample_trend_bars.index <= pd.to_datetime(t_date)]
    snap_truncated = compute_technicals(
        df=sub_bars,
        symbol="TEST",
        name="Test Asset",
        as_of_date=t_date,
    )

    assert snap_full is not None
    assert snap_truncated is not None
    assert snap_full.price == pytest.approx(snap_truncated.price)
    assert snap_full.dma_20 == pytest.approx(snap_truncated.dma_20)
    assert snap_full.dma_50 == pytest.approx(snap_truncated.dma_50)
    assert snap_full.rsi == pytest.approx(snap_truncated.rsi)
    assert snap_full.macd == pytest.approx(snap_truncated.macd)
    assert snap_full.adx == pytest.approx(snap_truncated.adx)
