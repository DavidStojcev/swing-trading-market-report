"""Pure inline SVG chart generator for macroeconomic historical trends.

Self-contained with zero external JavaScript or remote CDN dependencies.
Uses CSS custom properties to seamlessly adapt to light and dark modes.
Designed with expansive single-column viewBox dimensions (1000x340) for maximum clarity.
"""

from typing import Dict, List, Optional
from data.fred_provider import MacroHistoricalSeries


def _find_series(indicators: List[MacroHistoricalSeries], series_id: str) -> Optional[MacroHistoricalSeries]:
    for s in indicators:
        if s.series_id == series_id:
            return s
    return None


def render_inflation_chart(indicators: List[MacroHistoricalSeries], width: int = 1000, height: int = 340) -> str:
    """Render Trailing 12-Month Inflation Trajectory (CPI, Core CPI, Core PCE vs 2% Target)."""
    cpi = _find_series(indicators, "CPIAUCSL")
    core_cpi = _find_series(indicators, "CPILFESL")
    core_pce = _find_series(indicators, "PCEPILFE") or _find_series(indicators, "PCEPI")

    series_map = {}
    if cpi and cpi.points:
        series_map["Headline CPI"] = {"color": "#3b82f6", "series": cpi}
    if core_cpi and core_cpi.points:
        series_map["Core CPI"] = {"color": "#f59e0b", "series": core_cpi}
    if core_pce and core_pce.points:
        series_map["Core PCE"] = {"color": "#10b981", "series": core_pce}

    if not series_map:
        return ""

    # Common dates from longest series
    anchor_series = max(series_map.values(), key=lambda x: len(x["series"].points))["series"]
    dates = [p.label for p in anchor_series.points]
    n_pts = len(dates)

    # Global min/max including 2.0% reference target
    all_vals = [2.0]
    for s_info in series_map.values():
        all_vals.extend([p.yearly_val for p in s_info["series"].points])

    min_v = min(all_vals)
    max_v = max(all_vals)
    pad = max(0.5, (max_v - min_v) * 0.15)
    y_min = max(0.0, min_v - pad)
    y_max = max_v + pad

    pad_left = 60
    pad_right = 36
    pad_top = 48
    pad_bottom = 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def get_x(idx: int) -> float:
        return pad_left + (idx / max(1, n_pts - 1)) * plot_w

    def get_y(val: float) -> float:
        return pad_top + (1.0 - (val - y_min) / max(0.001, y_max - y_min)) * plot_h

    svg = []
    svg.append(f'<svg viewBox="0 0 {width} {height}" class="macro-chart-svg" xmlns="http://www.w3.org/2000/svg">')
    svg.append(f'<rect width="{width}" height="{height}" rx="12" fill="var(--bg-card-subtle)" stroke="var(--border)" stroke-width="1"/>')

    # Title & Legend
    svg.append(f'<text x="{pad_left}" y="28" font-size="15" font-weight="700" fill="var(--text-main)">Inflation Trajectory (% YoY)</text>')
    
    # Legend
    leg_x = width - pad_right
    for s_name, s_info in reversed(series_map.items()):
        color = s_info["color"]
        svg.append(f'<circle cx="{leg_x - 6}" cy="24" r="5" fill="{color}"/>')
        svg.append(f'<text x="{leg_x - 16}" y="28" font-size="12" font-weight="600" fill="var(--text-muted)" text-anchor="end">{s_name}</text>')
        leg_x -= (len(s_name) * 8 + 36)

    # Gridlines
    for step in range(5):
        gv = y_min + (step / 4.0) * (y_max - y_min)
        gy = get_y(gv)
        svg.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" stroke="var(--border)" stroke-dasharray="3,3" stroke-width="1"/>')
        svg.append(f'<text x="{pad_left - 10}" y="{gy + 4:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="end" font-family="monospace">{gv:.1f}%</text>')

    # 2.0% Target Line
    if y_min <= 2.0 <= y_max:
        ty = get_y(2.0)
        svg.append(f'<line x1="{pad_left}" y1="{ty:.1f}" x2="{width - pad_right}" y2="{ty:.1f}" stroke="#ef4444" stroke-dasharray="5,4" stroke-width="1.8"/>')
        svg.append(f'<text x="{width - pad_right - 6}" y="{ty - 6:.1f}" font-size="11" fill="#ef4444" font-weight="700" text-anchor="end">Fed Target (2.0%)</text>')

    # Plot Lines & Points
    for s_name, s_info in series_map.items():
        color = s_info["color"]
        pts = s_info["series"].points
        pt_dict = {p.label: p.yearly_val for p in pts}
        coords = []
        for i, d in enumerate(dates):
            if d in pt_dict:
                coords.append(f"{get_x(i):.1f},{get_y(pt_dict[d]):.1f}")
        if coords:
            svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(coords)}"/>')
            for i, d in enumerate(dates):
                if d in pt_dict:
                    val = pt_dict[d]
                    cx = get_x(i)
                    cy = get_y(val)
                    svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{color}" stroke="var(--bg-card-subtle)" stroke-width="1.5"><title>{s_name} ({d}): {val:.2f}% YoY</title></circle>')

    # X-Axis Ticks (every single month since width is expansive)
    for i in range(n_pts):
        cx = get_x(i)
        svg.append(f'<text x="{cx:.1f}" y="{height - 14}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{dates[i]}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)


def render_labor_chart(indicators: List[MacroHistoricalSeries], width: int = 1000, height: int = 340) -> str:
    """Render Trailing 12-Month Labor Market Momentum (Payrolls additions + Unemployment rate)."""
    payrolls = _find_series(indicators, "PAYEMS")
    unrate = _find_series(indicators, "UNRATE")

    if not payrolls or not payrolls.points:
        return ""

    dates = [p.label for p in payrolls.points]
    n_pts = len(dates)
    bar_vals = [p.monthly_val for p in payrolls.points]  # net additions in k

    # Line series: unemployment
    un_dict = {p.label: p.raw_level for p in unrate.points} if unrate else {}
    line_vals = [un_dict.get(d, 4.0) for d in dates]

    # Payroll scale
    b_min = min(0.0, min(bar_vals))
    b_max = max(bar_vals) * 1.2 if max(bar_vals) > 0 else 100.0
    pad_b = (b_max - b_min) * 0.1
    b_min -= pad_b
    b_max += pad_b

    # Unemployment scale
    l_min = min(line_vals) - 0.3
    l_max = max(line_vals) + 0.3

    pad_left = 65
    pad_right = 55
    pad_top = 48
    pad_bottom = 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def get_bar_y(val: float) -> float:
        return pad_top + (1.0 - (val - b_min) / max(0.001, b_max - b_min)) * plot_h

    def get_line_y(val: float) -> float:
        return pad_top + (1.0 - (val - l_min) / max(0.001, l_max - l_min)) * plot_h

    svg = []
    svg.append(f'<svg viewBox="0 0 {width} {height}" class="macro-chart-svg" xmlns="http://www.w3.org/2000/svg">')
    svg.append(f'<rect width="{width}" height="{height}" rx="12" fill="var(--bg-card-subtle)" stroke="var(--border)" stroke-width="1"/>')

    # Title & Legend
    svg.append(f'<text x="{pad_left}" y="28" font-size="15" font-weight="700" fill="var(--text-main)">Labor Market Momentum</text>')
    svg.append(f'<rect x="{width - pad_right - 230}" y="17" width="12" height="12" rx="2" fill="var(--green)"/>')
    svg.append(f'<text x="{width - pad_right - 210}" y="28" font-size="12" fill="var(--text-muted)">Nonfarm Payrolls (k)</text>')
    svg.append(f'<circle cx="{width - pad_right - 75}" cy="23" r="5" fill="#3b82f6"/>')
    svg.append(f'<text x="{width - pad_right - 62}" y="28" font-size="12" fill="var(--text-muted)">Unemployment (%)</text>')

    # Gridlines and Left Axis (Payrolls)
    y_zero = get_bar_y(0.0)
    svg.append(f'<line x1="{pad_left}" y1="{y_zero:.1f}" x2="{width - pad_right}" y2="{y_zero:.1f}" stroke="var(--border)" stroke-width="1.8"/>')

    for step in range(5):
        gv = b_min + (step / 4.0) * (b_max - b_min)
        gy = get_bar_y(gv)
        svg.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" stroke="var(--border)" stroke-dasharray="3,3" stroke-width="0.9"/>')
        svg.append(f'<text x="{pad_left - 10}" y="{gy + 4:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="end" font-family="monospace">{gv:+.0f}k</text>')

    # Right Axis (Unemployment)
    for step in range(4):
        lv = l_min + (step / 3.0) * (l_max - l_min)
        ly = get_line_y(lv)
        svg.append(f'<text x="{width - pad_right + 10}" y="{ly + 4:.1f}" font-size="11" fill="#3b82f6" text-anchor="start" font-family="monospace">{lv:.1f}%</text>')

    # Draw Payroll Bars
    bar_w = max(14.0, (plot_w / n_pts) * 0.46)
    for i, (d, bv) in enumerate(zip(dates, bar_vals)):
        x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
        bx = x_center - (bar_w / 2.0)
        by = min(get_bar_y(bv), y_zero)
        bh = max(2.0, abs(get_bar_y(bv) - y_zero))
        color = "var(--green)" if bv >= 0 else "var(--red)"
        svg.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="3" fill="{color}" opacity="0.88"><title>Payrolls ({d}): {bv:+.0f}k</title></rect>')

    # Draw Unemployment Line
    if unrate:
        coords = []
        for i, lv in enumerate(line_vals):
            x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
            coords.append(f"{x_center:.1f},{get_line_y(lv):.1f}")
        svg.append(f'<polyline fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" points="{" ".join(coords)}"/>')
        for i, (d, lv) in enumerate(zip(dates, line_vals)):
            x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
            cy = get_line_y(lv)
            svg.append(f'<circle cx="{x_center:.1f}" cy="{cy:.1f}" r="4.5" fill="#3b82f6" stroke="var(--bg-card-subtle)" stroke-width="1.5"><title>Unemployment ({d}): {lv:.1f}%</title></circle>')

    # Date Ticks (every month)
    for i in range(n_pts):
        cx = pad_left + (i + 0.5) * (plot_w / n_pts)
        svg.append(f'<text x="{cx:.1f}" y="{height - 14}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{dates[i]}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)


def render_rates_chart(indicators: List[MacroHistoricalSeries], width: int = 1000, height: int = 340) -> str:
    """Render Monetary Policy & Benchmark Treasury Yields (Fed Funds vs 10Y vs 2Y)."""
    dff = _find_series(indicators, "DFF")
    y10 = _find_series(indicators, "DGS10")
    y2 = _find_series(indicators, "DGS2")

    series_map = {}
    if y10 and y10.points:
        series_map["10Y Yield"] = {"color": "#06b6d4", "series": y10}
    if y2 and y2.points:
        series_map["2Y Yield"] = {"color": "#f97316", "series": y2}
    if dff and dff.points:
        series_map["Fed Funds"] = {"color": "#8b5cf6", "series": dff}

    if not series_map:
        return ""

    anchor = max(series_map.values(), key=lambda x: len(x["series"].points))["series"]
    dates = [p.label for p in anchor.points]
    n_pts = len(dates)

    all_vals = []
    for s_info in series_map.values():
        all_vals.extend([p.raw_level for p in s_info["series"].points])

    min_v = min(all_vals)
    max_v = max(all_vals)
    pad = max(0.2, (max_v - min_v) * 0.15)
    y_min = max(0.0, min_v - pad)
    y_max = max_v + pad

    pad_left = 60
    pad_right = 36
    pad_top = 48
    pad_bottom = 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def get_x(idx: int) -> float:
        return pad_left + (idx / max(1, n_pts - 1)) * plot_w

    def get_y(val: float) -> float:
        return pad_top + (1.0 - (val - y_min) / max(0.001, y_max - y_min)) * plot_h

    svg = []
    svg.append(f'<svg viewBox="0 0 {width} {height}" class="macro-chart-svg" xmlns="http://www.w3.org/2000/svg">')
    svg.append(f'<rect width="{width}" height="{height}" rx="12" fill="var(--bg-card-subtle)" stroke="var(--border)" stroke-width="1"/>')

    # Title & Legend
    svg.append(f'<text x="{pad_left}" y="28" font-size="15" font-weight="700" fill="var(--text-main)">Policy &amp; Treasury Yields (%)</text>')

    leg_x = width - pad_right
    for s_name, s_info in reversed(series_map.items()):
        color = s_info["color"]
        svg.append(f'<circle cx="{leg_x - 6}" cy="24" r="5" fill="{color}"/>')
        svg.append(f'<text x="{leg_x - 16}" y="28" font-size="12" font-weight="600" fill="var(--text-muted)" text-anchor="end">{s_name}</text>')
        leg_x -= (len(s_name) * 8 + 36)

    # Gridlines
    for step in range(5):
        gv = y_min + (step / 4.0) * (y_max - y_min)
        gy = get_y(gv)
        svg.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" stroke="var(--border)" stroke-dasharray="3,3" stroke-width="1"/>')
        svg.append(f'<text x="{pad_left - 10}" y="{gy + 4:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="end" font-family="monospace">{gv:.2f}%</text>')

    # Plot Lines & Points
    for s_name, s_info in series_map.items():
        color = s_info["color"]
        pts = s_info["series"].points
        pt_dict = {p.label: p.raw_level for p in pts}
        coords = []
        for i, d in enumerate(dates):
            if d in pt_dict:
                coords.append(f"{get_x(i):.1f},{get_y(pt_dict[d]):.1f}")
        if coords:
            svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(coords)}"/>')
            for i, d in enumerate(dates):
                if d in pt_dict:
                    val = pt_dict[d]
                    cx = get_x(i)
                    cy = get_y(val)
                    svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{color}" stroke="var(--bg-card-subtle)" stroke-width="1.5"><title>{s_name} ({d}): {val:.2f}%</title></circle>')

    # Date Ticks (every month)
    for i in range(n_pts):
        cx = get_x(i)
        svg.append(f'<text x="{cx:.1f}" y="{height - 14}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{dates[i]}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)


def render_activity_chart(indicators: List[MacroHistoricalSeries], width: int = 1000, height: int = 340) -> str:
    """Render Consumer Pulse & Growth (Retail Sales MoM + Consumer Sentiment Index)."""
    retail = _find_series(indicators, "RSAFS")
    sentiment = _find_series(indicators, "UMCSENT")

    if not retail or not retail.points:
        return ""

    dates = [p.label for p in retail.points]
    n_pts = len(dates)
    bar_vals = [p.monthly_val for p in retail.points]

    sent_dict = {p.label: p.raw_level for p in sentiment.points} if sentiment else {}
    line_vals = [sent_dict.get(d, 50.0) for d in dates]

    # Retail sales scale (MoM %)
    b_min = min(0.0, min(bar_vals))
    b_max = max(bar_vals) * 1.25 if max(bar_vals) > 0 else 1.0
    pad_b = (b_max - b_min) * 0.1
    b_min -= pad_b
    b_max += pad_b

    # Sentiment scale
    l_min = min(line_vals) - 4.0
    l_max = max(line_vals) + 4.0

    pad_left = 65
    pad_right = 55
    pad_top = 48
    pad_bottom = 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def get_bar_y(val: float) -> float:
        return pad_top + (1.0 - (val - b_min) / max(0.001, b_max - b_min)) * plot_h

    def get_line_y(val: float) -> float:
        return pad_top + (1.0 - (val - l_min) / max(0.001, l_max - l_min)) * plot_h

    svg = []
    svg.append(f'<svg viewBox="0 0 {width} {height}" class="macro-chart-svg" xmlns="http://www.w3.org/2000/svg">')
    svg.append(f'<rect width="{width}" height="{height}" rx="12" fill="var(--bg-card-subtle)" stroke="var(--border)" stroke-width="1"/>')

    # Title & Legend
    svg.append(f'<text x="{pad_left}" y="28" font-size="15" font-weight="700" fill="var(--text-main)">Consumer Pulse &amp; Activity</text>')
    svg.append(f'<rect x="{width - pad_right - 245}" y="17" width="12" height="12" rx="2" fill="#3b82f6"/>')
    svg.append(f'<text x="{width - pad_right - 225}" y="28" font-size="12" fill="var(--text-muted)">Retail Sales MoM (%)</text>')
    svg.append(f'<circle cx="{width - pad_right - 80}" cy="23" r="5" fill="#8b5cf6"/>')
    svg.append(f'<text x="{width - pad_right - 68}" y="28" font-size="12" fill="var(--text-muted)">Sentiment Index</text>')

    # Zero line for retail sales
    y_zero = get_bar_y(0.0)
    svg.append(f'<line x1="{pad_left}" y1="{y_zero:.1f}" x2="{width - pad_right}" y2="{y_zero:.1f}" stroke="var(--border)" stroke-width="1.8"/>')

    # Left Axis (Retail MoM %)
    for step in range(5):
        gv = b_min + (step / 4.0) * (b_max - b_min)
        gy = get_bar_y(gv)
        svg.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" stroke="var(--border)" stroke-dasharray="3,3" stroke-width="0.9"/>')
        svg.append(f'<text x="{pad_left - 10}" y="{gy + 4:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="end" font-family="monospace">{gv:+.1f}%</text>')

    # Right Axis (Sentiment)
    for step in range(4):
        lv = l_min + (step / 3.0) * (l_max - l_min)
        ly = get_line_y(lv)
        svg.append(f'<text x="{width - pad_right + 10}" y="{ly + 4:.1f}" font-size="11" fill="#8b5cf6" text-anchor="start" font-family="monospace">{lv:.0f}</text>')

    # Draw Retail Bars
    bar_w = max(14.0, (plot_w / n_pts) * 0.46)
    for i, (d, bv) in enumerate(zip(dates, bar_vals)):
        x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
        bx = x_center - (bar_w / 2.0)
        by = min(get_bar_y(bv), y_zero)
        bh = max(2.0, abs(get_bar_y(bv) - y_zero))
        color = "#3b82f6" if bv >= 0 else "#ef4444"
        svg.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="3" fill="{color}" opacity="0.88"><title>Retail Sales ({d}): {bv:+.2f}% MoM</title></rect>')

    # Draw Sentiment Line
    if sentiment:
        coords = []
        for i, lv in enumerate(line_vals):
            x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
            coords.append(f"{x_center:.1f},{get_line_y(lv):.1f}")
        svg.append(f'<polyline fill="none" stroke="#8b5cf6" stroke-width="3" stroke-linecap="round" points="{" ".join(coords)}"/>')
        for i, (d, lv) in enumerate(zip(dates, line_vals)):
            x_center = pad_left + (i + 0.5) * (plot_w / n_pts)
            cy = get_line_y(lv)
            svg.append(f'<circle cx="{x_center:.1f}" cy="{cy:.1f}" r="4.5" fill="#8b5cf6" stroke="var(--bg-card-subtle)" stroke-width="1.5"><title>Sentiment ({d}): {lv:.1f}</title></circle>')

    # Date Ticks (every month)
    for i in range(n_pts):
        cx = pad_left + (i + 0.5) * (plot_w / n_pts)
        svg.append(f'<text x="{cx:.1f}" y="{height - 14}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{dates[i]}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)
