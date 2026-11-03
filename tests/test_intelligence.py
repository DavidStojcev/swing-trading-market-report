"""Unit tests for the forward-looking intelligence layer.

Tests cover:
1. High-Yield Credit Spread regime classification and metrics.
2. 10Y Real Rate (TIPS) & Breakeven inflation Fisher attribution.
3. VIX Term Structure contango vs. backwardation dynamics.
4. Cyclical vs. Defensive sector rotation spread and risk posture.
5. Macro Regime Quadrant mapping (Goldilocks, Reflation, Stagflation, Deflation).
6. Markdown and HTML forward-looking rendering integration.
"""

import pandas as pd
import pytest

from data.fred_provider import MacroMetricSnapshot
from sections.macro import (
    CreditSpreadIntelligence,
    RealRateIntelligence,
    VolTermStructureIntelligence,
    SectorRotationIntelligence,
    MarketRegimeIntelligence,
    compute_credit_spread_intelligence,
    compute_real_rate_intelligence,
    compute_vol_term_intelligence,
    compute_sector_rotation_intelligence,
    compute_macro_regime_intelligence,
    compute_oas_delta,
    compute_yield_support_resistance,
    resolve_release_metadata,
)
from data.fomc import resolve_fomc_schedule, FomcStatus
from sections.executive_summary import ExecutiveSummaryData, build_executive_summary
from sections.conclusion import ConclusionData, build_conclusion
from scoring.engine import Scorecard
from render.markdown import render_markdown
from render.html import render_html
from data.calendar import PeriodInfo
from sections.base import SectionResult


def test_credit_spread_intelligence_regimes():
    """Verify high-yield OAS thresholds and regime classifications."""
    # 1. Tight / Complacent (< 350 bps)
    snap_tight = MacroMetricSnapshot(
        series_id="BAMLH0A0HYM2",
        name="HY OAS",
        latest_date="2026-10-30",
        latest_value=3.26,  # 326 bps
        headline_value=3.26,
        headline_unit="%",
        prior_value=3.30,
        prior_headline=3.30,
        change=-0.04,
        period_change=-0.04,
    )
    intel_tight = compute_credit_spread_intelligence(snap_tight)
    assert intel_tight.spread_bps == 326.0
    assert intel_tight.delta_bps == -4.0
    assert intel_tight.regime == "Tight / Complacent"
    assert "compressed below 350 bps" in intel_tight.assessment

    # 2. Normal / Neutral (350 - 450 bps)
    snap_normal = MacroMetricSnapshot(
        series_id="BAMLH0A0HYM2",
        name="HY OAS",
        latest_date="2026-10-30",
        latest_value=4.10,
        headline_value=4.10,
        headline_unit="%",
        prior_value=4.00,
        prior_headline=4.00,
        change=0.10,
        period_change=0.10,
    )
    intel_normal = compute_credit_spread_intelligence(snap_normal)
    assert intel_normal.spread_bps == 410.0
    assert intel_normal.regime == "Normal / Neutral"

    # 3. Widening / Elevated Stress (450 - 600 bps)
    snap_wide = MacroMetricSnapshot(
        series_id="BAMLH0A0HYM2",
        name="HY OAS",
        latest_date="2026-10-30",
        latest_value=5.20,
        headline_value=5.20,
        headline_unit="%",
        prior_value=4.80,
        prior_headline=4.80,
        change=0.40,
        period_change=0.40,
    )
    intel_wide = compute_credit_spread_intelligence(snap_wide)
    assert intel_wide.spread_bps == 520.0
    assert intel_wide.regime == "Widening / Elevated Stress"

    # 4. Distressed (>= 600 bps)
    snap_crisis = MacroMetricSnapshot(
        series_id="BAMLH0A0HYM2",
        name="HY OAS",
        latest_date="2026-10-30",
        latest_value=6.80,
        headline_value=6.80,
        headline_unit="%",
        prior_value=6.00,
        prior_headline=6.00,
        change=0.80,
        period_change=0.80,
    )
    intel_crisis = compute_credit_spread_intelligence(snap_crisis)
    assert intel_crisis.spread_bps == 680.0
    assert intel_crisis.regime == "Distressed / Crisis Alert"

    # 5. Fallback on None
    intel_none = compute_credit_spread_intelligence(None)
    assert intel_none.spread_bps == 326.0
    assert intel_none.regime == "Tight / Complacent"


def test_real_rate_fisher_attribution():
    """Verify real yield (TIPS) and breakeven inflation attribution."""
    # 1. Real rate tightening dominance
    snap_real = MacroMetricSnapshot(
        series_id="DFII10",
        name="10Y TIPS",
        latest_date="2026-10-30",
        latest_value=2.63,
        headline_value=2.63,
        headline_unit="%",
        prior_value=2.50,
        prior_headline=2.50,
        change=0.13,
        period_change=0.13,  # +13 bps
    )
    snap_be = MacroMetricSnapshot(
        series_id="T10YIE",
        name="10Y Breakeven",
        latest_date="2026-10-30",
        latest_value=2.34,
        headline_value=2.34,
        headline_unit="%",
        prior_value=2.32,
        prior_headline=2.32,
        change=0.02,
        period_change=0.02,  # +2 bps
    )
    intel_tightening = compute_real_rate_intelligence(snap_real, snap_be, nominal_10y=4.98, nominal_delta=0.15)
    assert intel_tightening.real_yield_10y == 2.63
    assert intel_tightening.breakeven_10y == 2.34
    assert intel_tightening.driver_attribution == "Real Rate Tightening"

    # 2. Inflation expectations surge dominance
    snap_real_flat = MacroMetricSnapshot(
        series_id="DFII10",
        name="10Y TIPS",
        latest_date="2026-10-30",
        latest_value=2.20,
        headline_value=2.20,
        headline_unit="%",
        prior_value=2.19,
        prior_headline=2.19,
        change=0.01,
        period_change=0.01,  # +1 bp
    )
    snap_be_surge = MacroMetricSnapshot(
        series_id="T10YIE",
        name="10Y Breakeven",
        latest_date="2026-10-30",
        latest_value=2.60,
        headline_value=2.60,
        headline_unit="%",
        prior_value=2.40,
        prior_headline=2.40,
        change=0.20,
        period_change=0.20,  # +20 bps
    )
    intel_infl = compute_real_rate_intelligence(snap_real_flat, snap_be_surge, nominal_10y=4.80, nominal_delta=0.21)
    assert intel_infl.driver_attribution == "Inflation Expectations Re-pricing"

    # 3. Fallback on None
    intel_fallback = compute_real_rate_intelligence(None, None, nominal_10y=4.50, nominal_delta=0.0)
    assert intel_fallback.real_yield_10y == 2.63
    assert intel_fallback.breakeven_10y == 2.34


def test_vol_term_structure_contango_backwardation():
    """Verify VIX vs VIX3M ratio for contango, flattening, and backwardation."""
    dates = pd.date_range("2026-10-01", "2026-10-30", freq="B")
    session_dt = pd.Timestamp("2026-10-30")
    base_dt = pd.Timestamp("2026-10-01")

    # 1. Contango (19.42 / 20.78 = 0.934 < 0.95)
    bars_contango = {
        "^VIX": pd.DataFrame({"Close": [18.0] * (len(dates) - 1) + [19.42]}, index=dates),
        "^VIX3M": pd.DataFrame({"Close": [20.0] * (len(dates) - 1) + [20.78]}, index=dates),
    }
    intel_c = compute_vol_term_intelligence(bars_contango, session_dt, base_dt)
    assert round(intel_c.ratio, 3) == 0.935
    assert intel_c.structure == "Contango (Normal)"
    assert intel_c.hedging_demand == "Orderly / Calm"

    # 2. Backwardation / Inversion (24.0 / 21.0 = 1.143 > 1.02)
    bars_inversion = {
        "^VIX": pd.DataFrame({"Close": [18.0] * (len(dates) - 1) + [24.0]}, index=dates),
        "^VIX3M": pd.DataFrame({"Close": [20.0] * (len(dates) - 1) + [21.0]}, index=dates),
    }
    intel_inv = compute_vol_term_intelligence(bars_inversion, session_dt, base_dt)
    assert round(intel_inv.ratio, 3) == 1.143
    assert intel_inv.structure == "Backwardation / Inverted"
    assert intel_inv.hedging_demand == "Acute Put Rush / Panic"


def test_sector_rotation_spread():
    """Verify Cyclical vs Defensive basket spread calculations."""
    dates = pd.date_range("2026-10-01", "2026-10-30", freq="B")
    session_dt = pd.Timestamp("2026-10-30")
    base_dt = pd.Timestamp("2026-10-01")

    # Defensive flight case (Defensives up +10%, Cyclicals up +3%)
    # Defensive: XLU, XLP, XLV
    # Cyclical: XLI, XLY, XLF
    bars = {
        "XLI": pd.DataFrame({"Close": [100.0] + [102.0] * (len(dates) - 1)}, index=dates),  # +2.0%
        "XLY": pd.DataFrame({"Close": [100.0] + [104.0] * (len(dates) - 1)}, index=dates),  # +4.0%
        "XLF": pd.DataFrame({"Close": [100.0] + [103.0] * (len(dates) - 1)}, index=dates),  # +3.0% -> Cyc avg = +3.0%
        "XLU": pd.DataFrame({"Close": [100.0] + [110.0] * (len(dates) - 1)}, index=dates),  # +10.0%
        "XLP": pd.DataFrame({"Close": [100.0] + [112.0] * (len(dates) - 1)}, index=dates),  # +12.0%
        "XLV": pd.DataFrame({"Close": [100.0] + [108.0] * (len(dates) - 1)}, index=dates),  # +8.0% -> Def avg = +10.0%
    }
    intel_rot = compute_sector_rotation_intelligence(bars, session_dt, base_dt)
    assert round(intel_rot.cyclical_return, 1) == 3.0
    assert round(intel_rot.defensive_return, 1) == 10.0
    assert round(intel_rot.spread, 1) == -7.0
    assert intel_rot.posture == "Defensive Flight / Capital Preservation"
    assert "Cons. Staples" in intel_rot.leading_defensive


def test_macro_regime_quadrant_mapping():
    """Verify 4-quadrant macroeconomic mapping."""
    intel_credit = CreditSpreadIntelligence(3.26, 326.0, -4.0, "Tight / Complacent", "Benign credit")
    intel_rates = RealRateIntelligence(2.63, 10.0, 2.34, 2.0, 4.98, 12.0, "Real Rate Tightening", "High hurdle")
    intel_vol = VolTermStructureIntelligence(19.42, 20.78, 0.934, -0.01, "Contango (Normal)", "Orderly", "Calm")
    intel_rot = SectorRotationIntelligence(3.0, 10.0, -7.0, "Defensive Flight", "XLY", "XLP", "Defensive flight")

    # 1. Reflation / Late-Cycle Tension across Daily, Weekly, and Monthly
    metrics_reflation = {
        "gdp": MacroMetricSnapshot("GDPC1", "GDP", "2026-10-30", 3.37, 3.37, "%", 3.0, 3.0, 0.37),
        "retail_sales": MacroMetricSnapshot("RSAFS", "Retail Sales", "2026-10-30", 0.77, 0.77, "%", 0.3, 0.3, 0.47),
        "payrolls": MacroMetricSnapshot("PAYEMS", "Payrolls", "2026-10-30", 158000.0, 254.0, "k", 157746.0, 159.0, 95.0),
        "core_cpi": MacroMetricSnapshot("CPILFESL", "Core CPI", "2026-10-30", 3.31, 3.31, "%", 3.2, 3.2, 0.11),
    }

    # Daily
    intel_daily = compute_macro_regime_intelligence(
        metrics_reflation, intel_credit, intel_rates, intel_vol, intel_rot, report_type="daily"
    )
    assert intel_daily.quadrant == "Reflation / Late-Cycle Tension"
    assert "Daily Tactical" in intel_daily.summary_badge
    assert "Tactical Session Posture" in intel_daily.forward_outlook
    assert "Next 1–3 Sessions" in intel_daily.forward_outlook

    # Weekly
    intel_weekly = compute_macro_regime_intelligence(
        metrics_reflation, intel_credit, intel_rates, intel_vol, intel_rot, report_type="weekly"
    )
    assert intel_weekly.quadrant == "Reflation / Late-Cycle Tension"
    assert "Weekly Horizon" in intel_weekly.summary_badge
    assert "Weekly Positioning & Sectors" in intel_weekly.forward_outlook
    assert "Coming Week Watch" in intel_weekly.forward_outlook

    # Monthly
    intel_monthly = compute_macro_regime_intelligence(
        metrics_reflation, intel_credit, intel_rates, intel_vol, intel_rot, report_type="monthly"
    )
    assert intel_monthly.quadrant == "Reflation / Late-Cycle Tension"
    assert "Monthly Strategic" in intel_monthly.summary_badge
    assert "Strategic Macro Regime & Rotation" in intel_monthly.forward_outlook
    assert "recession risks" in intel_monthly.forward_outlook

    # 2. Goldilocks (Growth Resilient + Inflation Easing)
    metrics_goldilocks = {
        "gdp": MacroMetricSnapshot("GDPC1", "GDP", "2026-10-30", 2.8, 2.8, "%", 2.5, 2.5, 0.3),
        "retail_sales": MacroMetricSnapshot("RSAFS", "Retail Sales", "2026-10-30", 0.4, 0.4, "%", 0.3, 0.3, 0.1),
        "payrolls": MacroMetricSnapshot("PAYEMS", "Payrolls", "2026-10-30", 158000.0, 180.0, "k", 157820.0, 150.0, 30.0),
        "core_cpi": MacroMetricSnapshot("CPILFESL", "Core CPI", "2026-10-30", 2.1, 2.1, "%", 2.3, 2.3, -0.2),
    }
    rates_low_be = RealRateIntelligence(1.8, 0.0, 2.05, 0.0, 3.85, 0.0, "Balanced", "Moderate")
    intel_gold = compute_macro_regime_intelligence(
        metrics_goldilocks,
        intel_credit,
        rates_low_be,
        intel_vol,
        intel_rot,
        report_type="monthly",
    )
    assert intel_gold.quadrant == "Goldilocks / Non-Inflationary Expansion"
    assert "Goldilocks Expansion" in intel_gold.summary_badge

    # 3. Stagflation (Growth Slowing + Inflation Sticky)
    metrics_stag = {
        "gdp": MacroMetricSnapshot("GDPC1", "GDP", "2026-10-30", 0.5, 0.5, "%", 0.8, 0.8, -0.3),
        "retail_sales": MacroMetricSnapshot("RSAFS", "Retail Sales", "2026-10-30", -0.5, -0.5, "%", -0.1, -0.1, -0.4),
        "payrolls": MacroMetricSnapshot("PAYEMS", "Payrolls", "2026-10-30", 158000.0, 20.0, "k", 157980.0, 50.0, -30.0),
        "core_cpi": MacroMetricSnapshot("CPILFESL", "Core CPI", "2026-10-30", 4.2, 4.2, "%", 4.0, 4.0, 0.2),
    }
    intel_stag = compute_macro_regime_intelligence(
        metrics_stag,
        intel_credit,
        intel_rates,
        intel_vol,
        intel_rot,
        report_type="monthly",
    )
    assert intel_stag.quadrant.startswith("Stagflationary Pressure")
    assert "Stagflation Risk" in intel_stag.summary_badge


def test_markdown_and_html_forward_looking_integration():
    """Verify that Markdown and HTML renderers include the forward-looking intelligence cleanly."""
    period = PeriodInfo(
        report_type="daily",
        as_of_date="2026-10-30",
        session_date="2026-10-30",
        current_start="2026-10-30",
        current_end="2026-10-30",
        baseline_date="2026-10-29",
        prev_period_start="2026-10-29",
        prev_period_end="2026-10-29",
        prev_baseline_date="2026-10-28",
        is_partial=False,
        session_count=1,
        notes="",
    )

    intel_credit = CreditSpreadIntelligence(3.26, 326.0, -4.0, "Tight / Complacent", "Benign credit")
    intel_rates = RealRateIntelligence(2.63, 10.0, 2.34, 2.0, 4.98, 12.0, "Real Rate Tightening", "High hurdle")
    intel_vol = VolTermStructureIntelligence(19.42, 20.78, 0.934, -0.01, "Contango (Normal)", "Orderly", "Calm")
    intel_rot = SectorRotationIntelligence(3.0, 10.0, -7.0, "Defensive Flight", "XLY", "XLP", "Defensive flight")
    intel_regime = MarketRegimeIntelligence(
        quadrant="Reflation / Late-Cycle Tension",
        growth_signal="Resilient / Expanding",
        inflation_signal="Firm / Sticky",
        summary_badge="Reflation / Late-Cycle Tension",
        forward_outlook="Resilient growth caps downside, but sticky inflation restricts multiples.",
        credit=intel_credit,
        rates=intel_rates,
        vol_term=intel_vol,
        rotation=intel_rot,
    )

    # Mock Scorecard
    sc = Scorecard(
        raw_score=4.5,
        max_score=10.0,
        normalized_score=0.45,
        verdict="Bullish",
        votes=[],
        caution_flags=[],
        top_bullish_factors=["Strong rally"],
        top_bearish_factors=[],
        summary_reasons=["Price above 50 DMA"],
    )

    sec1 = build_executive_summary(scorecard=sc, period_info=period, regime_intelligence=intel_regime)
    sec9 = build_conclusion(scorecard=sc, spx_snap=None, ndx_snap=None, regime_intelligence=intel_regime)

    # 1. Test Markdown output
    md_out = render_markdown(period, [sec1, sec9])
    assert "Macro Regime & Forward Implications (Reflation / Late-Cycle Tension)" in md_out
    assert "Cross-Market Macro Alignment" in md_out
    assert "326 bps OAS" in md_out

    # 2. Test HTML output
    html_out = render_html(period, [sec1, sec9])
    assert "Macro Regime &amp; Forward Implications: Reflation / Late-Cycle Tension" in html_out
    assert "Cross-Market Macro Alignment &amp; Execution Posture" in html_out
    assert "326 bps OAS" in html_out


def test_compute_oas_delta_consistency():
    """Verify that credit spread delta equals new level minus previous level, with sign matching direction."""
    # Falling OAS (spread tightening)
    curr_pct = 3.26
    prev_pct = 3.38
    spread_bps, delta_bps = compute_oas_delta(curr_pct, prev_pct)

    assert spread_bps == 326.0
    assert delta_bps == -12.0
    # Formula check: new level minus previous level equals displayed delta
    assert round(spread_bps - (prev_pct * 100.0), 1) == delta_bps
    assert (curr_pct < prev_pct) and (delta_bps < 0)

    # Rising OAS (spread widening)
    curr_wide = 4.15
    prev_wide = 3.90
    spread_bps2, delta_bps2 = compute_oas_delta(curr_wide, prev_wide)
    assert spread_bps2 == 415.0
    assert delta_bps2 == +25.0
    assert round(spread_bps2 - (prev_wide * 100.0), 1) == delta_bps2
    assert (curr_wide > prev_wide) and (delta_bps2 > 0)


def test_compute_yield_support_resistance():
    """Verify that trailing 3-month high/low are only classified as resistance/support when price respects boundary."""
    # Synthetic 63-day yield history with high of 5.31% and low of 4.63%
    dates = pd.date_range("2026-08-01", periods=63, freq="B")
    vals = [4.63] + [4.90] * 61 + [5.31]
    df = pd.DataFrame({"value": vals}, index=dates)

    # Current yield inside range (4.98%)
    support, resistance = compute_yield_support_resistance(df, current_yield=4.98, lookback_days=63)
    assert support == 4.63
    assert resistance == 5.31

    # Current yield above high (5.35%) -> resistance is None (breaking out), support is low (4.63%)
    sup_bo, res_bo = compute_yield_support_resistance(df, current_yield=5.35, lookback_days=63)
    assert res_bo is None
    assert sup_bo == 4.63

    # Current yield below low (4.50%) -> support is None (breaking down), resistance is high (5.31%)
    sup_bd, res_bd = compute_yield_support_resistance(df, current_yield=4.50, lookback_days=63)
    assert sup_bd is None
    assert res_bd == 5.31


def test_fomc_in_period_resolution():
    """Verify that FOMC meetings occurring within the report period are correctly identified with outcome and next date."""
    # October 2026 weekly period: Oct 23 to Oct 30, 2026. Meeting was on Oct 28, 2026.
    status = resolve_fomc_schedule(
        as_of_date="2026-10-30",
        fed_funds_rate=3.88,
        period_start_date="2026-10-23",
    )

    assert status.occurred_in_period is True
    assert status.last_meeting_date == "2026-10-28"
    assert status.outcome_action == "Hold"
    assert status.vote_count == "10-2"
    assert "Cook and Hammack dissented in favor of a 25 bp hike" in status.dissents
    assert status.rate_target_range == "3.75% – 4.00%"
    assert status.next_meeting_date == "2026-12-09"
    assert status.days_to_next_meeting == 40


def test_forward_outlook_appears_strictly_once():
    """Verify that the Institutional Forward Outlook narrative appears strictly once across the report."""
    period = PeriodInfo(
        report_type="weekly",
        as_of_date="2026-10-30",
        session_date="2026-10-30",
        current_start="2026-10-23",
        current_end="2026-10-30",
        baseline_date="2026-10-23",
        prev_period_start="2026-10-16",
        prev_period_end="2026-10-23",
        prev_baseline_date="2026-10-16",
        is_partial=False,
        session_count=5,
        notes="",
    )

    unique_outlook_text = "UNIQUE_INSTITUTIONAL_FORWARD_OUTLOOK_PARAGRAPH_12345"

    intel_credit = CreditSpreadIntelligence(3.26, 326.0, -12.0, "Tight / Complacent", "Benign credit")
    intel_rates = RealRateIntelligence(2.63, 10.0, 2.34, 2.0, 4.98, 12.0, "Real Rate Tightening", "High hurdle")
    intel_vol = VolTermStructureIntelligence(19.42, 20.78, 0.934, -0.01, "Contango (Normal)", "Orderly", "Calm")
    intel_rot = SectorRotationIntelligence(3.0, 10.0, -7.0, "Defensive Flight", "XLY", "XLP", "Defensive flight", rotation_summary="Defensives outpaced cyclicals.")
    intel_regime = MarketRegimeIntelligence(
        quadrant="Reflation / Late-Cycle Tension",
        growth_signal="Resilient / Expanding",
        inflation_signal="Firm / Sticky",
        summary_badge="Reflation / Late-Cycle Tension",
        forward_outlook=unique_outlook_text,
        credit=intel_credit,
        rates=intel_rates,
        vol_term=intel_vol,
        rotation=intel_rot,
    )

    sc = Scorecard(
        raw_score=4.5,
        max_score=10.0,
        normalized_score=0.45,
        verdict="Bullish",
        votes=[],
        caution_flags=[],
        top_bullish_factors=["Strong rally"],
        top_bearish_factors=[],
        summary_reasons=["Price above 50 DMA"],
    )

    sec1 = build_executive_summary(scorecard=sc, period_info=period, regime_intelligence=intel_regime)
    sec9 = build_conclusion(scorecard=sc, spx_snap=None, ndx_snap=None, regime_intelligence=intel_regime)

    # HTML count
    html_out = render_html(period, [sec1, sec9])
    assert html_out.count(unique_outlook_text) == 1, f"Expected forward outlook exactly 1 time in HTML, found {html_out.count(unique_outlook_text)}"

    # Markdown count
    md_out = render_markdown(period, [sec1, sec9])
    assert md_out.count(unique_outlook_text) == 1, f"Expected forward outlook exactly 1 time in Markdown, found {md_out.count(unique_outlook_text)}"


def test_html_attribute_validity():
    """Verify that no HTML attributes contain '<' or '>' characters or nested tags (Bug 1.8 check)."""
    import re
    period = PeriodInfo(
        report_type="weekly",
        as_of_date="2026-10-30",
        session_date="2026-10-30",
        current_start="2026-10-23",
        current_end="2026-10-30",
        baseline_date="2026-10-23",
        prev_period_start="2026-10-16",
        prev_period_end="2026-10-23",
        prev_baseline_date="2026-10-16",
        is_partial=False,
        session_count=5,
        notes="",
    )
    sc = Scorecard(
        raw_score=4.5,
        max_score=10.0,
        normalized_score=0.45,
        verdict="Neutral",
        votes=[],
        caution_flags=[],
        top_bullish_factors=[],
        top_bearish_factors=[],
        summary_reasons=["Balanced market"],
    )
    sec1 = build_executive_summary(scorecard=sc, period_info=period)
    sec9 = build_conclusion(scorecard=sc, spx_snap=None, ndx_snap=None)

    html_out = render_html(period, [sec1, sec9])
    invalid_class_tags = re.findall(r'class=[\"\'][^\"\']*<[^\"\']*[\"\']', html_out)
    assert len(invalid_class_tags) == 0, f"Found invalid tags inside class attribute: {invalid_class_tags}"
