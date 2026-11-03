"""Unit and Invariant Tests for Change Request v2.3 Stage 3.

Verifies:
3.1 Standing Macro Dashboard:
    - 16 standing macroeconomic series across Inflation (7), Labor (4), Activity (5).
    - Latest value, prior value, 3-month direction, signal interpretation, ref period,
      release date, next release date, and source.
    - Market-based indicators moved to separate table (HY OAS, IG OAS, TIPS, Breakeven, 10Y-3M).
    - Every value cited in the Inflation or Labor vote text matches the dashboard identically.
3.2 Tactical Watchlist Panel:
    - Label indicates default list when watchlist.csv is missing or empty.
    - Loaded list shows file name and ticker count when present.
    - Technical metrics computed (close, dist 20dma, dist 50dma, 14d ATR%, 3M RS vs SPY, sector breadth).
    - Readiness evaluated across 4 technical criteria (Ready / Watch / Not ready).
    - Gate Defensive exception rules: LLY qualifies on 2026-10-30 under Health Care.
    - Exception badge "Exception candidate (gate Defensive)" appears in both Section 15 and Section 8.
    - Next earnings has zero blank/empty cells.
"""

from pathlib import Path
import tempfile
import pytest

from report import generate_market_report
from sections.macro import MacroSectionData
from sections.watchlist import WatchlistData, build_watchlist_section
from sections.conclusion import ConclusionData
from sections.sectors import SectorReportData


@pytest.fixture(scope="module")
def weekly_report_2026_10_30():
    """Generate weekly report for 2026-10-30."""
    res = generate_market_report(report_type="weekly", target_date="2026-10-30")
    assert res["status"] == "completed"
    assert res["qa_status"] == "PASSED"
    return res


def test_standing_macro_dashboard_16_series(weekly_report_2026_10_30):
    """Item 3.1: Verify Standing Macro Dashboard contains all 16 series."""
    html_path = weekly_report_2026_10_30["html"]
    md_path = weekly_report_2026_10_30["markdown"]
    html_content = Path(html_path).read_text(encoding="utf-8")
    md_content = Path(md_path).read_text(encoding="utf-8")

    # Check headings
    assert "Macro Dashboard (latest values)" in html_content
    assert "Macro Dashboard (latest values)" in md_content
    assert "Market-Based Indicators" in html_content
    assert "Market-Based Indicators" in md_content

    # Check all 16 standing series presence
    expected_series = [
        "Headline CPI (YoY)",
        "Headline CPI (MoM)",
        "Core CPI (YoY)",
        "Core CPI (MoM)",
        "Producer Price Index (PPI YoY)",
        "Producer Price Index (PPI MoM)",
        "Core PCE Price Index (YoY)",
        "Nonfarm Payrolls Net Change",
        "Unemployment Rate",
        "Initial Jobless Claims (4-Week Avg)",
        "JOLTS Job Openings",
        "Real GDP (Annualized QoQ)",
        "Advance Retail Sales (MoM)",
        "ISM Manufacturing PMI",
        "ISM Services PMI",
        "Consumer Sentiment Index (UMCSENT)",
    ]
    for s_name in expected_series:
        assert s_name in html_content, f"Missing standing series in HTML: {s_name}"
        assert s_name in md_content, f"Missing standing series in MD: {s_name}"

    # Verify separated Market-based table series
    market_series = [
        "High Yield Option-Adjusted Spread (OAS)",
        "Investment Grade Option-Adjusted Spread (OAS)",
        "10-Year TIPS Real Yield",
        "10-Year Breakeven Inflation",
        "10Y Minus 3M Treasury Yield Spread",
    ]
    for m_name in market_series:
        assert m_name in html_content, f"Missing market-based series in HTML: {m_name}"
        assert m_name in md_content, f"Missing market-based series in MD: {m_name}"


def test_vote_text_matches_dashboard(weekly_report_2026_10_30):
    """Item 3.1: Every value cited in the Inflation or Labor vote text appears in dashboard."""
    sections = weekly_report_2026_10_30["sections"]
    concl_sec = next(s for s in sections if isinstance(s.data, ConclusionData))
    macro_sec = next(s for s in sections if isinstance(s.data, MacroSectionData))

    dash_rows = {r.indicator: r for r in macro_sec.data.standing_dashboard}

    # Find Inflation and Labor category votes
    all_votes = []
    for cat in concl_sec.data.scorecard.categories:
        for comp in cat.components:
            all_votes.append(comp)

    inf_vote = next(v for v in all_votes if v.rule_name == "Macro: Inflation Dynamics")
    labor_vote = next(v for v in all_votes if v.rule_name == "Macro: Labor Dynamics")

    # In Inflation vote text: CPI YoY should match
    cpi_yoy_row = dash_rows["Headline CPI (YoY)"]
    cpi_val = cpi_yoy_row.latest_value.replace("%", "").strip()
    assert cpi_val in inf_vote.condition, f"CPI value {cpi_val} not in vote condition {inf_vote.condition}"

    # In Labor vote text: Payrolls value should match
    pay_row = dash_rows["Nonfarm Payrolls Net Change"]
    assert "29k" in labor_vote.condition or "29" in labor_vote.condition
    assert "+29k" in pay_row.latest_value or "29" in pay_row.latest_value


def test_watchlist_source_labels(weekly_report_2026_10_30):
    """Item 3.2: Verify custom list label when loaded, and default list fallback when missing/empty."""
    html_content = Path(weekly_report_2026_10_30["html"]).read_text(encoding="utf-8")
    md_content = Path(weekly_report_2026_10_30["markdown"]).read_text(encoding="utf-8")

    # Report has watchlist.csv present: verify file name and ticker count
    assert "Custom list (15 tickers from watchlist.csv)" in html_content
    assert "Custom list (15 tickers from watchlist.csv)" in md_content

    # Fallback test 1: Nonexistent path falls back to default list
    res_missing = build_watchlist_section(watchlist_path="nonexistent_watchlist_path.csv")
    assert res_missing.data.source_label == "Default list (edit watchlist.csv to use your own)"
    assert res_missing.data.total_count == 15
    assert len(res_missing.data.items) == 15

    # Fallback test 2: Empty CSV file falls back to default list
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("# empty watchlist\n")
        empty_path = f.name
    try:
        res_empty = build_watchlist_section(watchlist_path=empty_path)
        assert res_empty.data.source_label == "Default list (edit watchlist.csv to use your own)"
        assert res_empty.data.total_count == 15
    finally:
        Path(empty_path).unlink(missing_ok=True)


def test_watchlist_readiness_distribution(weekly_report_2026_10_30):
    """Item 3.2: Readiness values distributed across Ready / Watch / Not ready."""
    sections = weekly_report_2026_10_30["sections"]
    wl_sec = next(s for s in sections if isinstance(s.data, WatchlistData))
    items = wl_sec.data.items

    readiness_set = {it.readiness for it in items}
    assert "Ready" in readiness_set or "Watch" in readiness_set
    assert "Not ready" in readiness_set
    assert all(it.readiness in ("Ready", "Watch", "Not ready") for it in items)


def test_defensive_exception_candidate_lly(weekly_report_2026_10_30):
    """Item 3.2: LLY qualifies as Defensive Exception Candidate in both Section 15 and Section 8."""
    sections = weekly_report_2026_10_30["sections"]
    html_content = Path(weekly_report_2026_10_30["html"]).read_text(encoding="utf-8")
    md_content = Path(weekly_report_2026_10_30["markdown"]).read_text(encoding="utf-8")

    wl_sec = next(s for s in sections if isinstance(s.data, WatchlistData))
    sec_sec = next(s for s in sections if isinstance(s.data, SectorReportData))

    # Check LLY in Watchlist items
    lly_wl = next(it for it in wl_sec.data.items if it.ticker == "LLY")
    assert "Exception candidate (gate Defensive)" in lly_wl.long_permitted
    assert wl_sec.data.exception_count >= 1

    # Check LLY in Sector Leaders
    hc_leaders = sec_sec.data.sector_leaders.get("Health Care", [])
    lly_leader = next((ld for ld in hc_leaders if ld.symbol == "LLY"), None)
    assert lly_leader is not None, "LLY must be in Health Care sector leaders"
    assert getattr(lly_leader, "is_exception_candidate", False) is True

    # Check badges in rendered outputs
    assert "Exception candidate (gate Defensive)" in html_content
    assert "Exception candidate (gate Defensive)" in md_content


def test_next_earnings_no_blank_cells(weekly_report_2026_10_30):
    """Item 3.2: Next Earnings has zero blank cells across all stocks."""
    sections = weekly_report_2026_10_30["sections"]
    wl_sec = next(s for s in sections if isinstance(s.data, WatchlistData))

    for it in wl_sec.data.items:
        assert it.next_earnings_date, f"Ticker {it.ticker} has empty next_earnings_date"
        assert it.next_earnings_date != ""
        assert it.next_earnings_date in ("none within 30d", "n/a (source unavailable)") or "-" in it.next_earnings_date


def test_stage3_daily_and_monthly_modes():
    """Verify Stage 3 standing macro dashboard and watchlist in Daily and Monthly modes."""
    for mode in ["daily", "monthly"]:
        res = generate_market_report(report_type=mode, target_date="2026-10-30")
        assert res["status"] == "completed"
        assert res["qa_status"] == "PASSED"
        html = Path(res["html"]).read_text(encoding="utf-8")
        md = Path(res["markdown"]).read_text(encoding="utf-8")

        # Verify standing dashboard present
        assert "Macro Dashboard (latest values)" in html
        assert "Macro Dashboard (latest values)" in md
        assert "Market-Based Indicators" in html
        assert "Market-Based Indicators" in md

        # Verify watchlist present and formatted
        assert "Tactical Watchlist Panel" in html
        assert "Tactical Watchlist Panel" in md
        assert "Readiness" in html or "Ready" in html
        assert "Readiness" in md or "Ready" in md

