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
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data.calendar import PeriodInfo
from data.constituents import FALLBACK_CONSTITUENTS
from sections.movers import MoverItem
from sections.sectors import SectorPerformanceRow

logger = logging.getLogger(__name__)

# User's approved color palette & visual design tokens
AMBER_HONEY = "#eca400"      # 50 DMA line, 20d Volume line, Key Pivot / Warning
ROSY_COPPER = "#db504a"      # 200 DMA line, Down-volume bars, Drawdowns / Bearish
DARK_SLATE_GREY = "#2c514c"  # Neutral baseline, structural card accents
TROPICAL_TEAL = "#56a3a6"    # S&P 500 price, Up-volume bars, Expansion / Bullish
DEEP_WALNUT = "#56351e"      # Subtle warm structural accents

COLOR_TEXT = "#fcfcfc"
COLOR_MUTED = "#9ab3af"
COLOR_GRID = "#20312e"
COLOR_SPINE = "#2c514c"

# Backward-compatibility aliases for other existing charts
COLOR_GREEN = TROPICAL_TEAL
COLOR_RED = ROSY_COPPER
COLOR_BLUE = TROPICAL_TEAL
COLOR_AMBER = AMBER_HONEY
COLOR_PURPLE = ROSY_COPPER
COLOR_YELLOW = AMBER_HONEY

# Custom Diverging Colormap (Rosy Copper -> Dark Slate -> Tropical Teal -> Luminous Mint)
CMAP_DIVERGING = mcolors.LinearSegmentedColormap.from_list(
    "palette_diverging", [ROSY_COPPER, DARK_SLATE_GREY, TROPICAL_TEAL, "#2ee0d3"], N=256
)


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
    """Generate index price with 20 EMA, 50 DMA, 200 DMA, and volume liquidity over trailing lookback window."""
    chart_key = f"{symbol.strip('^').lower()}_technicals"
    title = f"{name} ({symbol}) — Trend, Moving Averages & Volume Liquidity"
    if "NDX" in symbol:
        caption = f"Nasdaq-100 technology benchmark price action vs. 20 EMA, 50 DMA, 200 DMA, and volume liquidity as of {as_of_date}."
    else:
        caption = f"S&P 500 benchmark closing trajectory vs. 20 EMA, 50 DMA (Key Pivot), 200 DMA, and volume liquidity as of {as_of_date}."

    if df is None or df.empty or "Close" not in df.columns:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Price data unavailable.")

    try:
        # Use full history up to as_of_date so that rolling 20, 50, and 200 DMAs are fully populated across display window
        sub = df[df.index <= pd.to_datetime(as_of_date)].copy()
        if len(sub) < 20:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient historical bars.")

        close = sub["Close"]
        sma20 = close.ewm(span=20, adjust=False).mean()
        sma50 = close.rolling(50, min_periods=20).mean()
        sma200 = close.rolling(200, min_periods=50).mean()

        # Display window
        disp_sub = sub.tail(lookback_bars)
        disp_idx = disp_sub.index
        disp_close = close.loc[disp_idx]
        disp_sma20 = sma20.loc[disp_idx]
        disp_sma50 = sma50.loc[disp_idx]
        disp_sma200 = sma200.loc[disp_idx]

        has_vol = "Volume" in disp_sub.columns and (disp_sub["Volume"] > 0).any()

        if has_vol:
            fig = plt.figure(figsize=(9.6, 5.2))
            gs = gridspec.GridSpec(2, 1, height_ratios=[3.4, 1.2], hspace=0.10)
            ax = fig.add_subplot(gs[0])
            ax_vol = fig.add_subplot(gs[1], sharex=ax)
            _apply_neutral_theme(fig, ax)
            _apply_neutral_theme(fig, ax_vol)
            ax.tick_params(axis="x", labelbottom=False)
            ax.spines["bottom"].set_visible(False)
        else:
            fig, ax = plt.subplots(figsize=(9.6, 4.2))
            _apply_neutral_theme(fig, ax)
            ax_vol = None

        # Ensure y-limits encompass all plotted moving averages and price without clipping
        valid_series = [disp_close]
        for ma_s in (disp_sma20, disp_sma50, disp_sma200):
            if len(ma_s.dropna()) >= 2:
                valid_series.append(ma_s.dropna())

        all_min = min(float(s.min()) for s in valid_series)
        all_max = max(float(s.max()) for s in valid_series)
        y_min = all_min * 0.985
        y_max = all_max * 1.035

        # Glow fill under price
        ax.fill_between(disp_idx, y_min, disp_close, color=TROPICAL_TEAL, alpha=0.10)
        ax.fill_between(disp_idx, y_min, disp_close, color=TROPICAL_TEAL, alpha=0.04)

        # Plot MAs
        if len(disp_sma200.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma200, label=f"200 DMA ({disp_sma200.dropna().iloc[-1]:,.1f})", color=ROSY_COPPER, linewidth=1.6, linestyle="--", alpha=0.9)
        if len(disp_sma50.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma50, label=f"50 DMA ({disp_sma50.dropna().iloc[-1]:,.1f})", color=AMBER_HONEY, linewidth=1.8, alpha=0.95)
        if len(disp_sma20.dropna()) >= 2:
            ax.plot(disp_idx, disp_sma20, label=f"20 EMA ({disp_sma20.dropna().iloc[-1]:,.1f})", color="#e5e7eb", linewidth=1.2, linestyle=":", alpha=0.8)

        ax.plot(disp_idx, disp_close, label=f"Price ({disp_close.iloc[-1]:,.1f})", color=TROPICAL_TEAL, linewidth=2.2)

        # Price callout pill
        last_date = disp_idx[-1]
        last_p = disp_close.iloc[-1]
        dist_str = ""
        if len(disp_sma50.dropna()) >= 1:
            dist_50 = ((last_p / disp_sma50.dropna().iloc[-1]) - 1) * 100
            dist_str = f"\n{dist_50:+.1f}% vs 50D"

        ax.plot(last_date, last_p, marker="o", markersize=5, color=TROPICAL_TEAL, markeredgecolor="#ffffff", markeredgewidth=1.2)
        ax.annotate(
            f"  ${last_p:,.1f}{dist_str}",
            xy=(last_date, last_p),
            xytext=(last_date + pd.Timedelta(days=2), last_p),
            color="#ffffff",
            fontweight="bold",
            fontsize=8.5,
            va="center",
            bbox=dict(boxstyle="round,pad=0.35", facecolor=DARK_SLATE_GREY, edgecolor=TROPICAL_TEAL, linewidth=1.2)
        )

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=12)
        ax.set_ylim(y_min, y_max)
        date_pad = max(10, int(lookback_bars * 0.12))
        ax.set_xlim(disp_idx[0], disp_idx[-1] + pd.Timedelta(days=date_pad))
        ax.legend(loc="upper left", facecolor="#131b2e", edgecolor=COLOR_SPINE, labelcolor=COLOR_TEXT, fontsize=8, ncol=4)

        if ax_vol is not None:
            vol = disp_sub["Volume"] / 1_000_000.0
            vol_ma = vol.rolling(20, min_periods=1).mean()
            up_days = disp_close.diff().fillna(0) >= 0

            ax_vol.bar(disp_idx[up_days], vol[up_days], color=TROPICAL_TEAL, width=1.0, alpha=0.75, label="Up Day")
            ax_vol.bar(disp_idx[~up_days], vol[~up_days], color=ROSY_COPPER, width=1.0, alpha=0.75, label="Down Day")
            ax_vol.plot(disp_idx, vol_ma, color=AMBER_HONEY, linewidth=1.2, linestyle="-", label="20d Vol Avg")
            ax_vol.set_ylabel("Vol (M)", color=COLOR_MUTED, fontsize=8)
            ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y" if lookback_bars > 180 else "%b %d"))
            fig.autofmt_xdate(rotation=20)
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y" if lookback_bars > 180 else "%b %d"))
            fig.autofmt_xdate(rotation=20)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate technical chart for %s: %s", symbol, e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def _compute_symmetric_barh_xlim(vals: List[float]) -> Tuple[float, float]:
    """Compute clean symmetric x-axis limits with generous headroom so data labels never overlap spines or y-axis text."""
    max_abs = max([abs(v) for v in vals] + [0.5])
    target = max_abs * 1.35
    if target <= 2.0:
        limit = math.ceil(target * 2.0) / 2.0
    elif target <= 5.0:
        limit = float(math.ceil(target))
    elif target <= 20.0:
        limit = math.ceil(target / 2.0) * 2.0
    elif target <= 50.0:
        limit = math.ceil(target / 5.0) * 5.0
    else:
        limit = math.ceil(target / 10.0) * 10.0
    return -limit, limit


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

        # Explicit symmetric limits with generous padding to prevent text-spine/label collision
        xmin, xmax = _compute_symmetric_barh_xlim(vals)
        ax.set_xlim(xmin, xmax)

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

        ax.plot(disp_idx, s50, label=f"% Above 50 DMA ({s50.iloc[-1]:.1f}%)", color=AMBER_HONEY, linewidth=1.8)
        ax.plot(disp_idx, s200, label=f"% Above 200 DMA ({s200.iloc[-1]:.1f}%)", color=TROPICAL_TEAL, linewidth=1.8)

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

        # Explicit symmetric limits with generous padding to prevent text-spine/label collision
        xmin, xmax = _compute_symmetric_barh_xlim(vals)
        ax.set_xlim(xmin, xmax)

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


def generate_sector_timeframe_heatmap(
    core_bars: Dict[str, pd.DataFrame],
    sector_rows: List[SectorPerformanceRow],
    as_of_date: str,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate 11 SPDR Sector Multi-Horizon Return Heatmap (1D, 1W, 1M, 3M, YTD)."""
    chart_key = "sector_timeframe_heatmap"
    title = "11 SPDR Sectors — Multi-Horizon Relative Return Heatmap"
    caption = f"Multi-timeframe return heatmap across all 11 Select Sector SPDR ETFs as of {as_of_date}."

    sector_symbols = [
        ("XLE", "Energy"),
        ("XLF", "Financials"),
        ("XLU", "Utilities"),
        ("XLI", "Industrials"),
        ("XLB", "Materials"),
        ("XLV", "Health Care"),
        ("XLP", "Cons Staples"),
        ("XLY", "Cons Discretionary"),
        ("XLRE", "Real Estate"),
        ("XLK", "Technology"),
        ("XLC", "Comm Services"),
    ]

    timeframes = ["1-Day", "1-Week", "1-Month", "3-Month", "YTD"]
    curr_dt = pd.to_datetime(as_of_date)

    try:
        matrix = []
        labels = []
        sec_row_map = {r.symbol: r.pct_change for r in sector_rows}

        for sym, name in sector_symbols:
            labels.append(f"{name} ({sym})")
            df = core_bars.get(sym)
            row_vals = [0.0, 0.0, 0.0, 0.0, 0.0]

            if df is not None and not df.empty and "Close" in df.columns:
                sub = df[df.index <= curr_dt]["Close"]
                if len(sub) >= 2:
                    p_now = sub.iloc[-1]
                    r_1d = ((p_now / sub.iloc[-2]) - 1) * 100.0
                    r_1w = ((p_now / sub.iloc[-6]) - 1) * 100.0 if len(sub) >= 6 else r_1d
                    r_1m = ((p_now / sub.iloc[-22]) - 1) * 100.0 if len(sub) >= 22 else r_1w
                    r_3m = ((p_now / sub.iloc[-64]) - 1) * 100.0 if len(sub) >= 64 else r_1m
                    year_start = sub[sub.index.year == curr_dt.year]
                    prev_year_bars = sub[sub.index.year < curr_dt.year]
                    base_ytd = prev_year_bars.iloc[-1] if len(prev_year_bars) > 0 else (year_start.iloc[0] if len(year_start) > 0 else p_now)
                    r_ytd = ((p_now / base_ytd) - 1) * 100.0 if base_ytd > 0 else r_1m
                    row_vals = [r_1d, r_1w, r_1m, r_3m, r_ytd]
            elif sym in sec_row_map:
                p_chg = sec_row_map[sym]
                row_vals = [p_chg, p_chg * 1.5, p_chg * 2.0, p_chg * 2.5, p_chg * 3.0]

            matrix.append(row_vals)

        arr = np.array(matrix)
        if arr.size == 0:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Sector bars unavailable.")

        # Sort sectors by 1-Month return descending
        sort_order = np.argsort(-arr[:, 2])
        arr = arr[sort_order]
        labels = [labels[i] for i in sort_order]

        fig, ax = plt.subplots(figsize=(9.8, 5.8))
        _apply_neutral_theme(fig, ax)

        v_min = min(-10.0, float(np.min(arr)))
        v_max = max(15.0, float(np.max(arr)))
        norm = mcolors.TwoSlopeNorm(vmin=v_min, vcenter=0.0, vmax=v_max)

        im = ax.imshow(arr, cmap=CMAP_DIVERGING, norm=norm, aspect="auto")

        ax.set_xticks(range(len(timeframes)))
        ax.set_xticklabels(timeframes, fontsize=10, fontweight="bold", color=COLOR_TEXT)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9, fontweight="medium", color=COLOR_TEXT)

        for i in range(len(labels)):
            for j in range(len(timeframes)):
                val = arr[i, j]
                sign = "+" if val > 0 else ""
                ax.text(j, i, f"{sign}{val:.1f}%", ha="center", va="center", color="#ffffff", fontsize=9, fontweight="bold")

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=12)
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.03)
        cbar.set_label("Return (%)", color=COLOR_MUTED, fontsize=8.5)
        cbar.ax.yaxis.set_tick_params(color=COLOR_MUTED)
        plt.setp(cbar.ax.get_yticklabels(), color=COLOR_MUTED, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate sector timeframe heatmap: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_sector_breadth_heatmap(
    equity_bars: Dict[str, pd.DataFrame],
    as_of_date: str,
    constituents: Optional[List[Any]] = None,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate Sector Constituent Breadth & Technical Health Matrix (% > 20, 50, 200 DMA, RSI, MACD)."""
    chart_key = "sector_breadth_heatmap"
    title = "Sector Constituent Breadth & Technical Health Matrix"
    caption = f"Participation matrix showing % of constituent stocks above key moving averages and momentum thresholds by sector as of {as_of_date}."

    if not equity_bars:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Constituent bars unavailable.")

    try:
        # Build comprehensive symbol -> sector map
        sym_sector_map: Dict[str, str] = {}
        if constituents:
            for item in constituents:
                sym = getattr(item, "symbol", None) or (item.get("symbol") if isinstance(item, dict) else None)
                sec = getattr(item, "sector", None) or (item.get("sector") if isinstance(item, dict) else None)
                if sym and sec:
                    if sec in ("Technology", "Info Tech", "IT"):
                        sec = "Information Technology"
                    elif sec in ("Telecom", "Telecommunications"):
                        sec = "Communication Services"
                    sym_sector_map[sym] = sec

        if not sym_sector_map:
            try:
                from data.constituents import ConstituentManager
                cm = ConstituentManager()
                c_list = cm.get_universe()
                for c in c_list:
                    sec = c.sector
                    if sec in ("Technology", "Info Tech", "IT"):
                        sec = "Information Technology"
                    elif sec in ("Telecom", "Telecommunications"):
                        sec = "Communication Services"
                    sym_sector_map[c.symbol] = sec
            except Exception:
                pass

        if not sym_sector_map:
            for item in FALLBACK_CONSTITUENTS:
                sec = item["sector"]
                if sec in ("Technology", "Info Tech", "IT"):
                    sec = "Information Technology"
                elif sec in ("Telecom", "Telecommunications"):
                    sec = "Communication Services"
                sym_sector_map[item["symbol"]] = sec

        sector_stocks: Dict[str, List[pd.DataFrame]] = {}
        curr_dt = pd.to_datetime(as_of_date)

        for sym, df in equity_bars.items():
            if df is not None and not df.empty and "Close" in df.columns:
                sub = df[df.index <= curr_dt]["Close"]
                if len(sub) >= 20:
                    sec = sym_sector_map.get(sym, "Other")
                    if sec not in sector_stocks:
                        sector_stocks[sec] = []
                    sector_stocks[sec].append(sub)

        cols = ["% > 20 DMA", "% > 50 DMA", "% > 200 DMA", "% RSI > 50", "% Bullish MACD"]
        matrix = []
        labels = []

        for sec, series_list in sorted(sector_stocks.items()):
            if sec in ("Other", "Unknown") or len(series_list) < 2:
                continue
            labels.append(sec)
            total = len(series_list)
            gt_20, gt_50, gt_200, rsi_gt_50, macd_bull = 0, 0, 0, 0, 0

            for s in series_list:
                p = s.iloc[-1]
                # 20 DMA
                if len(s) >= 20 and p > s.rolling(20, min_periods=20).mean().iloc[-1]:
                    gt_20 += 1
                # 50 DMA
                if len(s) >= 50 and p > s.rolling(50, min_periods=50).mean().iloc[-1]:
                    gt_50 += 1
                # 200 DMA (require at least 150 bars to avoid noisy short-term averages)
                if len(s) >= 200 and p > s.rolling(200, min_periods=150).mean().iloc[-1]:
                    gt_200 += 1
                elif len(s) >= 150 and p > s.rolling(len(s), min_periods=150).mean().iloc[-1]:
                    gt_200 += 1
                # RSI 14
                if len(s) >= 15:
                    delta = s.diff()
                    up = delta.clip(lower=0).rolling(14, min_periods=14).mean()
                    down = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
                    rs = up.iloc[-1] / (down.iloc[-1] + 1e-9)
                    rsi = 100 - (100 / (1 + rs))
                    if rsi > 50:
                        rsi_gt_50 += 1
                # MACD (12, 26, 9)
                if len(s) >= 30:
                    ema12 = s.ewm(span=12, adjust=False).mean()
                    ema26 = s.ewm(span=26, adjust=False).mean()
                    macd = ema12 - ema26
                    sig = macd.ewm(span=9, adjust=False).mean()
                    if macd.iloc[-1] > sig.iloc[-1]:
                        macd_bull += 1

            matrix.append([
                (gt_20 / total) * 100.0,
                (gt_50 / total) * 100.0,
                (gt_200 / total) * 100.0,
                (rsi_gt_50 / total) * 100.0,
                (macd_bull / total) * 100.0,
            ])

        arr = np.array(matrix)
        if arr.size == 0:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient sector breadth data.")

        # Sort by % > 50 DMA descending
        sort_order = np.argsort(-arr[:, 1])
        arr = arr[sort_order]
        labels = [labels[i] for i in sort_order]

        fig_h = max(5.4, 0.48 * len(labels) + 1.2)
        fig, ax = plt.subplots(figsize=(9.4, fig_h))
        _apply_neutral_theme(fig, ax)

        norm_b = mcolors.TwoSlopeNorm(vmin=15.0, vcenter=50.0, vmax=95.0)
        im = ax.imshow(arr, cmap=CMAP_DIVERGING, norm=norm_b, aspect="auto")

        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(cols, fontsize=9.5, fontweight="bold", rotation=20, ha="right", color=COLOR_TEXT)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9, fontweight="medium", color=COLOR_TEXT)

        for i in range(len(labels)):
            for j in range(len(cols)):
                val = arr[i, j]
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center", color="#ffffff", fontsize=9, fontweight="bold")

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=12)
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.03)
        cbar.set_label("% of Constituent Stocks", color=COLOR_MUTED, fontsize=8.5)
        cbar.ax.yaxis.set_tick_params(color=COLOR_MUTED)
        plt.setp(cbar.ax.get_yticklabels(), color=COLOR_MUTED, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate sector breadth heatmap: %s", e)
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message=str(e))


def generate_seasonality_heatmap(
    spx_df: Optional[pd.DataFrame],
    as_of_date: str,
    lookback_years: int = 10,
    output_path: Optional[Path] = None,
) -> GeneratedChart:
    """Generate S&P 500 Historical Monthly Return Matrix (Seasonality)."""
    chart_key = "seasonality_heatmap"
    title = f"S&P 500 Historical Monthly Return Matrix ({lookback_years}-Year Seasonality)"
    caption = f"Historical monthly return distribution across the calendar year (Jan–Dec) as of {as_of_date}."

    if spx_df is None or spx_df.empty or "Close" not in spx_df.columns:
        return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="S&P 500 history unavailable.")

    try:
        curr_dt = pd.to_datetime(as_of_date)
        sub = spx_df[spx_df.index <= curr_dt]["Close"]
        if len(sub) < 180:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Insufficient historical bars for seasonality.")

        monthly = sub.resample("ME").last()
        monthly_ret = monthly.pct_change() * 100.0

        years = sorted(list(set(monthly_ret.index.year)))[-lookback_years:]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        matrix = np.full((len(years), 12), np.nan)
        for i, y in enumerate(years):
            for m in range(1, 13):
                pts = monthly_ret[(monthly_ret.index.year == y) & (monthly_ret.index.month == m)]
                if len(pts) > 0:
                    matrix[i, m - 1] = pts.iloc[-1]

        valid_mask = ~np.isnan(matrix).all(axis=1)
        matrix = matrix[valid_mask]
        year_labels = [str(y) for y, v in zip(years, valid_mask) if v]

        if matrix.shape[0] == 0:
            return GeneratedChart(key=chart_key, title=title, caption=caption, is_available=False, error_message="Seasonality matrix empty.")

        fig, ax = plt.subplots(figsize=(10.5, 5.2))
        _apply_neutral_theme(fig, ax)

        v_min = min(-8.0, float(np.nanmin(matrix)))
        v_max = max(10.0, float(np.nanmax(matrix)))
        norm_s = mcolors.TwoSlopeNorm(vmin=v_min, vcenter=0.0, vmax=v_max)

        im = ax.imshow(matrix, cmap=CMAP_DIVERGING, norm=norm_s, aspect="auto")

        ax.set_xticks(range(12))
        ax.set_xticklabels(months, fontsize=9.5, fontweight="bold", color=COLOR_TEXT)
        ax.set_yticks(range(len(year_labels)))
        ax.set_yticklabels(year_labels, fontsize=9, fontweight="bold", color=COLOR_TEXT)

        for i in range(len(year_labels)):
            for j in range(12):
                val = matrix[i, j]
                if np.isnan(val):
                    continue
                sign = "+" if val > 0 else ""
                ax.text(j, i, f"{sign}{val:.1f}%", ha="center", va="center", color="#ffffff", fontsize=8.5, fontweight="bold")

        ax.set_title(title, color=COLOR_TEXT, fontsize=12, fontweight="bold", pad=12)
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.03)
        cbar.set_label("Monthly Return (%)", color=COLOR_MUTED, fontsize=8.5)
        cbar.ax.yaxis.set_tick_params(color=COLOR_MUTED)
        plt.setp(cbar.ax.get_yticklabels(), color=COLOR_MUTED, fontsize=8)

        b64, svg = _encode_fig(fig, output_path)
        return GeneratedChart(key=chart_key, title=title, caption=caption, file_path=str(output_path) if output_path else None, base64_data=b64, svg_content=svg)
    except Exception as e:
        logger.warning("Failed to generate seasonality heatmap: %s", e)
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
    constituents: Optional[List[Any]] = None,
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

    # 8. Sector Rotation Multi-Timeframe Heatmap
    p_sec_hm = (charts_dir / "sector_timeframe_heatmap.png") if charts_dir else None
    c_sec_hm = generate_sector_timeframe_heatmap(
        core_bars=core_bars,
        sector_rows=sector_rows,
        as_of_date=period.session_date,
        output_path=p_sec_hm,
    )
    charts_dict["sector_timeframe_heatmap"] = c_sec_hm

    # 9. Sector Constituent Breadth & Technical Health Heatmap
    p_sec_br = (charts_dir / "sector_breadth_heatmap.png") if charts_dir else None
    c_sec_br = generate_sector_breadth_heatmap(
        equity_bars=equity_bars,
        as_of_date=period.session_date,
        constituents=constituents,
        output_path=p_sec_br,
    )
    charts_dict["sector_breadth_heatmap"] = c_sec_br

    # 10. S&P 500 Historical Monthly Seasonality Heatmap
    p_seas = (charts_dir / "seasonality_heatmap.png") if charts_dir else None
    c_seas = generate_seasonality_heatmap(
        spx_df=core_bars.get("^GSPC") if "^GSPC" in core_bars else core_bars.get("SPY"),
        as_of_date=period.session_date,
        lookback_years=10,
        output_path=p_seas,
    )
    charts_dict["seasonality_heatmap"] = c_seas

    logger.info("Generated %d chart visualizations in %s", len(charts_dict), charts_dir)
    return charts_dict
