"""Pytest shared test fixtures."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_trend_bars() -> pd.DataFrame:
    """Deterministic synthetic upward trending OHLCV DataFrame."""
    dates = pd.date_range(start="2026-01-01", periods=250, freq="B")
    np.random.seed(42)

    # Simulated geometric random walk with positive drift
    returns = 0.001 + 0.01 * np.random.randn(len(dates))
    prices = 100.0 * np.cumprod(1.0 + returns)

    highs = prices * (1.0 + 0.005 * np.random.rand(len(dates)))
    lows = prices * (1.0 - 0.005 * np.random.rand(len(dates)))
    opens = (highs + lows) / 2.0
    closes = prices
    volumes = np.random.randint(1000000, 5000000, size=len(dates))

    df = pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )
    return df


@pytest.fixture
def classic_rsi_series() -> pd.Series:
    """14-period classic textbook prices to test RSI calculations."""
    prices = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
        46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
        43.42, 42.66, 43.13,
    ]
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")
    return pd.Series(prices, index=dates)
