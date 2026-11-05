"""Unit and integration tests for Section: Tactical Watchlist Panel (Task 3.2)."""

from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from data.calendar import MarketCalendar
from data.macro_base import EarningsEvent
from render.html import render_html
from render.markdown import render_markdown
from sections.base import SectionResult
from sections.sectors import SectorBreadthItem, SectorReportData
from sections.swing_regime import SwingGateData
from sections.watchlist import (
    DEFAULT_TICKER_NAME_MAP,
    DEFAULT_TICKER_SECTOR_MAP,
    WatchlistData,
    WatchlistItem,
    build_watchlist_section,
    compute_atr_14,
    load_watchlist_tickers,
    resolve_long_permitted,
)


@pytest.fixture
def sample_stock_df() -> pd.DataFrame:
    """Generate 100 business days of synthetic OHLCV data."""
    dates = pd.date_range("2026-06-01", "2026-10-30", freq="B")
    np.random.seed(101)
    base = 200.0
    changes = np.random.randn(len(dates)) * 1.5
    closes = base + np.cumsum(changes)
    highs = closes + np.random.uniform(0.5, 2.0, size=len(dates))
    lows = closes - np.random.uniform(0.5, 2.0, size=len(dates))
    opens = closes + np.random.uniform(-0.5, 0.5, size=len(dates))
    volumes = np.random.uniform(20_000_000, 50_000_000, size=len(dates))

    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


@pytest.fixture
def sample_spy_df(sample_stock_df) -> pd.DataFrame:
    """Generate SPY benchmark dataframe."""
    df = sample_stock_df.copy()
    # Smooth baseline SPY
    df["Close"] = 500.0 + np.linspace(0, 50, len(df))
    df["High"] = df["Close"] + 1.0
    df["Low"] = df["Close"] - 1.0
    df["Open"] = df["Close"]
    return df


def test_load_watchlist_tickers_various_formats(tmp_path: Path):
    """Test reading CSVs with headers, plain lines, comma-separated lists, and comments."""
    # 1. Header with 'ticker'
    f1 = tmp_path / "w1.csv"
    f1.write_text("ticker\nAAPL\nMSFT\nNVDA\n", encoding="utf-8")
    assert load_watchlist_tickers(f1) == ["AAPL", "MSFT", "NVDA"]

    # 2. Header with 'symbol' and quotes
    f2 = tmp_path / "w2.csv"
    f2.write_text('"symbol"\n"AMZN"\n"GOOGL"\n"META"\n', encoding="utf-8")
    assert load_watchlist_tickers(f2) == ["AMZN", "GOOGL", "META"]

    # 3. Plain lines, no header, spaces, comments, duplicate symbols
    f3 = tmp_path / "w3.csv"
    f3.write_text("AAPL\n# comment\n  tsla  \n\nNVDA\naapl\n", encoding="utf-8")
    assert load_watchlist_tickers(f3) == ["AAPL", "TSLA", "NVDA"]

    # 4. Comma-separated on single line
    f4 = tmp_path / "w4.csv"
    f4.write_text("AAPL, MSFT, NVDA, AMZN", encoding="utf-8")
    assert load_watchlist_tickers(f4) == ["AAPL", "MSFT", "NVDA", "AMZN"]


def test_missing_or_empty_watchlist_file_handling(tmp_path: Path):
    """Verify graceful handling when watchlist.csv is missing or empty."""
    # When fallback_to_default=False, unavailable status returned
    res_missing = build_watchlist_section(watchlist_path=tmp_path / "does_not_exist.csv", fallback_to_default=False)
    assert not res_missing.is_available
    assert res_missing.status == "unavailable"
    assert "not found or contains no valid tickers" in res_missing.error_message
    assert res_missing.data.total_count == 0

    f_empty = tmp_path / "empty.csv"
    f_empty.write_text("", encoding="utf-8")
    res_empty = build_watchlist_section(watchlist_path=f_empty, fallback_to_default=False)
    assert not res_empty.is_available
    assert res_empty.status == "unavailable"
    assert res_empty.data.total_count == 0

    # When fallback_to_default=True, falls back to default 15-ticker list
    res_fallback = build_watchlist_section(watchlist_path=tmp_path / "does_not_exist.csv", fallback_to_default=True)
    assert res_fallback.data.source_label == "Default list (edit watchlist.csv to use your own)"
    assert res_fallback.data.total_count == 15


def test_gate_posture_long_permitted_derivation():
    """Verify gate posture string mappings for model filter status."""
    # Defensive
    assert resolve_long_permitted("DEFENSIVE") == "INACTIVE (Gate Defensive)"
    assert resolve_long_permitted("Gate Defensive") == "INACTIVE (Gate Defensive)"

    # Cautious / Selective / Reduced
    assert resolve_long_permitted("CAUTIOUS") == "SELECTIVE (Conservative)"
    assert resolve_long_permitted("SELECTIVE") == "SELECTIVE (Conservative)"
    assert resolve_long_permitted("REDUCED") == "SELECTIVE (Conservative)"

    # Open / Full
    assert resolve_long_permitted("OPEN") == "ACTIVE (Favorable Trend)"
    assert resolve_long_permitted("FULL") == "ACTIVE (Favorable Trend)"

    # SwingGateData object
    sg = SwingGateData(
        as_of_date="2026-10-30",
        posture="DEFENSIVE",
        posture_badge_class="badge-red",
        triggered_rule="Dual 50-DMA break",
        spy_price=570.0,
        spy_20ema=575.0,
        spy_20ema_dist_pct=-0.8,
        spy_20ema_pass=False,
        spy_50dma=580.0,
        spy_50dma_dist_pct=-1.7,
        spy_50dma_pass=False,
        qqq_price=480.0,
        qqq_20ema=485.0,
        qqq_20ema_dist_pct=-1.0,
        qqq_20ema_pass=False,
        qqq_50dma=490.0,
        qqq_50dma_dist_pct=-2.0,
        qqq_50dma_pass=False,
        vix_level=24.5,
        vix_5d_trend=2.0,
        vix_term_structure="Contango",
        breadth_pct_above_50dma=38.0,
        breadth_ad_state="Negative",
        net_new_highs=-12,
        execution_guidance="Quantitative model criteria reflect defensive posture.",
    )
    assert resolve_long_permitted(sg) == "INACTIVE (Gate Defensive)"


def test_compute_atr_14(sample_stock_df):
    """Verify 14-day Average True Range calculation."""
    atr = compute_atr_14(sample_stock_df)
    assert atr is not None
    assert atr > 0.0

    # Test short dataframe
    short_df = sample_stock_df.head(5)
    atr_short = compute_atr_14(short_df)
    assert atr_short is not None
    assert atr_short > 0.0

    # Test empty dataframe
    assert compute_atr_14(pd.DataFrame()) is None


def test_build_watchlist_section_full(tmp_path: Path, sample_stock_df, sample_spy_df):
    """Verify end-to-end watchlist builder with price metrics, earnings, and sector breadth."""
    # Write sample watchlist
    w_file = tmp_path / "watchlist.csv"
    w_file.write_text("ticker\nAAPL\nMSFT\nNVDA\n", encoding="utf-8")

    # Mock calendar provider with scheduled earnings
    class MockCalendarProvider:
        _scheduled_earnings = [
            {"symbol": "AAPL", "date": "2026-11-02", "hour": "amc", "name": "Apple Inc."},
            {"symbol": "MSFT", "date": "2026-10-28", "hour": "amc", "name": "Microsoft Corporation"},
        ]

        def get_upcoming_earnings(self, start_date, end_date, symbols=None):
            return [
                EarningsEvent(symbol="AAPL", name="Apple Inc.", date="2026-11-02", hour="amc"),
            ]

    # Mock sector breadth data
    breadth_items = [
        SectorBreadthItem(sector="Information Technology", symbol="XLK", pct_above_50dma=68.5, pct_above_20dma=55.0, net_new_highs=15),
    ]

    equity_bars = {
        "AAPL": sample_stock_df,
        "MSFT": sample_stock_df,
        "NVDA": sample_stock_df,
    }

    res = build_watchlist_section(
        watchlist_path=w_file,
        bars={"SPY": sample_spy_df},
        equity_bars=equity_bars,
        calendar_provider=MockCalendarProvider(),
        gate_posture="DEFENSIVE",
        sector_breadth_data=breadth_items,
        as_of_date="2026-10-30",
    )

    assert res.is_available
    data: WatchlistData = res.data
    assert data.total_count == 3
    assert data.gate_posture == "DEFENSIVE"
    assert data.long_permitted_default == "INACTIVE (Gate Defensive)"
    assert data.blocked_count == 3

    # Check AAPL
    aapl_item = next(it for it in data.items if it.ticker == "AAPL")
    assert aapl_item.name == "Apple Inc."
    assert aapl_item.sector == "Information Technology"
    assert aapl_item.close > 0.0
    assert aapl_item.dist_20dma_pct is not None
    assert aapl_item.dist_50dma_pct is not None
    assert aapl_item.atr_pct is not None
    assert aapl_item.rs_vs_spy is not None
    assert aapl_item.next_earnings_date == "2026-11-02"
    assert "68.5% > 50-DMA" in aapl_item.sector_breadth_status
    assert aapl_item.long_permitted == "INACTIVE (Gate Defensive)"


def test_root_default_watchlist_csv():
    """Verify default watchlist.csv in workspace root exists and contains required tickers."""
    root_csv = Path("watchlist.csv")
    assert root_csv.is_file(), "Default watchlist.csv should exist in the workspace root."

    tickers = load_watchlist_tickers(root_csv)
    expected_subset = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "LLY", "AVGO", "JPM", "VRT", "NOW", "AMD", "NFLX", "COST"}
    assert expected_subset.issubset(set(tickers)), f"Missing expected tickers from watchlist.csv: {expected_subset - set(tickers)}"


def test_watchlist_rendering_markdown_and_html(sample_stock_df, sample_spy_df):
    """Verify that WatchlistData renders in markdown and HTML without KaTeX math errors or unescaped dollars."""
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", datetime.strptime("2026-10-30", "%Y-%m-%d").date())

    res = build_watchlist_section(
        watchlist_path="watchlist.csv",
        bars={"SPY": sample_spy_df},
        equity_bars={"AAPL": sample_stock_df, "NVDA": sample_stock_df},
        gate_posture="CAUTIOUS",
        as_of_date="2026-10-30",
    )
    assert res.is_available

    sections = [res]

    # Markdown rendering
    md = render_markdown(period=period, sections=sections)
    assert "Tactical Watchlist Panel" in md
    assert "Focus Candidates:" in md
    assert "SELECTIVE (Conservative)" in md

    # Check for unescaped dollar signs
    lines = md.split("\n")
    for i, line in enumerate(lines):
        cleaned = line.replace("\\$", "").replace("`$`", "")
        import re
        no_code = re.sub(r"`[^`]*`", "", cleaned)
        assert "$" not in no_code, f"Unescaped dollar sign found in line {i+1}: {line}"

    # HTML rendering
    html = render_html(period=period, sections=sections)
    assert "Tactical Focus Universe:" in html
    assert "SELECTIVE" in html
    assert "report-table" in html


def test_watchlist_sorted_by_rs_descending(tmp_path: Path, sample_stock_df, sample_spy_df):
    """Verify that watchlist constituents are ordered by 3M Relative Strength vs SPY descending."""
    w_file = tmp_path / "watchlist_order.csv"
    w_file.write_text("ticker\nAAPL\nMSFT\nNVDA\nAMZN\n", encoding="utf-8")

    # Create distinct price trajectories to produce differing RS vs SPY
    # SPY is +10%
    # NVDA: +30% (highest RS)
    df_nvda = sample_stock_df.copy()
    df_nvda["Close"] = np.linspace(100, 130, len(df_nvda))

    # AAPL: +15% (second highest RS)
    df_aapl = sample_stock_df.copy()
    df_aapl["Close"] = np.linspace(100, 115, len(df_aapl))

    # MSFT: -5% (third)
    df_msft = sample_stock_df.copy()
    df_msft["Close"] = np.linspace(100, 95, len(df_msft))

    # AMZN: no price history (None RS -> last)

    equity_bars = {
        "NVDA": df_nvda,
        "AAPL": df_aapl,
        "MSFT": df_msft,
    }

    res = build_watchlist_section(
        watchlist_path=w_file,
        bars={"SPY": sample_spy_df},
        equity_bars=equity_bars,
        gate_posture="DEFENSIVE",
        as_of_date="2026-10-30",
    )

    assert res.is_available
    items = res.data.items
    assert len(items) == 4

    # Assert exact ordering: NVDA (+30%) -> AAPL (+15%) -> MSFT (-5%) -> AMZN (None)
    assert items[0].ticker == "NVDA"
    assert items[1].ticker == "AAPL"
    assert items[2].ticker == "MSFT"
    assert items[3].ticker == "AMZN"

    # Verify rs_vs_spy sequence is strictly monotonic non-increasing
    valid_rs = [it.rs_vs_spy for it in items if it.rs_vs_spy is not None]
    assert valid_rs == sorted(valid_rs, reverse=True)
    assert items[3].rs_vs_spy is None

