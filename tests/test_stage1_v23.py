"""Tests for Change Request v2.3 - Stage 1: Logic and Consistency Bugs."""

import os
from pathlib import Path
import re
import pytest

from config.settings import load_config
from report import generate_market_report
from scoring.engine import TrendScoringEngine
from scoring.rules import evaluate_volatility_risk_category
from sections.what_changed import WhatChangedData
from sections.conclusion import ConclusionData
from sections.executive_summary import ExecutiveSummaryData
from sections.forward_calendar import ForwardCalendarData
from sections.commodities_cross_asset import CommoditiesCrossAssetData


def test_1_1_prior_period_values_and_stability():
    """1.1: Prior score != current score when inputs changed, Tech-vs-Broad gap has numeric prior & delta."""
    res1 = generate_market_report(report_type="weekly", target_date="2026-10-30")
    res2 = generate_market_report(report_type="weekly", target_date="2026-10-30")

    wc1 = next(s.data for s in res1["sections"] if isinstance(s.data, WhatChangedData))
    wc2 = next(s.data for s in res2["sections"] if isinstance(s.data, WhatChangedData))

    # Test run-to-run stability
    for d1, d2 in zip(wc1.deltas, wc2.deltas):
        assert d1.name == d2.name
        assert d1.current_val == d2.current_val
        assert d1.prior_val == d2.prior_val
        assert d1.delta_str == d2.delta_str

    # Find Trend score delta
    score_delta = next(d for d in wc1.deltas if "Trend Score" in d.name)
    assert score_delta.prior_val != "n/a"
    # Prior score should not equal current score
    m_curr = re.search(r"([+-]?\d+\.\d+)", score_delta.current_val)
    m_prior = re.search(r"([+-]?\d+\.\d+)", score_delta.prior_val)
    assert m_curr and m_prior
    assert float(m_curr.group(1)) != float(m_prior.group(1)), f"Prior score {m_prior.group(1)} must not equal current {m_curr.group(1)}"

    # Tech vs Broad divergence
    tech_delta = next(d for d in wc1.deltas if "Tech vs. Broad" in d.name)
    assert "gap" in tech_delta.prior_val
    assert tech_delta.prior_val != tech_delta.current_val
    assert tech_delta.delta_str != "—"
    assert tech_delta.delta_str != "+0.00%"


def test_1_2_top_bullish_bearish_factors_ranking():
    """1.2: Top Bullish/Bearish Factors ranks all categories by weighted vote with category names."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    conc = next(s.data for s in res["sections"] if isinstance(s.data, ConclusionData))
    scorecard = conc.scorecard

    # Must contain category tags like [Rates & Macro], [Market Breadth], [Trend / Price]
    assert len(scorecard.top_bullish_factors) > 0
    assert len(scorecard.top_bearish_factors) > 0

    for bf in scorecard.top_bullish_factors:
        assert bf.startswith("[") and "]" in bf, f"Bullish factor {bf} must start with [Category Name]"
    for br in scorecard.top_bearish_factors:
        assert br.startswith("[") and "]" in br, f"Bearish factor {br} must start with [Category Name]"

    # Verify that not all factors are from Trend / Price
    all_categories = {re.match(r"\[(.*?)\]", f).group(1) for f in scorecard.top_bullish_factors + scorecard.top_bearish_factors if re.match(r"\[(.*?)\]", f)}
    assert len(all_categories) >= 2, f"Expected factors from multiple categories, found: {all_categories}"


def test_1_3_verdict_explanation_and_neutral_mixed():
    """1.3: Explanation names highest pos/neg contributors (Trend & Breadth) and header shows Neutral (Mixed)."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    exec_sec = next(s.data for s in res["sections"] if isinstance(s.data, ExecutiveSummaryData))
    assert "Neutral (Mixed)" in exec_sec.verdict

    # Check alignment note names Trend and Breadth
    align_note = exec_sec.alignment_note
    assert "Trend" in align_note, f"Expected 'Trend' in alignment note: {align_note}"
    assert "Breadth" in align_note, f"Expected 'Breadth' in alignment note: {align_note}"

    # HTML header must display NEUTRAL (MIXED)
    with open(res["html"], "r", encoding="utf-8") as f:
        html_content = f.read()
    assert "NEUTRAL (MIXED)" in html_content


def test_1_4_sentiment_min_inputs_and_footer():
    """1.4: Sentiment category dropped when <2 inputs, footer notes match scorecard."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    conc = next(s.data for s in res["sections"] if isinstance(s.data, ConclusionData))
    cat_sent = next((c for c in conc.scorecard.categories if c.category_key == "sentiment_positioning"), None)
    assert cat_sent is not None
    assert cat_sent.status == "unavailable"
    assert cat_sent.effective_weight == 0.0

    # Footer check
    with open(res["html"], "r", encoding="utf-8") as f:
        html_content = f.read()
    assert "not scored" in html_content or "displayed only" in html_content
    assert "Nasdaq Composite native volume (n/a - source unavailable)" in html_content


def test_1_5_oil_3m_single_source_of_truth():
    """1.5: WTI 3-month return is identical everywhere it appears (+29.60%)."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    comm = next(s.data for s in res["sections"] if isinstance(s.data, CommoditiesCrossAssetData))
    oil_item = next(it for it in comm.items if it.symbol == "CL=F")
    oil_3m_comm = round(oil_item.ret_3m, 2)

    conc = next(s.data for s in res["sections"] if isinstance(s.data, ConclusionData))
    oil_vote = next(v for v in conc.scorecard.votes if "Crude Oil (WTI)" in v.rule_name)
    m = re.search(r"3M trend ([+-]?\d+\.\d+)%", oil_vote.condition)
    assert m is not None
    oil_3m_vote = round(float(m.group(1)), 2)

    assert abs(oil_3m_comm - oil_3m_vote) < 0.05, f"Commodities {oil_3m_comm} != Vote {oil_3m_vote}"
    assert oil_3m_comm == pytest.approx(29.60, abs=0.1)


def test_1_6_vix_regime_and_gradient_consistency():
    """1.6: VIX tiers <16.5 Low, 16.5-20 Normal, 20-26 Elevated, >26 High Fear and gradient (+1 at 12, 0 at 18, -1 at 30)."""
    cfg = load_config()

    # Test gradient formula directly
    test_cases = [
        (12.0, 1.0, "positive"),
        (16.0, 0.33, "positive"),
        (18.0, 0.0, "neutral"),
        (19.42, -0.12, "negative"),
        (20.0, -0.17, "negative"),
        (25.0, -0.58, "negative"),
        (30.0, -1.0, "negative"),
    ]

    for vix, expected_score, expected_sign in test_cases:
        _, votes, _ = evaluate_volatility_risk_category(vix, vix, None, cfg.scoring)
        vix_vote = next(v for v in votes if "VIX Absolute Level" in v.rule_name)
        assert abs(vix_vote.vote - expected_score) <= 0.02, f"VIX {vix} expected score {expected_score}, got {vix_vote.vote}"
        if expected_sign == "positive":
            assert vix_vote.vote > 0
        elif expected_sign == "negative":
            assert vix_vote.vote < 0
        else:
            assert vix_vote.vote == 0.0


def test_1_7_calendar_importance_and_provenance():
    """1.7: At most 5 HIGH events in 10-session window, provenance fields present, NFP & UNRATE merged, no ISM in risk box."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    fwd = next(s.data for s in res["sections"] if isinstance(s.data, ForwardCalendarData))
    high_events = [e for e in fwd.events if e.importance == "high"]
    assert len(high_events) <= 5, f"Expected <= 5 HIGH events, found {len(high_events)}"

    # Verify Unemployment Rate is merged into Employment Situation
    titles = [e.title for e in fwd.events]
    assert not any(t == "Unemployment Rate" for t in titles), "Unemployment Rate should not be a separate standalone row"
    assert any("Employment Situation" in t for t in titles), "Employment Situation must be present"

    # Verify provenance fields
    for ev in fwd.events:
        assert ev.source_name, f"Event {ev.title} missing source_name"
        assert ev.source_url.startswith("http"), f"Event {ev.title} missing source_url"
        assert ev.retrieval_timestamp, f"Event {ev.title} missing retrieval_timestamp"

    # Single Biggest Risk check: must not pick ISM
    wc = next(s.data for s in res["sections"] if isinstance(s.data, WhatChangedData))
    assert "ISM" not in wc.single_biggest_risk, f"ISM should not be picked as Single Biggest Risk: {wc.single_biggest_risk}"
