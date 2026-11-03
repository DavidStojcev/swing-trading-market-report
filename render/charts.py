"""Publication-quality financial charts generator using matplotlib.

Creates transparent, theme-neutral PNG charts for US market reports:
1. S&P 500 price with 20/50/200 DMA over trailing 6-12 months
2. Nasdaq-100 price with 20/50/200 DMA over trailing 6-12 months
3. SPDR Sector performance horizontal bar chart (sorted, green/red)
4. S&P 500 market breadth over time (% above 50 & 200 DMA with 40%/60% thresholds)
5. Cboe Volatility Index (VIX) line chart with 20/25 risk regimes
6. 10Y Treasury yield & 2s10s yield curve spread
7. Top Movers horizontal bar chart for the report period

Charts are saved as individual PNG files for Markdown reports and converted to
base64 data URLs for self-contained HTML embedding and email delivery.
"""

import base64
from dataclasses import dataclass
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data.calendar import PeriodInfo
from sections.movers import MoverItem
from sections.sectors import SectorPerformanceRow

logger = logging.getLogger(__name__)

# Dark/Light neutral palette
COLOR_TEXT = "#cbd5e1"
COLOR_MUTED = "#94a3b8"
COLOR_GRID = "#64748b"
COLOR_SPINE = "#475569"
COLOR_GREEN = "#10b981"
COLOR_RED = "#ef4444"
COLOR_BLUE = "#38bdf8"
COLOR_AMBER = "#f59e0b"
COLOR_PURPLE = "#a78bfa"
COLOR_YELLOW = "#facc15"


@dataclass
class GeneratedChart:
    """Container for a generated chart file, inline base64 PNG data, and theme-adaptive SVG."""
    key: str
    title: str
    caption: str
    file_path: Optional[str] = None
    base64_data: str = ""
    svg_content: str = ""
    is_available: bool = True
    error_message: Optional[str] = None

    @property
    def data_uri(self) -> str:
        """Data URI for direct HTML inline img tags."""
        if self.base64_data:
            return f"data:image/png;base64,{self.base64_data}"
        return ""


def _apply_neutral_theme(fig: plt.Figure, ax: plt.Axes) -> None:
    """Apply transparent background and mid-tone neutral colors for light/dark contrast."""
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    ax.tick_params(colors=COLOR_MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(COLOR_SPINE)
        spine.set_alpha(0.5)
    ax.grid(True, color=COLOR_GRID, alpha=0.18, linestyle="--", linewidth=0.6)


def _encode_fig(fig: plt.Figure, output_path: Optional[Path] = None, dpi: int = 120) -> tuple[str, str]:
    """Save PNG to disk (if output_path given) and return (base64_png, clean_theme_adaptive_svg)."""
    # 1. Export SVG
    svg_buf = io.BytesIO()
    fig.savefig(svg_buf, format="svg", transparent=True, bbox_inches="tight")
    svg_buf.seek(0)
    raw_svg = svg_buf.getvalue().decode("utf-8")

    # Clean SVG: strip XML header and DOCTYPE so it embeds inline seamlessly
    start_svg = raw_svg.find("<svg")
    clean_svg = raw_svg[start_svg:] if start_svg != -1 else raw_svg

    # Replace hardcoded neutral colors with CSS custom properties so charts adapt dynamically
    clean_svg = clean_svg.replace(COLOR_TEXT, "var(--text-main)")
    clean_svg = clean_svg.replace(COLOR_MUTED, "var(--text-muted)")
    clean_svg = clean_svg.replace(COLOR_GRID, "var(--border)")
    clean_svg = clean_svg.replace(COLOR_SPINE, "var(--border)")
    clean_svg = clean_svg.replace("#131b2e", "transparent")

    # 2. Export PNG
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format="png", transparent=True, bbox_inches="tight", dpi=dpi)
    png_buf.seek(0)
    png_bytes = png_buf.getvalue()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(png_bytes)

    plt.close(fig)
    b64_png = base64.b64encode(png_bytes).decode("utf-8")
    return b64_png, clean_svg


def generate_index_technicals_chart(
    df: Optional[pd.DataFrame],
    symbol: str,
    name: str,
    as_of_date: str,
    lookback_bars: int = 130,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate index price with 20, 50, and 200 DMA over trailing lookback window."""
    chart_key = f"{symbol.strip('^').lower()}_technicals"
    title = f"{name} ({symbol}) — Trend & Moving Averages"
    caption = f"{name} closing price vs. 20-day, 50-day, and 200-day moving averages as of {as_of_date}."

    if df is None or df.empty or "Close" not in df.columns:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Price data unavailable.")

    try:
        # Use full history up to as_of_date so that rolling 20, 50, and 200 DMAs are fully populated across display window
        sub = df[df.index <= pd.to_datetime(as_of_date)].copy()
        if len(sub) < 20:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient historical bars.")

        close = sub["Close"]
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()

        # Display window
        disp_sub = sub.tail(lookback_bars)
        disp_idx = disp_sub.index
        disp_close = close.loc[disp_idx]
        disp_sma20 = sma20.loc[disp_idx]
        disp_sma50 = sma50.loc[disp_idx]
        disp_sma200 = sma200.loc[disp_idx]

        fig, ax = plt.subplots(figsize=(9, 4.2))
        _apply_neutral_theme(fig, ax)

        ax.plot(disp_idx, disp_close, label=f"Price ({disp_close.iloc[-1]:,.1f})", color=COLOR_BLUE, linewidth=1.8)
        if len(disp_sma20.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma20, label=f"20 DMA ({disp_sma20.dropna().iloc[-1]:,.1f})", color=COLOR_YELLOW, linewidth=1.2, linestyle="--")
        if len(disp_sma50.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma50, label=f"50 DMA ({disp_sma50.dropna().iloc[-1]:,.1f})", color="#60a5fa", linewidth=1.4)
        if len(disp_sma200.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma200, label=f"200 DMA ({disp_sma200.dropna().iloc[-1]:,.1f})", color=COLOR_RED, linewidth=1.4)

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y" if lookback_bars > 180 else "%b %d"))
        fig.autofmt_xdate(rotation=20)
        ax.legend(loc="upper left", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate technical chart for %s: %s", symbol, e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_sector_performance_chart(
    sector_rows: List[SectorPerformanceRow],
    period_name: str,
    as_of_date: str,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate horizontal ranked bar chart of the 11 SPDR sectors."""
    chart_key = "sector_performance"
    title = f"SPDR Sector Performance ({period_name})"
    caption = f"Ranked return across all 11 SPDR sectors for the {period_name.lower()} period ending {as_of_date}."

    if not sector_rows:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Sector data unavailable.")

    try:
        # Sort ascending for horizontal bar chart (best on top)
        sorted_rows = sorted(sector_rows, key=lambda r: r.pct_change)
        names = [f"{r.symbol} ({r.name[:18]})" for r in sorted_rows]
        vals = [r.pct_change for r in sorted_rows]
        colors = [COLOR_GREEN if v >= 0 else COLOR_RED for v in vals]

        fig, ax = plt.subplots(figsize=(8.5, 4.6))
        _apply_neutral_theme(fig, ax)

        bars = ax.barh(names, vals, color=colors, height=0.65, alpha=0.9)
        ax.axvline(0, color=COLOR_MUTED, linewidth=0.8, linestyle="--")

        # Value labels on bars
        for bar, val in zip(bars, vals):
            sign = "+" if val >= 0 else ""
            txt = f" {sign}{val:.2f}% "
            ha = "left" if val >= 0 else "right"
            x_pos = val
            ax.text(x_pos, bar.get_y() + bar.get_height() / 2, txt, va="center", ha=ha, color=COLOR_TEXT, fontsize=8, fontweight="bold")

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Period Return (%)", color=COLOR_MUTED, fontsize=9)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.1f}%"))

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate sector chart: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_breadth_trend_chart(
    equity_bars: Dict[str, pd.DataFrame],
    as_of_date: str,
    lookback_bars: int = 130,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate line chart of % of S&P 500 stocks above 50 DMA and 200 DMA over time."""
    chart_key = "breadth_history"
    title = "S&P 500 Market Breadth Over Time (% Above 50 & 200 DMA)"
    caption = f"Trailing history of S&P 500 constituent breadth with 40% (bearish) and 60% (bullish) reference boundaries as of {as_of_date}."

    if not equity_bars:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Constituent bars unavailable.")

    try:
        curr_dt = pd.to_datetime(as_of_date)
        closes = {}
        for sym, df in equity_bars.items():
            if df is not None and not df.empty and "Close" in df.columns:
                sub = df[df.index <= curr_dt]["Close"]
                if len(sub) >= 200:
                    closes[sym] = sub

        if len(closes) < 50:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient constituent coverage.")

        df_close = pd.DataFrame(closes).sort_index().ffill().dropna(how="all")
        if len(df_close) < 50:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient trading history.")

        sma50 = df_close.rolling(50, min_periods=50).mean()
        sma200 = df_close.rolling(200, min_periods=200).mean()

        pct_above_50 = (df_close > sma50).mean(axis=1) * 100.0
        pct_above_200 = (df_close > sma200).mean(axis=1) * 100.0

        disp_idx = df_close.index[-lookback_bars:]
        s50 = pct_above_50.loc[disp_idx]
        s200 = pct_above_200.loc[disp_idx]

        fig, ax = plt.subplots(figsize=(9, 4.2))
        _apply_neutral_theme(fig, ax)

        ax.plot(disp_idx, s50, label=f"% Above 50 DMA ({s50.iloc[-1]:.1f}%)", color=COLOR_BLUE, linewidth=1.8)
        ax.plot(disp_idx, s200, label=f"% Above 200 DMA ({s200.iloc[-1]:.1f}%)", color=COLOR_GREEN, linewidth=1.8)

        # Bullish/Bearish boundary zones
        ax.axhline(60, color=COLOR_GREEN, linestyle="--", linewidth=1.0, alpha=0.6, label="Bullish Threshold (60%)")
        ax.axhline(40, color=COLOR_RED, linestyle="--", linewidth=1.0, alpha=0.6, label="Bearish Threshold (40%)")
        ax.axhspan(60, 100, color=COLOR_GREEN, alpha=0.04)
        ax.axhspan(0, 40, color=COLOR_RED, alpha=0.04)

        ax.set_ylim(0, 100)
        ax.set_ylabel("% of Stocks", color=COLOR_MUTED, fontsize=9)
        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d" if lookback_bars < 180 else "%b %Y"))
        fig.autofmt_xdate(rotation=20)
        ax.legend(loc="lower left", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate breadth trend chart: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_vix_chart(
    vix_df: Optional[pd.DataFrame],
    as_of_date: str,
    lookback_bars: int = 130,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate VIX volatility index line chart with 20 and 25 regime boundaries."""
    chart_key = "vix_regime"
    title = "Cboe Volatility Index (VIX) — Regime & Risk Thresholds"
    caption = f"Trailing implied volatility levels with 20 (cautious) and 25 (elevated fear) boundaries as of {as_of_date}."

    if vix_df is None or vix_df.empty or "Close" not in vix_df.columns:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="VIX data unavailable.")

    try:
        curr_dt = pd.to_datetime(as_of_date)
        sub = vix_df[vix_df.index <= curr_dt].tail(lookback_bars)
        if len(sub) < 5:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient VIX history.")

        idx = sub.index
        vix_vals = sub["Close"]

        fig, ax = plt.subplots(figsize=(9, 4.0))
        _apply_neutral_theme(fig, ax)

        ax.plot(idx, vix_vals, color=COLOR_AMBER, linewidth=1.8, label=f"VIX Close ({vix_vals.iloc[-1]:.2f})")
        ax.axhline(20, color=COLOR_YELLOW, linestyle="--", linewidth=1.0, alpha=0.7, label="Cautious Boundary (20.0)")
        ax.axhline(25, color=COLOR_RED, linestyle="--", linewidth=1.0, alpha=0.7, label="Elevated Fear (25.0)")
        ax.axhspan(0, 16.5, color=COLOR_GREEN, alpha=0.04)
        ax.axhspan(20, 25, color=COLOR_YELLOW, alpha=0.05)
        ax.axhspan(25, max(35, float(vix_vals.max()) + 2), color=COLOR_RED, alpha=0.06)

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.set_ylabel("Index Level", color=COLOR_MUTED, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d" if lookback_bars < 180 else "%b %Y"))
        fig.autofmt_xdate(rotation=20)
        ax.legend(loc="upper right", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate VIX chart: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_rates_curve_chart(
    fred_provider: Any,
    as_of_date: str,
    lookback_days: int = 180,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate 10Y Treasury yield and 2s10s yield curve spread charts."""
    chart_key = "rates_yield_curve"
    title = "US Treasury 10Y Yield & 2s10s Curve Spread"
    caption = f"Benchmark 10-year Treasury yield and 2s10s term structure spread as of {as_of_date}."

    if fred_provider is None:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="FRED provider unavailable.")

    try:
        curr_dt = pd.to_datetime(as_of_date)
        start_dt = curr_dt - pd.Timedelta(days=lookback_days)

        y10_raw = fred_provider.fetch_series("DGS10", as_of_date=as_of_date) if hasattr(fred_provider, "fetch_series") else None
        s2s10_raw = fred_provider.fetch_series("T10Y2Y", as_of_date=as_of_date) if hasattr(fred_provider, "fetch_series") else None

        if y10_raw is None or s2s10_raw is None or y10_raw.empty or s2s10_raw.empty:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Treasury yield series empty.")

        y10_df = y10_raw[y10_raw["date"] >= start_dt].copy()
        s2s10_df = s2s10_raw[s2s10_raw["date"] >= start_dt].copy()

        if y10_df.empty or s2s10_df.empty:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient Treasury rate observations.")

        y10_dates = pd.to_datetime(y10_df["date"])
        y10_vals = y10_df["value"].values

        s2s10_dates = pd.to_datetime(s2s10_df["date"])
        s2s10_vals = s2s10_df["value"].values

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 4.8), sharex=True, gridspec_kw={"height_ratios": [1.2, 1.0]})
        _apply_neutral_theme(fig, ax1)
        _apply_neutral_theme(fig, ax2)

        # 10Y Yield
        ax1.plot(y10_dates, y10_vals, color=COLOR_BLUE, linewidth=1.8, label=f"10Y Yield ({y10_vals[-1]:.2f}%)")
        ax1.set_ylabel("Yield (%)", color=COLOR_MUTED, fontsize=8)
        ax1.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=8)
        ax1.legend(loc="upper left", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8)

        # 2s10s Spread in bps
        spread_bps = s2s10_vals * 100.0
        ax2.plot(s2s10_dates, spread_bps, color=COLOR_PURPLE, linewidth=1.6, label=f"2s10s Spread ({spread_bps[-1]:+.0f} bps)")
        ax2.axhline(0, color=COLOR_RED, linestyle="--", linewidth=1.0, alpha=0.7, label="Inversion Line (0 bps)")
        ax2.fill_between(s2s10_dates, spread_bps, 0, where=(spread_bps < 0), color=COLOR_RED, alpha=0.15)
        ax2.set_ylabel("Spread (bps)", color=COLOR_MUTED, fontsize=8)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d" if lookback_days < 200 else "%b %Y"))
        fig.autofmt_xdate(rotation=20)
        ax2.legend(loc="lower left", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8)

        fig.subplots_adjust(hspace=0.15)
        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate rates curve chart: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_movers_chart(
    gainers: List[MoverItem],
    losers: List[MoverItem],
    period_name: str,
    as_of_date: str,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate horizontal bar chart of top 5 gainers and bottom 5 losers."""
    chart_key = f"{period_name.lower()}_movers"
    title = f"Top Movers ({period_name}) — Top 5 Gainers & Bottom 5 Losers"
    caption = f"Extreme movers across S&P 500 and Nasdaq-100 constituents for the {period_name.lower()} period ending {as_of_date}."

    if not gainers and not losers:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Movers data unavailable.")

    try:
        # Losers bottom to top (worst at bottom), then gainers
        items = list(reversed(losers)) + gainers
        labels = [f"{m.symbol} ({m.name[:16]})" for m in items]
        vals = [m.pct_change for m in items]
        colors = [COLOR_GREEN if v >= 0 else COLOR_RED for v in vals]

        fig, ax = plt.subplots(figsize=(8.5, 4.4))
        _apply_neutral_theme(fig, ax)

        bars = ax.barh(labels, vals, color=colors, height=0.62, alpha=0.9)
        ax.axvline(0, color=COLOR_MUTED, linewidth=0.8, linestyle="--")

        for bar, val in zip(bars, vals):
            sign = "+" if val >= 0 else ""
            txt = f" {sign}{val:.2f}% "
            ha = "left" if val >= 0 else "right"
            ax.text(val, bar.get_y() + bar.get_height() / 2, txt, va="center", ha=ha, color=COLOR_TEXT, fontsize=8, fontweight="bold")

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Return (%)", color=COLOR_MUTED, fontsize=9)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.1f}%"))

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate movers chart: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_all_report_charts(
    period: PeriodInfo,
    core_bars: Dict[str, pd.DataFrame],
    equity_bars: Dict[str, pd.DataFrame],
    sector_rows: List[SectorPerformanceRow],
    gainers: List[MoverItem],
    losers: List[MoverItem],
    fred_provider: Optional[Any] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, GeneratedChart]:
    """Generate all 6 required report charts, saving PNG files and generating base64 strings."""
    charts_dict: Dict[str, GeneratedChart] = {}
    charts_dir = output_dir / f"{period.session_date}_charts" if output_dir else None

    lookback_bars = 252 if period.report_type == "monthly" else 130

    # 1. S&P 500 Technicals
    p_spx = (charts_dir / "spx_technicals.png") if charts_dir else None
    c_spx = generate_index_technicals_chart(
        df=core_bars.get("^GSPC"),
        symbol="^GSPC",
        name="S&P 500",
        as_of_date=period.session_date,
        lookback_bars=lookback_bars,
        output_path=p_spx,
    )
    charts_dict["spx_technicals"] = c_spx

    # 2. Nasdaq-100 Technicals
    p_ndx = (charts_dir / "ndx_technicals.png") if charts_dir else None
    c_ndx = generate_index_technicals_chart(
        df=core_bars.get("^NDX"),
        symbol="^NDX",
        name="Nasdaq-100",
        as_of_date=period.session_date,
        lookback_bars=lookback_bars,
        output_path=p_ndx,
    )
    charts_dict["ndx_technicals"] = c_ndx

    # 3. Sector Performance
    p_sec = (charts_dir / "sector_performance.png") if charts_dir else None
    c_sec = generate_sector_performance_chart(
        sector_rows=sector_rows,
        period_name=period.report_type.capitalize(),
        as_of_date=period.session_date,
        output_path=p_sec,
    )
    charts_dict["sector_performance"] = c_sec

    # 4. Market Breadth Over Time
    p_br = (charts_dir / "breadth_history.png") if charts_dir else None
    c_br = generate_breadth_trend_chart(
        equity_bars=equity_bars,
        as_of_date=period.session_date,
        lookback_bars=lookback_bars,
        output_path=p_br,
    )
    charts_dict["breadth_history"] = c_br

    # 5. VIX Regime
    p_vix = (charts_dir / "vix_regime.png") if charts_dir else None
    c_vix = generate_vix_chart(
        vix_df=core_bars.get("^VIX"),
        as_of_date=period.session_date,
        lookback_bars=lookback_bars,
        output_path=p_vix,
    )
    charts_dict["vix_regime"] = c_vix

    # 6. Rates & Curve Spread
    p_rates = (charts_dir / "rates_yield_curve.png") if charts_dir else None
    c_rates = generate_rates_curve_chart(
        fred_provider=fred_provider,
        as_of_date=period.session_date,
        lookback_days=180 if period.report_type != "monthly" else 365,
        output_path=p_rates,
    )
    charts_dict["rates_yield_curve"] = c_rates

    # 7. Top Movers
    p_mov = (charts_dir / f"{period.report_type}_movers.png") if charts_dir else None
    c_mov = generate_movers_chart(
        gainers=gainers,
        losers=losers,
        period_name=period.report_type.capitalize(),
        as_of_date=period.session_date,
        output_path=p_mov,
    )
    charts_dict["top_movers"] = c_mov

    logger.info("Generated %d chart visualizations in %s", len(charts_dict), charts_dir)
    return charts_dict
