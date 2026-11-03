"""Unit tests for top movers filtering and ranking."""

import pandas as pd
import pytest

from config.settings import MoversConfig
from sections.movers import _calculate_mover_stats


@pytest.fixture
def mover_cfg():
    return MoversConfig(
        min_price=5.0,
        min_avg_volume=1000000,
        min_market_cap=2000000000.0,
        top_n=5,
    )


def test_penny_stock_filtered_out(mover_cfg):
    """Stocks with price < $5 must be filtered out."""
    dates = pd.date_range("2026-10-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "Open": [3.0] * 10,
            "High": [3.5] * 10,
            "Low": [2.9] * 10,
            "Close": [3.2] * 10,  # Below min_price $5.0
            "Volume": [5000000] * 10,
        },
        index=dates,
    )

    stat = _calculate_mover_stats(
        df=df,
        symbol="PENNY",
        name="Penny Stock Inc",
        sector="Technology",
        market_cap=5000000000.0,
        curr_dt=dates[-1],
        base_dt=dates[0],
        movers_cfg=mover_cfg,
    )
    assert stat is None


def test_low_volume_stock_filtered_out(mover_cfg):
    """Stocks with 20d avg volume < 1,000,000 shares must be filtered out."""
    dates = pd.date_range("2026-10-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "Open": [50.0] * 10,
            "High": [51.0] * 10,
            "Low": [49.0] * 10,
            "Close": [50.5] * 10,
            "Volume": [200000] * 10,  # Below 1M avg volume
        },
        index=dates,
    )

    stat = _calculate_mover_stats(
        df=df,
        symbol="LOWVOL",
        name="Low Vol Corp",
        sector="Financials",
        market_cap=10000000000.0,
        curr_dt=dates[-1],
        base_dt=dates[0],
        movers_cfg=mover_cfg,
    )
    assert stat is None


def test_small_cap_filtered_out(mover_cfg):
    """Stocks with market cap < $2B must be filtered out."""
    dates = pd.date_range("2026-10-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "Open": [50.0] * 10,
            "High": [51.0] * 10,
            "Low": [49.0] * 10,
            "Close": [50.5] * 10,
            "Volume": [2000000] * 10,
        },
        index=dates,
    )

    stat = _calculate_mover_stats(
        df=df,
        symbol="MICRO",
        name="Micro Cap",
        sector="Industrials",
        market_cap=500000000.0,  # $500M < $2B
        curr_dt=dates[-1],
        base_dt=dates[0],
        movers_cfg=mover_cfg,
    )
    assert stat is None


def test_valid_mover_accepted(mover_cfg):
    """Compliant stock must pass all filters and calculate returns."""
    dates = pd.date_range("2026-10-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "Open": [100.0] * 10,
            "High": [105.0] * 10,
            "Low": [99.0] * 10,
            "Close": [100.0] * 9 + [110.0],  # 10% gain on final day
            "Volume": [2500000] * 10,
        },
        index=dates,
    )

    stat = _calculate_mover_stats(
        df=df,
        symbol="MEGA",
        name="Mega Corp",
        sector="Technology",
        market_cap=50000000000.0,
        curr_dt=dates[-1],
        base_dt=dates[0],
        movers_cfg=mover_cfg,
    )
    assert stat is not None
    assert stat.symbol == "MEGA"
    assert stat.close == 110.0
    assert stat.pct_change == pytest.approx(10.0)
    assert stat.avg_volume_20d >= 1000000


def test_timeframe_decluttering_in_renders():
    """Verify that Weekly and Monthly reports do not render irrelevant out-of-period mover tables."""
    from data.calendar import PeriodInfo
    from render.markdown import render_markdown
    from render.html import render_html
    from sections.base import SectionResult
    from sections.movers import MoverItem, PeriodMovers, TopMoversData

    dummy_item = MoverItem(
        symbol="AAPL", name="Apple Inc.", sector="Technology",
        pct_change=2.5, close=200.0, volume=10000000, avg_volume_20d=10000000, volume_ratio=1.0, market_cap=3e12
    )
    movers_data = TopMoversData(
        day=PeriodMovers("Daily", [dummy_item], [dummy_item]),
        week=PeriodMovers("Weekly", [dummy_item], [dummy_item]),
        month=PeriodMovers("Monthly", [dummy_item], [dummy_item]),
    )
    sec_movers = SectionResult(section_num=8, title="Top Movers", status="available", data=movers_data)

    p_weekly = PeriodInfo("weekly", "2026-10-30", "2026-10-30", "2026-10-26", "2026-10-30", "2026-10-23", "2026-10-19", "2026-10-23", "2026-10-16", False, 5)
    md_weekly = render_markdown(period=p_weekly, sections=[sec_movers])
    html_weekly = render_html(period=p_weekly, sections=[sec_movers])

    # Weekly report must display Weekly Movers, but NOT Daily Movers or Monthly Movers
    assert "### Weekly Movers" in md_weekly
    assert "### Daily Movers" not in md_weekly
    assert "### Monthly Movers" not in md_weekly
    assert "Weekly Universe Movers" in html_weekly
    assert "Daily Universe Movers" not in html_weekly
    assert "Monthly Universe Movers" not in html_weekly

    p_monthly = PeriodInfo("monthly", "2026-10-30", "2026-10-30", "2026-10-01", "2026-10-30", "2026-09-30", "2026-09-01", "2026-09-30", "2026-08-31", False, 22)
    md_monthly = render_markdown(period=p_monthly, sections=[sec_movers])
    html_monthly = render_html(period=p_monthly, sections=[sec_movers])

    # Monthly report must display Monthly Movers and Final Week Movers, but NOT Daily Movers
    assert "### Monthly Movers" in md_monthly
    assert "### Final Week Movers" in md_monthly
    assert "### Daily Movers" not in md_monthly
    assert "Monthly Universe Movers" in html_monthly
    assert "Final Week Universe Movers" in html_monthly
    assert "Daily Universe Movers" not in html_monthly
