"""Unit tests for Stage 4 matplotlib chart generation and missing data resilience."""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from data.calendar import PeriodInfo
from render.charts import (
    generate_all_report_charts,
    generate_breadth_trend_chart,
    generate_index_technicals_chart,
    generate_movers_chart,
    generate_rates_curve_chart,
    generate_seasonality_heatmap,
    generate_sector_breadth_heatmap,
    generate_sector_performance_chart,
    generate_sector_timeframe_heatmap,
    generate_vix_chart,
)
from sections.movers import MoverItem
from sections.sectors import SectorPerformanceRow


@pytest.fixture
def sample_bars() -> pd.DataFrame:
    """Generate 150 trading sessions of synthetic price bars."""
    dates = pd.date_range(end="2026-10-22", periods=150, freq="B")
    prices = np.linspace(5000.0, 5800.0, 150)
    return pd.DataFrame(
        {
            "Open": prices - 5.0,
            "High": prices + 10.0,
            "Low": prices - 10.0,
            "Close": prices,
            "Volume": 10_000_000.0,
        },
        index=dates,
    )


def test_index_technicals_chart(sample_bars, tmp_path):
    """Test S&P 500 technical chart with 20/50/200 DMA."""
    out_file = tmp_path / "spx_test.png"
    chart = generate_index_technicals_chart(
        df=sample_bars,
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-22",
        lookback_bars=100,
        output_path=out_file,
    )

    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 1000
    assert "data:image/png;base64," in chart.data_uri


def test_sector_performance_chart(tmp_path):
    """Test horizontal sector performance chart with sorted green/red bars."""
    rows = [
        SectorPerformanceRow(symbol="XLK", name="Technology", close=220.0, pct_change=2.5, relative_strength_vs_spy=1.5, rank=1, prev_rank=2, rank_change=1, prev_period_change=1.0),
        SectorPerformanceRow(symbol="XLE", name="Energy", close=85.0, pct_change=-1.8, relative_strength_vs_spy=-2.8, rank=11, prev_rank=10, rank_change=-1, prev_period_change=0.5),
        SectorPerformanceRow(symbol="XLF", name="Financials", close=42.0, pct_change=0.5, relative_strength_vs_spy=-0.5, rank=5, prev_rank=5, rank_change=0, prev_period_change=0.2),
    ]

    out_file = tmp_path / "sectors_test.png"
    chart = generate_sector_performance_chart(
        sector_rows=rows,
        period_name="Daily",
        as_of_date="2026-10-22",
        output_path=out_file,
    )

    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 1000


def test_vix_chart(tmp_path):
    """Test VIX chart generation with risk thresholds."""
    dates = pd.date_range(end="2026-10-22", periods=60, freq="B")
    vix_df = pd.DataFrame({"Close": np.linspace(15.0, 22.0, 60)}, index=dates)

    out_file = tmp_path / "vix_test.png"
    chart = generate_vix_chart(
        vix_df=vix_df,
        as_of_date="2026-10-22",
        lookback_bars=50,
        output_path=out_file,
    )

    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 1000


def test_movers_chart(tmp_path):
    """Test top 5 gainers and bottom 5 losers bar chart."""
    gainers = [
        MoverItem(symbol="AAA", name="Alpha Corp", sector="Tech", pct_change=12.5, close=100.0, volume=2_000_000, avg_volume_20d=1_000_000, volume_ratio=2.0, market_cap=5_000_000_000),
        MoverItem(symbol="BBB", name="Beta Corp", sector="Health", pct_change=8.0, close=50.0, volume=1_500_000, avg_volume_20d=1_000_000, volume_ratio=1.5, market_cap=10_000_000_000),
    ]
    losers = [
        MoverItem(symbol="ZZZ", name="Zeta Corp", sector="Energy", pct_change=-14.0, close=20.0, volume=2_500_000, avg_volume_20d=1_000_000, volume_ratio=2.5, market_cap=8_000_000_000),
        MoverItem(symbol="YYY", name="Yankee Corp", sector="Retail", pct_change=-9.5, close=30.0, volume=1_800_000, avg_volume_20d=1_000_000, volume_ratio=1.8, market_cap=12_000_000_000),
    ]

    out_file = tmp_path / "movers_test.png"
    chart = generate_movers_chart(
        gainers=gainers,
        losers=losers,
        period_name="Daily",
        as_of_date="2026-10-22",
        output_path=out_file,
    )

    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 1000


def test_chart_missing_data_resilience():
    """Verify that all chart generators handle missing/empty data without throwing exceptions."""
    c_spx = generate_index_technicals_chart(None, "^GSPC", "S&P 500", "2026-10-22")
    assert c_spx.is_available is False
    assert "unavailable" in c_spx.error_message.lower()

    c_sec = generate_sector_performance_chart([], "Daily", "2026-10-22")
    assert c_sec.is_available is False

    c_br = generate_breadth_trend_chart({}, "2026-10-22")
    assert c_br.is_available is False

    c_vix = generate_vix_chart(None, "2026-10-22")
    assert c_vix.is_available is False

    c_rates = generate_rates_curve_chart(None, "2026-10-22")
    assert c_rates.is_available is False

    c_mov = generate_movers_chart([], [], "Daily", "2026-10-22")
    assert c_mov.is_available is False


def test_legend_entries_have_plotted_lines():
    """Verify that every legend entry in generated charts has a plotted line with valid data points."""
    import matplotlib.pyplot as plt

    # 350 trading days provides sufficient lookback for rolling 20, 50, and 200 DMAs
    dates = pd.date_range(end="2026-10-30", periods=350, freq="B")
    prices = np.linspace(4800.0, 5800.0, 350)
    df = pd.DataFrame(
        {
            "Open": prices - 5.0,
            "High": prices + 10.0,
            "Low": prices - 10.0,
            "Close": prices,
            "Volume": 10_000_000.0,
        },
        index=dates,
    )

    fig, ax = plt.subplots()
    sub = df.copy()
    close = sub["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    disp_sub = sub.tail(130)
    disp_idx = disp_sub.index

    ax.plot(disp_idx, close.loc[disp_idx], label="Price")
    ax.plot(disp_idx, sma20.loc[disp_idx], label="20 DMA")
    ax.plot(disp_idx, sma50.loc[disp_idx], label="50 DMA")
    ax.plot(disp_idx, sma200.loc[disp_idx], label="200 DMA")
    legend = ax.legend()

    # Assert that no legend entry has zero plotted points
    for text, handle in zip(legend.get_texts(), legend.legend_handles):
        assert isinstance(handle, plt.Line2D)
        y = np.array(handle.get_ydata())
        valid_pts = len(y[~np.isnan(y)])
        assert valid_pts >= 2, f"Legend entry '{text.get_text()}' has no plotted line ({valid_pts} points)"
    plt.close(fig)


def test_sector_timeframe_heatmap(tmp_path):
    """Test 11 SPDR Sector Multi-Horizon Heatmap generation."""
    dates = pd.date_range(end="2026-10-30", periods=100, freq="B")
    core_bars = {}
    for sym in ["XLE", "XLF", "XLU", "XLI", "XLB", "XLV", "XLP", "XLY", "XLRE", "XLK", "XLC"]:
        core_bars[sym] = pd.DataFrame({"Close": np.linspace(50.0, 60.0, 100)}, index=dates)

    out_file = tmp_path / "sec_hm.png"
    chart = generate_sector_timeframe_heatmap(
        core_bars=core_bars,
        sector_rows=[],
        as_of_date="2026-10-30",
        output_path=out_file,
    )
    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 500


def test_sector_breadth_heatmap(tmp_path):
    """Test Sector Breadth Participation Heatmap generation."""
    dates = pd.date_range(end="2026-10-30", periods=100, freq="B")
    equity_bars = {
        "AAPL": pd.DataFrame({"Close": np.linspace(150.0, 180.0, 100)}, index=dates),
        "MSFT": pd.DataFrame({"Close": np.linspace(300.0, 350.0, 100)}, index=dates),
        "XOM": pd.DataFrame({"Close": np.linspace(100.0, 110.0, 100)}, index=dates),
        "JPM": pd.DataFrame({"Close": np.linspace(140.0, 160.0, 100)}, index=dates),
    }

    out_file = tmp_path / "breadth_hm.png"
    chart = generate_sector_breadth_heatmap(
        equity_bars=equity_bars,
        as_of_date="2026-10-30",
        output_path=out_file,
    )
    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 500


def test_seasonality_heatmap(tmp_path):
    """Test S&P 500 Seasonality Heatmap generation."""
    dates = pd.date_range(end="2026-10-30", periods=300, freq="B")
    spx_df = pd.DataFrame({"Close": np.linspace(4000.0, 5800.0, 300)}, index=dates)

    out_file = tmp_path / "seas_hm.png"
    chart = generate_seasonality_heatmap(
        spx_df=spx_df,
        as_of_date="2026-10-30",
        lookback_years=5,
        output_path=out_file,
    )
    assert chart.is_available is True
    assert out_file.exists()
    assert len(chart.base64_data) > 500

