"""Unit and acceptance tests for Stage 3 New Modules."""

from datetime import datetime
import numpy as np
import pandas as pd
import pytest

from config.settings import AppConfig, load_config
from data.calendar import MarketCalendar
from data.macro_base import MacroEvent
from render.html import render_html
from render.markdown import render_markdown
from sections.commodities_cross_asset import build_commodities_cross_asset, CommoditiesCrossAssetData
from sections.earnings import build_earnings_layer, EarningsLayerData
from sections.fed_path import build_fed_path, FedPathData
from sections.forward_calendar import build_forward_calendar, ForwardCalendarData
from sections.movers import MoverItem, PeriodMovers, TopMoversData
from sections.sentiment_positioning import build_sentiment_positioning, SentimentPositioningData
from sections.swing_regime import evaluate_swing_gate, SwingGateData
from sections.theme_relative_strength import build_theme_relative_strength, ThemeRelativeStrengthData
from sections.what_changed import build_what_changed, WhatChangedData


@pytest.fixture
def sample_config() -> AppConfig:
    return load_config()


@pytest.fixture
def sample_price_df() -> pd.DataFrame:
    """Generate 100 days of price history."""
    dates = pd.date_range("2026-06-01", "2026-10-30", freq="B")
    np.random.seed(42)
    closes = 500.0 + np.cumsum(np.random.randn(len(dates)) * 2.0)
    return pd.DataFrame(
        {
            "Open": closes - 1.0,
            "High": closes + 2.0,
            "Low": closes - 2.0,
            "Close": closes,
            "Volume": 50000000.0,
        },
        index=dates,
    )


def test_swing_gate_posture_logic(sample_price_df, sample_config):
    """Test Apex market gate parity and 4-tier posture derivation."""
    as_of = "2026-10-30"

    # 1. Test DEFENSIVE: both below 50-DMA
    # Create copies where close is below 50 DMA
    df_def = sample_price_df.copy()
    ma50 = df_def["Close"].rolling(50).mean().iloc[-1]
    df_def.iloc[-1, df_def.columns.get_loc("Close")] = ma50 * 0.95

    res_def = evaluate_swing_gate(
        spy_df=df_def,
        qqq_df=df_def,
        vix_current=24.0,
        vix_previous=22.0,
        vix_term_ratio=1.05,
        breadth_result=None,
        as_of_date=as_of,
        cfg=sample_config,
    )
    assert res_def.is_available
    data: SwingGateData = res_def.data
    assert data.posture == "DEFENSIVE"
    assert "Gate Rule 4 (Defensive)" in data.triggered_rule
    assert data.posture_badge_class == "badge-red"
    assert not data.spy_50dma_pass
    assert not data.qqq_50dma_pass

    # 2. Test SELECTIVE: one below 50-DMA, one above
    df_bull = sample_price_df.copy()
    df_bull.iloc[-1, df_bull.columns.get_loc("Close")] = ma50 * 1.05

    res_sel = evaluate_swing_gate(
        spy_df=df_bull,
        qqq_df=df_def,
        vix_current=20.0,
        vix_previous=19.0,
        vix_term_ratio=0.95,
        breadth_result=None,
        as_of_date=as_of,
        cfg=sample_config,
    )
    assert res_sel.data.posture == "SELECTIVE"
    assert "Gate Rule 3 (Selective)" in res_sel.data.triggered_rule
    assert res_sel.data.posture_badge_class == "badge-yellow"

    # 3. Test FULL: both above 20-EMA & 50-DMA, VIX < 19.5
    # Force last bar high above both
    df_full = sample_price_df.copy()
    c_last = float(df_full["Close"].max() * 1.10)
    df_full.iloc[-1, df_full.columns.get_loc("Close")] = c_last

    class DummyBreadth:
        pct_above_50_dma = type("Obj", (), {"current": 65.0})()
        ad_confirmation = "Positive Confirmation"
        net_new_highs = 45

    res_full = evaluate_swing_gate(
        spy_df=df_full,
        qqq_df=df_full,
        vix_current=16.5,
        vix_previous=17.0,
        vix_term_ratio=0.90,
        breadth_result=DummyBreadth(),
        as_of_date=as_of,
        cfg=sample_config,
    )
    assert res_full.data.posture == "FULL"
    assert "Gate Rule 1 (Full)" in res_full.data.triggered_rule
    assert res_full.data.posture_badge_class == "badge-green"


def test_forward_calendar_strict_future_filtering(sample_config):
    """Ensure no on-period or past releases ever appear in the forward calendar."""
    as_of = "2026-10-30"

    class MockProvider:
        def get_upcoming_events(self, start_date, end_date, min_importance="medium"):
            return [
                MacroEvent(title="Past Event", date="2026-10-28", time_et="14:00", importance="high"),
                MacroEvent(title="Same Day Event", date="2026-10-30", time_et="08:30", importance="high"),
                MacroEvent(title="US Midterm Elections", date="2026-11-03", time_et="All Day", importance="high"),
                MacroEvent(title="ISM Services PMI", date="2026-11-04", time_et="10:00", importance="medium"),
            ]

    res = build_forward_calendar(
        calendar_provider=MockProvider(),
        as_of_date=as_of,
        cfg=sample_config,
        lookahead_days=10,
    )
    assert res.is_available
    data: ForwardCalendarData = res.data
    # Past and same day must be strictly excluded
    for ev in data.events:
        assert ev.date > as_of
    assert len(data.events) == 2
    assert data.events[0].title == "US Midterm Elections"
    assert data.events[1].title == "ISM Services PMI"


def test_realized_volatility_and_risk_premium(sample_price_df, sample_config):
    """Verify 20-day realized volatility and VRP calculation."""
    as_of = "2026-10-30"
    vix = 19.42

    res = build_sentiment_positioning(
        spx_df=sample_price_df,
        vix_current=vix,
        as_of_date=as_of,
        cfg=sample_config,
    )
    assert res.is_available
    data: SentimentPositioningData = res.data
    assert data.vix == vix
    assert data.realized_vol_20d > 0.0
    assert abs(data.vol_risk_premium - (vix - data.realized_vol_20d)) < 1e-4
    assert data.put_call_status == "n/a (source unavailable)"
    assert "n/a (source unavailable" in data.fund_flows_status


def test_fed_path_builder_and_invariants(sample_config):
    """Verify Fed path metrics, countdown, and real policy rate."""
    as_of = "2026-10-30"
    res = build_fed_path(macro_data=None, as_of_date=as_of, cfg=sample_config)
    assert res.is_available
    data: FedPathData = res.data
    assert data.last_action_date == "2026-10-28"
    assert "Maintained" in data.last_action_description or "Hold" in data.last_action_description
    assert data.days_to_next_meeting > 0
    assert data.effective_fed_funds > 0
    assert data.real_policy_rate != 0


def test_theme_relative_strength_missing_ticker_resilience(sample_config):
    """Test that missing theme ETFs are handled gracefully as unavailable without crashing."""
    as_of = "2026-10-30"
    # Provide empty bars dict
    res = build_theme_relative_strength(bars={}, as_of_date=as_of, cfg=sample_config)
    assert res.is_available
    data: ThemeRelativeStrengthData = res.data
    assert len(data.items) > 0
    # All items should be marked unavailable
    for it in data.items:
        assert not it.is_available


def test_commodities_cross_asset_energy_shock(sample_config):
    """Test cross asset tracker and energy shock detection."""
    as_of = "2026-10-30"
    res = build_commodities_cross_asset(
        bars={},
        as_of_date=as_of,
        baseline_date="2026-10-23",
        prev_baseline_date="2026-10-16",
        macro_data=None,
        cfg=sample_config,
    )
    assert res.is_available
    data: CommoditiesCrossAssetData = res.data
    assert len(data.items) == 9
    assert data.energy_shock is not None
    assert isinstance(data.energy_shock.is_shock_active, bool)


def test_what_changed_top_5_deltas():
    """Verify what changed section builds strictly 5 deltas and synthesizes single biggest risk."""
    res = build_what_changed(
        scorecard=None,
        prior_scorecard=None,
        macro_data=None,
        breadth_res=None,
        sector_rotation=None,
        spx_snap=None,
        ndx_snap=None,
        as_of_date="2026-10-30",
    )
    assert res.is_available
    data: WhatChangedData = res.data
    assert len(data.deltas) <= 5
    assert len(data.single_biggest_risk) > 20


def test_render_markdown_and_html_stage3_integration(sample_config, sample_price_df):
    """Verify renderers process all Stage 3 sections without errors or unescaped dollar signs."""
    as_of = "2026-10-30"
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", pd.to_datetime(as_of).date())

    sec_what = build_what_changed(None, None, None, None, None, None, None, as_of)
    sec_swing = evaluate_swing_gate(sample_price_df, sample_price_df, 19.42, 19.0, 0.95, None, as_of, sample_config)
    sec_theme = build_theme_relative_strength({}, as_of, sample_config)
    sec_comm = build_commodities_cross_asset({}, as_of, "2026-10-23", "2026-10-16", None, sample_config)
    sec_fed = build_fed_path(None, as_of, sample_config)
    sec_cal = build_forward_calendar(None, as_of, sample_config)
    sec_earn = build_earnings_layer(None, [], {}, as_of, sample_config)
    sec_sent = build_sentiment_positioning(sample_price_df, 19.42, as_of, sample_config)

    # Movers with Stage 3 fields
    m_item = MoverItem(
        symbol="NVDA",
        name="NVIDIA Corporation",
        sector="Information Technology",
        pct_change=12.5,
        close=185.50,
        volume=60000000.0,
        avg_volume_20d=45000000.0,
        volume_ratio=1.33,
        market_cap=4.5e12,
        has_earnings_in_window=True,
        move_cause_tag="Earnings / Guidance",
        market_cap_str="\\$4.50T",
    )
    pm = PeriodMovers("Weekly", [m_item], [m_item], theme_summary="Semiconductor momentum outperforming software.")
    sec_mov = type("SecResult", (), {
        "section_num": 13,
        "title": "Top Movers",
        "is_available": True,
        "data": TopMoversData(day=pm, week=pm, month=pm),
    })()

    sections = [sec_what, sec_swing, sec_theme, sec_comm, sec_fed, sec_cal, sec_earn, sec_sent, sec_mov]
    for idx, s in enumerate(sections, start=1):
        s.section_num = idx

    # Render Markdown
    md = render_markdown(period=period, sections=sections)
    assert "Executive Delta Tracking" in md
    assert "Swing-Trade Exposure Gate" in md
    assert "Theme / Industry ETF" in md
    assert "Cross-Asset Multi-Market Snapshot" in md
    assert "Federal Reserve Monetary Stance" in md
    assert "S&P 500 Earnings Season Progress" in md
    assert "Movers by Theme:" in md
    assert "Volatility Risk Premium" in md

    # Check that literal dollar signs are escaped as \$ or in backticks
    # Find all unescaped dollars in prose/tables
    lines = md.split("\n")
    for i, line in enumerate(lines):
        # Strip escaped dollars and code spans
        cleaned = line.replace("\\$", "").replace("`$`", "")
        # Remove markdown inline code spans `...`
        import re
        no_code = re.sub(r"`[^`]*`", "", cleaned)
        assert "$" not in no_code, f"Unescaped dollar sign found in markdown line {i+1}: {line}"

    # Render HTML
    html = render_html(period=period, sections=sections)
    assert "SWING EXPOSURE POSTURE" in html
    assert "Single Biggest Forward Risk" in html
    assert "VOLATILITY RISK PREMIUM" in html
    assert "Movers by Theme:" in html
    assert "Theme / Industry ETF" in html
