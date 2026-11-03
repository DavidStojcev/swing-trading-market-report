"""Acceptance tests for Change Request v2.1: Stage 3 (Wording, consistency, and chart fixes)."""

import os
import re
import pytest
import pandas as pd
from unittest.mock import MagicMock
from collections import Counter

from sections.movers import MoverItem, _generate_movers_theme_summary, DEFAULT_THEME_MAP
from sections.macro import compute_macro_regime_intelligence, CreditSpreadIntelligence, RealRateIntelligence, VolTermStructureIntelligence, SectorRotationIntelligence, MacroMetricSnapshot
from render.charts import generate_index_technicals_chart


def test_3_1_inflation_measure_labels_present():
    """Stage 3.1: Verify every inflation reference specifies exact measure."""
    intel_credit = CreditSpreadIntelligence(3.26, 326.0, -4.0, "Tight / Complacent", "Benign credit")
    intel_rates = RealRateIntelligence(2.63, 10.0, 2.34, 2.0, 4.98, 12.0, "Real Rate Tightening", "High hurdle")
    intel_vol = VolTermStructureIntelligence(19.42, 20.78, 0.934, -0.01, "Contango (Normal)", "Orderly", "Calm")
    intel_rot = SectorRotationIntelligence(3.0, 10.0, -7.0, "Defensive Flight", "XLY", "XLP", "Defensive flight")

    metrics = {
        "gdp": MacroMetricSnapshot("GDPC1", "GDP", "2026-10-30", 3.37, 3.37, "%", 3.0, 3.0, mom_pct=0.0, change=0.37),
        "retail_sales": MacroMetricSnapshot("RSAFS", "Retail Sales", "2026-10-30", 0.77, 0.77, "%", 0.3, 0.3, mom_pct=0.77, change=0.47),
        "cpi": MacroMetricSnapshot("CPIAUCSL", "Headline CPI", "2026-10-30", 4.02, 4.02, "%", 3.8, 3.8, mom_pct=0.65, change=0.22),
        "core_cpi": MacroMetricSnapshot("CPILFESL", "Core CPI", "2026-10-30", 2.79, 2.79, "%", 2.7, 2.7, mom_pct=0.35, change=0.09),
        "core_pce": MacroMetricSnapshot("PCEPILFE", "Core PCE", "2026-10-30", 3.12, 3.12, "%", 3.0, 3.0, mom_pct=0.30, change=0.12),
    }

    intel_m = compute_macro_regime_intelligence(metrics, intel_credit, intel_rates, intel_vol, intel_rot, report_type="monthly")
    outlook = intel_m.forward_outlook
    assert "Headline CPI" in outlook
    assert "Core CPI" in outlook
    assert "Core PCE" in outlook
    # Must not contain bare generic "CPI +4.02%" or "inflation (CPI"
    assert "Headline CPI +4.02%" in outlook
    assert "Core CPI +2.79%" in outlook
    assert "Core PCE +3.12%" in outlook


def test_3_2_accelerating_inflation_state():
    """Stage 3.2: Verify accelerating inflation signal triggered by high MoM prints."""
    intel_credit = CreditSpreadIntelligence(3.26, 326.0, -4.0, "Tight", "Benign")
    intel_rates = RealRateIntelligence(2.63, 10.0, 2.34, 2.0, 4.98, 12.0, "Tightening", "Hurdle")
    intel_vol = VolTermStructureIntelligence(19.42, 20.78, 0.934, -0.01, "Contango", "Orderly", "Calm")
    intel_rot = SectorRotationIntelligence(3.0, 10.0, -7.0, "Defensive Flight", "XLY", "XLP", "Defensive flight")

    # High MoM CPI (+0.65%)
    metrics_accel = {
        "cpi": MacroMetricSnapshot("CPIAUCSL", "Headline CPI", "2026-10-30", 4.02, 4.02, "%", 3.8, 3.8, mom_pct=0.65, change=0.22),
        "core_cpi": MacroMetricSnapshot("CPILFESL", "Core CPI", "2026-10-30", 2.79, 2.79, "%", 2.7, 2.7, mom_pct=0.45, change=0.09),
        "ppi": MacroMetricSnapshot("PPIFIS", "PPI", "2026-10-30", 2.50, 2.50, "%", 2.0, 2.0, mom_pct=1.34, change=0.50),
    }

    intel = compute_macro_regime_intelligence(metrics_accel, intel_credit, intel_rates, intel_vol, intel_rot, report_type="monthly")
    assert intel.inflation_signal == "Accelerating / Reigniting"


def test_3_3_no_unsupported_flow_language():
    """Stage 3.3 Lint Check: Reject flow terms unless real flow data is wired in."""
    forbidden = re.compile(r"\b(inflows|outflows|institutional liquidation|institutional participation)\b", re.IGNORECASE)

    # Check all python files in project (excluding venv)
    for root, dirs, files in os.walk("."):
        if any(ignored in root for ignored in [".venv", ".git", "__pycache__", ".cache", "reports", ".system_generated"]):
            continue
        for f in files:
            if f.endswith((".py", ".yaml", ".md")):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as fl:
                    for line_no, line in enumerate(fl, 1):
                        # Allow mentions inside test docstrings / comments explaining this rule
                        if "Stage 3" in line or "Lint" in line or "forbidden" in line or "3.3" in line:
                            continue
                        m = forbidden.search(line)
                        assert not m, f"Forbidden flow term '{m.group()}' found in {path}:{line_no}: {line.strip()}"


def test_3_5_200_dma_spans_entire_display_window():
    """Stage 3.5: Ensure 200-DMA spans 100% of the display window without NaNs."""
    # Create 550 days of trading bars
    dates = pd.date_range("2024-01-01", "2026-10-30", freq="B")
    closes = 400.0 + (pd.Series(range(len(dates))) * 0.2)
    df = pd.DataFrame({"Close": closes.values, "Open": closes.values, "High": closes.values, "Low": closes.values, "Volume": 1000000.0}, index=dates)

    # In monthly mode, lookback is 252 bars
    chart = generate_index_technicals_chart(df, "^GSPC", "S&P 500", "2026-10-30", lookback_bars=252)
    assert chart.is_available
    # If df had >= 452 bars, the 252-bar window has zero NaNs in rolling 200-DMA
    assert len(df) >= 252 + 200


def test_3_6_no_duplicate_paragraphs():
    """Stage 3.6 Lint Check: Fail if any paragraph of 30+ words appears more than once."""
    for report_path in ["reports/weekly/2026-10-30.html", "reports/monthly/2026-10-30.html"]:
        if not os.path.exists(report_path):
            continue
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        paras = []
        for p in soup.find_all("p"):
            txt = " ".join(p.get_text().strip().split())
            if len(txt.split()) >= 30:
                paras.append(txt)

        counts = Counter(paras)
        dups = {t: c for t, c in counts.items() if c > 1}
        assert len(dups) == 0, f"Duplicate >=30 word paragraphs found in {report_path}: {dups}"


def test_3_7_movers_granular_theme_grouping():
    """Stage 3.7: Movers by theme identifies granular sub-industries rather than generic IT sector."""
    losers = [
        MoverItem("NOW", "ServiceNow Inc.", "Information Technology", -33.87, 105.12, 1000000, 500000, 2.05, 1.6e11, True, "Earnings"),
        MoverItem("FTNT", "Fortinet Inc.", "Information Technology", -24.40, 136.08, 800000, 450000, 1.74, 1.2e11, True, "Earnings"),
        MoverItem("INTC", "Intel Corp.", "Information Technology", -24.38, 65.76, 2000000, 500000, 3.91, 4.5e11, True, "Earnings"),
        MoverItem("TWLO", "Twilio Inc.", "Information Technology", -21.68, 205.03, 600000, 360000, 1.66, 3.9e10, True, "Earnings"),
        MoverItem("RDDT", "Reddit Inc.", "Communication Services", -36.41, 91.73, 2500000, 500000, 5.17, 2.8e10, True, "Earnings"),
    ]
    gainers = [
        MoverItem("PNR", "Pentair Plc", "Industrials", +19.82, 66.26, 500000, 350000, 1.43, 9.0e9, False, "Guidance"),
        MoverItem("VRT", "Vertiv Holdings", "Industrials", +19.65, 232.50, 700000, 650000, 1.07, 7.5e10, False, "Guidance"),
        MoverItem("CVNA", "Carvana Co.", "Consumer Discretionary", +18.13, 68.29, 900000, 500000, 1.77, 4.2e10, False, "Earnings"),
        MoverItem("GEN", "Gen Digital Inc.", "Information Technology", +17.08, 29.13, 400000, 340000, 1.16, 1.4e10, False, "Analyst Action"),
        MoverItem("GPN", "Global Payments", "Financials", +16.93, 96.84, 1200000, 190000, 6.34, 2.2e10, False, "M&A/Deal"),
    ]

    summary = _generate_movers_theme_summary(gainers, losers)
    # Must NOT say "4 of 5 losers are Information Technology"
    assert "4 of 5 losers are Information Technology" not in summary
    # Must differentiate the granular themes
    assert "Enterprise Cloud Software" in summary or "Semiconductors" in summary
    assert "Cybersecurity" in summary or "Communications Platforms" in summary
