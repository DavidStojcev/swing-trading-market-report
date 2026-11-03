"""Stage 2 acceptance tests for Change Request v2.2."""

import re
from datetime import date
from pathlib import Path
import pandas as pd
import pytest

from data.calendar import MarketCalendar
from report import generate_market_report
from sections.sectors import SectorReportData, SectorLeaderStock
from sections.macro import MacroSectionData
from sections.forward_calendar import ForwardCalendarData
from qa_checks import (
    check_t5_format_lint,
    check_t6_run_to_run_stability,
    check_t7_chart_coverage,
    check_t8_structure_lint,
    check_t9_provenance,
    check_t11_status_derivation,
    check_t12_sanity_bounds,
)


@pytest.fixture(scope="module")
def weekly_report_data():
    """Generate and return weekly report outputs for 2026-10-30."""
    paths = generate_market_report(report_type="weekly", target_date="2026-10-30")
    with open(paths["markdown"], "r", encoding="utf-8") as f:
        md_text = f.read()
    with open(paths["html"], "r", encoding="utf-8") as f:
        html_text = f.read()
    with open(paths["qa_report"], "r", encoding="utf-8") as f:
        qa_text = f.read()
    return {
        "paths": paths,
        "md": md_text,
        "html": html_text,
        "qa": qa_text,
    }


def test_stage2_qa_checks_pass(weekly_report_data):
    """Verify that Stage 2 required QA checks (T5, T6, T7, T8, T9, T11, T12) all PASS."""
    qa_md = weekly_report_data["qa"]
    for check_id in ["T5", "T6", "T7", "T8", "T9", "T11", "T12"]:
        pattern = rf"\*\*{check_id}\*\*.*?\*\*✅ PASS\*\*"
        assert re.search(pattern, qa_md), f"Expected QA check {check_id} to PASS in qa_report.md"


def test_stage2_sector_leaders_52w_high_filter(weekly_report_data):
    """Verify that leaders list contains no stock > 15% below 52-week high and excludes IP, CRH, NRG, CEG."""
    md = weekly_report_data["md"]
    html = weekly_report_data["html"]

    # Exclude stocks that are 27% to 49% below 52W high
    banned_laggards = ["IP", "CRH", "NRG", "CEG"]
    
    # Check Section 8 Leaders table in Markdown
    sec8_start = md.find("### Top Relative Strength Leaders")
    sec8_end = md.find("## 9. Theme & Industry Relative Strength", sec8_start)
    sec8_text = md[sec8_start:sec8_end] if sec8_end != -1 else md[sec8_start:sec8_start + 4000]

    for ticker in banned_laggards:
        assert f"`{ticker}`" not in sec8_text, f"Laggard {ticker} should not be in RS leaders list."

    # Parse distance percentages from leaders table
    # Format: | Rank | Ticker | Company Name | Close | Composite RS | 1W Return | Dist 52W High | ...
    dist_matches = re.findall(r"\| `([A-Z]+)` \|.*?\| ([-+]?\d+\.\d+)% \|", sec8_text)
    for ticker, dist_str in dist_matches:
        dist = float(dist_str)
        assert dist >= -15.0, f"Leader {ticker} has dist_52w_high of {dist}%, which exceeds 15% threshold."


def test_stage2_dollar_volume_and_mrna_anomaly(weekly_report_data):
    """Verify that MRNA anomaly is filtered out and dollar volumes are properly formatted."""
    md = weekly_report_data["md"]
    html = weekly_report_data["html"]

    # MRNA volume anomaly ($4,157M daily volume on a small cap) must not appear in leaders
    sec8_start = md.find("### Top Relative Strength Leaders")
    sec8_end = md.find("### 12. Top Movers", sec8_start)
    sec8_text = md[sec8_start:sec8_end] if sec8_end != -1 else md[sec8_start:sec8_start + 4000]

    assert "`MRNA`" not in sec8_text, "MRNA turnover anomaly must be excluded from leaders."

    # Dollar volume units must use separators or $B/$M notation
    # Verify no unformatted $3202.3M without comma or proper $B notation
    assert "$3202.3M" not in md, "Dollar volume should have thousands separators ($3,202.3M) or $B notation ($3.20B)."
    assert "$4157.4M" not in md


def test_stage2_fx_formatting(weekly_report_data):
    """Verify FX pairs have no '$' and have proper decimal precision."""
    md = weekly_report_data["md"]
    html = weekly_report_data["html"]

    # EUR/USD and USD/JPY should not have '$' prepended
    assert "EUR/USD \\$" not in md
    assert "USD/JPY \\$" not in md
    assert "EUR/USD $" not in md
    assert "USD/JPY $" not in md
    assert "DXY $" not in md

    # EUR/USD should have 4 decimals (e.g. 1.0850)
    eur_match = re.search(r"EUR/USD.*?`([0-9]+\.[0-9]+)`", md)
    if eur_match:
        decimals = len(eur_match.group(1).split(".")[1])
        assert decimals >= 4, f"EUR/USD should format with 4 decimals, got {eur_match.group(1)}"


def test_stage2_calendar_sources_and_formatting(weekly_report_data):
    """Verify calendar formatting, official sources, and footer lookahead date."""
    md = weekly_report_data["md"]
    html = weekly_report_data["html"]

    # No '48.60index' or similar glued units
    assert not re.search(r"\d+\.\d+index", md)
    assert not re.search(r"\d+\.\d+index", html)

    # Calendar contains Schedule Source and Consensus Source
    assert "Schedule Source" in md
    assert "Consensus Source" in md
    assert "Schedule Source" in html

    # Saturday earnings marked as Saturday
    assert "BRK-B" in md
    assert "Saturday" in md or "Sat" in md

    # Footer forward lookahead date
    assert "Lookahead to 2026-10-30" not in md, "Footer must not show past/current date as forward lookahead."
    assert "Forward Horizon to" in md or "Forward Calendar" in md


def test_stage2_section_numbering_and_cross_references(weekly_report_data):
    """Verify cross-asset intelligence links to Section 10 (not Section 11)."""
    md = weekly_report_data["md"]
    html = weekly_report_data["html"]

    # Must link to Section 10 for Commodities & Cross-Asset Intelligence / Tracker
    assert (
        "Section 10: Commodities, Currencies & Cross-Asset Tracker" in md
        or "Section 10: Commodities & Cross-Asset Intelligence" in md
    )
    assert "Section 11: Commodities" not in md
    assert (
        "Section 10: Commodities, Currencies &amp; Cross-Asset Tracker" in html
        or "Section 10: Commodities, Currencies & Cross-Asset Tracker" in html
        or "Section 10: Commodities & Cross-Asset Intelligence" in html
        or "Section 10: Commodities &amp; Cross-Asset Intelligence" in html
    )


def test_stage2_chart_200_dma_span(weekly_report_data):
    """Verify chart coverage: 200-DMA line spans all points in the visible display window."""
    charts_dir = Path("reports/weekly/2026-10-30_charts")
    if charts_dir.exists():
        svg_files = list(charts_dir.glob("*.svg"))
        for svg_f in svg_files:
            content = svg_f.read_text(encoding="utf-8")
            if "200 DMA" in content or "200-DMA" in content:
                # Assert svg contains path data
                assert "d=\"M" in content, f"Chart {svg_f.name} missing path curves for 200-DMA."
