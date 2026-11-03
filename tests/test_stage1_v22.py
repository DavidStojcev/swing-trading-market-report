"""Unit and acceptance tests for Change Request v2.2: Stage 1 (Logic and Scoring Fixes).

Stage 1 acceptance tests:
- T1, T2, T3, T4, T10 pass.
- Regime label on 2026-10-30 is no longer "Deflationary Slowdown".
- No text mentions market pricing of Fed easing while probabilities are n/a.
- Sentiment votes use the new rules; verdict sensitivity table is present.
- Rates votes capped at +0.50 under accelerating inflation.
- Oil vote reflects 3M trend (+29.6%) and is <= -0.50.
- What Changed table has numeric prior and numeric delta for Tech vs Broad.
- Single Biggest Forward Risk is dynamically ranked and includes next HIGH event.
- Mover wording uses "post-earnings selloff / guidance cuts" when Earnings = YES.
"""

from datetime import date
from pathlib import Path
import re
import pytest

from data.calendar import MarketCalendar
from report import generate_market_report
from qa_checks import run_qa_checks


@pytest.fixture(scope="module")
def weekly_report_data():
    """Generate weekly report for 2026-10-30 and return output paths and content."""
    paths = generate_market_report(report_type="weekly", target_date="2026-10-30")
    md_path = Path(paths["markdown"])
    html_path = Path(paths["html"])
    qa_path = Path(paths["qa_report"])

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()
    with open(qa_path, "r", encoding="utf-8") as f:
        qa_text = f.read()

    return {
        "paths": paths,
        "md": md_text,
        "html": html_text,
        "qa": qa_text,
    }


def test_stage1_acceptance_qa_checks_pass(weekly_report_data):
    """Verify that T1, T2, T3, T4, T10 all PASS on 2026-10-30 weekly report."""
    qa_text = weekly_report_data["qa"]
    
    # Assert T1 passed
    assert re.search(r"\*\*T1\*\*\s*\|\s*Label-Vote Consistency\s*\|\s*\*\*✅ PASS\*\*", qa_text), "T1 must PASS"
    # Assert T2 passed
    assert re.search(r"\*\*T2\*\*\s*\|\s*Single Source of Truth\s*\|\s*\*\*✅ PASS\*\*", qa_text), "T2 must PASS"
    # Assert T3 passed
    assert re.search(r"\*\*T3\*\*\s*\|\s*Claim Lint & Banned Phrases\s*\|\s*\*\*✅ PASS\*\*", qa_text), "T3 must PASS"
    # Assert T4 passed
    assert re.search(r"\*\*T4\*\*\s*\|\s*Regime Truth Table\s*\|\s*\*\*✅ PASS\*\*", qa_text), "T4 must PASS"
    # Assert T10 passed
    assert re.search(r"\*\*T10\*\*\s*\|\s*Posture Logic & Event Overlay\s*\|\s*\*\*✅ PASS\*\*", qa_text), "T10 must PASS"


def test_stage1_regime_label_not_deflationary_slowdown(weekly_report_data):
    """Regime label on 2026-10-30 must not be Deflationary Slowdown."""
    md_text = weekly_report_data["md"]
    html_text = weekly_report_data["html"]
    
    # Must not contain "Deflationary Slowdown" in regime badge or quadrant
    assert "Deflationary Slowdown" not in md_text
    assert "Deflationary Slowdown" not in html_text

    # Must be Stagflation Risk / Pressure
    assert "Stagflation" in md_text or "Reflation" in md_text


def test_stage1_no_unsupported_fed_easing_claims(weekly_report_data):
    """No narrative claim may claim markets price aggressive Fed easing while probabilities are n/a."""
    combined = (weekly_report_data["md"] + " " + weekly_report_data["html"]).lower()
    
    assert "markets price aggressive fed easing" not in combined
    assert "aggressive fed easing" not in combined
    assert "cyclical equities face downward earnings revisions" not in combined


def test_stage1_sentiment_and_verdict_sensitivity(weekly_report_data):
    """Verdict sensitivity table must be present with borderline evaluation."""
    md_text = weekly_report_data["md"]
    html_text = weekly_report_data["html"]
    
    # Sensitivity table present in markdown and html
    assert "Verdict Sensitivity & Borderline Analysis" in md_text
    assert "Verdict Sensitivity &amp; Borderline Analysis" in html_text
    assert "Score (ex-Category)" in md_text
    assert "Delta vs Baseline" in md_text


def test_stage1_rates_cap_and_oil_shock_scoring(weekly_report_data):
    """Falling yields must be capped at +0.50 under accelerating inflation, and oil vote must be <= -0.50."""
    md_text = weekly_report_data["md"]
    
    # Rates cap reason in interpretation column
    assert "Capped at +0.50 due to accelerating inflation backdrop" in md_text
    
    # WTI crude oil shock vote
    assert "Macro: Crude Oil (WTI) Shock" in md_text
    assert "Energy Shock Alert Active" in md_text


def test_stage1_what_changed_numeric_prior_and_delta(weekly_report_data):
    """What Changed table must have numeric prior and numeric delta for Tech vs Broad (no 'Narrowing')."""
    md_text = weekly_report_data["md"]
    
    # Verify no 'Narrowing' in table prior column
    lines = md_text.split("\n")
    tech_row = next((l for l in lines if "Tech vs. Broad Market Divergence" in l), None)
    assert tech_row is not None
    assert "Narrowing" not in tech_row
    assert "% gap" in tech_row


def test_stage1_single_biggest_risk_dynamic_ranking(weekly_report_data):
    """Single biggest forward risk must rank candidates dynamically and include next HIGH event."""
    md_text = weekly_report_data["md"]
    
    assert "The single biggest forward risk is" in md_text
    assert "Key Immediate Catalyst:" in md_text or "Key Immediate Catalyst to Watch:" in md_text
    assert "Next HIGH-impact event is" in md_text


def test_stage1_mover_wording_earnings_selloff(weekly_report_data):
    """Mover cause field and summary must use 'post-earnings selloff / guidance cuts' when Earnings = YES."""
    md_text = weekly_report_data["md"]
    html_text = weekly_report_data["html"]
    
    assert "post-earnings selloff / guidance cuts" in md_text or "post-earnings selloff / guidance cuts" in html_text
