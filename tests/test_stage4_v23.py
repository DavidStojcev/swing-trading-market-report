"""Stage 4 Test Suite (v2.3): Data-source decisions (Fed rate probabilities, Valuation & ERP, Actual vs Consensus)."""

import pytest
import pandas as pd

from data.calendar import PeriodInfo
from report import generate_market_report
from render.html import render_html
from render.markdown import render_markdown
from sections.base import SectionResult
from sections.fed_path import (
    FedPathData,
    build_fed_path,
    derive_fed_rate_probabilities,
)
from sections.macro import MacroSectionData
from sections.valuation import (
    ValuationData,
    build_valuation_section,
    compute_valuation_vs_rates,
)
from scoring.rules import evaluate_rates_macro_category


def _dummy_period(report_type: str = "weekly", dt: str = "2026-10-30") -> PeriodInfo:
    return PeriodInfo(
        report_type=report_type,
        as_of_date=dt,
        session_date=dt,
        current_start="2026-10-26",
        current_end=dt,
        baseline_date="2026-10-23",
        prev_period_start="2026-10-19",
        prev_period_end="2026-10-23",
        prev_baseline_date="2026-10-16",
        is_partial=False,
        session_count=5,
        notes="",
    )


def test_4_1_fed_rate_probabilities_derivation():
    """Test 4.1: Derive Hold / +25 / -25 probabilities from 30-day Fed funds futures (ZQ contracts)."""
    hold, hike, cut, src = derive_fed_rate_probabilities(
        as_of_date="2026-10-30",
        next_meeting_date="2026-12-09",
        effective_fed_funds=3.88,
    )

    assert hold is not None, "Hold probability should be derived from ZQ contract"
    assert hike is not None, "Hike probability should be derived from ZQ contract"
    assert cut is not None, "Cut probability should be derived from ZQ contract"

    # Probabilities must sum to ~1.0
    total_p = hold + hike + cut
    assert pytest.approx(total_p, abs=0.01) == 1.0, f"Probabilities sum to {total_p}, expected 1.0"

    # Source must include contract symbol and timestamp
    assert "CBOT 30-Day Fed Funds Futures" in src
    assert "ZQ" in src
    assert "16:00 ET" in src or "2026-10-30" in src

    # Test graceful fallback when contract data is missing/invalid
    hold_none, hike_none, cut_none, src_none = derive_fed_rate_probabilities(
        as_of_date="1980-01-01",  # historical date without ZQ data
        next_meeting_date="1980-02-15",
        effective_fed_funds=12.0,
    )
    assert hold_none is None
    assert hike_none is None
    assert cut_none is None
    assert "n/a (source unavailable)" in src_none


def test_4_1_fed_rate_probabilities_collapsed_panel_rendering():
    """Test 4.1: Collapse Fed rate probability panel to 'n/a (source unavailable)' when data missing."""
    p_info = _dummy_period()

    # Case A: Unavailable probabilities
    fed_data_unavail = FedPathData(
        last_action_date="2026-10-28",
        last_action_description="Target held at 3.75% – 4.00%",
        current_target_range="3.75% – 4.00%",
        effective_fed_funds=3.88,
        next_meeting_date="2026-12-09",
        days_to_next_meeting=40,
        market_implied_prob_hold=None,
        market_implied_prob_hike=None,
        market_implied_prob_cut=None,
        yield_2y=4.61,
        spread_2y_vs_fed_funds_bps=73.0,
        trailing_core_inflation=3.12,
        real_policy_rate=0.76,
        assessment="Fed policy remains restrictive.",
        prob_source="n/a (source unavailable)",
    )
    sec_unavail = SectionResult(section_num=9, title="Federal Reserve Policy Path", status="available", data=fed_data_unavail)

    html_out = render_html(p_info, [sec_unavail], {})
    md_out = render_markdown(p_info, [sec_unavail], {})

    # Must collapse to 'n/a (source unavailable)' and NOT print 'Hold n/a • +25 bps Hike n/a'
    assert "Market-Implied Probabilities:</strong> <span class=\"text-muted font-mono\">n/a (source unavailable)</span>" in html_out
    assert "Hold n/a" not in html_out
    assert "Market-Implied Probability for Next Decision:** `n/a (source unavailable)`" in md_out
    assert "Hold: n/a" not in md_out

    # Case B: Available probabilities
    fed_data_avail = FedPathData(
        last_action_date="2026-10-28",
        last_action_description="Target held at 3.75% – 4.00%",
        current_target_range="3.75% – 4.00%",
        effective_fed_funds=3.88,
        next_meeting_date="2026-12-09",
        days_to_next_meeting=40,
        market_implied_prob_hold=0.295,
        market_implied_prob_hike=0.705,
        market_implied_prob_cut=0.0,
        yield_2y=4.61,
        spread_2y_vs_fed_funds_bps=73.0,
        trailing_core_inflation=3.12,
        real_policy_rate=0.76,
        assessment="Fed policy remains restrictive.",
        prob_source="CBOT 30-Day Fed Funds Futures (ZQZ26.CBT: 95.995, as of 2026-10-30 16:00 ET)",
    )
    sec_avail = SectionResult(section_num=9, title="Federal Reserve Policy Path", status="available", data=fed_data_avail)

    html_avail = render_html(p_info, [sec_avail], {})
    md_avail = render_markdown(p_info, [sec_avail], {})

    assert "Hold <strong>29.5%</strong>" in html_avail
    assert "+25 bps Hike <strong>70.5%</strong>" in html_avail
    assert "-25 bps Cut <strong>0.0%</strong>" in html_avail
    assert "ZQZ26.CBT" in html_avail
    assert "Hold: `29.5%`" in md_avail
    assert "+25 bps Hike: `70.5%`" in md_avail


def test_4_2_valuation_and_erp_computation_and_collapsing():
    """Test 4.2: Compute ERP only when forward EPS is verified; collapse panel to 'n/a (source unavailable)' when missing."""
    p_info = _dummy_period()

    # Case A: Forward EPS is verified
    val_verified = compute_valuation_vs_rates(
        forward_pe=22.50,
        nominal_10y=4.25,
        real_10y=1.95,
        eps_revision_trend="Positive (+1.8%)",
        source="Consensus Forward EPS (FactSet)",
    )
    assert val_verified.forward_pe == 22.50
    assert val_verified.earnings_yield_pct == pytest.approx(4.4444, abs=0.01)
    # Nominal ERP = 4.4444% - 4.25% = +0.1944% = +19.44 bps
    assert val_verified.nominal_erp_bps == pytest.approx(19.44, abs=0.5)
    # Real ERP = 4.4444% - 1.95% = +2.4944% = +249.44 bps
    assert val_verified.real_erp_bps == pytest.approx(249.44, abs=0.5)

    sec_ver = SectionResult(section_num=5, title="S&P 500 Valuation vs Rates", status="available", data=val_verified)
    html_ver = render_html(p_info, [sec_ver], {})
    md_ver = render_markdown(p_info, [sec_ver], {})

    assert "22.50x" in html_ver
    assert "4.44%" in html_ver
    assert "+19.4 bps" in html_ver or "+19.44 bps" in html_ver
    assert "22.50x" in md_ver

    # Case B: Forward EPS is unavailable (missing/unverified)
    val_unavail = compute_valuation_vs_rates(
        forward_pe=None,
        nominal_10y=4.25,
        real_10y=1.95,
        source="n/a (source unavailable)",
    )
    assert val_unavail.forward_pe is None
    assert val_unavail.earnings_yield_pct is None
    assert val_unavail.nominal_erp_bps is None
    assert val_unavail.real_erp_bps is None

    sec_unver = SectionResult(section_num=5, title="S&P 500 Valuation vs Rates", status="available", data=val_unavail)
    html_unver = render_html(p_info, [sec_unver], {})
    md_unver = render_markdown(p_info, [sec_unver], {})

    # Panel must collapse to single 'n/a (source unavailable)' line and NOT render empty table
    assert "n/a (source unavailable)" in html_unver
    assert "Forward multiple on consensus 12M EPS" not in html_unver
    assert "n/a (source unavailable)" in md_unver
    assert "Forward multiple on consensus 12M EPS" not in md_unver


def test_4_3_actual_vs_consensus_and_no_consensus_tag():
    """Test 4.3: Economic releases without forecast show 'n/a (no consensus)'; direction-based votes tagged."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")

    # In MacroSectionData recent_releases, unpolled or synthesized events have '(no consensus)' tag
    macro_data = None
    for s in res["sections"]:
        if isinstance(s.data, MacroSectionData):
            macro_data = s.data
            break

    assert macro_data is not None, "MacroSectionData section must be present"

    # Evaluate direction-based votes
    score, votes, status = evaluate_rates_macro_category(macro_data)
    for v in votes:
        if "direction-based" in v.condition:
            assert "[direction-based (no consensus)]" in v.condition, (
                f"Vote '{v.rule_name}' condition must be tagged with '[direction-based (no consensus)]'"
            )


@pytest.mark.parametrize("report_type", ["daily", "weekly", "monthly"])
def test_4_4_multimode_verification(report_type):
    """Test 4.4: Run Daily, Weekly, and Monthly reports for 2026-10-30; verify all Stage 4 invariants."""
    res = generate_market_report(report_type=report_type, target_date="2026-10-30")

    sections = res["sections"]
    scorecard = res["scorecard"]
    html_path = res["html"]
    md_path = res["markdown"]

    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    assert len(sections) > 10
    assert scorecard is not None
    assert len(html_text) > 5000
    assert len(md_text) > 1000

    # 1. Fed rate probabilities derived with ZQ futures and source
    assert "ZQZ26.CBT" in html_text, f"{report_type} HTML missing ZQ contract source"
    assert "Hold" in html_text
    assert "+25 bps Hike" in html_text
    assert "-25 bps Cut" in html_text

    # 2. Valuation & ERP collapsed when unverified
    assert "n/a (source unavailable)" in html_text

    # 3. No raw broken 'Hold n/a'
    assert "Hold n/a" not in html_text
    assert "Hold: n/a" not in md_text
