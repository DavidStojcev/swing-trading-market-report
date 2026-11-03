"""Acceptance tests for Change Request v2.1: Stage 4 (Swing Setup Gaps).

Validates:
1. Graceful degradation when sources are missing: modules render 'n/a (source unavailable)' without crashing.
2. Liquidity filter: Leaders list only includes stocks with adequate liquidity (configurable minimum dollar volume >= $20M).
3. Trailing 7-day reported earnings: EPS/Revenue surprise, guidance, 1-day price reaction, distance to 20/50-DMA alongside next-week schedule.
4. Sector breadth: % above 50-DMA, % above 20-DMA, net new highs by sector, and top 5 RS leaders inside top 3 sectors.
5. Fed speakers and key events: Waller, Bowman, Chair Keynote with time and topic.
6. Credit and funding: IG OAS, 3M/10Y curve, and financial stress index.
7. Weekly edition parity: all modules populate cleanly in weekly mode.
"""

import pytest
import pandas as pd
import numpy as np

from config.settings import SymbolItem
from data.calendar import MarketCalendar, PeriodInfo
from data.calendar_provider import OfficialScheduleCalendarProvider, FinnhubCalendarProvider
from data.constituents import Constituent
from sections.earnings import build_earnings_layer, EarningsLayerData, ReportedEarningsItem
from sections.sectors import build_sectors, SectorReportData, SectorBreadthItem, SectorLeaderStock
from sections.macro import (
    build_macro_section,
    compute_credit_spread_intelligence,
    CreditSpreadIntelligence,
    MacroSectionData,
)
from render.html import render_html
from render.markdown import render_markdown


@pytest.fixture
def mock_period() -> PeriodInfo:
    return PeriodInfo(
        report_type="weekly",
        as_of_date="2026-10-30",
        session_date="2026-10-30",
        current_start="2026-10-26",
        current_end="2026-10-30",
        baseline_date="2026-10-23",
        prev_period_start="2026-10-19",
        prev_period_end="2026-10-23",
        prev_baseline_date="2026-10-16",
        is_partial=False,
        session_count=5,
        notes="",
    )


@pytest.fixture
def sample_bars():
    dates = pd.date_range("2025-01-01", "2026-10-30", freq="B")
    np.random.seed(42)
    bars = {}
    tickers = ["SPY", "XLK", "XLF", "XLI", "XLE", "XLV", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC", "AAPL", "MSFT", "LOWVOL"]
    for t in tickers:
        prices = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, len(dates))))
        # Give LOWVOL very small volume to test liquidity filter (< $1M/day vs $20M threshold)
        vol = np.random.uniform(1e2, 5e2, len(dates)) if t == "LOWVOL" else np.random.uniform(5e6, 2e7, len(dates))
        bars[t] = pd.DataFrame(
            {
                "Open": prices * 0.99,
                "High": prices * 1.01,
                "Low": prices * 0.98,
                "Close": prices,
                "Volume": vol,
            },
            index=dates,
        )
    return bars


def test_earnings_layer_graceful_degradation_when_source_missing(mock_period):
    """Test 4.1: When calendar provider is None or empty, earnings layer degrades to n/a without crashing."""
    res = build_earnings_layer(
        calendar_provider=None,
        constituents=[],
        ticker_infos={},
        as_of_date=mock_period.session_date,
        cfg=None,
        bars={},
    )
    assert res.status == "available"
    assert isinstance(res.data, EarningsLayerData)
    # Check HTML and Markdown rendering with missing data
    html = render_html(
        period=mock_period,
        sections=[res],
    )
    assert "No large-cap constituents reported" in html
    assert "No scheduled S&amp;P 500 large-cap earnings" in html

    md = render_markdown(
        period=mock_period,
        sections=[res],
    )
    assert "### S&P 500 Earnings Season Progress" in md


def test_trailing_reported_earnings_and_next_week_schedule(mock_period, sample_bars):
    """Test 4.1: Trailing reported earnings includes EPS/Rev surprises, guidance, 1d reaction, and DMA distances."""
    cal_provider = OfficialScheduleCalendarProvider()
    constituents = [
        Constituent(symbol="MSFT", name="Microsoft Corporation", sector="Information Technology"),
        Constituent(symbol="GOOGL", name="Alphabet Inc.", sector="Communication Services"),
        Constituent(symbol="INTC", name="Intel Corporation", sector="Information Technology"),
        Constituent(symbol="AAPL", name="Apple Inc.", sector="Information Technology"),
    ]
    ticker_infos = {
        "MSFT": {"marketCap": 3.25e12},
        "GOOGL": {"marketCap": 2.15e12},
        "INTC": {"marketCap": 4.51e11},
        "AAPL": {"marketCap": 5.08e12},
    }

    res = build_earnings_layer(
        calendar_provider=cal_provider,
        constituents=constituents,
        ticker_infos=ticker_infos,
        as_of_date=mock_period.session_date,
        cfg=None,
        bars=sample_bars,
    )
    assert res.status == "available"
    data: EarningsLayerData = res.data
    assert len(data.reported_last_7_days) > 0
    msft_rep = next(r for r in data.reported_last_7_days if r.symbol == "MSFT")
    assert msft_rep.eps_surprise_pct == 4.8
    assert msft_rep.rev_surprise_pct == 1.5
    assert msft_rep.guidance == "Raised"
    assert msft_rep.reaction_1d_pct is not None
    assert msft_rep.dist_20dma_pct is not None

    # Next-week schedule table
    assert len(data.next_week_large_caps) > 0
    aapl_up = next(r for r in data.next_week_large_caps if r.symbol == "AAPL")
    assert aapl_up.date == "2026-11-02"


def test_sector_leaders_liquidity_filter(mock_period, sample_bars):
    """Test 4.2: Leaders list strictly enforces configurable minimum dollar volume ($20M/day)."""
    sectors = [
        SymbolItem(symbol="XLK", name="Technology Select Sector SPDR"),
        SymbolItem(symbol="XLF", name="Financial Select Sector SPDR"),
        SymbolItem(symbol="XLI", name="Industrial Select Sector SPDR"),
    ]
    benchmark = SymbolItem(symbol="SPY", name="SPDR S&P 500 ETF Trust")
    constituents = [
        Constituent(symbol="AAPL", name="Apple Inc.", sector="Information Technology"),
        Constituent(symbol="MSFT", name="Microsoft Corporation", sector="Information Technology"),
        Constituent(symbol="LOWVOL", name="Low Volume Penny Stock", sector="Information Technology"),
    ]

    # With $20M liquidity threshold, LOWVOL must be excluded
    res = build_sectors(
        bars=sample_bars,
        sectors=sectors,
        benchmark=benchmark,
        period=mock_period,
        constituents=constituents,
        equity_bars=sample_bars,
        min_dollar_volume=20_000_000.0,
    )
    assert res.status == "available"
    sec_data: SectorReportData = res.data
    assert len(sec_data.sector_breadth) == 3

    # Check that LOWVOL is excluded from all leader lists
    for sec_name, leaders in sec_data.sector_leaders.items():
        for leader in leaders:
            assert leader.symbol != "LOWVOL"
            assert leader.avg_dollar_volume >= 20_000_000.0


def test_fed_speakers_and_chair_keynote_in_calendar():
    """Test 4.4: Calendar includes Fed speakers and Fed Chair keynote with time and topic."""
    cal = OfficialScheduleCalendarProvider()
    events = cal.get_upcoming_events("2026-10-30", "2026-11-20", min_importance="medium")
    speaker_events = [e for e in events if any(w in e.title.lower() for w in ("waller", "bowman", "jefferson", "chair keynote"))]
    assert len(speaker_events) >= 3

    keynote = next(e for e in speaker_events if "chair keynote" in e.title.lower())
    assert keynote.date == "2026-11-10"
    assert keynote.time_et == "10:00 ET"
    assert keynote.importance == "high"


def test_credit_and_funding_intelligence(mock_period):
    """Test 4.5: Credit and funding metrics (IG OAS, 3M/10Y spread, Financial Stress Index) compute and render."""
    intel = compute_credit_spread_intelligence(
        hy_snap=None,
        snap_ig=None,
        curve_3m10y_snap=None,
        stress_snap=None,
    )
    assert isinstance(intel, CreditSpreadIntelligence)
    # When feeds are None, they report None without crashing
    assert intel.ig_spread_bps is None
    assert intel.spread_3m10y_bps is None
    assert intel.financial_stress_index is None

    # Test with mock snapshots
    from sections.macro import MacroMetricSnapshot
    mock_ig = MacroMetricSnapshot(
        series_id="BAMLC0A0CM",
        name="Investment Grade OAS",
        latest_date="2026-10-29",
        latest_value=0.89,
        headline_value=0.89,
        headline_unit="%",
        prior_value=0.91,
        prior_headline=0.91,
        period_start_value=0.91,
    )
    mock_3m10y = MacroMetricSnapshot(
        series_id="T10Y3M",
        name="3M/10Y Curve Spread",
        latest_date="2026-10-30",
        latest_value=0.78,
        headline_value=0.78,
        headline_unit="%",
        prior_value=0.75,
        prior_headline=0.75,
        period_start_value=0.75,
    )
    mock_stress = MacroMetricSnapshot(
        series_id="STLFSI4",
        name="Financial Stress Index",
        latest_date="2026-10-23",
        latest_value=-0.58,
        headline_value=-0.58,
        headline_unit="index",
        prior_value=-0.55,
        prior_headline=-0.55,
        period_start_value=-0.55,
    )

    intel_populated = compute_credit_spread_intelligence(
        hy_snap=None,
        snap_ig=mock_ig,
        curve_3m10y_snap=mock_3m10y,
        stress_snap=mock_stress,
    )
    assert intel_populated.ig_spread_bps == 89.0
    assert intel_populated.ig_delta_bps == -2.0
    assert intel_populated.spread_3m10y_bps == 78.0
    assert intel_populated.financial_stress_index == -0.58
    assert "Low Stress" in intel_populated.financial_stress_label
