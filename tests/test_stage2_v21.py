"""Acceptance tests for Change Request v2.1: Stage 2 (Scorecard Logic)."""

import json
import re
import pytest
import pandas as pd
from unittest.mock import MagicMock

from config.settings import AppConfig, ScoringConfig, ScorecardCategoriesConfig
from indicators.breadth import MarketBreadthResult
from indicators.engine import TechnicalSnapshot
from scoring.engine import TrendScoringEngine, Scorecard
from scoring.rules import evaluate_rates_macro_category, evaluate_breadth_category
from sections.swing_regime import evaluate_swing_gate, SwingGateData
from sections.macro import MacroSectionData, MarketRegimeIntelligence


def test_2_1_rates_deduplication_monthly():
    """Stage 2.1: In monthly mode no two votes use the same underlying series and window."""
    mock_macro = MagicMock()
    mock_fr = MagicMock()
    mock_fr.yield_10y = 4.28
    mock_fr.yield_10y_delta = -0.31
    mock_fr.yield_10y_4w_delta = -0.31
    mock_fr.yield_10y_13w_delta = +0.15
    mock_fr.yield_2y = 4.10
    mock_fr.yield_2y_delta = -0.25
    mock_fr.yield_2y_4w_delta = -0.25
    mock_fr.yield_2y_13w_delta = +0.05
    mock_fr.spread_2s10s = 0.18
    mock_fr.curve_status = "Normal"
    mock_fr.is_inverted = False
    mock_macro.fed_rates = mock_fr
    mock_macro.intelligence = None
    mock_macro.metrics = {}
    mock_macro.recent_releases = []
    mock_macro.cross_assets = []

    score, votes, status = evaluate_rates_macro_category(mock_macro, report_type="monthly")
    assert status == "active"

    # Extract all series and windows evaluated
    # Check that rule names for 10Y and 2Y do not duplicate windows
    rules = [v.rule_name for v in votes]
    
    # 10Y should have Period Shift and 13-Week Trend, but NOT 4-Week Trend
    assert "Rates: 10Y Yield Period Shift" in rules
    assert "Rates: 10Y 13-Week Trend" in rules
    assert "Rates: 10Y 4-Week Trend" not in rules

    # 2Y should have exactly 1 short-window and 1 long-window
    assert "Rates: 2Y 13-Week Trend" in rules
    assert "Rates: 2Y Yield Period Shift" in rules or "Rates: 2Y 4-Week Trend" in rules
    assert not ("Rates: 2Y Yield Period Shift" in rules and "Rates: 2Y 4-Week Trend" in rules)


def test_2_2_rsp_vs_spy_rule_and_sign_match():
    """Stage 2.2: Vote sign must match the sign implied by its label."""
    # Test case 1: Broad Leadership (RSP outperforming SPY) -> vote must be positive (> 0)
    b_res_broad = MarketBreadthResult(
        as_of_date="2026-10-30",
        prev_date="2026-09-30",
        total_constituents=500,
        included_constituents=500,
        coverage_pct=100.0,
        spy_return_pct=-1.50,
        rsp_return_pct=+1.00,
        leadership_spread_pct=-2.50,  # SPY - RSP
        leadership_status="Broad Leadership: Equal-weight RSP outperforming cap-weight SPY by 2.50%",
    )
    score_broad, votes_broad, _ = evaluate_breadth_category(b_res_broad, report_type="monthly")
    v_rsp_broad = next(v for v in votes_broad if "RSP vs SPY" in v.rule_name)
    assert v_rsp_broad.vote > 0.0, f"Expected positive vote for Broad Leadership, got {v_rsp_broad.vote}"
    assert "Broad Leadership" in v_rsp_broad.condition

    # Test case 2: Narrow Leadership (SPY outperforming RSP) -> vote must be negative (< 0)
    b_res_narrow = MarketBreadthResult(
        as_of_date="2026-10-30",
        prev_date="2026-09-30",
        total_constituents=500,
        included_constituents=500,
        coverage_pct=100.0,
        spy_return_pct=+3.00,
        rsp_return_pct=+0.50,
        leadership_spread_pct=+2.50,  # SPY - RSP
        leadership_status="Narrow Leadership: Cap-weight SPY outperforming equal-weight RSP by 2.50%",
    )
    score_narrow, votes_narrow, _ = evaluate_breadth_category(b_res_narrow, report_type="monthly")
    v_rsp_narrow = next(v for v in votes_narrow if "RSP vs SPY" in v.rule_name)
    assert v_rsp_narrow.vote < 0.0, f"Expected negative vote for Narrow Leadership, got {v_rsp_narrow.vote}"
    assert "Narrow Leadership" in v_rsp_narrow.condition


def test_2_4_tips_real_rate_label():
    """Stage 2.4: 10Y TIPS real yield shows level (restrictive) and direction (easing)."""
    mock_macro = MagicMock()
    mock_macro.fed_rates = None
    mock_macro.metrics = {}
    mock_macro.recent_releases = []
    mock_macro.cross_assets = []
    
    mock_intel = MagicMock()
    mock_intel.rates = MagicMock()
    mock_intel.rates.real_yield_10y = 2.63
    mock_intel.rates.real_yield_delta_bps = -2.0  # falling
    mock_intel.rates.driver_attribution = "Real Rate Easing"
    mock_macro.intelligence = mock_intel

    _, votes, _ = evaluate_rates_macro_category(mock_macro)
    tips_vote = next(v for v in votes if "10Y TIPS" in v.rule_name)
    assert tips_vote.vote < 0.0, "High real rate (2.63%) should evaluate as negative score"
    assert "Restrictive Level" in tips_vote.condition
    assert "easing" in tips_vote.condition.lower()
    assert "Real rate: high but falling" in tips_vote.condition or "restrictive" in tips_vote.condition.lower()


def test_2_6_event_risk_overlay_caps_posture():
    """Stage 2.6: Event-risk overlay caps posture one tier more conservative within window."""
    dates = pd.date_range("2026-01-01", "2026-10-30", freq="B")
    spy_df = pd.DataFrame({"Close": [600.0 + i * 0.1 for i in range(len(dates))]}, index=dates)
    qqq_df = pd.DataFrame({"Close": [500.0 + i * 0.1 for i in range(len(dates))]}, index=dates)

    # 1. Without upcoming event: Should evaluate to FULL
    res_no_event = evaluate_swing_gate(
        spy_df=spy_df,
        qqq_df=qqq_df,
        vix_current=14.0,
        vix_previous=14.5,
        vix_term_ratio=0.92,
        breadth_result=MagicMock(pct_above_50_dma=MagicMock(current=65.0), ad_confirmation="Bullish", net_new_highs=25),
        as_of_date="2026-10-30",  # Friday
        upcoming_events=None,
    )
    assert res_no_event.data.posture == "FULL"

    # 2. With upcoming Nonfarm Payrolls on Tuesday (2 trading days away <= 3 days)
    mock_event = MagicMock()
    mock_event.title = "Nonfarm Payrolls (Oct)"
    mock_event.importance = "high"
    mock_event.date = "2026-11-03"  # Tuesday (2 business days after Friday Oct 30)

    res_with_event = evaluate_swing_gate(
        spy_df=spy_df,
        qqq_df=qqq_df,
        vix_current=14.0,
        vix_previous=14.5,
        vix_term_ratio=0.92,
        breadth_result=MagicMock(pct_above_50_dma=MagicMock(current=65.0), ad_confirmation="Bullish", net_new_highs=25),
        as_of_date="2026-10-30",
        upcoming_events=[mock_event],
        event_risk_window_days=3,
    )
    # FULL should be capped one step to REDUCED
    assert res_with_event.data.posture == "REDUCED"
    assert "Event-Risk Overlay" in res_with_event.data.triggered_rule


def _make_sample_snapshot():
    return TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-30",
        price=5800.0,
        dma_20=5750.0,
        dma_50=5700.0,
        dma_200=5400.0,
        price_vs_dma20_pct=0.87,
        price_vs_dma50_pct=1.75,
        price_vs_dma200_pct=7.41,
        cross_50_200="Bullish (50 > 200)",
        rsi=55.0,
        prev_rsi=54.0,
        delta_rsi=1.0,
        rsi_flag="Neutral",
        macd=15.0,
        macd_signal=10.0,
        macd_hist=5.0,
        macd_status="Bullish (MACD > Signal)",
        prev_macd=12.0,
        delta_macd=3.0,
        adx=22.0,
        plus_di=25.0,
        minus_di=18.0,
        prev_adx=21.0,
        delta_adx=1.0,
        trend_strength="Moderate Trend",
    )


def _make_scoring_engine():
    scoring_cfg = ScoringConfig(
        weights={
            "price_above_50_dma": 1.0,
            "price_above_200_dma": 1.0,
            "dma_50_above_200": 1.0,
            "macd_bullish": 1.0,
            "vix_bullish": 1.0,
        },
        thresholds={"bullish": 0.3, "bearish": -0.3},
        vix={"low_threshold": 20.0, "high_threshold": 25.0},
    )
    return TrendScoringEngine(
        scoring_cfg=scoring_cfg,
        cat_cfg=ScorecardCategoriesConfig(),
    )


def test_2_7_category_effective_weights():
    """Stage 2.7: Renormalized effective weights are computed and sum to 100%."""
    snap = _make_sample_snapshot()
    engine = _make_scoring_engine()
    # Sentiment is None (unavailable)
    sc = engine.compute_scorecard(
        spx_snapshot=snap,
        vix_current=16.0,
        vix_previous=15.5,
        sentiment_data=None,
    )
    active_cats = [c for c in sc.categories if c.status == "active"]
    eff_weight_sum = sum(c.effective_weight for c in active_cats)
    assert abs(eff_weight_sum - 1.0) < 1e-4, f"Effective weights should sum to 1.0, got {eff_weight_sum}"
    
    # Check that unavailable category has 0.0 effective weight
    unavail_cats = [c for c in sc.categories if c.status != "active"]
    assert len(unavail_cats) > 0
    for u in unavail_cats:
        assert u.effective_weight == 0.0


def test_reproducibility_from_json():
    """Stage 2 acceptance test: Scorecard must serialize to JSON and be fully reproducible."""
    snap = _make_sample_snapshot()
    engine = _make_scoring_engine()
    sc = engine.compute_scorecard(
        spx_snapshot=snap,
        vix_current=16.0,
        vix_previous=15.5,
    )
    sc_dict = sc.to_dict()
    json_str = json.dumps(sc_dict)
    loaded_dict = json.loads(json_str)

    assert loaded_dict["normalized_score"] == sc.normalized_score
    assert loaded_dict["verdict"] == sc.verdict
    assert len(loaded_dict["categories"]) == len(sc.categories)


def test_lint_no_eliminates_or_proves_in_source():
    """Stage 2 acceptance test: The word 'eliminates' or 'proves' never appears in narrative templates."""
    from sections.macro import build_macro_section
    import inspect
    source = inspect.getsource(build_macro_section)
    assert not re.search(r"\beliminates?\b", source, re.IGNORECASE), "Found 'eliminate(s)' in build_macro_section"
    assert not re.search(r"\bproves?\b", source, re.IGNORECASE), "Found 'prove(s)' in build_macro_section"
