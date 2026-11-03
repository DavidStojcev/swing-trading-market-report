"""Unit and integration tests for Stage 4: Presentation & UI/UX enhancements.

Validates:
1. Theme-adaptive inline SVG vector chart export with CSS variable replacement.
2. Sticky navigation bar with interactive "Jump to section..." select menu.
3. Top 10 numbers executive ticker strip with responsive micro-KPI pills.
4. Collapsible <details>/<summary> methodology notes for scoring and risk regimes.
5. 100% self-contained output with zero external network requests and < 1.5 MB size budget.
"""

from pathlib import Path
import re
import pytest
import pandas as pd
import numpy as np

from data.calendar import MarketCalendar
from render.charts import (
    generate_index_technicals_chart,
    generate_sector_performance_chart,
    generate_breadth_trend_chart,
    generate_vix_chart,
    generate_movers_chart,
    GeneratedChart,
)
from render.html import render_html, _render_chart_html, _render_top10_ticker_strip
from sections.base import SectionResult
from sections.executive_summary import ExecutiveSummaryData
from sections.swing_regime import evaluate_swing_gate, SwingGateData
from sections.index_snapshot import IndexSnapshotData, IndexSnapshotRow
from sections.volatility import VolatilityData
from sections.breadth import BreadthSectionData
from sections.sentiment_positioning import build_sentiment_positioning, SentimentPositioningData
from sections.commodities_cross_asset import build_commodities_cross_asset, CommoditiesCrossAssetData
from sections.movers import TopMoversData, PeriodMovers, MoverItem
from sections.sectors import SectorPerformanceRow
from config import load_config, AppConfig


@pytest.fixture
def sample_config() -> AppConfig:
    return load_config()


@pytest.fixture
def mock_price_df():
    """Create sample OHLCV DataFrame for technical charts."""
    dates = pd.date_range("2026-01-01", "2026-10-30", freq="B")
    np.random.seed(42)
    base = 5000.0
    returns = np.random.normal(0.0005, 0.01, size=len(dates))
    prices = base * np.exp(np.cumsum(returns))
    df = pd.DataFrame(
        {
            "Open": prices * 0.998,
            "High": prices * 1.005,
            "Low": prices * 0.995,
            "Close": prices,
            "Volume": np.random.uniform(3e7, 6e7, size=len(dates)),
        },
        index=dates,
    )
    return df


def test_charts_generate_inline_svg_with_theme_tokens(mock_price_df):
    """Verify matplotlib charts export clean inline SVG with CSS custom properties."""
    c = generate_index_technicals_chart(
        df=mock_price_df,
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-30",
        lookback_bars=100,
    )

    assert c.is_available is True
    assert c.svg_content != ""
    assert c.svg_content.startswith("<svg")
    assert "</svg>" in c.svg_content
    # Matplotlib clean SVG should replace neutral slate with CSS variables
    assert "var(--text-main)" in c.svg_content or "var(--text-muted)" in c.svg_content
    assert "var(--border)" in c.svg_content
    # Background should not contain hardcoded dark card background
    assert "#131b2e" not in c.svg_content


def test_html_renders_inline_svg_charts():
    """Verify _render_chart_html renders SVG directly into HTML."""
    chart = GeneratedChart(
        key="test_chart",
        title="Test Vector Chart",
        caption="Caption explaining test chart.",
        svg_content='<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="var(--text-main)"/></svg>',
        base64_data="dummy_b64",
    )
    rendered = _render_chart_html(chart)
    assert '<div class="chart-svg-wrapper"' in rendered
    assert '<svg viewBox="0 0 100 100">' in rendered
    assert '<img' not in rendered


def test_sticky_navigation_and_jump_menu():
    """Verify sticky navigation bar renders with brand, jump select, and top anchor."""
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", pd.to_datetime("2026-10-30").date())

    sec1 = SectionResult(section_num=1, title="Executive Summary & Macro Verdict", status="available", data=None)
    sec2 = SectionResult(section_num=2, title="What Changed", status="available", data=None)
    sec3 = SectionResult(section_num=3, title="Swing-Trade Regime Gate", status="available", data=None)
    sections = [sec1, sec2, sec3]

    html = render_html(period=period, sections=sections)

    assert '<div class="sticky-nav-bar" id="report-nav">' in html
    assert 'US Market Briefing &bull; 2026-10-30' in html
    assert '<select id="jump-select"' in html
    assert '<option value="#section-1">1. Executive Summary & Macro Verdict</option>' in html
    assert '<option value="#section-2">2. What Changed</option>' in html
    assert '<option value="#section-3">3. Swing-Trade Regime Gate</option>' in html
    assert 'href="#top"' in html
    assert 'id="top"' in html


def test_top10_ticker_strip_rendering(mock_price_df):
    """Verify executive top 10 numbers ticker strip renders all core metrics."""
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", pd.to_datetime("2026-10-30").date())

    # Build representative sections
    rows = [
        IndexSnapshotRow("^GSPC", "S&P 500", 5864.67, 0.25, 5e7, 4e7, 1.25, "1.25x", 0.10, 0.15),
        IndexSnapshotRow("^NDX", "Nasdaq-100", 20387.25, 0.41, 6e7, 5e7, 1.20, "1.20x", -0.20, 0.61),
    ]
    sec_snap = SectionResult(section_num=7, title="Benchmark Index Snapshot", status="available", data=IndexSnapshotData(rows=rows))
    sec_exec = SectionResult(
        section_num=1,
        title="Executive Summary",
        status="available",
        data=ExecutiveSummaryData(
            verdict="Constructive",
            normalized_score=0.22,
            raw_score=2.2,
            max_score=10.0,
            reasons=["Strong market breadth across sectors"],
            report_type="weekly",
            as_of_date="2026-10-30",
            session_date="2026-10-30",
            is_partial=False,
            notes="",
        ),
    )
    sec_vix = SectionResult(section_num=12, title="Volatility Regime", status="available", data=VolatilityData(symbol="^VIX", name="CBOE Volatility Index", current_level=19.42, prev_level=18.92, change=0.50, pct_change=2.64, implied_daily_move_pct=1.21, period_low=18.5, period_high=20.1, regime="Cautious", regime_description="Elevated tension"))

    sections = [sec_exec, sec_snap, sec_vix]
    html = render_html(period=period, sections=sections)

    assert '<div class="top10-ticker-strip">' in html
    assert 'S&P 500' in html
    assert '5,864.67' in html
    assert '+0.25%' in html
    assert 'Nasdaq-100' in html
    assert '20,387.25' in html
    assert 'CBOE VIX' in html
    assert '19.42' in html
    assert 'Macro Score' in html
    assert '+0.22' in html


def test_collapsible_methodology_notes(mock_price_df, sample_config):
    """Verify collapsible <details>/<summary> methodology notes appear in key sections."""
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", pd.to_datetime("2026-10-30").date())

    sec_exec = SectionResult(
        section_num=1,
        title="Executive Summary",
        status="available",
        data=ExecutiveSummaryData(
            verdict="Neutral",
            normalized_score=0.05,
            raw_score=0.5,
            max_score=10.0,
            reasons=["Holding 50-DMA"],
            report_type="weekly",
            as_of_date="2026-10-30",
            session_date="2026-10-30",
            is_partial=False,
            notes="",
        ),
    )
    sec_swing = evaluate_swing_gate(mock_price_df, mock_price_df, 19.42, 19.0, 0.95, None, "2026-10-30", sample_config)
    sec_vix = SectionResult(section_num=12, title="Volatility Regime", status="available", data=VolatilityData(symbol="^VIX", name="CBOE Volatility Index", current_level=19.42, prev_level=18.92, change=0.50, pct_change=2.64, implied_daily_move_pct=1.21, period_low=18.5, period_high=20.1, regime="Cautious", regime_description="Elevated tension"))

    sections = [sec_exec, sec_swing, sec_vix]
    html = render_html(period=period, sections=sections)

    assert '<details class="methodology-note"' in html
    assert '<summary>ℹ️ How this score is calculated</summary>' in html
    assert '<summary>ℹ️ How the Swing-Trade Posture is determined</summary>' in html
    assert '<summary>ℹ️ Volatility Regimes &amp; Risk Thresholds</summary>' in html


def test_html_self_contained_and_size_budget(mock_price_df, sample_config):
    """Verify HTML report has zero external network calls and stays well under 1.5 MB."""
    cal = MarketCalendar()
    period = cal.resolve_period("weekly", pd.to_datetime("2026-10-30").date())

    sec_exec = SectionResult(
        section_num=1,
        title="Executive Summary",
        status="available",
        data=ExecutiveSummaryData(
            verdict="Constructive",
            normalized_score=0.25,
            raw_score=2.5,
            max_score=10.0,
            reasons=["Strong breadth"],
            report_type="weekly",
            as_of_date="2026-10-30",
            session_date="2026-10-30",
            is_partial=False,
            notes="",
        ),
    )
    sec_swing = evaluate_swing_gate(mock_price_df, mock_price_df, 19.42, 19.0, 0.95, None, "2026-10-30", sample_config)

    # Generate sample charts
    chart_spx = generate_index_technicals_chart(mock_price_df, "^GSPC", "S&P 500", "2026-10-30", lookback_bars=100)
    chart_vix = generate_vix_chart(mock_price_df, "2026-10-30", lookback_bars=100)
    charts = {"spx_technicals": chart_spx, "vix_regime": chart_vix}

    html = render_html(period=period, sections=[sec_exec, sec_swing], charts=charts)

    # Size budget: 1.5 MB = 1,572,864 bytes
    html_bytes = len(html.encode("utf-8"))
    assert html_bytes < 1_500_000, f"HTML report exceeded 1.5 MB: {html_bytes} bytes"

    # Zero remote network requests
    assert "http://" not in html, "Found unescaped external HTTP link"
    assert "https://" not in html, "Found unescaped external HTTPS link"
    assert "fonts.googleapis.com" not in html
    assert "cdn." not in html
    assert "unpkg.com" not in html
