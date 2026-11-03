"""Unit tests for Stage 3 Market Breadth indicator calculations, scoring votes, and section builder."""

from datetime import date
from typing import Dict, List
import numpy as np
import pandas as pd
import pytest

from config.settings import BreadthConfig, BreadthScoringConfig
from data.calendar import PeriodInfo
from data.constituents import Constituent
from indicators.breadth import (
    BreadthMetric,
    MarketBreadthResult,
    compute_market_breadth,
)
from scoring.rules import IndicatorVote, evaluate_breadth_votes
from sections.breadth import BreadthSectionData, build_breadth_section


@pytest.fixture
def mock_period() -> PeriodInfo:
    return PeriodInfo(
        report_type="daily",
        as_of_date="2026-10-22",
        session_date="2026-10-22",
        current_start="2026-10-22",
        current_end="2026-10-22",
        baseline_date="2026-10-21",
        prev_period_start="2026-10-21",
        prev_period_end="2026-10-21",
        prev_baseline_date="2026-10-20",
        is_partial=False,
        session_count=1,
    )


@pytest.fixture
def sample_constituents() -> List[Constituent]:
    return [
        Constituent(symbol="SYM_UP_1", name="Alpha Inc", sector="Technology", in_sp500=True),
        Constituent(symbol="SYM_UP_2", name="Beta Inc", sector="Technology", in_sp500=True),
        Constituent(symbol="SYM_UP_3", name="Gamma Inc", sector="Health Care", in_sp500=True),
        Constituent(symbol="SYM_DOWN_1", name="Delta Inc", sector="Financials", in_sp500=True),
        Constituent(symbol="SYM_DOWN_2", name="Epsilon Inc", sector="Energy", in_sp500=True),
    ]


@pytest.fixture
def sample_equity_bars() -> Dict[str, pd.DataFrame]:
    """Generate 260 trading sessions of synthetic price bars for 5 constituents."""
    dates = pd.date_range(end="2026-10-22", periods=260, freq="B")
    bars = {}

    # Stocks 1-3: Trending up, above 20, 50, 200 DMA, hitting new 52-week highs today
    for sym in ["SYM_UP_1", "SYM_UP_2", "SYM_UP_3"]:
        prices = np.linspace(100.0, 150.0, 260)
        # Give a jump on last day for new 52-week high
        prices[-1] = 160.0
        df = pd.DataFrame(
            {
                "Open": prices - 1.0,
                "High": prices + 1.0,
                "Low": prices - 2.0,
                "Close": prices,
                "Volume": 1_000_000.0,
            },
            index=dates,
        )
        bars[sym] = df

    # Stock 4: Trending down, below 20, 50, 200 DMA, hitting new 52-week low today
    prices_down_1 = np.linspace(150.0, 100.0, 260)
    prices_down_1[-1] = 90.0
    bars["SYM_DOWN_1"] = pd.DataFrame(
        {
            "Open": prices_down_1 + 1.0,
            "High": prices_down_1 + 2.0,
            "Low": prices_down_1 - 1.0,
            "Close": prices_down_1,
            "Volume": 1_000_000.0,
        },
        index=dates,
    )

    # Stock 5: Mostly flat/lower today, below 20/50/200 DMA, but not a new 52w low
    prices_down_2 = np.concatenate([np.full(60, 100.0), np.linspace(100.0, 140.0, 100), np.linspace(140.0, 110.0, 100)])
    prices_down_2[-1] = 109.0  # fell today vs yesterday (110), but above 52w low (100)
    bars["SYM_DOWN_2"] = pd.DataFrame(
        {
            "Open": prices_down_2,
            "High": prices_down_2 + 1.0,
            "Low": prices_down_2 - 1.0,
            "Close": prices_down_2,
            "Volume": 1_000_000.0,
        },
        index=dates,
    )

    return bars


def test_breadth_ma_and_ad_metrics(sample_equity_bars, sample_constituents, mock_period):
    """Test % above 20/50/200 DMA, A/D counts, and 52-week highs/lows."""
    cfg = BreadthConfig(
        enabled=True,
        min_coverage_pct=90.0,
        min_history_bars=252,
        mcclellan_enabled=True,
    )

    res = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
    )

    # 5 constituents total, all 5 have 260 bars
    assert res.total_constituents == 5
    assert res.included_constituents == 5
    assert res.coverage_pct == 100.0
    assert res.coverage_warning is None

    # SYM_UP_1, SYM_UP_2, SYM_UP_3 are above 20/50/200 DMA (3 of 5 = 60.0%)
    assert res.pct_above_20_dma.current == 60.0
    assert res.pct_above_50_dma.current == 60.0
    assert res.pct_above_200_dma.current == 60.0

    # Advancers vs decliners: 3 stocks rose today, 2 stocks fell today
    assert res.advancers == 3
    assert res.decliners == 2
    assert res.net_advancers == 1
    assert res.unchanged == 0
    assert res.ad_ratio == pytest.approx(1.5, 0.01)
    assert res.pct_positive_return.current == 60.0
    assert "Above 50-day MA" in res.cum_ad_trend or "Steady" in res.cum_ad_trend

    # 52-week highs: 3 stocks hit new 52-week high (SYM_UP_1, 2, 3)
    # 52-week lows: 1 stock hit new 52-week low (SYM_DOWN_1)
    assert res.new_52w_highs == 3
    assert res.new_52w_lows == 1
    assert res.net_new_highs == 2


def test_insufficient_history_handling(sample_equity_bars, sample_constituents, mock_period):
    """Test skipping tickers with < 252 bars and triggering coverage warning when coverage < 95%."""
    # Truncate two tickers to only 100 bars (< 252 bars)
    sample_equity_bars["SYM_UP_1"] = sample_equity_bars["SYM_UP_1"].tail(100)
    sample_equity_bars["SYM_UP_2"] = sample_equity_bars["SYM_UP_2"].tail(100)

    cfg = BreadthConfig(
        enabled=True,
        min_coverage_pct=95.0,  # Requires 95% coverage
        min_history_bars=252,
    )

    res = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
    )

    # 3 of 5 valid = 60.0% coverage (< 95.0%)
    assert res.total_constituents == 5
    assert res.included_constituents == 3
    assert res.coverage_pct == 60.0
    assert res.coverage_warning is not None
    assert "below minimum threshold" in res.coverage_warning


def test_narrow_leadership_and_broad_leadership(sample_equity_bars, sample_constituents, mock_period):
    """Test equal-weight vs cap-weight divergence detection (RSP vs SPY)."""
    dates = pd.date_range(end="2026-10-22", periods=260, freq="B")
    
    # Case 1: Cap-weight SPY surges +2.5% while RSP is only +0.5% (Spread = +2.0% > 1.0% margin) -> Narrow leadership!
    spy_prices = np.full(260, 500.0)
    spy_prices[-1] = 512.5  # +2.5%
    spy_df = pd.DataFrame({"Close": spy_prices}, index=dates)

    rsp_prices = np.full(260, 150.0)
    rsp_prices[-1] = 150.75  # +0.5%
    rsp_df = pd.DataFrame({"Close": rsp_prices}, index=dates)

    cfg = BreadthConfig(enabled=True)

    res_narrow = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
        spy_df=spy_df,
        rsp_df=rsp_df,
    )

    assert res_narrow.narrow_leadership is True
    assert "Narrow Leadership" in res_narrow.leadership_status
    assert res_narrow.spy_return_pct == pytest.approx(2.5, 0.01)
    assert res_narrow.rsp_return_pct == pytest.approx(0.5, 0.01)
    assert res_narrow.leadership_spread_pct == pytest.approx(2.0, 0.01)

    # Case 2: RSP outperforms SPY (Equal-weight leads)
    rsp_prices[-1] = 154.5  # +3.0%
    spy_prices[-1] = 505.0  # +1.0%
    rsp_df2 = pd.DataFrame({"Close": rsp_prices}, index=dates)
    spy_df2 = pd.DataFrame({"Close": spy_prices}, index=dates)

    res_broad = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
        spy_df=spy_df2,
        rsp_df=rsp_df2,
    )

    assert res_broad.narrow_leadership is False
    assert "Broad Leadership" in res_broad.leadership_status


def test_breadth_scoring_votes():
    """Test vote generation from market breadth metrics."""
    scoring_cfg = BreadthScoringConfig(
        enabled=True,
        weights={
            "stocks_above_50_dma": 0.5,
            "stocks_above_200_dma": 0.5,
            "net_new_highs": 0.5,
            "narrow_leadership": 0.5,
            "ad_line_confirmation": 0.5,
        },
        thresholds={
            "ma_bullish_pct": 60.0,
            "ma_bearish_pct": 40.0,
            "net_highs_strongly_negative": -10.0,
            "narrow_leadership_margin_pct": 1.0,
        },
    )

    # Bullish breadth scenario
    bull_result = MarketBreadthResult(
        as_of_date="2026-10-22",
        prev_date="2026-10-21",
        total_constituents=500,
        included_constituents=495,
        coverage_pct=99.0,
        pct_above_50_dma=BreadthMetric(current=65.0, previous=62.0, change=3.0),
        pct_above_200_dma=BreadthMetric(current=62.0, previous=60.0, change=2.0),
        net_new_highs=25,
        delta_net_new_highs=5,
        narrow_leadership=False,
        leadership_status="Broad Leadership",
        leadership_spread_pct=-1.5,
        ad_confirmation="Confirming Rally",
        ad_ratio=2.2,
    )

    votes = evaluate_breadth_votes(bull_result, scoring_cfg)
    assert len(votes) == 5
    # All 5 votes should be +1 (or positive)
    for v in votes:
        assert v.vote == 1
        assert v.weighted_vote == 0.5

    # Bearish / Narrow breadth scenario
    bear_result = MarketBreadthResult(
        as_of_date="2026-10-22",
        prev_date="2026-10-21",
        total_constituents=500,
        included_constituents=495,
        coverage_pct=99.0,
        pct_above_50_dma=BreadthMetric(current=35.0, previous=38.0, change=-3.0),
        pct_above_200_dma=BreadthMetric(current=32.0, previous=34.0, change=-2.0),
        net_new_highs=-15,
        delta_net_new_highs=-5,
        narrow_leadership=True,
        leadership_status="Narrow Leadership Warning",
        leadership_spread_pct=1.8,
        ad_confirmation="Bearish Divergence",
        ad_ratio=0.6,
    )

    bear_votes = evaluate_breadth_votes(bear_result, scoring_cfg)
    assert len(bear_votes) == 5
    for v in bear_votes:
        assert v.vote == -1
        assert v.weighted_vote == -0.5

    # Confirming Decline must vote -1 (Bearish), Bullish Divergence must vote +1 (Bullish)
    decline_res = MarketBreadthResult(
        as_of_date="2026-10-22",
        prev_date="2026-10-21",
        total_constituents=500,
        included_constituents=495,
        coverage_pct=99.0,
        ad_confirmation="Confirming Decline",
        ad_ratio=0.5,
    )
    v_dec = next(v for v in evaluate_breadth_votes(decline_res, scoring_cfg) if "A/D Line" in v.rule_name)
    assert v_dec.vote == -1

    bull_div_res = MarketBreadthResult(
        as_of_date="2026-10-22",
        prev_date="2026-10-21",
        total_constituents=500,
        included_constituents=495,
        coverage_pct=99.0,
        ad_confirmation="Bullish Divergence",
        ad_ratio=1.8,
    )
    v_bdiv = next(v for v in evaluate_breadth_votes(bull_div_res, scoring_cfg) if "A/D Line" in v.rule_name)
    assert v_bdiv.vote == 1


def test_section_builder_and_empty_handling():
    """Test build_breadth_section wrapper and unavailable state handling."""
    # Available result
    valid_res = MarketBreadthResult(
        as_of_date="2026-10-22",
        prev_date="2026-10-21",
        total_constituents=500,
        included_constituents=495,
        coverage_pct=99.0,
    )
    sec = build_breadth_section(valid_res, section_num=7)
    assert sec.is_available is True
    assert sec.section_num == 7
    assert isinstance(sec.data, BreadthSectionData)

    # Empty / None result
    sec_none = build_breadth_section(None, section_num=7)
    assert sec_none.is_available is False
    assert "unavailable" in sec_none.error_message.lower()


def test_ad_confirmation_and_divergence(sample_equity_bars, sample_constituents, mock_period):
    """Test A/D line confirmation vs divergence logic against index direction."""
    cfg = BreadthConfig(enabled=True)

    # 1. Index up (+1.5%) and A/D net positive -> Confirming Rally
    res_confirm = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
        spx_return_pct=1.5,
    )
    assert res_confirm.ad_confirmation == "Confirming Rally"

    # 2. Index up (+1.5%) but A/D net negative -> Bearish Divergence
    # Reverse price action so decliners > advancers
    dates = pd.date_range(end="2026-10-22", periods=260, freq="B")
    bear_bars = {}
    for i, sym in enumerate(["SYM_UP_1", "SYM_UP_2", "SYM_UP_3", "SYM_DOWN_1", "SYM_DOWN_2"]):
        prices = np.full(260, 100.0)
        # 4 stocks drop today, only 1 rises
        if i == 0:
            prices[-1] = 105.0
        else:
            prices[-1] = 95.0
        bear_bars[sym] = pd.DataFrame({"Close": prices}, index=dates)

    res_div = compute_market_breadth(
        equity_bars=bear_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
        spx_return_pct=1.5,  # Index up, but 4 decliners vs 1 advancer
    )
    assert res_div.ad_confirmation == "Bearish Divergence"


def test_prior_snapshot_delta_integration(sample_equity_bars, sample_constituents, mock_period):
    """Test that prior snapshot values are correctly used for delta comparisons."""
    cfg = BreadthConfig(enabled=True)
    prior_snap = {
        "breadth": {
            "pct_above_20_dma": 50.0,
            "pct_above_50_dma": 40.0,
            "pct_above_200_dma": 55.0,
            "ad_ratio": 1.0,
            "cumulative_ad": 10.0,
            "net_new_highs": -2,
            "pct_positive_return": 45.0,
        }
    }

    res = compute_market_breadth(
        equity_bars=sample_equity_bars,
        constituents=sample_constituents,
        period=mock_period,
        cfg=cfg,
        prior_snapshot=prior_snap,
    )

    # Current % above 50 DMA is 60.0%; prior snapshot was 40.0% -> change = +20.0%
    assert res.pct_above_50_dma.previous == 40.0
    assert res.pct_above_50_dma.change == pytest.approx(20.0, 0.01)

    # Current % above 200 DMA is 60.0%; prior snapshot was 55.0% -> change = +5.0%
    assert res.pct_above_200_dma.previous == 55.0
    assert res.pct_above_200_dma.change == pytest.approx(5.0, 0.01)

    # Current net new highs is 2; prior snapshot was -2 -> change = +4
    assert res.prev_net_new_highs == -2
    assert res.delta_net_new_highs == 4

