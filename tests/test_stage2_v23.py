"""Unit and Invariant Tests for Change Request v2.3 Stage 2.

Verifies:
1. Removal of "elevated term premium" / "term premium" from Fed section.
2. Neutral wording replacing "institutional" (no "Medium-term institutional trend regime",
   no "institutional distribution").
3. Resolution of template glitch ("Tactical leadership reflects Sector returns show leadership in...").
4. Elimination of duplicate sentence ("The sharpest rank contraction was Energy...").
5. Watchlist "Close" column has zero literal backslashes ("\\$1,417.54").
6. Section titles referenced in cross-links match headings exactly:
   - Section 10: "Commodities, Currencies & Cross-Asset Tracker"
   - Section 12: "Forward Calendar & Catalyst Horizon"
"""

import re
from pathlib import Path
from bs4 import BeautifulSoup
import pytest

from report import generate_market_report


@pytest.fixture(scope="module")
def weekly_report_data_v23():
    """Generate weekly report for 2026-10-30."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")
    assert res["status"] == "completed"
    assert res["qa_status"] == "PASSED"
    return res


def test_no_term_premium_claim(weekly_report_data_v23):
    """Item 2.1: Verify 'term premium' is removed unless term premium model added."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    md = Path(weekly_report_data_v23["markdown"]).read_text(encoding="utf-8")
    
    assert "term premium" not in html.lower()
    assert "term premium" not in md.lower()
    assert "elevated term premium" not in html.lower()
    assert "elevated term premium" not in md.lower()


def test_neutral_institutional_wording(weekly_report_data_v23):
    """Item 2.2: Verify 'institutional' wording is replaced with neutral phrasing."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    md = Path(weekly_report_data_v23["markdown"]).read_text(encoding="utf-8")

    assert "institutional distribution" not in html.lower()
    assert "institutional distribution" not in md.lower()
    assert "institutional trend" not in html.lower()
    assert "institutional trend" not in md.lower()
    assert "institutional participation" not in html.lower()
    assert "institutional liquidation" not in html.lower()


def test_template_glitch_resolved(weekly_report_data_v23):
    """Item 2.3: Verify sentence assembly glitch is resolved."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    md = Path(weekly_report_data_v23["markdown"]).read_text(encoding="utf-8")

    # The collision was "Tactical leadership reflects Sector returns show leadership in"
    assert "tactical leadership reflects sector returns" not in html.lower()
    assert "tactical leadership reflects sector returns" not in md.lower()
    assert "leadership reflects sector returns" not in html.lower()
    assert "leadership reflects sector returns" not in md.lower()


def test_no_duplicate_sentence_across_sections(weekly_report_data_v23):
    """Item 2.4: Verify 'The sharpest rank contraction was...' appears at most once."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    md = Path(weekly_report_data_v23["markdown"]).read_text(encoding="utf-8")

    target_phrase = "posted the strongest momentum shift"
    assert html.count(target_phrase) <= 1
    assert md.count(target_phrase) <= 1

    # In addition, check that no sentence of 12+ words appears > 1 time
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["thead", "th", "script", "style", "svg"]):
        tag.decompose()
    text = soup.get_text()
    sentences = re.split(r"[\.\?!]\s+", text)
    cleaned = []
    for s in sentences:
        s_clean = " ".join(s.strip().split())
        words = s_clean.split()
        if len(words) >= 12:
            cleaned.append(s_clean)

    from collections import Counter
    counts = Counter(cleaned)
    duplicates = {s: c for s, c in counts.items() if c > 1}
    assert not duplicates, f"Found duplicate sentences in HTML: {duplicates}"


def test_watchlist_no_literal_backslash(weekly_report_data_v23):
    """Item 2.5: Verify Watchlist Close column and HTML output have no literal backslash '\\$'."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    assert r"\$" not in html
    # Assert dollar signs are properly formatted
    assert "$1,417.54" in html


def test_cross_link_headings_match_exactly(weekly_report_data_v23):
    """Item 2.6: Verify section titles referenced in cross-links match headings exactly."""
    html = Path(weekly_report_data_v23["html"]).read_text(encoding="utf-8")
    md = Path(weekly_report_data_v23["markdown"]).read_text(encoding="utf-8")

    # Section 10: "Commodities, Currencies & Cross-Asset Tracker"
    assert (
        "Section 10: Commodities, Currencies &amp; Cross-Asset Tracker" in html
        or "Section 10: Commodities, Currencies & Cross-Asset Tracker" in html
    )
    assert "Section 10: Commodities & Cross-Asset Intelligence" not in html
    assert "Section 10: Commodities &amp; Cross-Asset Intelligence" not in html

    assert "Section 10: Commodities, Currencies & Cross-Asset Tracker" in md
    assert "Section 10: Commodities & Cross-Asset Intelligence" not in md

    # Section 12: "Forward Calendar & Catalyst Horizon"
    assert (
        "Section 12: Forward Calendar &amp; Catalyst Horizon" in html
        or "Section 12: Forward Calendar & Catalyst Horizon" in html
    )
    assert "Section 12: Forward Calendar & Catalyst Radar" not in html
    assert "Section 12: Forward Calendar &amp; Catalyst Radar" not in html

    assert "Section 12: Forward Calendar & Catalyst Horizon" in md
    assert "Section 12: Forward Calendar & Catalyst Radar" not in md


def test_stage2_daily_and_monthly_modes():
    """Verify Stage 2 invariants in Daily and Monthly modes."""
    for mode in ["daily", "monthly"]:
        res = generate_market_report(report_type=mode, target_date="2026-10-30")
        assert res["status"] == "completed"
        assert res["qa_status"] == "PASSED"
        html = Path(res["html"]).read_text(encoding="utf-8")
        assert r"\$" not in html
        assert "term premium" not in html.lower()
        assert "institutional distribution" not in html.lower()
        assert "tactical leadership reflects sector returns" not in html.lower()
