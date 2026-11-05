"""Self-contained HTML report generator with inline CSS and light/dark mode."""

from typing import Any, Dict, List, Optional
from data.calendar import PeriodInfo
from sections.base import SectionResult
from sections.breadth import BreadthSectionData
from sections.conclusion import ConclusionData
from sections.executive_summary import ExecutiveSummaryData
from sections.index_snapshot import IndexSnapshotData
from sections.macro import MacroSectionData
from sections.movers import TopMoversData
from sections.sectors import SectorReportData
from sections.technicals import TechnicalsData
from sections.volatility import VolatilityData
from sections.what_changed import WhatChangedData
from sections.swing_regime import SwingGateData
from sections.theme_relative_strength import ThemeRelativeStrengthData
from sections.commodities_cross_asset import CommoditiesCrossAssetData
from sections.fed_path import FedPathData
from sections.forward_calendar import ForwardCalendarData
from sections.earnings import EarningsLayerData
from sections.sentiment_positioning import SentimentPositioningData
from sections.valuation import ValuationData
from sections.watchlist import WatchlistData
from render.svg_charts import render_inflation_chart, render_labor_chart, render_rates_chart, render_activity_chart


def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return '<span class="text-muted font-mono">n/a</span>'
    sign = "+" if val > 0 else ""
    color_class = "text-green" if val > 0 else ("text-red" if val < 0 else "text-muted")
    return f'<span class="{color_class} font-mono">{sign}{val:.2f}%</span>'


def _fmt_delta(val: float) -> str:
    sign = "+" if val > 0 else ""
    color_class = "text-green" if val > 0 else ("text-red" if val < 0 else "text-muted")
    return f'<span class="{color_class} font-mono">{sign}{val:.2f}</span>'


def _fmt_price(val: float) -> str:
    return f'<span class="font-mono">{val:,.2f}</span>'


def _fmt_macro_val(val: Optional[float], unit: str) -> str:
    """Format macro release value according to its economic unit."""
    if val is None or not isinstance(val, (int, float)):
        return str(val) if val is not None else "n/a"
    u = (unit or "").strip()
    if u == "claims":
        return f"{val:,.0f}" if abs(val) >= 1000 else f"{val:.0f}k"
    if u == "k":
        return f"{val:+.0f}k"
    if u == "index":
        return f"{val:.1f}"
    if u == "%":
        return f"{val:.2f}%"
    return f"{val:+.2f}{u}"


def _render_chart_html(chart: Optional[Any]) -> str:
    """Render inline responsive theme-aware chart card for HTML reports."""
    if chart is None:
        return ""
    has_svg = bool(getattr(chart, "svg_content", ""))
    has_b64 = bool(getattr(chart, "base64_data", ""))
    if not getattr(chart, "is_available", False) or (not has_svg and not has_b64):
        title = getattr(chart, "title", "Chart")
        err = getattr(chart, "error_message", "Chart temporarily unavailable")
        return f'<div class="alert alert-info" style="margin: 12px 0;">📊 <em>{title}: {err}</em></div>'

    if has_svg:
        visual = f'<div class="chart-svg-wrapper" id="chart_{chart.key}">{chart.svg_content}</div>'
    else:
        visual = f'<img src="{chart.data_uri}" alt="{chart.title}" style="max-width: 100%; height: auto; border-radius: 8px;" id="chart_{chart.key}">'

    return f"""
    <div class="macro-chart-box chart-svg-container" style="margin: 18px 0; text-align: center;">
        {visual}
        <p class="table-caption" style="margin-top: 6px;"><em>{chart.caption}</em></p>
    </div>
    """


def _render_sidebar(period: PeriodInfo, sections: List[SectionResult]) -> str:
    """Render collapsible 5-category accordion sidebar matching Zen / Tropical Earth theme."""
    sec_map = {s.section_num: s for s in sections}

    categories = [
        ("1. Overview & Posture", [1, 2, 3, 4], True),
        ("2. Technicals & Breadth", [5, 6, 7, 14], False),
        ("3. Sectors & Themes", [8, 9], False),
        ("4. Macro & Catalysts", [10, 11, 12, 17], False),
        ("5. Fundamentals & Outlook", [13, 15, 16, 18, 19], False),
    ]

    default_titles = {
        1: "Executive Summary",
        2: "What Changed: Key Deltas",
        3: "Swing-Trade Posture",
        4: "Index Snapshot",
        5: "Technical Indicators",
        6: "Market Breadth",
        7: "Volatility (VIX)",
        8: "Sector Performance",
        9: "Theme Relative Strength",
        10: "Cross-Asset Tracker",
        11: "Fed Policy Path",
        12: "Forward Calendar",
        13: "Earnings Progress",
        14: "Top Movers",
        15: "Tactical Watchlist",
        16: "Market Sentiment",
        17: "Macro Events",
        18: "Market Outlook",
        19: "Footer & Disclaimer",
    }

    is_full_report = len(sections) >= 10
    details_html = []

    for cat_title, nums, is_open in categories:
        links_html = []
        for n in nums:
            if n in sec_map:
                t = default_titles.get(n, sec_map[n].title) if is_full_report else sec_map[n].title
                links_html.append(f'<a href="#section-{n}" class="nav-link">{n}. {t}</a>')
            elif is_full_report:
                t = default_titles.get(n, f"Section {n}")
                links_html.append(f'<a href="#section-{n}" class="nav-link">{n}. {t}</a>')

        if links_html:
            open_attr = "open" if is_open else ""
            details_html.append(f"""
            <details {open_attr}>
                <summary>{cat_title}</summary>
                {''.join(links_html)}
            </details>
            """)

    # Render any unmapped sections in a dynamic section if present
    mapped_nums = {n for _, nums, _ in categories for n in nums}
    extra_links = [
        f'<a href="#section-{s.section_num}" class="nav-link">{s.section_num}. {s.title}</a>'
        for s in sections
        if s.section_num not in mapped_nums
    ]
    if extra_links:
        details_html.append(f"""
        <details open>
            <summary>Additional Sections</summary>
            {''.join(extra_links)}
        </details>
        """)

    return f"""
    <aside class="sidebar" id="sidebar">
        <div class="brand">
            <h1>Market Briefing</h1>
            <p>Report Date: {period.session_date}</p>
            <div style="margin-top: 8px; display: flex; align-items: center; gap: 6px;">
                <span style="width: 6px; height: 6px; border-radius: 50%; background: var(--tropical-teal); display: inline-block;"></span>
                <span style="font-size: 0.7rem; font-weight: 700; color: var(--tropical-teal);">LIVE DATA</span>
            </div>
        </div>

        <nav class="nav-menu">
            {''.join(details_html)}
        </nav>
        <div class="sidebar-footer">
            <button class="theme-toggle-btn" onclick="toggleTheme()">🌓 Toggle Theme</button>
        </div>
    </aside>
    """


def _render_top10_ticker_strip(sections: List[SectionResult]) -> str:
    """Render compact executive ticker strip of top 10 core market metrics."""
    spx_close, spx_pct = None, None
    ndx_close, ndx_pct = None, None
    posture, posture_class = "NEUTRAL", "badge-neutral"
    macro_score, macro_regime, score_class = None, "Neutral", "text-muted"
    vix_val, vix_delta = None, None
    breadth_50 = None
    y10, y10_delta = None, None
    oas_bps, oas_delta = None, None
    vrp, vrp_regime = None, "Normal"
    wti_price, wti_3m = None, None

    for sec in sections:
        if not sec.is_available:
            continue
        data = sec.data
        if isinstance(data, IndexSnapshotData):
            for r in data.rows:
                if r.symbol == "^GSPC":
                    spx_close, spx_pct = r.close, r.pct_change
                elif r.symbol == "^NDX":
                    ndx_close, ndx_pct = r.close, r.pct_change
        elif isinstance(data, SwingGateData):
            posture = data.posture
            posture_class = data.posture_badge_class
        elif isinstance(data, ExecutiveSummaryData):
            macro_score = data.normalized_score
            macro_regime = data.verdict
            v_low = data.verdict.lower()
            score_class = "text-green" if v_low in ("bullish", "risk-on", "constructive") else ("text-red" if v_low in ("bearish", "risk-off", "cautious") else "text-muted")
        elif isinstance(data, VolatilityData):
            vix_val = data.current_level
            vix_delta = data.change
        elif isinstance(data, BreadthSectionData):
            breadth_50 = data.result.pct_above_50_dma.current
        elif isinstance(data, MacroSectionData):
            if data.fed_rates:
                y10 = data.fed_rates.yield_10y
                y10_delta = data.fed_rates.yield_10y_delta * 100.0
                if getattr(data.fed_rates, "hy_spread", None) is not None:
                    oas_bps = data.fed_rates.hy_spread * 100.0
                if getattr(data.fed_rates, "hy_spread_delta", None) is not None:
                    oas_delta = data.fed_rates.hy_spread_delta * 100.0
            if getattr(data, "intelligence", None) and getattr(data.intelligence, "credit", None):
                oas_bps = data.intelligence.credit.spread_bps
                oas_delta = data.intelligence.credit.delta_bps
        elif isinstance(data, SentimentPositioningData):
            vrp = data.vol_risk_premium
            vrp_regime = data.vol_premium_regime.split("(")[0].strip()
        elif isinstance(data, CommoditiesCrossAssetData):
            for row in data.items:
                if row.symbol == "CL=F":
                    wti_price = row.current_price
                    wti_3m = row.ret_3m

    # Formatting 4 primary hero KPI items
    spx_str = f"{spx_close:,.2f}" if spx_close is not None else "n/a"
    if spx_pct is not None:
        spx_arrow = "▲" if spx_pct > 0 else ("▼" if spx_pct < 0 else "—")
        spx_sign = "+" if spx_pct > 0 else ""
        spx_sub = f"{spx_arrow} {spx_sign}{spx_pct:.2f}%"
        spx_c = "text-green" if spx_pct > 0 else ("text-red" if spx_pct < 0 else "text-muted")
    else:
        spx_sub = "—"
        spx_c = "text-muted"

    ndx_str = f"{ndx_close:,.2f}" if ndx_close is not None else "n/a"
    if ndx_pct is not None:
        ndx_arrow = "▲" if ndx_pct > 0 else ("▼" if ndx_pct < 0 else "—")
        ndx_sign = "+" if ndx_pct > 0 else ""
        ndx_sub = f"{ndx_arrow} {ndx_sign}{ndx_pct:.2f}%"
        ndx_c = "text-green" if ndx_pct > 0 else ("text-red" if ndx_pct < 0 else "text-muted")
    else:
        ndx_sub = "—"
        ndx_c = "text-muted"

    score_str = f"{macro_score:+.2f}" if macro_score is not None else "n/a"
    score_sub = macro_regime

    posture_badge_cls = "badge-red" if posture == "DEFENSIVE" else ("badge-green" if posture == "FULL" else "badge-amber")

    # Formatting 6 secondary KPI items
    vix_str = f"{vix_val:.2f}" if vix_val is not None else "n/a"
    vix_sub = f"{vix_delta:+.2f} 5d" if vix_delta is not None else "—"
    vix_c = "text-red" if (vix_val and vix_val >= 20.0) else ("text-green" if (vix_val and vix_val < 16.5) else "text-muted")

    br_str = f"{breadth_50:.1f}%" if breadth_50 is not None else "n/a"
    br_sub = "SPX > 50-DMA"
    br_c = "text-green font-bold" if (breadth_50 and breadth_50 >= 60.0) else ("text-red font-bold" if (breadth_50 and breadth_50 <= 40.0) else "text-muted")

    y10_str = f"{y10:.2f}%" if y10 is not None else "n/a"
    y10_sub = f"{y10_delta:+.0f} bps" if y10_delta is not None else "—"

    oas_str = f"{oas_bps:.0f} bps" if oas_bps is not None else "n/a"
    oas_sub = f"{oas_delta:+.0f} bps" if oas_delta is not None else "—"
    oas_c = "text-green" if (oas_delta and oas_delta < 0) else ("text-red" if (oas_delta and oas_delta > 0) else "text-muted")

    vrp_str = f"{vrp:+.1f} pts" if vrp is not None else "n/a"
    vrp_sub = vrp_regime[:10]
    vrp_c = "text-green" if (vrp and vrp > 2.0) else ("text-red" if (vrp and vrp < 0) else "text-muted")

    wti_str = f"${wti_price:.2f}" if wti_price is not None else "n/a"
    wti_sub = f"{wti_3m:+.2f}% 3M" if wti_3m is not None else "WTI Oil"
    wti_c = "text-red" if (wti_3m and wti_3m > 15.0) else "text-muted"

    return f"""
    <div class="top10-ticker-strip">
        <div class="kpi-grid">
            <a href="#section-4" class="kpi-card" title="Jump to S&P 500 in Index Snapshot">
                <span class="kpi-label">S&amp;P 500 (^GSPC)</span>
                <span class="kpi-val font-mono">{spx_str}</span>
                <span class="kpi-sub {spx_c} font-mono">{spx_sub}</span>
            </a>
            <a href="#section-4" class="kpi-card" title="Jump to Nasdaq-100 in Index Snapshot">
                <span class="kpi-label">Nasdaq-100 (^NDX)</span>
                <span class="kpi-val font-mono">{ndx_str}</span>
                <span class="kpi-sub {ndx_c} font-mono">{ndx_sub}</span>
            </a>
            <a href="#section-1" class="kpi-card" title="Jump to Executive Summary & Macro Verdict">
                <span class="kpi-label">Macro Score</span>
                <span class="kpi-val font-mono">{score_str}</span>
                <span class="kpi-sub text-muted font-mono">{score_sub}</span>
            </a>
            <a href="#section-3" class="kpi-card" title="Jump to Swing-Trade Posture Gate">
                <span class="kpi-label">Swing Posture</span>
                <span class="badge {posture_badge_cls}" style="width: fit-content; margin-top: 4px;">{posture}</span>
                <span class="kpi-sub text-muted" style="margin-top: auto;">Apex Gate</span>
            </a>
        </div>
        <div class="kpi-secondary-grid">
            <a href="#section-7" class="kpi-secondary-card" title="Jump to Volatility (VIX)">
                <span class="kpi-label">CBOE VIX</span>
                <span class="kpi-val font-mono">{vix_str}</span>
                <span class="kpi-sub {vix_c} font-mono">{vix_sub}</span>
            </a>
            <a href="#section-6" class="kpi-secondary-card" title="Jump to Market Breadth">
                <span class="kpi-label">50-DMA Breadth</span>
                <span class="kpi-val font-mono">{br_str}</span>
                <span class="kpi-sub {br_c} font-mono">{br_sub}</span>
            </a>
            <a href="#section-10" class="kpi-secondary-card" title="Jump to Cross-Asset Rates">
                <span class="kpi-label">10Y Treasury</span>
                <span class="kpi-val font-mono">{y10_str}</span>
                <span class="kpi-sub text-muted font-mono">{y10_sub}</span>
            </a>
            <a href="#section-10" class="kpi-secondary-card" title="Jump to Credit Spreads">
                <span class="kpi-label">HY OAS Spread</span>
                <span class="kpi-val font-mono">{oas_str}</span>
                <span class="kpi-sub {oas_c} font-mono">{oas_sub}</span>
            </a>
            <a href="#section-16" class="kpi-secondary-card" title="Jump to Volatility Risk Premium">
                <span class="kpi-label">Vol Risk (VRP)</span>
                <span class="kpi-val font-mono">{vrp_str}</span>
                <span class="kpi-sub {vrp_c} font-mono">{vrp_sub}</span>
            </a>
            <a href="#section-10" class="kpi-secondary-card" title="Jump to Commodities">
                <span class="kpi-label">WTI Crude</span>
                <span class="kpi-val font-mono">{wti_str}</span>
                <span class="kpi-sub {wti_c} font-mono">{wti_sub}</span>
            </a>
        </div>
    </div>
    """


def render_html(
    period: PeriodInfo,
    sections: List[SectionResult],
    charts: Optional[Dict[str, Any]] = None,
) -> str:
    """Render self-contained HTML market report."""
    rep_title = f"{period.report_type.capitalize()} US Market Report"

    # Build Jump-to navigation options from report sections
    jump_options = []
    for s in sections:
        clean_title = s.title.replace("&amp;", "&")
        jump_options.append(f'<option value="#section-{s.section_num}">{s.section_num}. {clean_title}</option>')

    rep_type_label = period.report_type.upper()
    if period.report_type == "daily":
        trailing_text = "Trailing 1-day session"
    elif period.report_type == "weekly":
        trailing_text = "Trailing 1-week"
    elif period.report_type == "monthly":
        trailing_text = "Trailing 1-month"
    else:
        trailing_text = f"Trailing {period.report_type}"

    sidebar_html = _render_sidebar(period, sections)
    top10_html = _render_top10_ticker_strip(sections)

    top_bar_html = f"""
    <div class="sticky-nav-bar" id="report-nav">
        <div class="nav-inner" style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
            <div class="nav-brand" style="display: flex; align-items: center; gap: 12px;">
                <button class="toggle-sidebar-btn" onclick="toggleSidebar()" title="Toggle Navigation Sidebar">
                    <span style="font-size: 1rem;">☰</span> Chapters
                </button>
                <span class="nav-brand-title" style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">US Market Briefing &bull; {period.session_date}</span>
            </div>
            <div class="nav-controls" style="display: flex; align-items: center; gap: 8px;">
                <select id="jump-select" class="nav-select" onchange="if(this.value){{location.href=this.value; this.value='';}}" title="Jump to section">
                    <option value="">Jump to section...</option>
                    {''.join(jump_options)}
                </select>
                <button class="nav-btn" onclick="toggleTheme()" title="Toggle Theme">🌓 Theme</button>
                <a href="#top" class="nav-btn" title="Back to top">↑ Top</a>
            </div>
        </div>
    </div>
    """

    header_html = f"""
    <header class="report-header" id="top" style="margin-bottom: 28px;">
        <span class="badge badge-primary" style="margin-bottom: 12px; font-size: 0.75rem; letter-spacing: 0.05em;">{rep_type_label} INSTITUTIONAL REPORT</span>
        <h1 style="font-size: 2.2rem; font-weight: 700; line-height: 1.1; margin-bottom: 8px; letter-spacing: -0.02em; color: var(--text-main);">US Market Dynamics</h1>
        <p style="font-size: 0.95rem; color: var(--text-muted); max-width: 650px; margin: 0; line-height: 1.5;">
            Comprehensive analysis of equities, macro conditions, and systemic risk. {trailing_text} to {period.session_date}.
        </p>
        {f'<div class="alert alert-info" style="margin-top: 12px;">ℹ️ <strong>Partial Period:</strong> {period.notes}</div>' if period.is_partial else ''}
    </header>
    """

    body_html: List[str] = []

    for sec in sections:
        body_html.append(f'<section class="section-card card" id="section-{sec.section_num}">')
        body_html.append(f'<div class="section-header"><span class="section-num">{sec.section_num}</span><h2 class="section-title">{sec.title}</h2></div>')

        if not sec.is_available:
            err = sec.error_message or "Data source temporarily unavailable."
            body_html.append(f'<div class="alert alert-warning">⚠️ <strong>Section Unavailable:</strong> {err}</div></section>')
            continue

        # Section: Executive Summary
        if isinstance(sec.data, ExecutiveSummaryData):
            d: ExecutiveSummaryData = sec.data
            v_low = d.verdict.lower()
            if v_low in ("bullish", "risk-on", "constructive"):
                v_class = "badge-green"
                banner_border = "var(--tropical-teal)"
            elif v_low in ("bearish", "risk-off", "cautious"):
                v_class = "badge-red"
                banner_border = "var(--rosy-copper)"
            else:
                v_class = "badge-amber"
                banner_border = "var(--amber-honey)"
            
            regime_callout_html = ""
            if d.forward_outlook:
                reg_name = d.regime_summary or "Active Macro Regime"
                regime_callout_html = f"""
                <div class="regime-callout-card" style="margin-top: 16px; padding: 14px 18px; border-radius: 8px; background: var(--bg-card-subtle); border-left: 4px solid var(--tropical-teal);">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                        <span style="font-size: 1.1rem;">🧭</span>
                        <span style="font-weight: 700; font-size: 0.82rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--tropical-teal);">Macro Regime &amp; Forward Implications: {reg_name}</span>
                    </div>
                    <div style="font-size: 0.90rem; line-height: 1.5; color: var(--text-main);">{d.forward_outlook}</div>
                </div>
                """

            conf_badge = f'<div class="score-sub font-mono" style="margin-top: 4px; color: var(--text-muted); font-size: 11px;">{d.confidence}</div>' if d.confidence else ''

            alignment_callout_html = ""
            if getattr(d, "alignment_note", ""):
                alignment_callout_html = f"""
                <div class="alert alert-info" style="margin-top: 14px; margin-bottom: 14px; display: flex; align-items: flex-start; gap: 10px;">
                    <span style="font-size: 1.1rem; line-height: 1;">⚖️</span>
                    <div>
                        <strong style="display: block; margin-bottom: 2px;">Regime vs. Posture Alignment:</strong> 
                        {d.alignment_note}
                    </div>
                </div>
                """

            body_html.append(f"""
            <div class="verdict-banner" style="border-left-color: {banner_border};">
                <div class="verdict-box">
                    <span class="verdict-label">Market Regime Verdict</span>
                    <span class="verdict-badge {v_class}">{d.verdict.upper()}</span>
                </div>
                <div class="score-box" style="margin-left: auto; text-align: right;">
                    <span class="score-label">Trend Score</span>
                    <span class="score-val font-mono">{d.normalized_score:+.2f}</span>
                    {conf_badge}
                </div>
            </div>
            {alignment_callout_html}
            {regime_callout_html}
            <div class="summary-reasons" style="margin-top: 16px;">
                <ul class="reasons-list">
                    {''.join(f'<li>{r}</li>' for r in d.reasons)}
                </ul>
            </div>
            <details class="methodology-note" style="margin-top: 18px;">
                <summary>ℹ️ How this score is calculated</summary>
                <div class="methodology-content">
                    <p><strong>Category Weighting &amp; Caps:</strong> Evaluates 5 independent signal categories with fixed caps: Trend/Price (30%), Market Breadth (20%), Rates &amp; Macro (20%), Volatility &amp; Risk Appetite (15%), and Sentiment &amp; Positioning (15%). Correlated inputs cannot exceed their category allocation.</p>
                    <p style="margin-top: 6px;"><strong>Continuous Gradients:</strong> Breadth and rate thresholds use continuous linear interpolation (-1.0 to +1.0) between neutral and extreme bounds rather than binary cliffs.</p>
                    <p style="margin-top: 6px;"><strong>Divergence Gating &amp; Missing Inputs:</strong> The Trend category takes the weaker of S&amp;P 500 and Nasdaq-100 to penalize narrow single-index rallies. If an input source is temporarily unavailable, it is excluded and active category denominators are renormalized without defaulting to 0.</p>
                    <p style="margin-top: 6px;"><strong>Regime Bands:</strong> Risk-On (&ge; +0.35), Constructive (+0.10 to +0.35), Neutral (-0.10 to +0.10), Cautious (-0.35 to -0.10), Risk-Off (&lt; -0.35).</p>
                </div>
            </details>
            """)

        # Section: What Changed (Executive Deltas vs Prior Report)
        elif isinstance(sec.data, WhatChangedData):
            w_data: WhatChangedData = sec.data
            delta_rows = []
            for d in w_data.deltas:
                val_class = "text-green font-bold" if d.valence == "positive" else ("text-red font-bold" if d.valence == "negative" else "text-muted font-bold")
                delta_sign = "+" if (d.delta_str and not d.delta_str.startswith(("+", "-", "—"))) else ""
                formatted_delta = f"{delta_sign}{d.delta_str}" if d.delta_str != "—" else "—"
                sub_detail = f'<div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">{d.detail}</div>' if d.detail else ""
                delta_rows.append(f"""
                <tr>
                    <td><strong>{d.name}</strong>{sub_detail}</td>
                    <td class="text-right font-mono font-bold">{d.current_val}</td>
                    <td class="text-right font-mono {val_class}">{formatted_delta}</td>
                </tr>
                """)

            risk_html = ""
            if w_data.single_biggest_risk:
                risk_html = f"""
                <div class="alert alert-warning" style="margin-top: 14px;">
                    <strong style="display: block; margin-bottom: 2px;">⚠️ Single Biggest Forward Risk:</strong>
                    {w_data.single_biggest_risk}
                </div>
                """

            body_html.append(f"""
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th class="text-right">Current Status</th>
                            <th class="text-right">Period &Delta;</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(delta_rows)}
                    </tbody>
                </table>
            </div>
            {risk_html}
            """)

        # Section: Swing-Trade Exposure Gate & Posture
        elif isinstance(sec.data, SwingGateData):
            sg: SwingGateData = sec.data
            
            spy_20_pill = '<span class="badge badge-green">PASS</span>' if sg.spy_20ema_pass else '<span class="badge badge-red">FAIL</span>'
            spy_50_pill = '<span class="badge badge-green">PASS</span>' if sg.spy_50dma_pass else '<span class="badge badge-red">FAIL</span>'
            qqq_20_pill = '<span class="badge badge-green">PASS</span>' if sg.qqq_20ema_pass else '<span class="badge badge-red">FAIL</span>'
            qqq_50_pill = '<span class="badge badge-green">PASS</span>' if sg.qqq_50dma_pass else '<span class="badge badge-red">FAIL</span>'

            if sg.posture == "FULL":
                posture_badge_cls = "badge-green"
                banner_border = "var(--tropical-teal)"
            elif sg.posture in ("REDUCED", "SELECTIVE"):
                posture_badge_cls = "badge-amber"
                banner_border = "var(--amber-honey)"
            else:
                posture_badge_cls = "badge-red"
                banner_border = "var(--rosy-copper)"

            monthly_gate_note = """
            <div class="alert alert-info" style="margin-top: 12px; margin-bottom: 12px;">
                💡 <strong>Monthly Strategic Allocation Note:</strong> The Swing-Trade Exposure Gate provides tactical weekly guardrails. For long-term multi-asset allocators, macro regime signals and credit spreads (Section 17) take precedence over short-term swing stops.
            </div>
            """ if period.report_type == "monthly" else ""

            spy_20_c = "text-green font-bold" if sg.spy_20ema_pass else "text-red font-bold"
            spy_50_c = "text-green font-bold" if sg.spy_50dma_pass else "text-red font-bold"
            qqq_20_c = "text-green font-bold" if sg.qqq_20ema_pass else "text-red font-bold"
            qqq_50_c = "text-green font-bold" if sg.qqq_50dma_pass else "text-red font-bold"

            body_html.append(f"""
            <div class="verdict-banner" style="border-left-color: {banner_border};">
                <div class="verdict-box">
                    <span class="verdict-label">Execution Posture</span>
                    <span class="verdict-badge {posture_badge_cls}">{sg.posture}</span>
                </div>
                <div style="flex: 1; padding-left: 16px;">
                    <div style="font-weight: 500; font-size: 0.85rem;">{sg.triggered_rule}</div>
                    {f'<div style="font-size: 0.78rem; color: rgba(255,255,255,0.7); margin-top: 4px;">{sg.execution_guidance}</div>' if sg.execution_guidance else ''}
                </div>
            </div>
            {monthly_gate_note}

            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Index ETF</th>
                            <th class="text-right">Price</th>
                            <th class="text-right">Dist 20-EMA</th>
                            <th class="text-center">20-EMA Gate</th>
                            <th class="text-right">Dist 50-DMA</th>
                            <th class="text-center">50-DMA Gate</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td class="flex-cell">
                                <span class="ticker-circle">S</span>
                                <strong>SPY</strong>
                            </td>
                            <td class="text-right font-mono">${sg.spy_price:,.2f}</td>
                            <td class="text-right font-mono {spy_20_c}">{_fmt_pct(sg.spy_20ema_dist_pct)}</td>
                            <td class="text-center">{spy_20_pill}</td>
                            <td class="text-right font-mono {spy_50_c}">{_fmt_pct(sg.spy_50dma_dist_pct)}</td>
                            <td class="text-center">{spy_50_pill}</td>
                        </tr>
                        <tr>
                            <td class="flex-cell">
                                <span class="ticker-circle">Q</span>
                                <strong>QQQ</strong>
                            </td>
                            <td class="text-right font-mono">${sg.qqq_price:,.2f}</td>
                            <td class="text-right font-mono {qqq_20_c}">{_fmt_pct(sg.qqq_20ema_dist_pct)}</td>
                            <td class="text-center">{qqq_20_pill}</td>
                            <td class="text-right font-mono {qqq_50_c}">{_fmt_pct(sg.qqq_50dma_dist_pct)}</td>
                            <td class="text-center">{qqq_50_pill}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="vix-grid" style="margin-top: 18px;">
                <div class="vix-metric">
                    <span class="vix-label">VIX LEVEL &amp; 5D TREND</span>
                    <span class="vix-val font-mono">{sg.vix_level:.2f}</span>
                    <span class="vix-sub">5d Δ: {_fmt_delta(sg.vix_5d_trend)} pts</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">VOL TERM STRUCTURE</span>
                    <span class="vix-val" style="font-size: 16px; margin: 4px 0;">{sg.vix_term_structure}</span>
                    <span class="vix-sub">Hedging Pressure</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">S&amp;P 500 &gt; 50 DMA</span>
                    <span class="vix-val font-mono">{sg.breadth_pct_above_50dma:.1f}%</span>
                    <span class="vix-sub">{sg.breadth_ad_state}</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">NET NEW 52W HIGHS</span>
                    <span class="vix-val font-mono">{sg.net_new_highs:+d}</span>
                    <span class="vix-sub">Expansion Gauge</span>
                </div>
            </div>

            <details class="methodology-note" style="margin-top: 16px;">
                <summary>ℹ️ How the Swing-Trade Posture is determined</summary>
                <div class="methodology-content">
                    <p>The Swing-Trade Regime Gate evaluates benchmark index moving averages, implied volatility, and market breadth to establish systematic quantitative posture thresholds:</p>
                    <ul style="padding-left: 18px; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">
                        <li><strong>FULL:</strong> SPY &amp; QQQ both above rising 20-EMA, VIX &lt; 20.0 in contango, and &gt; 50% of stocks &gt; 50-DMA. Favorable broad-market expansion environment.</li>
                        <li><strong>REDUCED:</strong> Either index below 20-EMA or VIX in 20.0–25.0 cautious zone. Measured exposure profile under consolidating benchmark averages.</li>
                        <li><strong>SELECTIVE:</strong> VIX &gt; 25.0, breadth &lt; 40%, or key moving average divergences. Restrictive exposure profile favoring relative strength divergence.</li>
                        <li><strong>DEFENSIVE:</strong> Both indices below 50-DMA or acute systemic distress. High-risk distribution regime with benchmark moving averages broken.</li>
                    </ul>
                </div>
            </details>
            """)

        # Section: Index Snapshot
        elif isinstance(sec.data, IndexSnapshotData):
            snap_data: IndexSnapshotData = sec.data
            rows_html = []
            for r in snap_data.rows:
                vol_str = r.volume_ratio_display if hasattr(r, "volume_ratio_display") and r.volume_ratio_display else (f"{r.volume_ratio:.2f}x" if r.volume_ratio > 0.01 else "&mdash;")
                rows_html.append(f"""
                <tr>
                    <td><strong>{r.name}</strong> <span class="ticker-sub font-mono">{r.symbol}</span></td>
                    <td class="text-right">{_fmt_price(r.close)}</td>
                    <td class="text-right">{_fmt_pct(r.pct_change)}</td>
                    <td class="text-right font-mono">{vol_str}</td>
                    <td class="text-right">{_fmt_pct(r.prev_period_change)}</td>
                    <td class="text-right">{_fmt_pct(r.delta_vs_prev_period)}</td>
                </tr>
                """)
            val_card_html = ""
            if getattr(snap_data, "valuation", None):
                v = snap_data.valuation
                pe_disp = f"{v.forward_pe:.2f}x" if v.forward_pe is not None else '<span class="text-muted font-mono">n/a</span>'
                nom_disp = f"{v.nominal_erp_bps:+.1f} bps" if v.nominal_erp_bps is not None else '<span class="text-muted font-mono">n/a</span>'
                real_disp = f"{v.real_erp_bps:+.1f} bps" if v.real_erp_bps is not None else '<span class="text-muted font-mono">n/a</span>'
                val_card_html = f"""
                <div class="note-box" style="margin-top: 12px;">
                    <strong>S&amp;P 500 Valuation vs. Rates:</strong> Forward P/E: <span class="font-mono font-bold">{pe_disp}</span> &bull; 
                    Nominal ERP: <span class="font-mono font-bold">{nom_disp}</span> &bull; 
                    Real ERP: <span class="font-mono font-bold">{real_disp}</span> &bull; 
                    Forward EPS Trend: <span class="font-mono font-bold">{v.eps_revision_trend}</span>
                </div>
                """

            body_html.append(f"""
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Benchmark Index</th>
                            <th class="text-right">Close</th>
                            <th class="text-right">Period Return</th>
                            <th class="text-right">Vol vs 20d Avg</th>
                            <th class="text-right">Prev Return</th>
                            <th class="text-right">Period &Delta;</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows_html)}
                    </tbody>
                </table>
            </div>
            {val_card_html}
            """)


        # Section: Technical Indicators
        elif isinstance(sec.data, TechnicalsData):
            t_data: TechnicalsData = sec.data
            cards = []
            for snap in t_data.snapshots:
                rsi_badge = "badge-red" if "Overbought" in snap.rsi_flag else ("badge-green" if "Oversold" in snap.rsi_flag else "badge-muted")
                cards.append(f"""
                <div class="tech-card">
                    <div class="tech-header">
                        <h3>{snap.name} <span class="font-mono text-muted">({snap.symbol})</span></h3>
                        <span class="tech-price font-mono">{snap.price:,.2f}</span>
                    </div>
                    <div class="grid-2">
                        <div class="metric-group">
                            <span class="metric-title">Moving Averages</span>
                            <div class="metric-row"><span>20 DMA:</span> <span>{_fmt_price(snap.dma_20)} ({_fmt_pct(snap.price_vs_dma20_pct)})</span></div>
                            <div class="metric-row"><span>50 DMA:</span> <span>{_fmt_price(snap.dma_50)} ({_fmt_pct(snap.price_vs_dma50_pct)})</span></div>
                            <div class="metric-row"><span>200 DMA:</span> <span>{_fmt_price(snap.dma_200)} ({_fmt_pct(snap.price_vs_dma200_pct)})</span></div>
                            <div class="metric-row"><span>50/200 Cross:</span> <strong>{snap.cross_50_200}</strong></div>
                        </div>
                        <div class="metric-group">
                            <span class="metric-title">Momentum & Trend</span>
                            <div class="metric-row">
                                <span>RSI (14):</span> 
                                <span><strong class="font-mono">{snap.rsi:.1f}</strong> (Prev: {snap.prev_rsi:.1f}, &Delta;: {_fmt_delta(snap.delta_rsi)}) <span class="badge {rsi_badge}">{snap.rsi_flag}</span></span>
                            </div>
                            <div class="metric-row">
                                <span>MACD (12,26,9):</span> 
                                <span>Line <strong class="font-mono">{snap.macd:.2f}</strong> &bull; Sig <span class="font-mono">{snap.macd_signal:.2f}</span> &bull; Hist {_fmt_delta(snap.macd_hist)}</span>
                            </div>
                            <div class="metric-row"><span>MACD Status:</span> <em>{snap.macd_status}</em></div>
                            <div class="metric-row">
                                <span>ADX (14):</span> 
                                <span><strong class="font-mono">{snap.adx:.1f}</strong> (+DI: {snap.plus_di:.1f}, -DI: {snap.minus_di:.1f}, &Delta;: {_fmt_delta(snap.delta_adx)}) — <em>{snap.trend_strength}</em></span>
                            </div>
                        </div>
                    </div>
                </div>
                """)
            body_html.append(f'<div class="tech-container">{"".join(cards)}</div>')
            if charts:
                body_html.append(_render_chart_html(charts.get("spx_technicals")))
                body_html.append(_render_chart_html(charts.get("ndx_technicals")))

        # Section: Volatility
        elif isinstance(sec.data, VolatilityData):
            vd: VolatilityData = sec.data
            if vd.current_level < 16.5:
                regime_class = "badge-bullish"
            elif vd.current_level < 20.0:
                regime_class = "badge-neutral"
            else:
                regime_class = "badge-bearish"

            body_html.append(f"""
            <div class="vix-grid">
                <div class="vix-metric">
                    <span class="vix-label">VIX LEVEL</span>
                    <span class="vix-val font-mono">{vd.current_level:.2f}</span>
                    <span class="vix-sub">Previous: {vd.prev_level:.2f}</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">PERIOD CHANGE</span>
                    <span class="vix-val font-mono">{_fmt_delta(vd.change)}</span>
                    <span class="vix-sub">({_fmt_pct(vd.pct_change)})</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">IMPLIED DAILY MOVE</span>
                    <span class="vix-val font-mono">&plusmn;{vd.implied_daily_move_pct:.2f}%</span>
                    <span class="vix-sub">Rule of 16 (1&sigma;)</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">PERIOD RANGE</span>
                    <span class="vix-val font-mono">{vd.period_low:.2f} &ndash; {vd.period_high:.2f}</span>
                    <span class="vix-sub">Intra-period range</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">VOLATILITY REGIME</span>
                    <span class="badge {regime_class}">{vd.regime.upper()}</span>
                    <p class="vix-desc">{vd.regime_description}</p>
                </div>
            </div>
            """)

            if charts:
                body_html.append(_render_chart_html(charts.get("vix_regime")))

            body_html.append("""
            <details class="methodology-note" style="margin-top: 16px;">
                <summary>ℹ️ Volatility Regimes &amp; Risk Thresholds</summary>
                <div class="methodology-content">
                    <p><strong>Regime Classification:</strong> Implied volatility boundaries derived from CBOE VIX pricing:</p>
                    <ul style="padding-left: 18px; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">
                        <li><strong>&lt; 16.5 Low / Complacent:</strong> Favorable conditions for multi-day swing breakout setups with minimal overnight gap hazard.</li>
                        <li><strong>16.5 – 20.0 Normal:</strong> Standard historical distribution; typical 1&sigma; daily moves (~1.0% to 1.25%).</li>
                        <li><strong>20.0 – 26.0 Elevated / Caution:</strong> Increased hedging demand, choppy rotational intraday swings, and wider bid-ask spreads.</li>
                        <li><strong>&gt; 26.0 High Fear:</strong> Acute market distress, elevated overnight gap hazard, and sharp correlation spikes across assets.</li>
                    </ul>
                </div>
            </details>
            """)

        # Section: Macro & Economic Events (Stage 2)
        elif isinstance(sec.data, MacroSectionData):
            m_data: MacroSectionData = sec.data
            fr = m_data.fed_rates
            if fr.is_inverted:
                inv_badge = "badge-bearish"
            elif fr.spread_2s10s <= 0.15:
                inv_badge = "badge-neutral"
            else:
                inv_badge = "badge-bullish"

            # 1. Fed & Rates Overview
            body_html.append(f"""
            <div class="vix-grid" style="margin-bottom: 20px;">
                <div class="vix-metric">
                    <span class="vix-label">FED FUNDS EFFECTIVE</span>
                    <span class="vix-val font-mono">{fr.fed_funds_rate:.2f}%</span>
                    <span class="vix-sub">Target: {fr.target_range}</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">10-YEAR YIELD</span>
                    <span class="vix-val font-mono">{fr.yield_10y:.2f}%</span>
                    <span class="vix-sub">Period &Delta;: {_fmt_delta(fr.yield_10y_delta * 100)} bps</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">2-YEAR YIELD</span>
                    <span class="vix-val font-mono">{fr.yield_2y:.2f}%</span>
                    <span class="vix-sub">Period &Delta;: {_fmt_delta(fr.yield_2y_delta * 100)} bps</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">2s10s SPREAD</span>
                    <span class="vix-val font-mono">{fr.spread_2s10s * 100:+.1f} bps</span>
                    <span class="badge {inv_badge}">{fr.curve_status.upper()}</span>
                </div>
            </div>
            """)


            # 2. Standing Macro Dashboard (latest values, Stage 3: 3.1)
            if getattr(m_data, "standing_dashboard", None):
                if period.report_type == "daily":
                    cpi_row = next((r for r in m_data.standing_dashboard if "CPI" in r.indicator and "YoY" in r.indicator), None)
                    pce_row = next((r for r in m_data.standing_dashboard if "Core PCE" in r.indicator), None)
                    pay_row = next((r for r in m_data.standing_dashboard if "Nonfarm" in r.indicator or "Payrolls" in r.indicator), None)
                    un_row = next((r for r in m_data.standing_dashboard if "Unemployment" in r.indicator), None)
                    gdp_row = next((r for r in m_data.standing_dashboard if "GDP" in r.indicator), None)

                    anchors = []
                    if cpi_row:
                        anchors.append(f'CPI YoY <span class="font-mono font-bold">{cpi_row.latest_value}</span>')
                    if pce_row:
                        anchors.append(f'Core PCE YoY <span class="font-mono font-bold">{pce_row.latest_value}</span>')
                    if pay_row:
                        anchors.append(f'Payrolls <span class="font-mono font-bold">{pay_row.latest_value}</span>')
                    if un_row:
                        anchors.append(f'Unemployment <span class="font-mono font-bold">{un_row.latest_value}</span>')
                    if gdp_row:
                        anchors.append(f'Real GDP <span class="font-mono font-bold">{gdp_row.latest_value}</span>')
                    anchor_str = " &bull; ".join(anchors) if anchors else "Inflation and labor anchors stable"

                    body_html.append(f"""
                    <h3 class="sub-title">Macro Dashboard (latest values)</h3>
                    <div style="padding: 14px 18px; border-radius: 8px; background: var(--bg-card-subtle); border-left: 4px solid var(--primary); margin-bottom: 20px;">
                        <p style="font-size: 13px; margin: 0; line-height: 1.5;">ℹ️ <strong>Standing Baseline:</strong> No major macro prints released on this session. Key anchors: {anchor_str}. <span class="text-muted">The complete 16-indicator multi-month tracking matrix and release cadence are published in the Weekly &amp; Monthly reports.</span></p>
                    </div>
                    """)
                else:
                    dash_rows = []
                    for row in m_data.standing_dashboard:
                        if "Rising" in row.direction_3m:
                            dir_style = "color: #0284c7; font-weight: bold;"
                        elif "Falling" in row.direction_3m:
                            dir_style = "color: #d97706; font-weight: bold;"
                        else:
                            dir_style = "color: var(--text-muted);"

                        dash_rows.append(f"""
                        <tr>
                            <td><strong>{row.indicator}</strong></td>
                            <td><span class="text-muted" style="font-size: 12px;">{row.category}</span></td>
                            <td class="text-right font-mono font-bold">{row.latest_value}</td>
                            <td class="text-right font-mono text-muted">{row.prior_value}</td>
                            <td class="text-center font-mono" style="{dir_style}">{row.direction_3m}</td>
                            <td class="text-center"><span class="badge badge-neutral" style="font-size: 11px;">{row.plain_label}</span></td>
                            <td class="text-center font-mono" style="font-size: 12px;">{row.reference_period}</td>
                            <td class="text-center font-mono" style="font-size: 12px;">{row.release_date}</td>
                            <td class="text-center font-mono" style="font-size: 12px; color: var(--color-primary);">{row.next_release_date}</td>
                            <td><span class="text-muted" style="font-size: 11px;">{row.source}</span></td>
                        </tr>
                        """)

                    body_html.append(f"""
                    <h3 class="sub-title">Macro Dashboard (latest values)</h3>
                    <p class="table-caption">Standing macroeconomic indicators across Inflation, Labor, and Economic Activity with 3-month trajectories and scheduled catalyst cadence.</p>
                    <div class="table-container">
                        <table class="report-table compact-table">
                            <thead>
                                <tr>
                                    <th>Indicator</th>
                                    <th>Category</th>
                                    <th class="text-right">Latest Value</th>
                                    <th class="text-right">Prior Value</th>
                                    <th class="text-center">3M Direction</th>
                                    <th class="text-center">Signal Interpretation</th>
                                    <th class="text-center">Ref. Period</th>
                                    <th class="text-center">Release Date</th>
                                    <th class="text-center">Next Release</th>
                                    <th>Source</th>
                                </tr>
                            </thead>
                            <tbody>{''.join(dash_rows)}</tbody>
                        </table>
                    </div>
                    """)

            # 3. Market-Based Indicators Table (Stage 3: 3.1)
            if getattr(m_data, "market_indicators", None):
                mkt_rows = []
                for row in m_data.market_indicators:
                    mkt_rows.append(f"""
                    <tr>
                        <td><strong>{row.indicator}</strong></td>
                        <td class="text-center font-mono" style="font-size: 12px;">{row.series_id}</td>
                        <td class="text-right font-mono font-bold">{row.latest_level}</td>
                        <td class="text-right font-mono text-muted">{row.prior_level}</td>
                        <td class="text-right font-mono font-bold">{row.period_change}</td>
                        <td class="text-center"><span class="badge badge-neutral" style="font-size: 11px;">{row.trend_3m}</span></td>
                        <td><span class="text-muted" style="font-size: 11px;">{row.source}</span></td>
                    </tr>
                    """)

                body_html.append(f"""
                <h3 class="sub-title" style="margin-top: 24px;">Market-Based Indicators</h3>
                <p class="table-caption">Daily financial series reflecting credit spreads, TIPS real yields, breakeven inflation, and term structure slopes.</p>
                <div class="table-container">
                    <table class="report-table compact-table">
                        <thead>
                            <tr>
                                <th>Indicator</th>
                                <th class="text-center">Series ID</th>
                                <th class="text-right">Latest Level</th>
                                <th class="text-right">Prior Level</th>
                                <th class="text-right">Period &Delta;</th>
                                <th class="text-center">Regime / Status</th>
                                <th>Source</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(mkt_rows)}</tbody>
                    </table>
                </div>
                """)

            # 4. Key Economic Releases (this period)
            body_html.append("""
            <h3 class="sub-title" style="margin-top: 24px;">Key Economic Releases (this period)</h3>
            """)
            if m_data.recent_releases:
                rel_rows = []
                for r in m_data.recent_releases[:8]:
                    s_badge = (
                        "badge-red" if r.surprise_flag in ("hot", "weak") else (
                            "badge-green" if r.surprise_flag in ("cool", "strong") else "badge-muted"
                        )
                    )
                    act_val = _fmt_macro_val(r.actual, r.unit)
                    fc_val = _fmt_macro_val(r.forecast, r.unit) if r.forecast is not None else '<span class="text-muted font-mono">n/a (no consensus)</span>'
                    pr_val = _fmt_macro_val(r.previous, r.unit)
                    s_label = r.surprise_flag.upper() if r.surprise_flag not in ("n/a", "n/a (no consensus)", "n/a (unpolled)") else "NO CONSENSUS"

                    rel_rows.append(f"""
                    <tr>
                        <td><strong>{r.title}</strong></td>
                        <td class="text-center font-mono">{r.reference_period or r.date}</td>
                        <td class="text-center font-mono">{r.release_date or r.date}</td>
                        <td class="text-right font-mono font-bold">{act_val}</td>
                        <td class="text-right font-mono">{fc_val}</td>
                        <td class="text-right font-mono">{pr_val}</td>
                        <td class="text-center"><span class="badge {s_badge}">{s_label}</span></td>
                    </tr>
                    """)
                body_html.append(f"""
                <div class="table-container">
                    <table class="report-table">
                        <thead>
                            <tr><th>Event</th><th class="text-center">Reference Period</th><th class="text-center">Release Date</th><th class="text-right">Actual</th><th class="text-right">Forecast</th><th class="text-right">Previous</th><th class="text-center">Surprise</th></tr>
                        </thead>
                        <tbody>{''.join(rel_rows)}</tbody>
                    </table>
                </div>
                """)
            else:
                body_html.append("""
                <p class="text-muted" style="font-size: 13px; margin: 12px 0;">No major scheduled economic releases occurred during this reporting period.</p>
                """)

            # Forward-Looking Financial Conditions & Regime Quadrant
            if m_data.intelligence:
                intel = m_data.intelligence
                credit_badge = "badge-bullish" if ("Tight" in intel.credit.regime or "Normal" in intel.credit.regime) else "badge-bearish"
                vol_badge = "badge-bullish" if "Contango" in intel.vol_term.structure else ("badge-neutral" if "Flat" in intel.vol_term.structure else "badge-bearish")
                rot_badge = "badge-bullish" if intel.rotation.spread > 1.5 else ("badge-neutral" if intel.rotation.spread >= -1.5 else "badge-bearish")
                quad_badge = "badge-bullish" if "Goldilocks" in intel.quadrant else ("badge-neutral" if "Reflation" in intel.quadrant else "badge-bearish")

                body_html.append(f"""
                <h3 class="sub-title" style="margin-top: 24px;">Forward-Looking Financial Conditions &amp; Risk Premiums</h3>
                <div class="vix-grid" style="margin-bottom: 20px;">
                    <div class="vix-metric">
                        <span class="vix-label">HIGH-YIELD CREDIT OAS</span>
                        <span class="vix-val font-mono">{intel.credit.spread_bps:.0f} <small style="font-size: 13px;">bps</small></span>
                        <span class="vix-sub">Period &Delta;: {_fmt_delta(intel.credit.delta_bps)} bps ({intel.credit.spread_pct:.2f}%)</span>
                        <div style="margin-top: 6px;"><span class="badge {credit_badge}">{intel.credit.regime.upper()}</span></div>
                        <p class="vix-desc">{intel.credit.assessment}</p>
                    </div>
                    <div class="vix-metric">
                        <span class="vix-label">REAL 10Y TIPS YIELD</span>
                        <span class="vix-val font-mono">{intel.rates.real_yield_10y:.2f}%</span>
                        <span class="vix-sub">Period &Delta;: {_fmt_delta(intel.rates.real_yield_delta_bps)} bps | 10Y BE: {intel.rates.breakeven_10y:.2f}%</span>
                        <div style="margin-top: 6px;"><span class="badge badge-primary">{intel.rates.driver_attribution.upper()}</span></div>
                        <p class="vix-desc">{intel.rates.assessment}</p>
                    </div>
                    <div class="vix-metric">
                        <span class="vix-label">VIX TERM STRUCTURE (1M/3M)</span>
                        <span class="vix-val font-mono">{intel.vol_term.ratio:.3f}</span>
                        <span class="vix-sub">1M: {intel.vol_term.vix_1m:.2f} | 3M: {intel.vol_term.vix_3m:.2f} (&Delta; {intel.vol_term.ratio_delta:+.3f})</span>
                        <div style="margin-top: 6px;"><span class="badge {vol_badge}">{intel.vol_term.structure.upper()}</span></div>
                        <p class="vix-desc">{intel.vol_term.assessment}</p>
                    </div>
                    <div class="vix-metric">
                        <span class="vix-label">SECTOR ROTATION SPREAD</span>
                        <span class="vix-val font-mono">{intel.rotation.spread:+.2f}%</span>
                        <span class="vix-sub">Leading: {", ".join(intel.rotation.top_inflows[:2]) if intel.rotation.top_inflows else "Defensives"}</span>
                        <div style="margin-top: 6px;"><span class="badge {rot_badge}">{intel.rotation.posture.upper()}</span></div>
                        <p class="vix-desc"><strong>Lagging Sectors:</strong> {", ".join(intel.rotation.top_outflows[-2:]) if intel.rotation.top_outflows else "Growth"}. {intel.rotation.assessment}</p>
                    </div>
                </div>

                <!-- Credit & Funding Conditions (Stage 4: 4.5) -->
                <h3 class="sub-title" style="margin-top: 24px;">Credit &amp; Funding Conditions (Systemic Liquidity)</h3>
                <div class="vix-grid" style="margin-bottom: 20px;">
                    <div class="vix-metric">
                        <span class="vix-label">INVESTMENT-GRADE CREDIT OAS</span>
                        <span class="vix-val font-mono">{f"{intel.credit.ig_spread_bps:.0f} bps" if intel.credit.ig_spread_bps is not None else "n/a (source unavailable)"}</span>
                        <span class="vix-sub">{f"Period &Delta;: {_fmt_delta(intel.credit.ig_delta_bps)} bps" if intel.credit.ig_delta_bps is not None else "n/a"}</span>
                        <div style="margin-top: 6px;"><span class="badge badge-green">TIGHT / LOW SPREAD</span></div>
                        <p class="vix-desc">ICE BofA US Investment Grade Option-Adjusted Spread (FRED BAMLC0A0CM).</p>
                    </div>
                    <div class="vix-metric">
                        <span class="vix-label">3M / 10Y YIELD CURVE</span>
                        <span class="vix-val font-mono">{f"{intel.credit.spread_3m10y_bps:+.0f} bps" if intel.credit.spread_3m10y_bps is not None else "n/a (source unavailable)"}</span>
                        <span class="vix-sub">10Y minus 3M T-Bill (FRED T10Y3M)</span>
                        <div style="margin-top: 6px;"><span class="badge badge-bullish">{"NORMAL / UN-INVERTED" if (intel.credit.spread_3m10y_bps is not None and intel.credit.spread_3m10y_bps > 0) else "INVERTED"}</span></div>
                        <p class="vix-desc">Benchmark short-funding vs. long-duration curve spread.</p>
                    </div>
                    <div class="vix-metric">
                        <span class="vix-label">FINANCIAL STRESS INDEX</span>
                        <span class="vix-val font-mono">{f"{intel.credit.financial_stress_index:.2f}" if intel.credit.financial_stress_index is not None else "n/a (source unavailable)"}</span>
                        <span class="vix-sub">{intel.credit.financial_stress_label if intel.credit.financial_stress_index is not None else "n/a"}</span>
                        <div style="margin-top: 6px;"><span class="badge badge-primary">LOW STRESS</span></div>
                        <p class="vix-desc">St. Louis Fed Financial Stress Index (STLFSI4; 0 = normal average stress).</p>
                    </div>
                </div>

                <div class="macro-regime-card" style="background: var(--bg-card-subtle); border: 1px solid var(--border); border-radius: 10px; padding: 18px 22px; margin-bottom: 24px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
                        <div>
                            <span style="font-size: 11px; font-weight: 700; color: var(--text-muted); letter-spacing: 0.06em; text-transform: uppercase;">ACTIVE MACRO REGIME QUADRANT</span>
                            <div style="margin-top: 4px;"><span class="badge {quad_badge}" style="font-size: 13px; padding: 5px 12px;">{intel.summary_badge.upper()}</span></div>
                        </div>
                        <div style="display: flex; gap: 16px; font-size: 13px;">
                            <span><strong>Growth Signal:</strong> <span class="font-mono">{intel.growth_signal}</span></span>
                            <span><strong>Inflation Signal:</strong> <span class="font-mono">{intel.inflation_signal}</span></span>
                        </div>
                    </div>
                    <p style="font-size: 14px; line-height: 1.6; margin: 0; color: var(--text-main);">
                        <strong>Macro Positioning Synthesis:</strong> Economic activity reflects <strong>{intel.growth_signal}</strong> with inflation <strong>{intel.inflation_signal}</strong>, setting an active {intel.rotation.posture.lower()} tone.
                    </p>
                </div>
                """)

            # S&P 500 Valuation vs. Rates & ERP (Stage 3 Task 3.1 & Stage 4 Task 4.2)
            if m_data.valuation:
                v = m_data.valuation
                if v.forward_pe is None:
                    body_html.append("""
                    <h3 class="sub-title" style="margin-top: 24px;">S&amp;P 500 Valuation vs. Rates &amp; Equity Risk Premium</h3>
                    <div style="padding: 12px 16px; background: var(--bg-card-subtle); border-radius: 8px; font-size: 13px; color: var(--text-muted); margin-bottom: 16px;">
                        <span class="font-mono font-bold">n/a (source unavailable)</span> &mdash; Forward valuation multiples and consensus forward EPS estimates are currently unavailable from data provider. Equity Risk Premium metrics are omitted until verified forward earnings estimates are available.
                    </div>
                    """)
                else:
                    pe_str = f"{v.forward_pe:.2f}x"
                    ey_str = f"{v.earnings_yield_pct:.2f}%" if v.earnings_yield_pct is not None else '<span class="text-muted">n/a (source unavailable)</span>'
                    nom_hurdle = f"10Y Treasury ({v.nominal_10y_yield:.2f}%)" if v.nominal_10y_yield is not None else "10Y Treasury (DGS10)"
                    nom_erp_str = f"{v.nominal_erp_bps:+.1f} bps" if v.nominal_erp_bps is not None else "n/a (source unavailable)"
                    nom_class = "text-green font-bold" if (v.nominal_erp_bps and v.nominal_erp_bps >= 100.0) else ("text-yellow font-bold" if v.nominal_erp_bps else "text-muted")
                    real_hurdle = f"10Y TIPS ({v.real_10y_yield:.2f}%)" if v.real_10y_yield is not None else "10Y TIPS Real Yield (DFII10)"
                    real_erp_str = f"{v.real_erp_bps:+.1f} bps" if v.real_erp_bps is not None else "n/a (source unavailable)"
                    real_class = "text-green font-bold" if (v.real_erp_bps and v.real_erp_bps >= 200.0) else ("text-yellow font-bold" if v.real_erp_bps else "text-muted")

                    body_html.append(f"""
                    <h3 class="sub-title" style="margin-top: 24px;">S&amp;P 500 Valuation vs. Rates &amp; Equity Risk Premium</h3>
                    <div class="note-box" style="margin-bottom: 16px;">
                        <strong>Valuation &amp; ERP Context:</strong> {v.assessment}
                    </div>
                    <div class="table-container">
                        <table class="report-table">
                            <thead>
                                <tr>
                                    <th>Valuation Metric</th>
                                    <th class="text-center">Current Level</th>
                                    <th class="text-center">Benchmark / Hurdle</th>
                                    <th class="text-center">Spread / Risk Premium</th>
                                    <th>Sourcing &amp; Context</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><strong>Forward P/E</strong></td>
                                    <td class="text-center font-mono font-bold">{pe_str}</td>
                                    <td class="text-center">&mdash;</td>
                                    <td class="text-center">&mdash;</td>
                                    <td>Forward multiple on consensus 12M EPS ({v.source})</td>
                                </tr>
                                <tr>
                                    <td><strong>Earnings Yield (1/PE)</strong></td>
                                    <td class="text-center font-mono font-bold">{ey_str}</td>
                                    <td class="text-center">&mdash;</td>
                                    <td class="text-center">&mdash;</td>
                                    <td>Equity cash generation yield (1 / Forward P/E)</td>
                                </tr>
                                <tr>
                                    <td><strong>Nominal Equity Risk Premium (ERP)</strong></td>
                                    <td class="text-center font-mono">{ey_str}</td>
                                    <td class="text-center font-mono">{nom_hurdle}</td>
                                    <td class="text-center font-mono {nom_class}">{nom_erp_str}</td>
                                    <td>Earnings Yield minus 10Y Benchmark Yield</td>
                                </tr>
                                <tr>
                                    <td><strong>Real Equity Risk Premium (Real ERP)</strong></td>
                                    <td class="text-center font-mono">{ey_str}</td>
                                    <td class="text-center font-mono">{real_hurdle}</td>
                                    <td class="text-center font-mono {real_class}">{real_erp_str}</td>
                                    <td>Earnings Yield minus 10Y TIPS Real Yield</td>
                                </tr>
                                <tr>
                                    <td><strong>Forward EPS Revision Trend</strong></td>
                                    <td class="text-center font-mono font-bold" colspan="3">{v.eps_revision_trend}</td>
                                    <td>Revision momentum across S&amp;P 500 constituents</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    """)

            # 3. Cross-Asset Snapshot (Stage 3: 3.6 De-duplicate; link to Section 10 & 12)
            body_html.append("""
            <div class="alert alert-info" style="margin: 16px 0;">
                📊 <strong>Cross-Asset Intelligence &amp; Catalyst Horizon:</strong> Detailed commodity price performance, oil, gold, dollar, and bond cross-market alignments are consolidated in <a href="#section-10" style="color: var(--primary); font-weight: 700; text-decoration: underline;">Section 10: Commodities, Currencies &amp; Cross-Asset Tracker</a>. Forward event releases and catalyst horizons are tracked in <a href="#section-12" style="color: var(--primary); font-weight: 700; text-decoration: underline;">Section 12: Forward Calendar &amp; Catalyst Horizon</a>.
            </div>
            """)

            # 5. Historical Trends & Trajectory with Charts (Monthly Report)
            if m_data.historical_overview and m_data.historical_overview.indicators:
                inds = m_data.historical_overview.indicators
                chart_infl = render_inflation_chart(inds)
                chart_labor = render_labor_chart(inds)
                chart_rates = render_rates_chart(inds)
                chart_act = render_activity_chart(inds)

                body_html.append(f"""
                <h3 class="sub-title" style="margin-top: 28px;">Macroeconomic Historical Trends &amp; Visualizations (Trailing 12 Months)</h3>
                <div class="macro-charts-stack">
                    <div class="macro-chart-box">{chart_infl}</div>
                    <div class="macro-chart-box">{chart_labor}</div>
                    <div class="macro-chart-box">{chart_rates}</div>
                    <div class="macro-chart-box">{chart_act}</div>
                </div>
                """)

                # Historical Matrix Table (excluding quarterly series like GDP from monthly columns)
                anchor = next((ind for ind in inds if len(ind.points) >= 6 and ind.series_id != "GDPC1"), None)
                matrix_dates = [p.label for p in anchor.points[-6:]] if anchor else []

                th_cols = "".join(f'<th class="text-right">{md}</th>' for md in matrix_dates)
                rows_html = []
                for ind in inds:
                    if ind.series_id == "GDPC1" or "Q" in getattr(ind.points[0], "label", ""):
                        continue
                    lp = ind.latest_point
                    pp = ind.prior_point
                    if not lp:
                        continue

                    # Formatting monthly and yearly values
                    if "k" in ind.monthly_unit:
                        m_str = f'<span class="font-mono font-bold {("text-green" if lp.monthly_val >= 0 else "text-red")}">{lp.monthly_val:+.0f}k</span>'
                        y_str = f'<span class="font-mono font-bold">{lp.yearly_val:+.0f}k</span>'
                    elif ind.category == "Rates & Policy" or ind.series_id == "UNRATE":
                        m_str = f'<span class="font-mono font-bold">{lp.monthly_val:.2f}%</span>'
                        y_str = f'<span class="font-mono">{lp.yearly_val:+.2f}%</span>'
                    elif "index" in ind.monthly_unit:
                        m_str = f'<span class="font-mono font-bold">{lp.monthly_val:.1f}</span>'
                        y_str = f'<span class="font-mono">{lp.yearly_val:+.1f} pts</span>'
                    elif "%" in ind.monthly_unit:
                        m_str = _fmt_pct(lp.monthly_val) if "% MoM" in ind.monthly_unit or "%" == ind.monthly_unit else f'<span class="font-mono">{lp.monthly_val:.2f}%</span>'
                        y_str = _fmt_pct(lp.yearly_val) if "% YoY" in ind.yearly_unit else f'<span class="font-mono">{lp.yearly_val:.2f}%</span>'
                    else:
                        m_str = f'<span class="font-mono font-bold">{lp.monthly_val:.1f}</span>'
                        y_str = f'<span class="font-mono">{lp.yearly_val:+.1f}</span>'

                    # Prior values
                    if pp:
                        if "k" in ind.monthly_unit:
                            pr_str = f'<span class="font-mono text-muted">{pp.monthly_val:+.0f}k</span>'
                        elif ind.category == "Rates & Policy" or ind.series_id == "UNRATE":
                            pr_str = f'<span class="font-mono text-muted">{pp.monthly_val:.2f}%</span>'
                        elif "index" in ind.monthly_unit:
                            pr_str = f'<span class="font-mono text-muted">{pp.monthly_val:.1f}</span>'
                        elif "%" in ind.monthly_unit:
                            pr_str = f'<span class="font-mono text-muted">{pp.monthly_val:+.2f}%</span>'
                        else:
                            pr_str = f'<span class="font-mono text-muted">{pp.monthly_val:.1f}</span>'
                    else:
                        pr_str = '<span class="text-muted">n/a</span>'

                    # Trailing months values
                    pt_map = {p.label: p for p in ind.points}
                    td_history = []
                    for md in matrix_dates:
                        if md in pt_map:
                            p = pt_map[md]
                            if "k" in ind.monthly_unit:
                                td_history.append(f'<td class="text-right font-mono {("text-green" if p.monthly_val >= 0 else "text-red")}">{p.monthly_val:+.0f}k</td>')
                            elif ind.category == "Rates & Policy" or ind.series_id == "UNRATE":
                                td_history.append(f'<td class="text-right font-mono">{p.monthly_val:.2f}%</td>')
                            elif "index" in ind.monthly_unit:
                                td_history.append(f'<td class="text-right font-mono">{p.monthly_val:.1f}</td>')
                            elif "%" in ind.monthly_unit:
                                td_history.append(f'<td class="text-right font-mono {("text-green" if p.monthly_val > 0 else ("text-red" if p.monthly_val < 0 else "text-muted"))}">{p.monthly_val:+.2f}%</td>')
                            else:
                                td_history.append(f'<td class="text-right font-mono">{p.monthly_val:.1f}</td>')
                        else:
                            td_history.append('<td class="text-right font-mono text-muted">—</td>')

                    # Trend badge with category-aware economic valence
                    if ind.trend_direction == "Rising":
                        if ind.category == "Inflation":
                            t_badge = '<span class="badge badge-red">▲ ACCELERATING</span>'
                        elif ind.series_id == "UNRATE":
                            t_badge = '<span class="badge badge-red">▲ RISING</span>'
                        elif ind.category == "Rates & Policy":
                            t_badge = '<span class="badge badge-neutral">▲ RISING</span>'
                        else:
                            t_badge = '<span class="badge badge-green">▲ EXPANDING</span>'
                    elif ind.trend_direction == "Falling":
                        if ind.category == "Inflation":
                            t_badge = '<span class="badge badge-green">▼ MODERATING</span>'
                        elif ind.series_id == "UNRATE":
                            t_badge = '<span class="badge badge-green">▼ FALLING</span>'
                        elif ind.category == "Rates & Policy":
                            t_badge = '<span class="badge badge-neutral">▼ EASING</span>'
                        else:
                            t_badge = '<span class="badge badge-red">▼ SLOWING</span>'
                    else:
                        t_badge = '<span class="badge badge-muted">▶ STEADY</span>'

                    rows_html.append(f"""
                    <tr>
                        <td><strong>{ind.name}</strong> <span class="ticker-sub font-mono">({ind.category})</span></td>
                        <td class="text-center font-mono">{lp.label}</td>
                        <td class="text-right">{m_str}</td>
                        <td class="text-right">{y_str}</td>
                        <td class="text-right">{pr_str}</td>
                        {''.join(td_history)}
                        <td class="text-center">{t_badge}</td>
                    </tr>
                    """)

                body_html.append(f"""
                <h3 class="sub-title">Key Macroeconomic Reports: Monthly &amp; Yearly Matrix</h3>
                <div class="table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Report Indicator</th>
                                <th class="text-center">Latest Period</th>
                                <th class="text-right">Monthly Value</th>
                                <th class="text-right">Yearly Value</th>
                                <th class="text-right">Prior Month</th>
                                {th_cols}
                                <th class="text-center">1-Yr Trend</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(rows_html)}</tbody>
                    </table>
                </div>
                """)
            if charts:
                body_html.append(_render_chart_html(charts.get("rates_yield_curve")))


        # Section: Sector Report
        elif isinstance(sec.data, SectorReportData):
            s_data: SectorReportData = sec.data
            s_rows = []
            for sr in s_data.rows:
                r_delta_class = "text-green" if sr.rank_change > 0 else ("text-red" if sr.rank_change < 0 else "text-muted")
                r_delta_str = f"+{sr.rank_change}" if sr.rank_change > 0 else str(sr.rank_change)
                s_rows.append(f"""
                <tr>
                    <td class="text-center"><strong>#{sr.rank}</strong></td>
                    <td><strong>{sr.name}</strong></td>
                    <td class="font-mono text-center">{sr.symbol}</td>
                    <td class="text-right">{_fmt_price(sr.close)}</td>
                    <td class="text-right">{_fmt_pct(sr.pct_change)}</td>
                    <td class="text-right">{_fmt_pct(sr.relative_strength_vs_spy)}</td>
                    <td class="text-center font-mono">#{sr.prev_rank}</td>
                    <td class="text-center font-mono {r_delta_class}"><strong>{r_delta_str}</strong></td>
                </tr>
                """)
            w_tag = "[1-Month Strategic View]" if period.report_type == "monthly" else ("[1-Week Swing View]" if period.report_type == "weekly" else "[Daily Tactical View]")
            
            # Sector Breadth Table (Stage 4: 4.2)
            b_rows = []
            if getattr(s_data, "sector_breadth", None):
                for b_item in s_data.sector_breadth:
                    p50_str = f"{b_item.pct_above_50dma:.1f}%" if b_item.pct_above_50dma is not None else '<span class="text-muted">n/a</span>'
                    p20_str = f"{b_item.pct_above_20dma:.1f}%" if b_item.pct_above_20dma is not None else '<span class="text-muted">n/a</span>'
                    nh_str = f"{b_item.net_new_highs:+d}" if b_item.net_new_highs is not None else '<span class="text-muted">n/a</span>'
                    p50_class = "text-green font-bold" if (b_item.pct_above_50dma or 0) >= 60.0 else (("text-red font-bold") if (b_item.pct_above_50dma or 0) < 40.0 else "text-muted")
                    b_rows.append(f"""
                    <tr>
                        <td><strong>{b_item.sector}</strong></td>
                        <td class="font-mono text-center">{b_item.symbol}</td>
                        <td class="text-right font-mono {p50_class}">{p50_str}</td>
                        <td class="text-right font-mono">{p20_str}</td>
                        <td class="text-right font-mono font-bold">{nh_str}</td>
                    </tr>
                    """)

            breadth_table_html = ""
            if b_rows:
                breadth_table_html = f"""
                <h3 class="sub-title" style="margin-top: 24px;">Sector Breadth &amp; Moving Average Distribution</h3>
                <p class="table-caption">Constituent breadth participation (% above 50-DMA, % above 20-DMA, and 52-week net new highs) across each sector.</p>
                <div class="table-container">
                    <table class="report-table compact-table">
                        <thead>
                            <tr>
                                <th>Sector Name</th>
                                <th class="text-center">ETF Symbol</th>
                                <th class="text-right">% &gt; 50-DMA</th>
                                <th class="text-right">% &gt; 20-DMA</th>
                                <th class="text-right">Net New Highs (52W)</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(b_rows)}</tbody>
                    </table>
                </div>
                """

            # Sector Leaders Table (Stage 4: 4.2 & Stage 2: 2.2)
            leaders_html = ""
            if getattr(s_data, "sector_leaders", None):
                if period.report_type == "daily":
                    top_syms = []
                    for s_name, l_list in s_data.sector_leaders.items():
                        top_2 = [f"<strong>{s_name}:</strong> " + ", ".join([f'<span class="font-mono font-bold">{l.symbol}</span> ({l.name}, RS {_fmt_pct(l.composite_rs if l.composite_rs != 0.0 else l.rs_vs_spy_pct)})' for l in l_list[:2]])]
                        top_syms.extend(top_2)
                    summary_html = " &bull; ".join(top_syms) if top_syms else "None"
                    banner_html = ""
                    if getattr(s_data, "defensive_exception_banner", None):
                        banner_html = f"""
                        <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 4px; margin-top: 12px; margin-bottom: 16px; color: #b91c1c; font-weight: 600;">
                            {s_data.defensive_exception_banner}
                        </div>
                        """
                    leaders_html = f"""
                    <h3 class="sub-title" style="margin-top: 24px;">Top Relative Strength Leaders (Top 3 Leading Sectors)</h3>
                    {banner_html}
                    <div style="padding: 14px 18px; border-radius: 8px; background: var(--bg-card-subtle); border-left: 4px solid var(--primary); margin-top: 12px; margin-bottom: 16px;">
                        <p style="font-size: 13px; margin: 0; line-height: 1.5;">💡 <strong>Tactical RS Leaders Snapshot:</strong> {summary_html}. <span class="text-muted">The complete 21-stock screening matrix and multi-factor breakdown are published in the Weekly &amp; Monthly reports.</span></p>
                    </div>
                    """
                else:
                    leader_sections = []
                    for sec_name, l_list in s_data.sector_leaders.items():
                        l_rows = []
                        for rank_idx, leader in enumerate(l_list, 1):
                            if leader.avg_dollar_volume >= 1e9:
                                d_vol_str = f"${leader.avg_dollar_volume / 1e9:,.2f}B"
                            else:
                                d_vol_str = f"${leader.avg_dollar_volume / 1e6:,.1f}M"
                            crs_val = leader.composite_rs if leader.composite_rs != 0.0 else leader.rs_vs_spy_pct
                            exc_badge = ' <span class="badge badge-yellow" style="font-size: 11px; margin-left: 4px;">Exception candidate (gate Defensive)</span>' if getattr(leader, "is_exception_candidate", False) else ""
                            l_rows.append(f"""
                            <tr>
                                <td class="text-center font-bold">#{rank_idx}</td>
                                <td class="font-mono"><strong>{leader.symbol}</strong>{exc_badge}</td>
                                <td>{leader.name}</td>
                                <td class="text-right font-mono">${leader.close:,.2f}</td>
                                <td class="text-right font-bold font-mono">{_fmt_pct(crs_val)}</td>
                                <td class="text-right font-mono">{_fmt_pct(leader.ret_1w)}</td>
                                <td class="text-right font-mono">{_fmt_pct(leader.dist_52w_high_pct)}</td>
                                <td class="text-right font-mono">{leader.volume_ratio:.2f}x</td>
                                <td class="text-right font-mono text-muted">{d_vol_str}</td>
                            </tr>
                            """)
                        leader_sections.append(f"""
                        <div style="margin-top: 16px;">
                            <h4 style="font-size: 14px; font-weight: 700; color: var(--primary); margin-bottom: 6px;">Top Relative Strength Stocks: {sec_name}</h4>
                            <div class="table-container">
                                <table class="report-table compact-table">
                                    <thead>
                                        <tr>
                                            <th class="text-center">Rank</th>
                                            <th>Ticker</th>
                                            <th>Company Name</th>
                                            <th class="text-right">Close</th>
                                            <th class="text-right">Composite RS</th>
                                            <th class="text-right">1W Return</th>
                                            <th class="text-right">Dist 52W High</th>
                                            <th class="text-right">20D Vol Ratio</th>
                                            <th class="text-right">Avg $ Volume</th>
                                        </tr>
                                    </thead>
                                    <tbody>{''.join(l_rows)}</tbody>
                                </table>
                            </div>
                        </div>
                        """)
                    if leader_sections:
                        banner_html = ""
                        if getattr(s_data, "defensive_exception_banner", None):
                            banner_html = f"""
                            <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 4px; margin-top: 12px; margin-bottom: 16px; color: #b91c1c; font-weight: 600;">
                                {s_data.defensive_exception_banner}
                            </div>
                            """
                        leaders_html = f"""
                        <h3 class="sub-title" style="margin-top: 24px;">Top Relative Strength Leaders (Top 3 Leading Sectors)</h3>
                        {banner_html}
                        <p class="table-caption">Screened for stocks above 50-DMA, within 15% of 52-week highs, and minimum $20M daily dollar volume (ranked by Composite RS vs SPY).</p>
                        {''.join(leader_sections)}
                        """

            body_html.append(f"""
            <h3 class="sub-title">11 SPDR Sector Relative Strength Matrix {w_tag}</h3>
            <p class="table-caption">Benchmark SPY Return: {_fmt_pct(s_data.spy_pct_change)} (Previous Period: {_fmt_pct(s_data.spy_prev_pct_change)})</p>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th class="text-center">Rank</th>
                            <th>Sector</th>
                            <th class="text-center">Symbol</th>
                            <th class="text-right">Close</th>
                            <th class="text-right">Return</th>
                            <th class="text-right">RS vs SPY</th>
                            <th class="text-center">Prior Rank</th>
                            <th class="text-center">Rank &Delta;</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(s_rows)}
                    </tbody>
                </table>
            </div>
            {breadth_table_html}
            {leaders_html}
            """)

            if charts:
                if charts.get("sector_timeframe_heatmap"):
                    body_html.append(_render_chart_html(charts.get("sector_timeframe_heatmap")))
                body_html.append(_render_chart_html(charts.get("sector_performance")))

        # Section: Theme & Industry Relative Strength
        elif isinstance(sec.data, ThemeRelativeStrengthData):
            tr: ThemeRelativeStrengthData = sec.data
            is_d = getattr(tr, "primary_window", "1W") == "1D"
            is_m = getattr(tr, "primary_window", "1W") == "1M"
            t_rows = []
            for item in tr.items:
                if not item.is_available:
                    t_rows.append(f"""
                    <tr>
                        <td class="text-center text-muted">&mdash;</td>
                        <td><strong>{item.name}</strong></td>
                        <td class="font-mono text-center">{item.symbol}</td>
                        <td>{item.category}</td>
                        <td colspan="7" class="text-center text-muted">n/a (source unavailable)</td>
                    </tr>
                    """)
                    continue
                r_delta_class = "text-green font-bold" if item.rank_change > 0 else ("text-red font-bold" if item.rank_change < 0 else "text-muted")
                r_delta_str = f"+{item.rank_change}" if item.rank_change > 0 else str(item.rank_change)
                d50_class = "badge-green" if item.above_50dma else "badge-red"
                d50_tag = "Above" if item.above_50dma else "Below"

                if is_d:
                    ret_primary = _fmt_pct(item.ret_1d)
                    ret_secondary = _fmt_pct(item.ret_1w)
                    ret_tertiary = _fmt_pct(item.ret_1m)
                elif is_m:
                    ret_primary = _fmt_pct(item.ret_1m)
                    ret_secondary = _fmt_pct(item.ret_1w)
                    ret_tertiary = _fmt_pct(item.ret_3m)
                else:
                    ret_primary = _fmt_pct(item.ret_1w)
                    ret_secondary = _fmt_pct(item.ret_1m)
                    ret_tertiary = _fmt_pct(item.ret_3m)

                t_rows.append(f"""
                <tr>
                    <td class="text-center"><strong>#{item.rank}</strong></td>
                    <td><strong>{item.name}</strong></td>
                    <td class="font-mono text-center">{item.symbol}</td>
                    <td>{item.category}</td>
                    <td class="text-right font-mono">${item.close:,.2f}</td>
                    <td class="text-right">{ret_primary}</td>
                    <td class="text-right">{ret_secondary}</td>
                    <td class="text-right">{ret_tertiary}</td>
                    <td class="text-right">{_fmt_pct(item.rs_vs_spy)}</td>
                    <td class="text-center font-mono {r_delta_class}">{r_delta_str}</td>
                    <td class="text-center"><span class="badge {d50_class}">{item.dist_50dma_pct:+.1f}% ({d50_tag})</span></td>
                </tr>
                """)

            summary_box = ""
            if tr.top_theme_summary:
                summary_box = f'<div class="alert alert-info" style="margin-bottom: 14px;">🏆 <strong>Theme Leadership:</strong> {tr.top_theme_summary}</div>'

            commentary_box = ""
            if tr.commentary:
                commentary_box = f'<p class="table-caption" style="margin-top: 10px;">💡 <em>{tr.commentary}</em></p>'

            bench_caption = getattr(tr, "primary_benchmark_label", f"Benchmark SPY 1-Week Return: {_fmt_pct(tr.spy_1w_return)}")
            bench_val = getattr(tr, "primary_benchmark_return", tr.spy_1w_return)
            
            if is_d:
                w_primary_hdr = "1D Return (Primary)"
                w_sec_hdr = "1W Return"
                w_tert_hdr = "1M Return"
                rs_hdr = "RS vs SPY (1D)"
                rank_d_hdr = "Rank &Delta; (vs 1W)"
            elif is_m:
                w_primary_hdr = "1M Return (Primary)"
                w_sec_hdr = "1W Return"
                w_tert_hdr = "3M Return"
                rs_hdr = "RS vs SPY (1M)"
                rank_d_hdr = "Rank &Delta; (vs 3M)"
            else:
                w_primary_hdr = "1W Return (Primary)"
                w_sec_hdr = "1M Return"
                w_tert_hdr = "3M Return"
                rs_hdr = "RS vs SPY (1W)"
                rank_d_hdr = "Rank &Delta; (vs 1M)"

            body_html.append(f"""
            {summary_box}
            <p class="table-caption">Benchmark {bench_caption}: {_fmt_pct(bench_val)} &bull; Primary Window: <strong>{getattr(tr, 'primary_window', '1W')}</strong></p>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th class="text-center">Rank</th>
                            <th>Theme / Industry ETF</th>
                            <th class="text-center">Symbol</th>
                            <th>Category</th>
                            <th class="text-right">Close</th>
                            <th class="text-right">{w_primary_hdr}</th>
                            <th class="text-right">{w_sec_hdr}</th>
                            <th class="text-right">{w_tert_hdr}</th>
                            <th class="text-right">{rs_hdr}</th>
                            <th class="text-center">{rank_d_hdr}</th>
                            <th class="text-center">50-DMA Dist</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(t_rows)}
                    </tbody>
                </table>
            </div>
            {commentary_box}
            """)

        # Section: Commodities, Currencies & Cross-Asset
        elif isinstance(sec.data, CommoditiesCrossAssetData):
            ca_data: CommoditiesCrossAssetData = sec.data
            ca_rows = []
            for it in ca_data.items:
                if not it.is_available:
                    ca_rows.append(f"""
                    <tr>
                        <td><strong>{it.name}</strong></td>
                        <td class="font-mono text-center">{it.symbol}</td>
                        <td colspan="4" class="text-center text-muted">n/a (source unavailable)</td>
                    </tr>
                    """)
                    continue
                is_fx = "=X" in it.symbol or "/" in it.name or "DXY" in it.name or "DX-Y" in it.symbol
                if is_fx:
                    if "JPY" in it.symbol or "JPY" in it.name:
                        price_display = f"{it.current_price:,.2f}"
                    elif it.current_price < 10.0:
                        price_display = f"{it.current_price:.4f}"
                    else:
                        price_display = f"{it.current_price:,.2f}"
                else:
                    price_display = f"${it.current_price:,.2f}"
                ca_rows.append(f"""
                <tr>
                    <td><strong>{it.name}</strong></td>
                    <td class="font-mono text-center">{it.symbol}</td>
                    <td class="text-right font-mono">{price_display}</td>
                    <td class="text-right">{_fmt_pct(it.period_ret)}</td>
                    <td class="text-right">{_fmt_pct(it.prior_period_ret)}</td>
                    <td class="text-right">{_fmt_pct(it.ret_3m)}</td>
                </tr>
                """)

            shock_box = ""
            if ca_data.energy_shock:
                eshk = ca_data.energy_shock
                s_badge = '<span class="badge badge-red">⚠️ ACTIVE ENERGY SHOCK ALERT</span>' if eshk.is_shock_active else '<span class="badge badge-green">🟢 INACTIVE / NORMAL</span>'
                shock_box = f"""
                <div class="card" style="margin-top: 16px; background: var(--bg-card-subtle); border-left: 4px solid {('var(--red)' if eshk.is_shock_active else 'var(--green)')};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; font-size: 0.85rem; text-transform: uppercase;">Energy Shock &amp; Macro Inflation Pass-Through</span>
                        {s_badge}
                    </div>
                    <div style="display: flex; gap: 24px; font-size: 13px; margin-bottom: 8px;">
                        <div>Oil 3-Month Trailing Return: <strong>{_fmt_pct(eshk.oil_3m_change_pct)}</strong></div>
                        <div>Headline CPI YoY: <strong>{eshk.headline_cpi_yoy:.2f}%</strong></div>
                        <div>Core CPI YoY: <strong>{eshk.core_cpi_yoy:.2f}%</strong></div>
                        <div>Gap (Headline - Core): <strong>{eshk.headline_core_gap_pct:+.2f}%</strong></div>
                    </div>
                    <p style="font-size: 13px; color: var(--text-muted);">{eshk.assessment}</p>
                </div>
                """

            body_html.append(f"""
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Asset Name</th>
                            <th class="text-center">Symbol</th>
                            <th class="text-right">Current Price</th>
                            <th class="text-right">Period Return</th>
                            <th class="text-right">Prior Return</th>
                            <th class="text-right">3-Month Return</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(ca_rows)}
                    </tbody>
                </table>
            </div>
            {shock_box}
            """)

        # Section: Market Breadth (Stage 3)
        elif isinstance(sec.data, BreadthSectionData):
            b_data: BreadthSectionData = sec.data
            r = b_data.result

            cov_warn_html = f'<div class="alert alert-warning">⚠️ <strong>Coverage Warning:</strong> {r.coverage_warning}</div>' if r.coverage_warning else ""
            
            # MA Regimes
            r20_class = "badge-bullish" if r.pct_above_20_dma.current >= 60 else ("badge-bearish" if r.pct_above_20_dma.current <= 40 else "badge-neutral")
            r20_text = "Bullish (>60%)" if r.pct_above_20_dma.current >= 60 else ("Bearish (<40%)" if r.pct_above_20_dma.current <= 40 else "Neutral")
            
            r50_class = "badge-bullish" if r.pct_above_50_dma.current >= 60 else ("badge-bearish" if r.pct_above_50_dma.current <= 40 else "badge-neutral")
            r50_text = "Bullish (>60%)" if r.pct_above_50_dma.current >= 60 else ("Bearish (<40%)" if r.pct_above_50_dma.current <= 40 else "Neutral")

            r200_class = "badge-bullish" if r.pct_above_200_dma.current >= 60 else ("badge-bearish" if r.pct_above_200_dma.current <= 40 else "badge-neutral")
            r200_text = "Bullish (>60%)" if r.pct_above_200_dma.current >= 60 else ("Bearish (<40%)" if r.pct_above_200_dma.current <= 40 else "Neutral")

            lead_class = "badge-bearish" if r.narrow_leadership else ("badge-bullish" if "Broad" in r.leadership_status else "badge-neutral")
            lead_tag = "Narrow Leadership Warning" if r.narrow_leadership else ("Broad Leadership" if "Broad" in r.leadership_status else "Balanced")

            mcclellan_html = ""
            if r.mcclellan_oscillator is not None:
                m_class = "badge-bullish" if "Bullish" in (r.mcclellan_status or "") or "Overbought" in (r.mcclellan_status or "") else "badge-bearish"
                mcclellan_html = f"""
                <div class="tech-card">
                    <div class="tech-header">
                        <span class="metric-title">McClellan Oscillator</span>
                        <span class="badge {m_class}">{r.mcclellan_status}</span>
                    </div>
                    <div style="font-size: 22px; font-weight: 800; font-family: monospace; margin-bottom: 8px;">
                        {r.mcclellan_oscillator:+.2f}
                    </div>
                    <div class="metric-row"><span class="text-muted">Previous Period:</span> <span class="font-mono">{r.prev_mcclellan_oscillator:+.2f}</span></div>
                    <div class="metric-row"><span class="text-muted">Period Change:</span> <span>{_fmt_delta(r.delta_mcclellan_oscillator or 0.0)}</span></div>
                    <div class="metric-row" style="margin-top: 6px;"><span class="text-muted" style="font-size: 11px;">19-EMA minus 39-EMA of daily net advances</span></div>
                </div>
                """

            body_html.append(f"""
            <div class="alert alert-info">
                <strong>Breadth Read:</strong> {r.breadth_read} &bull; <em>Coverage: {r.included_constituents} of {r.total_constituents} S&P 500 constituents ({r.coverage_pct:.1f}%)</em>
            </div>
            {cov_warn_html}

            <div class="vix-grid" style="margin: 16px 0;">
                <div class="vix-metric">
                    <span class="vix-label">STOCKS > 50 DMA</span>
                    <span class="vix-val">{r.pct_above_50_dma.current:.1f}%</span>
                    <span class="vix-sub">Period Δ: {_fmt_pct(r.pct_above_50_dma.change)}</span>
                    <span class="vix-desc">Prev Period: {r.pct_above_50_dma.previous:.1f}%</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">STOCKS > 200 DMA</span>
                    <span class="vix-val">{r.pct_above_200_dma.current:.1f}%</span>
                    <span class="vix-sub">Period Δ: {_fmt_pct(r.pct_above_200_dma.change)}</span>
                    <span class="vix-desc">Prev Period: {r.pct_above_200_dma.previous:.1f}%</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">A/D RATIO (ADV / DEC)</span>
                    <span class="vix-val">{r.ad_ratio:.2f}x</span>
                    <span class="vix-sub">🟢 {r.advancers} Up &bull; 🔴 {r.decliners} Down ({r.net_advancers:+d} Net)</span>
                    <span class="vix-desc">{r.ad_confirmation} &bull; {r.cum_ad_trend}</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">NET NEW 52-WEEK HIGHS</span>
                    <span class="vix-val">{r.net_new_highs:+d}</span>
                    <span class="vix-sub">Highs: {r.new_52w_highs} &bull; Lows: {r.new_52w_lows}</span>
                    <span class="vix-desc">Period Δ: {r.delta_net_new_highs:+d}</span>
                </div>
            </div>

            <h3 class="sub-title">Moving Average Participation Matrix</h3>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Breadth Metric</th>
                            <th class="text-right">Current %</th>
                            <th class="text-right">Prior Period %</th>
                            <th class="text-right">Period &Delta;</th>
                            <th class="text-center">Trend Regime</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong>% of Stocks Above 20 DMA</strong></td>
                            <td class="text-right font-mono font-bold">{r.pct_above_20_dma.current:.1f}%</td>
                            <td class="text-right font-mono">{r.pct_above_20_dma.previous:.1f}%</td>
                            <td class="text-right">{_fmt_pct(r.pct_above_20_dma.change)}</td>
                            <td class="text-center"><span class="badge {r20_class}">{r20_text}</span></td>
                        </tr>
                        <tr>
                            <td><strong>% of Stocks Above 50 DMA</strong></td>
                            <td class="text-right font-mono font-bold">{r.pct_above_50_dma.current:.1f}%</td>
                            <td class="text-right font-mono">{r.pct_above_50_dma.previous:.1f}%</td>
                            <td class="text-right">{_fmt_pct(r.pct_above_50_dma.change)}</td>
                            <td class="text-center"><span class="badge {r50_class}">{r50_text}</span></td>
                        </tr>
                        <tr>
                            <td><strong>% of Stocks Above 200 DMA</strong></td>
                            <td class="text-right font-mono font-bold">{r.pct_above_200_dma.current:.1f}%</td>
                            <td class="text-right font-mono">{r.pct_above_200_dma.previous:.1f}%</td>
                            <td class="text-right">{_fmt_pct(r.pct_above_200_dma.change)}</td>
                            <td class="text-center"><span class="badge {r200_class}">{r200_text}</span></td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="grid-2" style="margin-top: 18px;">
                <div class="tech-card">
                    <div class="tech-header">
                        <span class="metric-title">Leadership: Equal-Weight (RSP) vs Cap-Weight (SPY)</span>
                        <span class="badge {lead_class}">{lead_tag}</span>
                    </div>
                    <div class="metric-group">
                        <div class="metric-row"><span class="text-muted">Cap-Weight SPY Return:</span> <span>{_fmt_pct(r.spy_return_pct)}</span></div>
                        <div class="metric-row"><span class="text-muted">Equal-Weight RSP Return:</span> <span>{_fmt_pct(r.rsp_return_pct)}</span></div>
                        <div class="metric-row"><span class="text-muted">Leadership Spread (SPY - RSP):</span> <span>{_fmt_pct(r.leadership_spread_pct)}</span></div>
                        <div class="metric-row"><span class="text-muted">Positive Return Participation:</span> <span class="font-mono">{r.pct_positive_return.current:.1f}% of universe</span></div>
                    </div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">{r.leadership_status}</p>
                </div>
                {mcclellan_html}
            </div>

            <p class="table-caption" style="margin-top: 14px;"><em>*Note: Market breadth calculations use the current S&P 500 constituent roster (subject to survivorship bias for historical comparisons).</em></p>
            """)
            if charts:
                if charts.get("sector_breadth_heatmap"):
                    body_html.append(_render_chart_html(charts.get("sector_breadth_heatmap")))
                body_html.append(_render_chart_html(charts.get("breadth_history")))

            body_html.append("""
            <details class="methodology-note" style="margin-top: 16px;">
                <summary>ℹ️ Breadth Thresholds &amp; Linear Gradient Scoring</summary>
                <div class="methodology-content">
                    <p><strong>Participation Boundaries:</strong> Evaluates market participation across all 500 constituents of the S&amp;P 500:</p>
                    <ul style="padding-left: 18px; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">
                        <li><strong>&ge; 60% Bullish Expansion:</strong> Broad participation across cyclical, industrial, and technology sectors confirming rally sustainability.</li>
                        <li><strong>40% – 60% Neutral / Rotational:</strong> Mixed internal health where market performance relies on specific leadership sectors.</li>
                        <li><strong>&le; 40% Bearish Narrowing:</strong> Severe participation deficit. Historically signals broad distribution and elevated vulnerability.</li>
                    </ul>
                    <p style="margin-top: 6px;"><strong>Linear Gradient:</strong> Breadth scoring interpolates linearly between 40% (-1.0) and 60% (+1.0) without threshold cliffs.</p>
                </div>
            </details>
            """)

        # Section: Federal Reserve Policy Path
        elif isinstance(sec.data, FedPathData):
            fp: FedPathData = sec.data
            prob_src = getattr(fp, "prob_source", "CBOT 30-Day Fed Funds Futures")
            if fp.market_implied_prob_hold is not None:
                hold_p = f"{fp.market_implied_prob_hold * 100:.1f}%"
                hike_p = f"{fp.market_implied_prob_hike * 100:.1f}%" if getattr(fp, "market_implied_prob_hike", None) is not None else "0.0%"
                cut_p = f"{fp.market_implied_prob_cut * 100:.1f}%" if fp.market_implied_prob_cut is not None else "0.0%"
                prob_line = f'<strong>Market-Implied Probabilities:</strong> Hold <strong>{hold_p}</strong> &bull; +25 bps Hike <strong>{hike_p}</strong> &bull; -25 bps Cut <strong>{cut_p}</strong> <span style="color: var(--text-muted); font-size: 12px;">(Source: {prob_src})</span>'
            else:
                prob_line = '<strong>Market-Implied Probabilities:</strong> <span class="text-muted font-mono">n/a (source unavailable)</span>'

            fed_details_box = f"""
            <div style="margin-top: 14px; padding: 12px 16px; background: var(--bg-card-subtle); border-radius: 8px;">
                <div style="font-size: 13px; margin-bottom: 4px;">{prob_line}</div>
                <div style="font-size: 13px; color: var(--text-muted); margin-top: 6px;">🧭 <em>{fp.assessment}</em></div>
            </div>
            """ if (period.report_type == "daily" and fp.days_to_next_meeting > 1) else f"""
            <div style="margin-top: 14px; padding: 12px 16px; background: var(--bg-card-subtle); border-radius: 8px;">
                <div style="font-size: 13px; margin-bottom: 4px;"><strong>Most Recent Decision:</strong> <span class="font-mono">{fp.last_action_date}</span> &mdash; {fp.last_action_description}</div>
                <div style="font-size: 13px; margin-bottom: 4px;">{prob_line}</div>
                <div style="font-size: 13px; color: var(--text-muted); margin-top: 6px;">🧭 <em>{fp.assessment}</em></div>
            </div>
            """

            body_html.append(f"""
            <div class="vix-grid">
                <div class="vix-metric">
                    <span class="vix-label">FED FUNDS TARGET RANGE</span>
                    <span class="vix-val font-mono">{fp.current_target_range}</span>
                    <span class="vix-sub">Effective: {fp.effective_fed_funds:.2f}%</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">NEXT FOMC DECISION</span>
                    <span class="vix-val font-mono" style="font-size: 18px;">{fp.next_meeting_date}</span>
                    <span class="vix-sub">{fp.days_to_next_meeting} calendar days away</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">2Y YIELD VS. FED FUNDS</span>
                    <span class="vix-val font-mono">{fp.spread_2y_vs_fed_funds_bps:+.1f} bps</span>
                    <span class="vix-sub">2Y Yield: {fp.yield_2y:.2f}%</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">REAL POLICY RATE</span>
                    <span class="vix-val font-mono">{fp.real_policy_rate:+.2f}%</span>
                    <span class="vix-sub">{getattr(fp, 'real_rate_driver_measure', 'Core PCE')}: {fp.trailing_core_inflation:.2f}% YoY</span>
                </div>
            </div>

            {fed_details_box}
            """)

        # Section: Forward Catalyst Calendar
        elif isinstance(sec.data, ForwardCalendarData):
            fc: ForwardCalendarData = sec.data
            cal_rows = []
            for ev in fc.events:
                is_speech = any(w in ev.title.lower() for w in ("remarks", "speech", "keynote", "discussion"))
                is_chair_keynote = "chair keynote" in ev.title.lower()
                if is_chair_keynote:
                    imp_badge = '<span class="badge badge-red font-bold">HIGH (KEYNOTE)</span>'
                elif ev.importance == "high":
                    imp_badge = '<span class="badge badge-red">HIGH</span>'
                elif ev.importance == "medium":
                    imp_badge = '<span class="badge badge-neutral">MEDIUM</span>'
                else:
                    imp_badge = '<span class="badge badge-muted">LOW</span>'

                if is_speech:
                    pr_val = '<span class="text-muted font-mono">—</span>'
                    fc_val = '<span class="text-muted font-mono">— (speaker)</span>'
                    cons_src = '<span class="text-muted font-mono">—</span>'
                else:
                    def _fmt_h_val(val: Optional[float], unit: str) -> str:
                        if val is None:
                            return "n/a"
                        if not unit or unit == "index":
                            return f"{val:.2f}"
                        elif unit == "%":
                            return f"{val:.2f}%"
                        elif unit == "k":
                            return f"{val:,.0f}k"
                        else:
                            return f"{val:.2f} {unit}"

                    fc_val = f'<span class="font-mono font-bold">{_fmt_h_val(ev.forecast, ev.unit)}</span>' if ev.forecast is not None else '<span class="text-muted font-mono">n/a (no consensus)</span>'
                    pr_val = f'<span class="font-mono">{_fmt_h_val(ev.previous, ev.unit)}</span>' if ev.previous is not None else '<span class="text-muted font-mono">n/a</span>'
                    cons_src = 'Finnhub Economic API' if ev.forecast is not None else '<span class="text-muted">n/a (unpolled)</span>'
                sched_src = f'<a href="{ev.source_url}" target="_blank" style="color: var(--primary); text-decoration: none;">{ev.source_name or ev.source}</a>' if getattr(ev, "source_url", None) else (ev.source or "Official U.S. Schedule")

                cal_rows.append(f"""
                <tr>
                    <td class="text-center font-mono">{ev.date}</td>
                    <td class="text-center font-mono">{ev.time_et}</td>
                    <td><strong>{ev.title}</strong></td>
                    <td class="text-center">{imp_badge}</td>
                    <td class="text-right">{pr_val}</td>
                    <td class="text-right">{fc_val}</td>
                    <td style="font-size: 12px; color: var(--text-muted);">{sched_src}</td>
                    <td style="font-size: 12px; color: var(--text-muted);">{cons_src}</td>
                </tr>
                """)

            cal_caption = f"Tracking imminent catalysts (next 24h-48h) through <strong>{fc.lookahead_date}</strong> &bull; Schedule Source: Official Federal Schedules | Consensus Source: Finnhub Economic API" if period.report_type == "daily" else f"Tracking catalyst releases through <strong>{fc.lookahead_date}</strong> &bull; Schedule Source: Official Federal Schedules | Consensus Source: Finnhub Economic API"
            body_html.append(f"""
            <p class="table-caption">{cal_caption}</p>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th class="text-center">Date</th>
                            <th class="text-center">Time (ET)</th>
                            <th>Catalyst Event</th>
                            <th class="text-center">Impact</th>
                            <th class="text-right">Prior</th>
                            <th class="text-right">Consensus</th>
                            <th>Schedule Source</th>
                            <th>Consensus Source</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(cal_rows)}
                    </tbody>
                </table>
            </div>
            """)

        # Section: Corporate Earnings Layer
        elif isinstance(sec.data, EarningsLayerData):
            el: EarningsLayerData = sec.data
            pct_rep = f"{el.pct_reported:.1f}%" if el.pct_reported is not None else "n/a"
            eps_bt = f"{el.eps_beat_rate:.1f}%" if el.eps_beat_rate is not None else "n/a"
            rev_bt = f"{el.rev_beat_rate:.1f}%" if el.rev_beat_rate is not None else "n/a"
            med_sur = f"{el.median_surprise_pct:+.1f}%" if el.median_surprise_pct is not None else "n/a"

            # 1. Trailing Reported Large Caps
            rep_rows = []
            for r in el.reported_last_7_days:
                eps_s = f'<span class="font-mono font-bold {("text-green" if r.eps_surprise_pct > 0 else "text-red")}">{r.eps_surprise_pct:+.1f}%</span>' if r.eps_surprise_pct is not None else '<span class="text-muted">n/a</span>'
                rev_s = f'<span class="font-mono {("text-green" if r.rev_surprise_pct > 0 else "text-red")}">{r.rev_surprise_pct:+.1f}%</span>' if r.rev_surprise_pct is not None else '<span class="text-muted">n/a</span>'
                react_s = _fmt_pct(r.reaction_1d_pct)
                d20_s = _fmt_pct(r.dist_20dma_pct)
                d50_s = _fmt_pct(r.dist_50dma_pct)
                guid_badge = '<span class="badge badge-green">Raised</span>' if r.guidance == "Raised" else ('<span class="badge badge-red">Lowered</span>' if r.guidance == "Lowered" else f'<span class="badge badge-muted">{r.guidance}</span>')
                rep_rows.append(f"""
                <tr>
                    <td class="font-mono"><strong>{r.symbol}</strong></td>
                    <td>{r.name}</td>
                    <td>{r.sector}</td>
                    <td class="text-center font-mono">{r.date}</td>
                    <td class="text-center font-mono"><span class="badge badge-muted">{r.timing}</span></td>
                    <td class="text-right">{eps_s}</td>
                    <td class="text-right">{rev_s}</td>
                    <td class="text-center">{guid_badge}</td>
                    <td class="text-right">{react_s}</td>
                    <td class="text-right">{d20_s}</td>
                    <td class="text-right">{d50_s}</td>
                </tr>
                """)

            # 2. Upcoming Large Caps
            top_rows = []
            for item in el.next_week_large_caps:
                timing_badge = '<span class="badge badge-primary">BMO</span>' if 'Before' in item.timing else ('<span class="badge badge-neutral">AMC</span>' if 'After' in item.timing else '<span class="badge badge-muted">UNSPEC</span>')
                clean_mcap = item.market_cap_str.replace('\\$', '$')
                top_rows.append(f"""
                <tr>
                    <td class="font-mono"><strong>{item.symbol}</strong></td>
                    <td>{item.name}</td>
                    <td>{item.sector}</td>
                    <td class="text-right font-mono">{clean_mcap}</td>
                    <td class="text-center font-mono">{item.date}</td>
                    <td class="text-center">{timing_badge} <span style="font-size: 12px; color: var(--text-muted);">{item.timing}</span></td>
                </tr>
                """)

            recent_title = "Recent Large-Cap Reports (Last 24h–48h)" if period.report_type == "daily" else "Recent Large-Cap Earnings Results (Trailing 7 Days)"
            upcoming_title = "Imminent Earnings: Tonight AMC &amp; Tomorrow BMO" if period.report_type == "daily" else "Next-Week Earnings: Top S&amp;P 500 Large-Cap Catalysts"

            body_html.append(f"""
            <div class="vix-grid">
                <div class="vix-metric">
                    <span class="vix-label">SEASON PROGRESS</span>
                    <span class="vix-val font-mono">{pct_rep}</span>
                    <span class="vix-sub">S&amp;P 500 Reported</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">EPS BEAT RATE</span>
                    <span class="vix-val font-mono">{eps_bt}</span>
                    <span class="vix-sub">Surprise &gt; 0</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">REVENUE BEAT RATE</span>
                    <span class="vix-val font-mono">{rev_bt}</span>
                    <span class="vix-sub">Top-Line Expansion</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">MEDIAN SURPRISE</span>
                    <span class="vix-val font-mono">{med_sur}</span>
                    <span class="vix-sub">EPS Outperformance</span>
                </div>
            </div>

            <h3 class="sub-title">{recent_title}</h3>
            <div class="table-container">
                <table class="report-table compact-table">
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company Name</th>
                            <th>Sector</th>
                            <th class="text-center">Report Date</th>
                            <th class="text-center">Timing</th>
                            <th class="text-right">EPS Surprise</th>
                            <th class="text-right">Rev Surprise</th>
                            <th class="text-center">Guidance</th>
                            <th class="text-right">1-Day Reaction</th>
                            <th class="text-right">Dist 20-DMA</th>
                            <th class="text-right">Dist 50-DMA</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rep_rows) if rep_rows else '<tr><td colspan="11" class="text-center text-muted">No large-cap constituents reported in trailing window.</td></tr>'}
                    </tbody>
                </table>
            </div>

            <h3 class="sub-title" style="margin-top: 24px;">{upcoming_title}</h3>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company Name</th>
                            <th>Sector</th>
                            <th class="text-right">Market Cap</th>
                            <th class="text-center">Scheduled Date</th>
                            <th class="text-center">Timing</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(top_rows) if top_rows else '<tr><td colspan="6" class="text-center text-muted">No scheduled S&amp;P 500 large-cap earnings in horizon window.</td></tr>'}
                    </tbody>
                </table>
            </div>
            """)

        # Section: Top Movers
        elif isinstance(sec.data, TopMoversData):
            m_data: TopMoversData = sec.data
            # Display timeframe-appropriate mover sets to eliminate out-of-period clutter
            if period.report_type == "daily":
                display_periods = [(m_data.day, "Daily Universe Movers")]
            elif period.report_type == "weekly":
                display_periods = [(m_data.week, "Weekly Universe Movers")]
            else:  # monthly
                display_periods = [(m_data.month, "Monthly Universe Movers")]

            for pm, title_label in display_periods:
                body_html.append(f'<h3 class="mover-period-title">{title_label}</h3>')
                if pm.theme_summary:
                    body_html.append(f'<div class="alert alert-info" style="margin-bottom: 12px;">🏷️ <strong>Movers by Theme:</strong> {pm.theme_summary}</div>')
                body_html.append('<div class="movers-split">')

                # Gainers
                g_rows = []
                for g in pm.gainers:
                    earn_pill = '<span class="badge badge-primary">YES</span>' if g.has_earnings_in_window else '<span class="badge badge-muted">NO</span>'
                    g_mcap = (g.market_cap_str or 'n/a').replace('\\$', '$')
                    g_rows.append(f"""
                    <tr>
                        <td><strong>{g.symbol}</strong><br><span class="ticker-sub">{g.name[:18]}</span></td>
                        <td>{g.sector}</td>
                        <td class="text-right font-mono">{g_mcap}</td>
                        <td class="text-right font-mono">${g.close:,.2f}</td>
                        <td class="text-right">{_fmt_pct(g.pct_change)}</td>
                        <td class="text-right font-mono">{g.volume_ratio:.2f}x</td>
                        <td class="text-center">{earn_pill}</td>
                        <td style="font-size: 11px; color: var(--text-muted); max-width: 140px; line-height: 1.25;">{g.move_cause_tag}</td>
                    </tr>
                    """)
                body_html.append(f"""
                <div class="mover-table-box">
                    <h4 class="mover-subheading text-green">Top 5 Gainers</h4>
                    <div class="table-container">
                        <table class="report-table compact-table">
                            <thead>
                                <tr>
                                    <th>Ticker</th>
                                    <th>Sector</th>
                                    <th class="text-right">Mkt Cap</th>
                                    <th class="text-right">Close</th>
                                    <th class="text-right">Change</th>
                                    <th class="text-right">20d Vol</th>
                                    <th class="text-center">Earnings?</th>
                                    <th>Cause</th>
                                </tr>
                            </thead>
                            <tbody>{''.join(g_rows)}</tbody>
                        </table>
                    </div>
                </div>
                """)

                # Losers
                l_rows = []
                for l in pm.losers:
                    earn_pill = '<span class="badge badge-primary">YES</span>' if l.has_earnings_in_window else '<span class="badge badge-muted">NO</span>'
                    l_mcap = (l.market_cap_str or 'n/a').replace('\\$', '$')
                    l_rows.append(f"""
                    <tr>
                        <td><strong>{l.symbol}</strong><br><span class="ticker-sub">{l.name[:18]}</span></td>
                        <td>{l.sector}</td>
                        <td class="text-right font-mono">{l_mcap}</td>
                        <td class="text-right font-mono">${l.close:,.2f}</td>
                        <td class="text-right">{_fmt_pct(l.pct_change)}</td>
                        <td class="text-right font-mono">{l.volume_ratio:.2f}x</td>
                        <td class="text-center">{earn_pill}</td>
                        <td style="font-size: 11px; color: var(--text-muted); max-width: 140px; line-height: 1.25;">{l.move_cause_tag}</td>
                    </tr>
                    """)
                body_html.append(f"""
                <div class="mover-table-box">
                    <h4 class="mover-subheading text-red">Top 5 Losers</h4>
                    <div class="table-container">
                        <table class="report-table compact-table">
                            <thead>
                                <tr>
                                    <th>Ticker</th>
                                    <th>Sector</th>
                                    <th class="text-right">Mkt Cap</th>
                                    <th class="text-right">Close</th>
                                    <th class="text-right">Change</th>
                                    <th class="text-right">20d Vol</th>
                                    <th class="text-center">Earnings?</th>
                                    <th>Cause</th>
                                </tr>
                            </thead>
                            <tbody>{''.join(l_rows)}</tbody>
                        </table>
                    </div>
                </div>
                """)

                body_html.append('</div>')
            if charts:
                body_html.append(_render_chart_html(charts.get("top_movers")))

        # Section: Sentiment, Positioning & Volatility Risk Premium
        elif isinstance(sec.data, SentimentPositioningData):
            sp: SentimentPositioningData = sec.data
            vrp_class = "text-green font-bold" if sp.vol_risk_premium > 2.0 else ("text-red font-bold" if sp.vol_risk_premium < -1.0 else "text-muted font-bold")

            sentiment_rows = []
            if getattr(sp, "items", None):
                for s_item in sp.items:
                    sentiment_rows.append(f"""
                    <tr>
                        <td><strong>{s_item.name}</strong></td>
                        <td class="text-center font-mono font-bold">{s_item.reading}</td>
                        <td style="font-size: 13px; color: var(--text-muted);">{s_item.diagnostic}</td>
                    </tr>
                    """)

            sentiment_table_html = ""
            if sentiment_rows:
                sentiment_table_html = f"""
                <div class="table-container" style="margin-top: 16px;">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Positioning &amp; Sentiment Metric</th>
                                <th class="text-center">Current Reading</th>
                                <th>Data Status &amp; Methodology Diagnostic</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(sentiment_rows)}</tbody>
                    </table>
                </div>
                """

            body_html.append(f"""
            <div class="vix-grid">
                <div class="vix-metric">
                    <span class="vix-label">CBOE VIX INDEX</span>
                    <span class="vix-val font-mono">{sp.vix:.2f}</span>
                    <span class="vix-sub">Implied Volatility</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">20-DAY REALIZED VOL</span>
                    <span class="vix-val font-mono">{sp.realized_vol_20d:.2f}%</span>
                    <span class="vix-sub">Historical Price Variance</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">VOLATILITY RISK PREMIUM</span>
                    <span class="vix-val font-mono {vrp_class}">{sp.vol_risk_premium:+.2f} pts</span>
                    <span class="vix-sub">VIX &minus; Realized Vol</span>
                </div>
                <div class="vix-metric">
                    <span class="vix-label">VRP REGIME</span>
                    <span class="vix-val" style="font-size: 15px; margin: 4px 0;">{sp.vol_premium_regime.split('(')[0].strip()}</span>
                    <span class="vix-sub">Options Pricing Premium</span>
                </div>
            </div>

            {sentiment_table_html}

            <div class="regime-callout-card" style="margin-top: 14px; padding: 12px 16px; border-radius: 8px; background: rgba(59, 130, 246, 0.08); border-left: 4px solid var(--primary);">
                <div style="font-size: 13px; line-height: 1.5; color: var(--text-main);">🧭 <strong>Options Pricing Context:</strong> {sp.assessment}</div>
            </div>

            <details class="methodology-note" style="margin-top: 16px;">
                <summary>ℹ️ Volatility Risk Premium (VRP) &amp; Positioning Methodology</summary>
                <div class="methodology-content">
                    <p><strong>Volatility Risk Premium (VRP):</strong> Calculated as CBOE VIX (30-day implied volatility) minus trailing 20-day annualized realized volatility of the S&amp;P 500.</p>
                    <ul style="padding-left: 18px; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">
                        <li><strong>Positive VRP (&gt; +2.0 pts):</strong> Volatility contango. Market participants are paying normal insurance premiums for index protection, signaling orderly hedging behavior.</li>
                        <li><strong>Negative VRP (&lt; 0 pts):</strong> Volatility backwardation. Historical realized moves exceed forward implied pricing, reflecting acute liquidation, panic selling, or sudden dislocation.</li>
                    </ul>
                    <p style="margin-top: 6px;"><strong>Data Integrity:</strong> In accordance with Ground Rule 2, unverified sentiment feeds render "n/a (source unavailable)" and are excluded from scorecard denominators.</p>
                </div>
            </details>
            """)

        # Section: Tactical Watchlist Panel (Stage 3: Task 3.2)
        elif isinstance(sec.data, WatchlistData):
            wl: WatchlistData = sec.data
            wl_rows = []
            for it in wl.items:
                c_str = f"${it.close:,.2f}" if it.close > 0 else "&mdash;"
                d20_str = _fmt_pct(it.dist_20dma_pct)
                d50_str = _fmt_pct(it.dist_50dma_pct)
                atr_str = f"{it.atr_pct:.2f}%" if it.atr_pct is not None else "&mdash;"

                if it.rs_vs_spy is not None:
                    rs_c = "text-green font-bold" if it.rs_vs_spy > 0 else ("text-red font-bold" if it.rs_vs_spy < 0 else "text-muted")
                    rs_str = f'<span class="{rs_c} font-mono">{it.rs_vs_spy:+.2f}%</span>'
                else:
                    rs_str = "&mdash;"

                # Readiness badge
                if it.readiness == "Ready":
                    readiness_badge = '<span class="badge badge-green font-bold">Ready</span>'
                elif it.readiness == "Watch":
                    readiness_badge = '<span class="badge badge-yellow font-bold">Watch</span>'
                else:
                    readiness_badge = '<span class="badge badge-neutral" style="color: var(--text-muted); font-size: 11px;">Not ready</span>'

                # Technical filter badge
                if "Exception candidate" in it.long_permitted:
                    dir_badge = '<span class="badge badge-yellow font-bold">Exception candidate (gate Defensive)</span>'
                elif "BLOCKED" in it.long_permitted or "INACTIVE" in it.long_permitted:
                    dir_badge = '<span class="badge badge-red font-bold">INACTIVE</span>'
                elif "SELECTIVE" in it.long_permitted:
                    dir_badge = '<span class="badge badge-yellow font-bold">SELECTIVE</span>'
                else:
                    dir_badge = '<span class="badge badge-green font-bold">ACTIVE</span>'

                if it.next_earnings_date in ("none within 30d", "n/a (source unavailable)", "n/a"):
                    earn_badge = f'<span class="text-muted font-mono" style="font-size: 12px;">{it.next_earnings_date}</span>'
                else:
                    earn_badge = f'<span class="font-mono font-bold" style="font-size: 12px;">{it.next_earnings_date}</span>'

                wl_rows.append(f"""
                <tr>
                    <td class="font-mono font-bold" style="color: var(--color-primary);">{it.ticker}</td>
                    <td>{it.name}</td>
                    <td><span class="text-muted" style="font-size: 13px;">{it.sector}</span></td>
                    <td class="text-right font-mono">{c_str}</td>
                    <td class="text-right">{d20_str}</td>
                    <td class="text-right">{d50_str}</td>
                    <td class="text-right font-mono">{atr_str}</td>
                    <td class="text-right">{rs_str}</td>
                    <td class="text-center font-mono" style="font-size: 13px;">{it.sector_breadth_status}</td>
                    <td class="text-center">{readiness_badge}</td>
                    <td class="text-center">{earn_badge}</td>
                    <td class="text-center">{dir_badge}</td>
                </tr>
                """)

            exc_note = f", {wl.exception_count} Exception Candidates" if getattr(wl, "exception_count", 0) > 0 else ""
            src_note = f" &bull; {wl.source_label}" if getattr(wl, "source_label", "") else ""
            monthly_wl_note = '<div style="font-size: 13px; color: var(--text-muted); margin-top: 6px;">💡 <em>Strategic Watchlist Context: For monthly asset allocation, prioritize candidates with sustained 3-month RS outperformance maintaining position above rising 50-day moving averages.</em></div>' if period.report_type == "monthly" else ""
            body_html.append(f"""
            <div class="note-box" style="margin-bottom: 16px;">
                <strong>Tactical Focus Universe:</strong> Tracking {wl.total_count} focus large-cap tickers{src_note}.<br>
                Market Gate Posture: <strong>{wl.gate_posture}</strong> &bull; Filter Status: <strong>{wl.long_permitted_default}</strong>
                ({wl.blocked_count} Inactive, {wl.selective_count} Selective, {wl.permitted_count} Active{exc_note}).
                {monthly_wl_note}
            </div>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company Name</th>
                            <th>Sector</th>
                            <th class="text-right">Close</th>
                            <th class="text-right">&Delta; 20-DMA</th>
                            <th class="text-right">&Delta; 50-DMA</th>
                            <th class="text-right">14D ATR%</th>
                            <th class="text-right">RS vs SPY (3M)</th>
                            <th class="text-center">Sector Breadth (&gt;50-DMA)</th>
                            <th class="text-center">Readiness (Gate Open)</th>
                            <th class="text-center">Next Earnings</th>
                            <th class="text-center">Filter Status</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(wl_rows) if wl_rows else '<tr><td colspan="12" class="text-center text-muted">No watchlist focus items available.</td></tr>'}</tbody>
                </table>
            </div>
            """)

        # Section: S&P 500 Valuation vs Rates (CR v2.2 Stage 3 Task 3.1 & Stage 4 Task 4.2)
        elif isinstance(sec.data, ValuationData):
            v: ValuationData = sec.data
            if v.forward_pe is None:
                body_html.append("""
                <div style="padding: 12px 16px; background: var(--bg-card-subtle); border-radius: 8px; font-size: 13px; color: var(--text-muted); margin-bottom: 16px;">
                    <span class="font-mono font-bold">n/a (source unavailable)</span> &mdash; Forward valuation multiples and consensus forward EPS estimates are currently unavailable from data provider. Equity Risk Premium metrics are omitted until verified forward earnings estimates are available.
                </div>
                """)
            else:
                pe_str = f"{v.forward_pe:.2f}x"
                ey_str = f"{v.earnings_yield_pct:.2f}%" if v.earnings_yield_pct is not None else '<span class="text-muted">n/a (source unavailable)</span>'
                nom_hurdle = f"10Y Treasury ({v.nominal_10y_yield:.2f}%)" if v.nominal_10y_yield is not None else "10Y Treasury (DGS10)"
                nom_erp_str = f"{v.nominal_erp_bps:+.1f} bps" if v.nominal_erp_bps is not None else "n/a (source unavailable)"
                nom_class = "text-green font-bold" if (v.nominal_erp_bps and v.nominal_erp_bps >= 100.0) else ("text-yellow font-bold" if v.nominal_erp_bps else "text-muted")
                real_hurdle = f"10Y TIPS ({v.real_10y_yield:.2f}%)" if v.real_10y_yield is not None else "10Y TIPS Real Yield (DFII10)"
                real_erp_str = f"{v.real_erp_bps:+.1f} bps" if v.real_erp_bps is not None else "n/a (source unavailable)"
                real_class = "text-green font-bold" if (v.real_erp_bps and v.real_erp_bps >= 200.0) else ("text-yellow font-bold" if v.real_erp_bps else "text-muted")

                body_html.append(f"""
                <div class="note-box" style="margin-bottom: 16px;">
                    <strong>Valuation &amp; ERP Context:</strong> {v.assessment}
                </div>
                <div class="table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Valuation Metric</th>
                                <th class="text-center">Current Level</th>
                                <th class="text-center">Benchmark / Hurdle</th>
                                <th class="text-center">Spread / Risk Premium</th>
                                <th>Sourcing &amp; Context</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>Forward P/E</strong></td>
                                <td class="text-center font-mono font-bold">{pe_str}</td>
                                <td class="text-center">&mdash;</td>
                                <td class="text-center">&mdash;</td>
                                <td>Forward multiple on consensus 12M EPS ({v.source})</td>
                            </tr>
                            <tr>
                                <td><strong>Earnings Yield (1/PE)</strong></td>
                                <td class="text-center font-mono font-bold">{ey_str}</td>
                                <td class="text-center">&mdash;</td>
                                <td class="text-center">&mdash;</td>
                                <td>Equity cash generation yield (1 / Forward P/E)</td>
                            </tr>
                            <tr>
                                <td><strong>Nominal Equity Risk Premium (ERP)</strong></td>
                                <td class="text-center font-mono">{ey_str}</td>
                                <td class="text-center font-mono">{nom_hurdle}</td>
                                <td class="text-center font-mono {nom_class}">{nom_erp_str}</td>
                                <td>Earnings Yield minus 10Y Benchmark Yield</td>
                            </tr>
                            <tr>
                                <td><strong>Real Equity Risk Premium (Real ERP)</strong></td>
                                <td class="text-center font-mono">{ey_str}</td>
                                <td class="text-center font-mono">{real_hurdle}</td>
                                <td class="text-center font-mono {real_class}">{real_erp_str}</td>
                                <td>Earnings Yield minus 10Y TIPS Real Yield</td>
                            </tr>
                            <tr>
                                <td><strong>Forward EPS Revision Trend</strong></td>
                                <td class="text-center font-mono font-bold" colspan="3">{v.eps_revision_trend}</td>
                                <td>Revision momentum across S&amp;P 500 constituents</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                """)

        # Section: Conclusion
        elif isinstance(sec.data, ConclusionData):
            cd: ConclusionData = sec.data
            v_low = cd.verdict.lower()
            v_class = "badge-bullish" if v_low in ("bullish", "risk-on", "constructive") else ("badge-bearish" if v_low in ("bearish", "risk-off", "cautious") else "badge-neutral")

            # 1. Category Breakdown Table (Requirement 2)
            cat_rows = []
            if cd.scorecard and cd.scorecard.categories:
                for cat in cd.scorecard.categories:
                    st_badge = '<span class="badge badge-green">ACTIVE</span>' if cat.status == "active" else '<span class="badge badge-muted">UNAVAILABLE (RENORMALIZED)</span>'
                    sc_class = "text-green font-bold" if cat.score > 0.1 else ("text-red font-bold" if cat.score < -0.1 else "text-muted")
                    w_sc_str = f"{cat.weighted_score:+.2f}" if cat.status == "active" else "—"
                    eff_w_str = f"{cat.effective_weight * 100:.1f}%" if cat.status == "active" else "— (dropped)"
                    cat_rows.append(f"""
                    <tr>
                        <td><strong>{cat.name}</strong></td>
                        <td class="text-center font-mono">{cat.weight * 100:.0f}%</td>
                        <td class="text-center font-mono font-bold">{eff_w_str}</td>
                        <td class="text-center font-mono {sc_class}">{cat.score:+.2f}</td>
                        <td class="text-center font-mono {sc_class}">{w_sc_str}</td>
                        <td class="text-center">{st_badge}</td>
                        <td><small>{cat.notes or f'{len(cat.components)} component indicators evaluated'}</small></td>
                    </tr>
                    """)

            # 2. Intraperiod Session Volatility Table (Requirement 6)
            intra_rows = []
            if cd.scorecard and cd.scorecard.intraperiod_context:
                for sess in cd.scorecard.intraperiod_context:
                    spx_c = "text-green font-bold" if sess.spx_change_pct > 0 else ("text-red font-bold" if sess.spx_change_pct < 0 else "text-muted")
                    ndx_c = "text-green font-bold" if sess.ndx_change_pct > 0 else ("text-red font-bold" if sess.ndx_change_pct < 0 else "text-muted")
                    alert_badge = '<span class="badge badge-red font-bold">⚠️ Large Move (&ge; 1.5%)</span>' if sess.is_large_move else '<span class="text-muted">Normal</span>'
                    intra_rows.append(f"""
                    <tr>
                        <td class="text-center font-mono">{sess.date}</td>
                        <td class="text-right font-mono">{sess.spx_close:,.2f}</td>
                        <td class="text-right font-mono {spx_c}">{sess.spx_change_pct:+.2f}%</td>
                        <td class="text-right font-mono">{sess.ndx_close:,.2f}</td>
                        <td class="text-right font-mono {ndx_c}">{sess.ndx_change_pct:+.2f}%</td>
                        <td class="text-center">{alert_badge}</td>
                    </tr>
                    """)

            # 3. Component Indicator Voting Rows
            vote_rows = []
            for v in cd.scorecard.votes:
                v_class_vote = "text-green font-bold" if v.vote > 0.05 else ("text-red font-bold" if v.vote < -0.05 else "text-muted")
                v_str = f"{v.vote:+.2f}"
                vote_rows.append(f"""
                <tr>
                    <td><strong>{v.rule_name}</strong></td>
                    <td class="text-center font-mono {v_class_vote}">{v_str}</td>
                    <td class="text-center font-mono">{v.weight:.1f}</td>
                    <td class="text-center font-mono">{v.weighted_vote:+.2f}</td>
                    <td><small>{v.condition}</small></td>
                    <td><em>{v.interpretation}</em></td>
                </tr>
                """)

            levels_html = []
            for al in cd.asset_levels:
                l_rows = []
                for kl in al.levels:
                    l_type_class = "text-green" if kl.level_type == "Support" else "text-red"
                    l_rows.append(f"""
                    <tr>
                        <td>{kl.label}</td>
                        <td class="text-right font-mono">{kl.price:,.2f}</td>
                        <td class="text-right font-mono">{_fmt_pct(kl.distance_pct)}</td>
                        <td class="text-center font-bold {l_type_class}">{kl.level_type}</td>
                    </tr>
                    """)
                levels_html.append(f"""
                <div class="levels-box">
                    <h4>{al.name} ({al.symbol}) &bull; Current: <span class="font-mono">{al.current_price:,.2f}</span></h4>
                    <table class="report-table compact-table">
                        <thead><tr><th>Level</th><th class="text-right">Price</th><th class="text-right">Distance</th><th class="text-center">Type</th></tr></thead>
                        <tbody>{''.join(l_rows)}</tbody>
                    </table>
                </div>
                """)

            forward_strat_html = ""
            if cd.regime_intelligence:
                intel = cd.regime_intelligence
                forward_strat_html = f"""
                <div class="forward-strategy-card" style="margin-top: 24px; padding: 18px 22px; border-radius: 10px; background: var(--bg-card-subtle); border: 1px solid var(--border); border-left: 4px solid var(--primary);">
                    <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 8px; color: var(--primary); display: flex; align-items: center; gap: 8px;">
                        <span>🔭</span> Cross-Market Macro Alignment &amp; Execution Posture
                    </h3>
                    <p style="font-size: 14px; line-height: 1.5; margin: 0; color: var(--text-main);">
                        <strong>Alignment:</strong> The technical trend stands at <strong>{cd.verdict.upper()}</strong> ({cd.normalized_score:+.2f}), operating within an active <strong>{intel.summary_badge}</strong> regime. Corporate credit remains <strong>{intel.credit.regime}</strong> ({intel.credit.spread_bps:.0f} bps OAS) with volatility term structure in <strong>{intel.vol_term.structure}</strong> (ratio {intel.vol_term.ratio:.3f}). Tactical sector rotation shows {intel.rotation.rotation_summary} (see <a href="#section-17" style="color: var(--primary); text-decoration: underline;">Section 17: Macro &amp; Economic Events</a> for sector momentum details).
                    </p>
                </div>
                """

            conf_label = f'<div class="score-sub font-mono" style="margin-top: 4px; color: var(--text-muted); font-size: 11px;">Confidence: <strong>{cd.scorecard.confidence}</strong></div>' if cd.scorecard and cd.scorecard.confidence else ''

            sens_html = ""
            if cd.scorecard and getattr(cd.scorecard, "sensitivity", None):
                sens = cd.scorecard.sensitivity
                if period.report_type == "daily":
                    if sens.is_borderline:
                        sens_html = f"""
                        <div class="alert alert-warning" style="margin-top: 16px; margin-bottom: 12px;">
                            ⚠️ <strong>Regime Edge Warning:</strong> Current score <code>{sens.baseline_score:+.2f}</code> sits within 0.03 pts of regime threshold (<strong>{sens.borderline_label}</strong>).
                        </div>
                        """
                else:
                    sens_rows = []
                    for s_it in sens.items:
                        v_badge = "badge-green" if s_it.verdict_ex in ("Risk-on", "Constructive") else ("badge-red" if s_it.verdict_ex in ("Cautious", "Risk-off") else "badge-yellow")
                        d_color = "text-green" if s_it.delta_vs_baseline > 0 else ("text-red" if s_it.delta_vs_baseline < 0 else "text-muted")
                        sens_rows.append(f"""
                        <tr>
                            <td><strong>{s_it.excluded_category}</strong></td>
                            <td class="text-center font-mono">{s_it.score_ex:+.2f}</td>
                            <td class="text-center"><span class="badge {v_badge}">{s_it.verdict_ex}</span></td>
                            <td class="text-center font-mono {d_color}">{s_it.delta_vs_baseline:+.2f}</td>
                        </tr>
                        """)
                    borderline_alert = ""
                    if sens.is_borderline:
                        borderline_alert = f"""
                        <div class="alert alert-warning" style="margin-bottom: 12px;">
                            ⚠️ <strong>Regime Edge Warning:</strong> Current score <code>{sens.baseline_score:+.2f}</code> sits within 0.03 pts of regime threshold (<strong>{sens.borderline_label}</strong>).
                        </div>
                        """
                    sens_html = f"""
                    <h3 class="sub-title" style="margin-top: 24px;">Verdict Sensitivity &amp; Borderline Analysis</h3>
                    {borderline_alert}
                    <div class="table-container">
                        <table class="report-table compact-table">
                            <thead>
                                <tr>
                                    <th>Excluded Category</th>
                                    <th class="text-center">Score (ex-Category)</th>
                                    <th class="text-center">Implied Verdict</th>
                                    <th class="text-center">Delta vs Baseline</th>
                                </tr>
                            </thead>
                            <tbody>{''.join(sens_rows)}</tbody>
                        </table>
                    </div>
                    """

            intra_html = ""
            if intra_rows and period.report_type != "daily":
                intra_html = f"""
                <h3 class="sub-title">Intraperiod Daily Session Volatility</h3>
                <div class="table-container">
                    <table class="report-table compact-table">
                        <thead>
                            <tr>
                                <th class="text-center">Session Date</th>
                                <th class="text-right">S&amp;P 500 Close</th>
                                <th class="text-right">S&amp;P 500 Return</th>
                                <th class="text-right">Nasdaq-100 Close</th>
                                <th class="text-right">Nasdaq-100 Return</th>
                                <th class="text-center">Single-Session Move (&ge; 1.5%)</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(intra_rows)}</tbody>
                    </table>
                </div>
                """

            voting_html = ""
            if period.report_type != "daily":
                voting_html = f"""
                <h3 class="sub-title">Explainable Component Indicator Voting</h3>
                <div class="table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Indicator Rule</th>
                                <th class="text-center">Gradient Vote</th>
                                <th class="text-center">Weight</th>
                                <th class="text-center">Weighted Vote</th>
                                <th>Metric Details</th>
                                <th>Interpretation</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(vote_rows)}</tbody>
                    </table>
                </div>
                """
            else:
                voting_html = """
                <div style="padding: 12px 16px; border-radius: 8px; background: var(--bg-card-subtle); margin-top: 16px; margin-bottom: 16px;">
                    <p style="font-size: 12px; margin: 0; color: var(--text-muted); font-style: italic;">Individual indicator voting rules, sensitivity analysis, and intraperiod trajectory are published in the Weekly &amp; Monthly strategic reports.</p>
                </div>
                """

            v_low = cd.verdict.lower()
            if v_low in ("bullish", "risk-on", "constructive"):
                v_class = "badge-green"
                banner_border = "var(--tropical-teal)"
            elif v_low in ("bearish", "risk-off", "cautious"):
                v_class = "badge-red"
                banner_border = "var(--rosy-copper)"
            else:
                v_class = "badge-amber"
                banner_border = "var(--amber-honey)"

            conf_html = f'<div style="font-size: 0.82rem; color: var(--text-muted); font-family: var(--font-mono); margin: -8px 0 20px 0;"><strong>Confidence:</strong> {cd.scorecard.confidence}</div>' if cd.scorecard and cd.scorecard.confidence else ''

            body_html.append(f"""
            <div class="verdict-banner" style="border-left-color: {banner_border}; margin-bottom: 14px;">
                <div class="verdict-box">
                    <span class="verdict-label">Final Regime Outlook</span>
                    <span class="verdict-badge {v_class}">{cd.verdict.upper()}</span>
                </div>
                <div class="score-box" style="margin-left: auto; text-align: right;">
                    <span class="score-label">Normalized Score</span>
                    <span class="score-val font-mono">{cd.normalized_score:+.2f}</span>
                    <span class="score-sub font-mono" style="color: rgba(255,255,255,0.65); font-size: 11px; margin-left: 8px;">(Scale: -1.0 to +1.0)</span>
                </div>
            </div>
            {conf_html}

            <h3 class="sub-title">Macro &amp; Micro Trend Scorecard by Category</h3>
            <div class="table-container">
                <table class="report-table">
                    <thead>
                        <tr>
                            <th>Category</th>
                            <th class="text-center">Weight Cap</th>
                            <th class="text-center">Effective Weight</th>
                            <th class="text-center">Category Score</th>
                            <th class="text-center">Weighted Score</th>
                            <th class="text-center">Status</th>
                            <th>Diagnostic Notes / Drivers</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(cat_rows)}</tbody>
                </table>
            </div>

            {sens_html}

            {intra_html}

            {voting_html}

            <div class="grid-2 drivers-grid">
                <div class="driver-card driver-bullish">
                    <h4 class="text-green">🟢 Top Bullish Factors</h4>
                    <ul>{''.join(f'<li>{bf}</li>' for bf in cd.top_bullish_factors)}</ul>
                </div>
                <div class="driver-card driver-bearish">
                    <h4 class="text-red">🔴 Top Bearish Factors</h4>
                    <ul>{''.join(f'<li>{br}</li>' for br in cd.top_bearish_factors)}</ul>
                </div>
            </div>

            {f'<div class="alert alert-warning">⚠️ <strong>Caution Flags:</strong> {" &bull; ".join(cd.caution_flags)}</div>' if cd.caution_flags else ''}

            <h3 class="sub-title">Key Benchmark Support & Resistance Levels</h3>
            <div class="grid-2">{''.join(levels_html)}</div>
            {forward_strat_html}
            """)

            if charts and charts.get("seasonality_heatmap"):
                body_html.append(_render_chart_html(charts.get("seasonality_heatmap")))

        # Section: Footer
        elif isinstance(sec.data, dict) and "disclaimer" in sec.data:
            disclaimer = sec.data.get("disclaimer", "For informational purposes only. Not financial advice.")
            sources = sec.data.get("data_sources", [])
            overall_status = sec.data.get("overall_status", "PARTIAL")
            missing_inputs = sec.data.get("missing_inputs", [])
            sources_html = ""
            if sources:
                s_rows = []
                for s in sources:
                    status_badge = "badge-bullish" if "COMPLETE" in s.status.upper() else ("badge-neutral" if "PARTIAL" in s.status.upper() else "badge-muted")
                    s_rows.append(f"""
                    <tr>
                        <td><strong>{s.source_name}</strong></td>
                        <td>{s.coverage}</td>
                        <td class="font-mono text-center">{s.fetch_time}</td>
                        <td class="text-center"><span class="badge {status_badge}">{s.status.upper()}</span></td>
                        <td>{s.notes}</td>
                    </tr>
                    """)

                missing_html = ""
                if missing_inputs:
                    missing_str = "; ".join(missing_inputs)
                    missing_html = f'<div class="alert alert-warning" style="margin-top: 10px; text-align: left;">⚠️ <strong>Missing / Unavailable Inputs:</strong> {missing_str}</div>'

                overall_badge = "badge-bullish" if overall_status.upper() == "COMPLETE" else "badge-neutral"
                sources_html = f"""
                <h3 class="sub-title" style="margin-top: 24px;">Data Quality &amp; Provenance &bull; <span class="badge {overall_badge}">STATUS: {overall_status.upper()}</span></h3>
                {missing_html}
                <div class="table-container">
                    <table class="report-table compact-table">
                        <thead>
                            <tr>
                                <th>Source</th>
                                <th>Coverage</th>
                                <th class="text-center">Fetch / Window</th>
                                <th class="text-center">Status</th>
                                <th>Fallbacks &amp; Data Notes</th>
                            </tr>
                        </thead>
                        <tbody>{''.join(s_rows)}</tbody>
                    </table>
                </div>
                """

            body_html.append(f"""
            <footer class="report-footer">
                <p><strong>Disclaimer:</strong> {disclaimer}</p>
                {sources_html}
                <p class="footer-sub" style="margin-top: 14px;">Generated by Automated Market Report Engine &bull; System Time: {period.as_of_date}</p>
            </footer>
            """)

        body_html.append('</section>')

    # Complete HTML Document with Inline CSS and Theme Toggle
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{rep_title} - {period.session_date}</title>
    <style>
        :root, body.theme-zen {{
            /* Tropical Earth Palette */
            --amber-honey: #eca400;
            --rosy-copper: #db504a;
            --dark-slate-grey: #2c514c;
            --tropical-teal: #56a3a6;
            --deep-walnut: #56351e;

            /* Mappings */
            --bg-page: #FDFBF7;
            --bg-sidebar: var(--dark-slate-grey);
            --bg-card: #FFFFFF;
            --bg-card-subtle: rgba(44, 81, 76, 0.05);
            --bg-nav: rgba(253, 251, 247, 0.94);
            
            --text-main: var(--deep-walnut);
            --text-muted: rgba(86, 53, 30, 0.65);
            --text-sidebar: #E0EAE9;
            
            --primary: var(--dark-slate-grey); 
            --border: rgba(86, 53, 30, 0.15);
            
            --accent-green-bg: rgba(86, 163, 166, 0.15);
            --accent-green-txt: #2c514c;
            --accent-red-bg: rgba(219, 80, 74, 0.12);
            --accent-red-txt: #b33934;
            --accent-amber-bg: rgba(236, 164, 0, 0.15);
            --accent-amber-txt: #8f5d00;
            
            --green: #2c514c;
            --red: #db504a;
            --amber: #eca400;
            --accent: var(--tropical-teal);
            
            --badge-bullish-bg: rgba(86, 163, 166, 0.15);
            --badge-bullish-text: #2c514c;
            --badge-bearish-bg: rgba(219, 80, 74, 0.12);
            --badge-bearish-text: #b33934;
            --badge-neutral-bg: rgba(236, 164, 0, 0.15);
            --badge-neutral-text: #8f5d00;
            
            --shadow-card: 0 4px 12px rgba(86, 53, 30, 0.04);
            --radius-card: 12px;
        }}

        html.dark, body.dark {{
            --bg-page: #152422;
            --bg-sidebar: #101c1a;
            --bg-card: #1c302d;
            --bg-card-subtle: rgba(86, 163, 166, 0.08);
            --bg-nav: rgba(21, 36, 34, 0.94);
            
            --text-main: #FDFBF7;
            --text-muted: rgba(253, 251, 247, 0.65);
            --text-sidebar: #E0EAE9;
            
            --primary: var(--tropical-teal);
            --border: rgba(253, 251, 247, 0.12);
            
            --accent-green-bg: rgba(86, 163, 166, 0.25);
            --accent-green-txt: #7cd3d5;
            --accent-red-bg: rgba(219, 80, 74, 0.25);
            --accent-red-txt: #ff7d78;
            --accent-amber-bg: rgba(236, 164, 0, 0.25);
            --accent-amber-txt: #ffc44d;
            
            --green: #7cd3d5;
            --red: #ff7d78;
            --amber: #ffc44d;
            --accent: var(--tropical-teal);
            
            --badge-bullish-bg: rgba(86, 163, 166, 0.25);
            --badge-bullish-text: #7cd3d5;
            --badge-bearish-bg: rgba(219, 80, 74, 0.25);
            --badge-bearish-text: #ff7d78;
            --badge-neutral-bg: rgba(236, 164, 0, 0.25);
            --badge-neutral-text: #ffc44d;
            
            --shadow-card: 0 4px 12px rgba(0, 0, 0, 0.25);
        }}

        @media (prefers-color-scheme: dark) {{
            :root:not(.light) {{
                --bg-page: #152422;
                --bg-sidebar: #101c1a;
                --bg-card: #1c302d;
                --bg-card-subtle: rgba(86, 163, 166, 0.08);
                --bg-nav: rgba(21, 36, 34, 0.94);
                
                --text-main: #FDFBF7;
                --text-muted: rgba(253, 251, 247, 0.65);
                --text-sidebar: #E0EAE9;
                
                --primary: var(--tropical-teal);
                --border: rgba(253, 251, 247, 0.12);
                
                --accent-green-bg: rgba(86, 163, 166, 0.25);
                --accent-green-txt: #7cd3d5;
                --accent-red-bg: rgba(219, 80, 74, 0.25);
                --accent-red-txt: #ff7d78;
                --accent-amber-bg: rgba(236, 164, 0, 0.25);
                --accent-amber-txt: #ffc44d;
                
                --green: #7cd3d5;
                --red: #ff7d78;
                --amber: #ffc44d;
                --accent: var(--tropical-teal);
                
                --badge-bullish-bg: rgba(86, 163, 166, 0.25);
                --badge-bullish-text: #7cd3d5;
                --badge-bearish-bg: rgba(219, 80, 74, 0.25);
                --badge-bearish-text: #ff7d78;
                --badge-neutral-bg: rgba(236, 164, 0, 0.25);
                --badge-neutral-text: #ffc44d;
                
                --shadow-card: 0 4px 12px rgba(0, 0, 0, 0.25);
            }}
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html {{ scroll-behavior: smooth; font-size: 14px; }}
        
        body {{
            font-family: 'Founders Grotesk', 'Helvetica Neue', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            line-height: 1.5;
            display: flex;
            min-height: 100vh;
            overflow-x: hidden;
        }}

        .font-mono {{
            font-family: 'Gt American Mono', 'JetBrains Mono', SFMono-Regular, Menlo, Monaco, Consolas, ui-monospace, monospace;
            letter-spacing: -0.02em;
        }}
        .font-bold {{ font-weight: 700; }}

        /* --- Sidebar --- */
        .sidebar {{
            width: 265px;
            background-color: var(--bg-sidebar);
            color: var(--text-sidebar);
            height: 100vh;
            position: fixed;
            top: 0;
            left: 0;
            display: flex;
            flex-direction: column;
            padding: 22px 18px;
            border-right: 1px solid var(--border);
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 100;
        }}
        
        .sidebar.collapsed {{
            transform: translateX(-100%);
        }}

        .brand {{ margin-bottom: 18px; }}
        .brand h1 {{
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            line-height: 1.2;
            margin-bottom: 4px;
            color: #FFFFFF;
        }}
        .brand p {{
            font-size: 0.82rem;
            color: var(--tropical-teal);
            font-weight: 500;
        }}

        .nav-menu {{
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            flex-grow: 1;
            margin-bottom: 16px;
            padding-right: 4px;
        }}
        
        .nav-menu::-webkit-scrollbar {{ width: 4px; }}
        .nav-menu::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.2); border-radius: 4px; }}

        details > summary {{
            list-style: none;
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--amber-honey);
            padding: 9px 10px;
            cursor: pointer;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background-color 0.2s;
            margin-top: 4px;
        }}
        details > summary::-webkit-details-marker {{ display: none; }}
        details > summary:hover {{ background-color: rgba(255, 255, 255, 0.05); }}
        details > summary::after {{ content: '+'; font-size: 1.15em; line-height: 0.5; color: var(--tropical-teal); }}
        details[open] > summary::after {{ content: '−'; }}

        .nav-link {{
            text-decoration: none;
            color: rgba(255,255,255,0.88);
            font-size: 0.86rem;
            font-weight: 400;
            padding: 6px 10px 6px 14px;
            border-radius: 6px;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            line-height: 1.3;
            margin-bottom: 3px;
        }}
        .nav-link:hover {{
            background-color: rgba(255,255,255,0.1);
            color: #FFFFFF;
            transform: translateX(3px);
        }}

        .sidebar-footer {{
            padding-top: 16px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}

        .theme-toggle-btn {{
            width: 100%;
            padding: 9px;
            background: var(--amber-honey);
            color: var(--deep-walnut);
            border: none;
            border-radius: 8px;
            font-family: inherit;
            font-weight: 700;
            font-size: 0.88rem;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 6px;
        }}
        .theme-toggle-btn:hover {{
            background-color: #f5b324;
        }}

        /* --- Main Content --- */
        .main-content {{
            margin-left: 265px;
            flex-grow: 1;
            padding: 24px 40px 48px 40px;
            max-width: 1300px;
            transition: margin-left 0.3s cubic-bezier(0.16, 1, 0.3, 1), max-width 0.3s;
        }}
        .main-content.expanded {{
            margin-left: 0;
            max-width: 100%;
        }}

        .top-bar {{
            display: flex;
            align-items: center;
            margin-bottom: 24px;
        }}

        .sticky-nav-bar {{
            position: sticky;
            top: 0;
            z-index: 90;
            background: var(--bg-nav);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            padding: 10px 0;
        }}
        .nav-inner {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
        }}
        .nav-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .toggle-sidebar-btn {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--primary);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 700;
            font-family: inherit;
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }}
        .toggle-sidebar-btn:hover {{
            border-color: var(--tropical-teal);
        }}
        .nav-controls {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-select {{
            background: var(--bg-card);
            color: var(--text-main);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            outline: none;
            max-width: 280px;
        }}
        .nav-btn {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-main);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
        }}
        .nav-btn:hover, .nav-select:hover {{
            border-color: var(--tropical-teal);
        }}

        @media (max-width: 1024px) {{
            .sidebar {{ transform: translateX(-100%); }}
            .sidebar.mobile-open {{ transform: translateX(0); }}
            .main-content {{ margin-left: 0; padding: 16px; }}
            .main-content.expanded {{ margin-left: 0; }}
        }}

        /* --- Cards & Headers --- */
        .section-card, .card {{
            background: var(--bg-card);
            border-radius: var(--radius-card);
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: var(--shadow-card);
            border: 1px solid var(--border);
            scroll-margin-top: 64px;
        }}

        .section-header {{
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
        }}
        .section-num {{
            background: var(--bg-sidebar);
            color: #FFF;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
        }}
        .section-title {{
            font-size: 1.25rem;
            font-weight: 600;
            letter-spacing: -0.01em;
            color: var(--text-main);
            margin: 0;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }}
        .badge-primary {{ background: var(--bg-sidebar); color: #FFF; }}
        .badge-green, .badge-bullish {{ background: var(--accent-green-bg); color: var(--accent-green-txt); }}
        .badge-red, .badge-bearish {{ background: var(--accent-red-bg); color: var(--accent-red-txt); }}
        .badge-amber, .badge-neutral {{ background: var(--accent-amber-bg); color: var(--accent-amber-txt); }}

        .text-green {{ color: var(--accent-green-txt); }}
        .text-red {{ color: var(--accent-red-txt); }}
        .text-muted {{ color: var(--text-muted); }}
        .text-right {{ text-align: right; }}
        .text-center {{ text-align: center; }}

        /* --- KPI Grid --- */
        .top10-ticker-strip {{ margin-bottom: 24px; }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 16px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border-radius: var(--radius-card);
            padding: 16px;
            box-shadow: var(--shadow-card);
            display: flex;
            flex-direction: column;
            gap: 4px;
            border: 1px solid var(--border);
            text-decoration: none;
            color: inherit;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}
        .kpi-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(86, 53, 30, 0.08);
        }}
        .kpi-label {{
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            text-transform: uppercase;
        }}
        .kpi-val {{
            font-size: 1.4rem;
            font-weight: 600;
            color: var(--text-main);
        }}
        .kpi-sub {{
            font-size: 0.75rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .kpi-secondary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
        }}
        .kpi-secondary-card {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 2px;
            border: 1px solid var(--border);
            text-decoration: none;
            color: inherit;
            transition: background-color 0.15s ease;
        }}
        .kpi-secondary-card:hover {{
            background: var(--bg-card-subtle);
        }}
        .kpi-secondary-card .kpi-label {{ font-size: 0.65rem; }}
        .kpi-secondary-card .kpi-val {{ font-size: 1rem; }}
        .kpi-secondary-card .kpi-sub {{ font-size: 0.7rem; }}

        /* --- Tables --- */
        .table-container {{
            overflow-x: auto;
            margin-top: 12px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }}
        .report-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            text-align: left;
        }}
        .report-table th {{
            background: var(--bg-card-subtle);
            color: var(--text-main);
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
        }}
        .report-table td {{
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
            color: var(--text-main);
        }}
        .report-table tbody tr {{ transition: background-color 0.1s ease; }}
        .report-table tbody tr:nth-child(even) {{ background-color: var(--bg-card-subtle); }}
        .report-table tbody tr:hover {{ background-color: rgba(236, 164, 0, 0.08); }}
        .report-table tr:last-child td {{ border-bottom: none; }}
        .compact-table td, .compact-table th {{ padding: 6px 8px; font-size: 0.8rem; }}

        .ticker-circle {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: var(--bg-sidebar);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.65rem;
            font-weight: 700;
            color: #FFF;
            margin-right: 8px;
        }}
        .flex-cell {{ display: flex; align-items: center; }}

        /* --- Verdict Banners --- */
        .verdict-banner {{
            display: flex;
            gap: 24px;
            background: var(--bg-sidebar);
            padding: 16px 24px;
            border-radius: 12px;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
            border-left: 4px solid var(--amber-honey);
            color: #FFF;
        }}
        .verdict-box {{
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }}
        .score-box {{
            display: flex;
            align-items: baseline;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .verdict-label, .score-label {{
            font-size: 0.7rem;
            font-weight: 600;
            color: rgba(255,255,255,0.7);
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .verdict-badge {{
            font-size: 0.95rem;
            padding: 6px 14px;
            border-radius: 6px;
            font-weight: 600;
        }}
        .verdict-banner .badge-amber, .verdict-banner .badge-neutral {{
            background: var(--amber-honey);
            color: #1e332f;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .verdict-banner .badge-red, .verdict-banner .badge-bearish {{
            background: var(--rosy-copper);
            color: #FFFFFF;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .verdict-banner .badge-green, .verdict-banner .badge-bullish {{
            background: var(--tropical-teal);
            color: #FFFFFF;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .score-val {{
            font-size: 1.6rem;
            font-weight: 600;
            line-height: 1;
        }}

        .reasons-list {{ padding-left: 20px; display: flex; flex-direction: column; gap: 8px; }}
        .reasons-heading, .sub-title {{ font-size: 1rem; font-weight: 700; margin: 16px 0 10px 0; color: var(--text-main); }}

        .methodology-note {{
            margin: 16px 0;
            padding: 12px 16px;
            background: var(--bg-card-subtle);
            border: 1px dashed var(--border);
            border-radius: 8px;
            font-size: 0.8rem;
        }}
        .methodology-note summary {{
            cursor: pointer;
            font-weight: 700;
            color: var(--primary);
            user-select: none;
            outline: none;
        }}
        .methodology-note summary:hover {{ text-decoration: underline; }}
        .methodology-content {{
            margin-top: 10px;
            color: var(--text-muted);
            line-height: 1.6;
        }}
        .methodology-content strong {{ color: var(--text-main); }}

        .alert {{ padding: 12px 16px; border-radius: 8px; font-size: 0.85rem; margin: 12px 0; line-height: 1.5; }}
        .alert-info {{ background: var(--bg-card-subtle); border-left: 4px solid var(--tropical-teal); color: var(--text-main); }}
        .alert-warning {{ background: rgba(236, 164, 0, 0.12); color: var(--text-main); border-left: 4px solid var(--amber-honey); }}
        .alert-danger {{ background: rgba(219, 80, 74, 0.12); color: var(--text-main); border-left: 4px solid var(--rosy-copper); }}

        .chart-svg-container {{
            margin: 20px 0;
            text-align: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            padding: 16px 20px;
        }}
        .chart-svg-wrapper {{
            width: 100%;
            overflow-x: auto;
            display: flex;
            justify-content: center;
        }}
        .chart-svg-wrapper svg {{
            max-width: 100%;
            height: auto;
            display: block;
        }}
        .macro-chart-box {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; }}
        .macro-chart-svg {{ width: 100%; height: auto; display: block; }}
        .macro-charts-stack {{ display: flex; flex-direction: column; gap: 24px; margin: 20px 0 28px 0; }}

        .vix-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
        .vix-metric {{ background: var(--bg-card-subtle); padding: 14px; border-radius: 8px; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--border); }}
        .vix-label {{ font-size: 0.7rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; }}
        .vix-val {{ font-size: 1.3rem; font-weight: 700; }}
        .vix-sub {{ font-size: 0.75rem; color: var(--text-muted); }}
        .vix-desc {{ font-size: 0.75rem; margin-top: 4px; color: var(--text-muted); }}

        .grid-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-top: 10px; }}
        .tech-card {{
            background: var(--bg-card-subtle);
            border-radius: 10px;
            padding: 18px;
            margin-bottom: 16px;
            border: 1px solid var(--border);
        }}
        .tech-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }}
        .tech-price {{ font-size: 1.25rem; font-weight: 700; }}
        .metric-group {{ display: flex; flex-direction: column; gap: 6px; }}
        .metric-title {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px; }}
        .metric-row {{ display: flex; justify-content: space-between; font-size: 0.8rem; }}

        .mover-period-title {{ font-size: 1rem; font-weight: 700; margin: 20px 0 10px 0; color: var(--text-main); }}
        .movers-split {{ display: flex; flex-direction: column; gap: 20px; }}
        .mover-table-box {{ background: var(--bg-card-subtle); padding: 16px 18px; border-radius: 10px; overflow-x: auto; border: 1px solid var(--border); }}
        .mover-subheading {{ font-size: 0.85rem; font-weight: 700; margin-bottom: 8px; }}

        .drivers-grid {{ margin: 16px 0; }}
        .driver-card {{ padding: 16px; border-radius: 10px; }}
        .driver-card ul {{ padding-left: 20px; margin-top: 8px; display: flex; flex-direction: column; gap: 4px; font-size: 0.85rem; }}
        .driver-bullish {{ background: var(--accent-green-bg); color: var(--accent-green-txt); }}
        .driver-bearish {{ background: var(--accent-red-bg); color: var(--accent-red-txt); }}

        .levels-box {{ background: var(--bg-card-subtle); padding: 14px; border-radius: 8px; border: 1px solid var(--border); }}
        .levels-box h4 {{ font-size: 0.85rem; font-weight: 700; margin-bottom: 8px; }}

        .report-footer {{ border-top: 1px solid var(--border); padding-top: 16px; text-align: center; color: var(--text-muted); font-size: 0.8rem; }}
        .footer-sub {{ font-size: 0.7rem; margin-top: 4px; }}
        .table-caption {{ font-size: 0.75rem; color: var(--text-muted); margin-bottom: 8px; }}
    </style>
</head>
<body class="theme-zen">
    {sidebar_html}
    <main class="main-content" id="main-content">
        {top_bar_html}
        {header_html}
        {top10_html}
        {''.join(body_html)}
    </main>
    <script>
        function toggleSidebar() {{
            const sidebar = document.getElementById('sidebar');
            const main = document.getElementById('main-content');
            if (window.innerWidth > 1024) {{
                sidebar.classList.toggle('collapsed');
                main.classList.toggle('expanded');
            }} else {{
                sidebar.classList.toggle('mobile-open');
            }}
        }}
        function toggleTheme() {{
            const html = document.documentElement;
            const body = document.body;
            if (html.classList.contains('dark') || body.classList.contains('dark')) {{
                html.classList.remove('dark');
                body.classList.remove('dark');
                body.classList.add('theme-zen');
                localStorage.setItem('theme', 'light');
            }} else {{
                html.classList.add('dark');
                body.classList.add('dark');
                body.classList.remove('theme-zen');
                localStorage.setItem('theme', 'dark');
            }}
        }}
        (function() {{
            const saved = localStorage.getItem('theme');
            if (saved === 'dark') {{
                document.documentElement.classList.add('dark');
                document.body.classList.add('dark');
                document.body.classList.remove('theme-zen');
            }}
        }})();
    </script>
</body>
</html>
"""
