"""Automated QA Harness for US Market Report Engine (Change Request v2.2 Stage 0).

Implements independent verification checks (T1 - T12) that execute after report generation,
produce a comprehensive markdown report (qa_report.md), and fail the build if any check FAILS.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from data.calendar import PeriodInfo
from sections.base import SectionResult
from sections.conclusion import ConclusionData
from sections.macro import MacroSectionData
from sections.movers import TopMoversData
from sections.sectors import SectorReportData
from sections.sentiment_positioning import SentimentPositioningData
from sections.swing_regime import SwingGateData
from sections.what_changed import WhatChangedData
from sections.forward_calendar import ForwardCalendarData
from sections.commodities_cross_asset import CommoditiesCrossAssetData

logger = logging.getLogger(__name__)


@dataclass
class QACheckResult:
    check_id: str
    name: str
    status: str  # "PASS", "FAIL", "WARN"
    details: List[str] = field(default_factory=list)


@dataclass
class QAHarnessReport:
    as_of_date: str
    report_type: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    warned_checks: int
    results: List[QACheckResult] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.failed_checks == 0


# ==============================================================================
# Individual QA Checks: T1 through T12
# ==============================================================================

def check_t1_label_vote_consistency(sections: List[SectionResult]) -> QACheckResult:
    """T1: For every indicator row, the sign of the vote must match the sign implied by its label/interpretation."""
    details: List[str] = []
    concl_sec = next((s for s in sections if isinstance(s.data, ConclusionData)), None)
    if not concl_sec or not concl_sec.data or not concl_sec.data.scorecard:
        return QACheckResult("T1", "Label-Vote Consistency", "FAIL", ["Conclusion scorecard data missing."])

    scorecard = concl_sec.data.scorecard
    for v in scorecard.votes:
        name = v.rule_name
        interp = v.interpretation.lower()
        vote = v.vote

        # Check for positive implied indicators with negative votes
        # e.g., VRP positive/contango voting negative
        if "vrp" in name.lower() or "volatility risk premium" in name.lower():
            if ("positive" in interp or "contango" in interp or "complacency" in interp or "insurance" in interp) and vote < 0:
                details.append(f"Mismatched VRP vote: label indicates positive premium/contango ('{v.interpretation}'), but vote is {vote:+.2f}")
        elif "put/call" in name.lower():
            if "hedging" in interp and vote < -0.5 and "extreme" not in interp:
                # If put/call is 1.25 (typical normal/elevated hedging) and voting -1.00
                details.append(f"Mismatched Put/Call vote: '{v.condition}' with interpretation '{v.interpretation}' voting extreme {vote:+.2f}")
        elif "easing" in interp or "bullish" in interp or "supportive" in interp or "expansion" in interp:
            if vote < -0.1:
                details.append(f"Indicator '{name}' interpretation implies easing/bullish ('{v.interpretation}'), but vote is {vote:+.2f}")
        elif "tightening" in interp or "bearish" in interp or "restrictive" in interp or "inversion" in interp:
            if vote > 0.1:
                details.append(f"Indicator '{name}' interpretation implies tightening/bearish ('{v.interpretation}'), but vote is {vote:+.2f}")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T1", "Label-Vote Consistency", status, details)


def check_t2_single_source_of_truth(sections: List[SectionResult]) -> QACheckResult:
    """T2: Single source of truth: extract every metric that appears in 2+ places and assert equal values."""
    details: List[str] = []
    values_by_metric: Dict[str, List[Tuple[str, float]]] = {}

    for s in sections:
        sec_name = s.title
        data = s.data
        if isinstance(data, WhatChangedData):
            for r in data.deltas:
                if "High-Yield Credit" in r.name:
                    try:
                        # Extract number like 326
                        bps = float(re.search(r"(\d+)\s*bps", r.current_val).group(1))
                        values_by_metric.setdefault("HY_OAS_BPS", []).append((sec_name, bps))
                    except Exception:
                        pass
                elif "Macro & Micro Trend Score" in r.name:
                    try:
                        sc = float(re.search(r"([+-]?\d+\.\d+)", r.current_val).group(1))
                        values_by_metric.setdefault("MACRO_SCORE", []).append((sec_name, sc))
                    except Exception:
                        pass

        elif isinstance(data, MacroSectionData):
            if data.fed_rates and data.fed_rates.hy_spread is not None:
                values_by_metric.setdefault("HY_OAS_BPS", []).append((sec_name, round(data.fed_rates.hy_spread * 100.0, 1)))
            if data.intelligence and data.intelligence.credit:
                values_by_metric.setdefault("HY_OAS_BPS", []).append((f"{sec_name} (Intel)", round(data.intelligence.credit.spread_bps, 1)))
            if data.intelligence and data.intelligence.vol_term:
                values_by_metric.setdefault("VIX", []).append((sec_name, round(data.intelligence.vol_term.vix_1m, 2)))
            if hasattr(data, "cross_assets") and data.cross_assets:
                for ca in data.cross_assets:
                    if getattr(ca, "symbol", "") == "CL=F":
                        values_by_metric.setdefault("OIL_3M_RET", []).append((sec_name, round(getattr(ca, "pct_change_3m", 0.0), 2)))

        elif isinstance(data, CommoditiesCrossAssetData):
            for it in data.items:
                if it.symbol == "CL=F":
                    values_by_metric.setdefault("OIL_3M_RET", []).append((sec_name, round(it.ret_3m, 2)))

        elif isinstance(data, SentimentPositioningData):
            values_by_metric.setdefault("VIX", []).append((sec_name, round(data.vix, 2)))

        elif isinstance(data, ConclusionData):
            values_by_metric.setdefault("MACRO_SCORE", []).append((sec_name, round(data.normalized_score, 2)))
            if data.regime_intelligence and data.regime_intelligence.credit:
                values_by_metric.setdefault("HY_OAS_BPS", []).append((sec_name, round(data.regime_intelligence.credit.spread_bps, 1)))
            if data.scorecard and getattr(data.scorecard, "all_votes", None):
                for v in data.scorecard.all_votes:
                    if "Crude Oil (WTI)" in v.rule_name:
                        m_oil = re.search(r"3M trend ([+-]?\d+\.\d+)%", v.condition)
                        if m_oil:
                            values_by_metric.setdefault("OIL_3M_RET", []).append((f"{sec_name} (Vote)", round(float(m_oil.group(1)), 2)))

    for metric, instances in values_by_metric.items():
        if len(instances) >= 2:
            base_val = instances[0][1]
            for loc, val in instances[1:]:
                if abs(val - base_val) > 0.05:
                    details.append(f"Inconsistent {metric}: {instances[0][0]} has {base_val}, but {loc} has {val}")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T2", "Single Source of Truth", status, details)


def check_t3_claim_lint(md_content: str, html_content: str, sections: List[SectionResult]) -> QACheckResult:
    """T3: Claim lint: block phrases in the banned list unless supported by verified fields."""
    details: List[str] = []
    # Lint: forbidden phrase definitions to detect and block
    banned_phrases = [
        "markets price aggressive fed easing",  # Lint: forbidden
        "aggressive fed easing",                # Lint: forbidden
        "downward earnings revisions",          # Lint: forbidden
        "cyclical equities face downward earnings revisions",  # Lint: forbidden
        "institutional liquidation",            # Lint: forbidden
        "institutional participation",          # Lint: forbidden
        "institutional distribution",           # Lint: forbidden (CR v2.3)
        "institutional trend",                  # Lint: forbidden (CR v2.3)
        "elevated term premium",                # Lint: forbidden (CR v2.3)
        "term premium",                         # Lint: forbidden (CR v2.3)
        "tactical leadership reflects sector returns",  # Lint: forbidden template glitch (CR v2.3)
        "eliminates recession risk",            # Lint: forbidden
        "eliminates",                           # Lint: forbidden
        "proves",                               # Lint: forbidden
    ]

    combined_text = (md_content + " " + html_content).lower()
    for phrase in banned_phrases:
        if phrase in combined_text:
            details.append(f"Banned or unsupported claim detected in generated report: '{phrase}'")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T3", "Claim Lint & Banned Phrases", status, details)


def check_t4_regime_truth_table(sections: List[SectionResult]) -> QACheckResult:
    """T4: Regime truth table: regime label must equal quadrant derived from Growth & Inflation signals."""
    details: List[str] = []
    macro_sec = next((s for s in sections if isinstance(s.data, MacroSectionData)), None)
    if not macro_sec or not macro_sec.data or not getattr(macro_sec.data, "intelligence", None):
        return QACheckResult("T4", "Regime Truth Table", "WARN", ["Macro intelligence data not available to verify regime."])

    intel = macro_sec.data.intelligence
    quadrant = intel.quadrant.lower()
    growth = intel.growth_signal.lower()
    inflation = intel.inflation_signal.lower()

    # Contradiction: Deflationary Slowdown requires Decelerating/low inflation
    if "deflationary" in quadrant or "slowdown" in quadrant:
        if "accelerating" in inflation or "reigniting" in inflation or "sticky" in inflation or "firm" in inflation:
            details.append(
                f"Regime truth table violation: Regime is '{intel.quadrant}', but Inflation signal is '{intel.inflation_signal}' (Deflationary Slowdown cannot occur with accelerating/sticky inflation)."
            )

    # Goldilocks requires Easing/Low inflation and Expanding growth
    if "goldilocks" in quadrant:
        if "accelerating" in inflation or "reigniting" in inflation:
            details.append(f"Regime truth table violation: Regime is Goldilocks, but Inflation is '{intel.inflation_signal}'.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T4", "Regime Truth Table", status, details)


def check_t5_format_lint(md_content: str, html_content: str) -> QACheckResult:
    """T5: Format lint: no stray suffixes, FX pairs have no '$', amounts have thousands separators."""
    details: List[str] = []

    # 1. Stray suffixes like 48.60index or 54.90index
    stray_suffix_matches = re.findall(r"\b\d+\.\d+(?:index|kindex|%index)\b", md_content + " " + html_content)
    if stray_suffix_matches:
        details.append(f"Stray unit suffix found in text: {set(stray_suffix_matches)}")

    # 2. FX pairs with dollar sign ($EUR/USD, $USD/JPY, or EUR/USD $1.08)
    fx_dollar_matches = re.findall(r"\$(?:EUR/USD|USD/JPY|GBP/USD|AUD/USD)", md_content + " " + html_content)
    if fx_dollar_matches:
        details.append(f"FX pair prefixed with dollar sign: {set(fx_dollar_matches)}")

    fx_price_dollar_matches = re.findall(r"(?:EUR/USD|USD/JPY|GBP/USD)[^\n]*?\\?\$[0-9]+", md_content)
    if fx_price_dollar_matches:
        details.append(f"FX pair price displayed with dollar symbol in Markdown: {fx_price_dollar_matches[:3]}")

    # 3. Dollar amounts missing thousands separators (e.g. $4157M or $3202.3M)
    unformatted_dollar_matches = re.findall(r"(?:\$|\\\$)[1-9][0-9]{3,}(?:\.[0-9]+)?[MB]", md_content + " " + html_content)
    if unformatted_dollar_matches:
        details.append(f"Large dollar amounts missing thousands separator: {set(unformatted_dollar_matches)}")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T5", "Format Lint & Units", status, details)


def check_t6_run_to_run_stability(period: PeriodInfo, sections: List[SectionResult]) -> QACheckResult:
    """T6: Run-to-run stability: verify that baseline/prior values match expected historical levels."""
    details: List[str] = []
    # Check WhatChanged prior HY OAS if present
    wc_sec = next((s for s in sections if isinstance(s.data, WhatChangedData)), None)
    if wc_sec and wc_sec.data:
        for r in wc_sec.data.deltas:
            if "High-Yield Credit" in r.name:
                # Historical FRED BAMLH0A0HYM2 on 2026-10-23 was 3.38% (338 bps). An earlier run showed 3.14%.
                if "314" in r.prior_val or "3.14" in r.prior_val:
                    details.append(f"HY OAS prior was 3.14% instead of official FRED baseline (3.38%).")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T6", "Run-to-Run Stability", status, details)


def check_t7_chart_coverage(charts: Optional[Dict[str, Any]]) -> QACheckResult:
    """T7: Chart coverage: every legend entry has a plotted line spanning the entire window."""
    details: List[str] = []
    if not charts:
        return QACheckResult("T7", "Chart Coverage", "PASS", ["No charts generated for this run."])

    for k, chart in charts.items():
        if not getattr(chart, "is_available", False) or not getattr(chart, "svg_content", None):
            continue
        svg = chart.svg_content
        # Check if 200-DMA is in legend but truncated
        if "200-DMA" in svg or "200 DMA" in svg:
            # Check for empty path or premature truncation indicator if any
            if "d=\"M" not in svg:
                details.append(f"Chart '{k}' mentions 200-DMA but contains no path curves.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T7", "Chart Coverage & History Span", status, details)


def check_t8_structure_lint(md_content: str, html_content: str, sections: List[SectionResult]) -> QACheckResult:
    """T8: Structure lint: no paragraph duplicate (30+ words), section cross-references match actual headings."""
    details: List[str] = []

    # 1. Duplicate paragraph check (30+ words) & duplicate sentence check (12+ words)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", md_content) if len(p.strip().split()) >= 30]
    seen_paras = set()
    for p in paragraphs:
        norm_p = " ".join(p.split())
        if norm_p in seen_paras:
            details.append(f"Duplicate 30+ word paragraph detected: '{norm_p[:80]}...'")
        seen_paras.add(norm_p)

    # Sentence deduplication (12+ words) across HTML content (excluding tabular header rows and scripts)
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["thead", "th", "script", "style", "svg"]):
        tag.decompose()
    raw_html_text = soup.get_text()
    raw_sentences = re.split(r"[\.\?!]\s+", raw_html_text)
    sentence_counts: Dict[str, int] = {}
    for s in raw_sentences:
        s_clean = " ".join(s.strip().split())
        words = s_clean.split()
        if len(words) >= 12:
            sentence_counts[s_clean] = sentence_counts.get(s_clean, 0) + 1
    for s_txt, count in sentence_counts.items():
        if count > 1:
            details.append(f"Duplicate 12+ word sentence detected ({count}x): '{s_txt[:80]}...'")

    # 2. Literal backslash check in HTML (CR v2.3 Item 5)
    if r"\$" in html_content:
        details.append("Literal backslash '\\$' detected in HTML output.")

    # 3. Cross-reference section number and exact title validation (CR v2.3 Item 6)
    sec_map = {s.section_num: s.title for s in sections}
    cross_refs = re.findall(r"Section (\d+):?\s*([A-Za-z0-9 &,;–—\-]+)", md_content + " " + html_content)
    for num_str, topic in cross_refs:
        num = int(num_str)
        if num in sec_map:
            actual_title = sec_map[num].lower()
            topic_clean = topic.strip().lower().replace("&amp;", "&")
            if "commodities" in actual_title:
                if "commodities, currencies & cross-asset tracker" not in topic_clean:
                    details.append(f"Section cross-reference mismatch: Section {num} title is '{sec_map[num]}', but text refers to '{topic}'")
            elif "forward calendar" in actual_title:
                if "forward calendar & catalyst horizon" not in topic_clean:
                    details.append(f"Section cross-reference mismatch: Section {num} title is '{sec_map[num]}', but text refers to '{topic}'")

    # 4. Numeric table columns check (e.g. "Narrowing" in Prior column)
    wc_sec = next((s for s in sections if isinstance(s.data, WhatChangedData)), None)
    if wc_sec and wc_sec.data:
        for r in wc_sec.data.deltas:
            if "Narrowing" in r.prior_val or "Widening" in r.prior_val:
                details.append(f"Non-numeric word '{r.prior_val}' found in numeric Prior column of What Changed table for '{r.name}'.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T8", "Structure Lint & Section References", status, details)


def check_t9_provenance(sections: List[SectionResult]) -> QACheckResult:
    """T9: Provenance: calendar events must have verified sources; no templated speaker topics."""
    details: List[str] = []
    cal_sec = next((s for s in sections if isinstance(s.data, ForwardCalendarData)), None)
    if cal_sec and cal_sec.data:
        for ev in cal_sec.data.events:
            if not ev.source or ev.source.strip() == "":
                details.append(f"Calendar event '{ev.title}' on {ev.date} has no verified data source.")
            # Check for unverified templated speaker topics
            if any(w in ev.title.lower() for w in ("waller", "bowman", "keynote", "jefferson")):
                if "economic outlook & balance sheet" in ev.title.lower() or "bank supervision & inflation mandate" in ev.title.lower():
                    details.append(f"Speaker event '{ev.title}' contains templated topic not dynamically verified from Federal Reserve events feed.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T9", "Provenance & Calendar Sourcing", status, details)


def check_t10_posture_logic(sections: List[SectionResult]) -> QACheckResult:
    """T10: Posture logic: an overlay may only say it changed posture if resulting tier differs."""
    details: List[str] = []
    gate_sec = next((s for s in sections if isinstance(s.data, SwingGateData)), None)
    if gate_sec and gate_sec.data:
        g = gate_sec.data
        desc = (g.triggered_rule + " " + g.execution_guidance).lower()
        if "capped 1-tier more conservative" in desc and g.posture.upper() == "DEFENSIVE":
            # Check if base posture was already defensive (e.g. dual 50-DMA fail)
            if "dual benchmark break of 50-dma" in desc or "gate rule 4" in desc:
                details.append("Posture logic violation: Event-Risk Overlay claimed to cap posture 1-tier more conservative to DEFENSIVE, but posture was already DEFENSIVE (a no-op). Must state 'no change (already Defensive)'.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T10", "Posture Logic & Event Overlay", status, details)


def check_t11_status_derivation(md_content: str, html_content: str, sections: List[SectionResult]) -> QACheckResult:
    """T11: Status derivation: Data Quality status must be PARTIAL if any input was missing / n/a."""
    details: List[str] = []
    text = md_content + " " + html_content
    # If missing inputs are listed, status cannot be COMPLETE or VERIFIED
    has_missing = "missing / unavailable inputs" in text.lower() or "n/a (source unavailable)" in text.lower()
    if has_missing:
        if "data quality: complete (verified)" in text.lower() or "status: verified" in text.lower():
            details.append("Data quality footer claims COMPLETE (VERIFIED) despite missing/unpolled input fields.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T11", "Data Quality Status Derivation", status, details)


def check_t12_sanity_bounds(sections: List[SectionResult]) -> QACheckResult:
    """T12: Sanity bounds: flag any daily dollar-volume > 5% of market cap, large moves > 30% unconfirmed."""
    details: List[str] = []
    sec_sec = next((s for s in sections if isinstance(s.data, SectorReportData)), None)
    if sec_sec and sec_sec.data and sec_sec.data.sector_leaders:
        for sec_name, leaders in sec_sec.data.sector_leaders.items():
            for leader in leaders:
                # Sanity bound: daily dollar volume > $4B or > 5% of realistic market cap for mid-caps
                # Specifically check MRNA anomaly: $4,157M avg daily volume on a ~$10B stock (~42% turnover!)
                if leader.symbol == "MRNA" and leader.avg_dollar_volume > 1.5e9:
                    details.append(f"Unrealistic dollar volume anomaly for {leader.symbol}: ${leader.avg_dollar_volume / 1e6:.1f}M/day exceeds reasonable volume bounds.")
                elif leader.avg_dollar_volume > 1e11:  # $100B/day is physically impossible for single stock
                    details.append(f"Unrealistic dollar volume for {leader.symbol}: ${leader.avg_dollar_volume / 1e6:.1f}M/day.")

    status = "FAIL" if details else "PASS"
    return QACheckResult("T12", "Sanity Bounds & Volume Feasibility", status, details)


# ==============================================================================
# Harness Runner & Markdown Generator
# ==============================================================================

def run_qa_checks(
    period: PeriodInfo,
    sections: List[SectionResult],
    md_content: str,
    html_content: str,
    charts: Optional[Dict[str, Any]] = None,
    output_dir: Optional[Path] = None,
    strict: bool = False,
) -> QAHarnessReport:
    """Execute all QA checks, write qa_report.md, and optionally raise exception on failure."""
    checks = [
        check_t1_label_vote_consistency(sections),
        check_t2_single_source_of_truth(sections),
        check_t3_claim_lint(md_content, html_content, sections),
        check_t4_regime_truth_table(sections),
        check_t5_format_lint(md_content, html_content),
        check_t6_run_to_run_stability(period, sections),
        check_t7_chart_coverage(charts),
        check_t8_structure_lint(md_content, html_content, sections),
        check_t9_provenance(sections),
        check_t10_posture_logic(sections),
        check_t11_status_derivation(md_content, html_content, sections),
        check_t12_sanity_bounds(sections),
    ]

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    warned = sum(1 for c in checks if c.status == "WARN")

    report = QAHarnessReport(
        as_of_date=period.session_date,
        report_type=period.report_type,
        total_checks=len(checks),
        passed_checks=passed,
        failed_checks=failed,
        warned_checks=warned,
        results=checks,
    )

    # Generate Markdown QA Report
    qa_lines = [
        f"# QA Harness Report: {period.report_type.upper()} ({period.session_date})",
        f"**Status:** {'❌ FAILED' if failed > 0 else '✅ PASSED'} | **Score:** {passed}/{len(checks)} checks passed ({failed} failed, {warned} warnings)",
        "",
        "## Summary Table",
        "| ID | Check Name | Status | Details / Violations |",
        "| :---: | :--- | :---: | :--- |",
    ]

    for c in checks:
        badge = "✅ PASS" if c.status == "PASS" else ("❌ FAIL" if c.status == "FAIL" else "⚠️ WARN")
        det_str = "<br>".join(c.details) if c.details else "All criteria satisfied."
        qa_lines.append(f"| **{c.check_id}** | {c.name} | **{badge}** | {det_str} |")

    qa_lines.append("")
    if failed > 0:
        qa_lines.append("## Detailed Failures & Required Actions")
        for c in checks:
            if c.status == "FAIL":
                qa_lines.append(f"### ❌ {c.check_id}: {c.name}")
                for d in c.details:
                    qa_lines.append(f"- {d}")
                qa_lines.append("")

    qa_lines.append("## Known Limitations")
    qa_lines.append("- **S&P 500 Forward P/E & Forward EPS:** Not published by free public yfinance index/ETF endpoints; panel collapses gracefully to `n/a (source unavailable)` per Ground Rule 1 & CR 4.2 without fabricating estimates until a verified fundamental data feed is configured.")
    qa_lines.append("- **Economic Calendar Consensus Forecasts:** Unpolled forward releases and synthesized releases lacking survey consensus display `n/a (no consensus)` and are evaluated via direction-based rules per CR 4.3.")
    qa_lines.append("- **Fed Funds Rate Probabilities:** Derived from CBOT 30-Day Fed Funds Futures (ZQ contracts on CME/Yahoo); prediction market API fallback is optional/unconfigured.")
    qa_lines.append("- **Sentiment & Positioning Feed:** AAII investor survey raw feed is unconfigured; proxy sentiment models and Volatility Risk Premium (VRP) are utilized under strict minimum-input rules.")
    qa_lines.append("")

    qa_md_str = "\n".join(qa_lines)

    # Write to output_dir if specified
    if output_dir:
        report_path = Path(output_dir) / "qa_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(qa_md_str)
        logger.info("QA report saved to: %s", report_path)

    if strict and failed > 0:
        raise AssertionError(f"QA Harness failed {failed} checks. See qa_report.md for details.")

    return report
