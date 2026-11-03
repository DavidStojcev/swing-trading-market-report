"""Market breadth calculation module for US equity universe (S&P 500 constituents).

Computes:
- % of stocks above 20-day, 50-day, and 200-day moving averages
- Advance / Decline counts, ratio, cumulative A/D line, and confirmation/divergence vs S&P 500
- New 52-week highs vs new 52-week lows and net new highs
- % of stocks with positive return over the period
- Equal-weight (RSP) vs cap-weight (SPY) leadership divergence
- McClellan Oscillator (19-EMA minus 39-EMA of daily net advances)
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config.settings import BreadthConfig
from data.calendar import PeriodInfo
from data.constituents import Constituent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BreadthMetric:
    """Individual breadth metric with current value, previous period value, and delta."""
    current: float
    previous: float
    change: float
    unit: str = "%"


@dataclass
class MarketBreadthResult:
    """Consolidated market breadth results across moving averages, A/D, highs/lows, and leadership."""
    as_of_date: str
    prev_date: str
    total_constituents: int
    included_constituents: int
    coverage_pct: float
    coverage_warning: Optional[str] = None

    # Moving Average Breadth
    pct_above_20_dma: BreadthMetric = field(default_factory=lambda: BreadthMetric(0.0, 0.0, 0.0))
    pct_above_50_dma: BreadthMetric = field(default_factory=lambda: BreadthMetric(0.0, 0.0, 0.0))
    pct_above_200_dma: BreadthMetric = field(default_factory=lambda: BreadthMetric(0.0, 0.0, 0.0))

    # Advance / Decline
    advancers: int = 0
    decliners: int = 0
    unchanged: int = 0
    net_advancers: int = 0
    ad_ratio: float = 1.0
    prev_ad_ratio: float = 1.0
    delta_ad_ratio: float = 0.0
    cumulative_ad: float = 0.0
    prev_cumulative_ad: float = 0.0
    delta_cumulative_ad: float = 0.0
    cum_ad_trend: str = "Neutral"
    ad_confirmation: str = "Neutral"

    # 52-Week Highs / Lows
    new_52w_highs: int = 0
    new_52w_lows: int = 0
    net_new_highs: int = 0
    prev_net_new_highs: int = 0
    delta_net_new_highs: int = 0

    # Period Participation
    pct_positive_return: BreadthMetric = field(default_factory=lambda: BreadthMetric(0.0, 0.0, 0.0))

    # Equal-weight vs Cap-weight Divergence (RSP vs SPY)
    spy_return_pct: float = 0.0
    rsp_return_pct: float = 0.0
    leadership_spread_pct: float = 0.0
    narrow_leadership: bool = False
    leadership_status: str = "Balanced Leadership"

    # McClellan Oscillator
    mcclellan_oscillator: Optional[float] = None
    prev_mcclellan_oscillator: Optional[float] = None
    delta_mcclellan_oscillator: Optional[float] = None
    mcclellan_status: Optional[str] = None

    # Plain-language summary
    breadth_read: str = ""


def _extract_period_return(
    df: Optional[pd.DataFrame],
    curr_dt: pd.Timestamp,
    base_dt: pd.Timestamp,
) -> float:
    """Extract percentage return for an ETF or index between base_dt and curr_dt."""
    if df is None or df.empty or "Close" not in df.columns:
        return 0.0

    sub = df[df.index <= curr_dt]
    if sub.empty:
        return 0.0

    curr_close = float(sub["Close"].iloc[-1])

    # Find close at or before base_dt
    base_sub = df[df.index <= base_dt]
    if not base_sub.empty:
        base_close = float(base_sub["Close"].iloc[-1])
    elif len(sub) >= 2:
        base_close = float(sub["Close"].iloc[-2])
    else:
        base_close = curr_close

    if base_close <= 0:
        return 0.0
    return ((curr_close - base_close) / base_close) * 100.0


def compute_market_breadth(
    equity_bars: Dict[str, pd.DataFrame],
    constituents: List[Constituent],
    period: PeriodInfo,
    cfg: BreadthConfig,
    spy_df: Optional[pd.DataFrame] = None,
    rsp_df: Optional[pd.DataFrame] = None,
    spx_return_pct: Optional[float] = None,
    prior_snapshot: Optional[Dict[str, Any]] = None,
) -> MarketBreadthResult:
    """Compute comprehensive market breadth metrics across S&P 500 constituents using vectorized pandas."""
    # 1. Resolve S&P 500 universe
    sp500_tickers = [c.symbol for c in constituents if c.in_sp500]
    if not sp500_tickers:
        sp500_tickers = [c.symbol for c in constituents]
    total_constituents = len(sp500_tickers)

    curr_dt = pd.to_datetime(period.session_date)
    base_dt = pd.to_datetime(period.baseline_date)
    prev_end_dt = pd.to_datetime(period.prev_period_end)
    prev_base_dt = pd.to_datetime(period.prev_baseline_date)

    # 2. Filter constituents with sufficient history (>= min_history_bars, default 252)
    min_bars = cfg.min_history_bars
    closes_dict: Dict[str, pd.Series] = {}
    insufficient_tickers: List[str] = []

    for sym in sp500_tickers:
        df = equity_bars.get(sym)
        if df is None or df.empty or "Close" not in df.columns:
            insufficient_tickers.append(sym)
            continue

        # Filter up to current evaluation date
        sub = df[df.index <= curr_dt]
        if len(sub) < min_bars:
            insufficient_tickers.append(sym)
            continue

        closes_dict[sym] = sub["Close"]

    if insufficient_tickers:
        logger.info(
            "Skipped %d tickers with insufficient history (< %d bars): %s",
            len(insufficient_tickers),
            min_bars,
            insufficient_tickers[:5],
        )

    included_count = len(closes_dict)
    coverage_pct = (included_count / total_constituents * 100.0) if total_constituents > 0 else 0.0
    coverage_warning = None
    if coverage_pct < cfg.min_coverage_pct:
        coverage_warning = (
            f"Universe coverage ({coverage_pct:.1f}%) is below minimum threshold of "
            f"{cfg.min_coverage_pct:.1f}% ({included_count}/{total_constituents} tickers)."
        )
        logger.warning(coverage_warning)

    # If insufficient data across universe, return empty fallback
    if included_count == 0:
        return MarketBreadthResult(
            as_of_date=period.session_date,
            prev_date=period.prev_period_end,
            total_constituents=total_constituents,
            included_constituents=0,
            coverage_pct=0.0,
            coverage_warning="No constituent bar data available.",
            breadth_read="Market breadth data unavailable due to missing historical bars.",
        )

    # 3. Construct aligned wide DataFrame (Dates x Tickers)
    df_close = pd.DataFrame(closes_dict).sort_index().ffill().dropna(how="all")
    if len(df_close) < 20:
        return MarketBreadthResult(
            as_of_date=period.session_date,
            prev_date=period.prev_period_end,
            total_constituents=total_constituents,
            included_constituents=included_count,
            coverage_pct=coverage_pct,
            coverage_warning="Insufficient trading sessions in price matrix.",
            breadth_read="Market breadth data unavailable (insufficient trading days).",
        )

    # Determine index positions for current and previous period evaluation
    curr_pos = -1

    # Find previous period evaluation position in df_close
    prev_pos = None
    sub_prev = df_close[df_close.index <= prev_end_dt]
    if not sub_prev.empty:
        prev_pos = len(sub_prev) - 1
    if prev_pos is None or prev_pos < 0 or prev_pos >= (len(df_close) - 1):
        prev_pos = max(0, len(df_close) - 2)

    # Find baseline position for period return
    base_pos = None
    sub_base = df_close[df_close.index <= base_dt]
    if not sub_base.empty:
        base_pos = len(sub_base) - 1
    if base_pos is None or base_pos < 0 or base_pos >= len(df_close):
        base_pos = max(0, len(df_close) - 2)

    # Find prior baseline position
    prev_base_pos = None
    sub_prev_base = df_close[df_close.index <= prev_base_dt]
    if not sub_prev_base.empty:
        prev_base_pos = len(sub_prev_base) - 1
    if prev_base_pos is None or prev_base_pos < 0 or prev_base_pos >= len(df_close):
        prev_base_pos = max(0, prev_pos - 1)

    # 4. Moving Average Breadth (% of stocks above 20, 50, 200 DMA)
    sma20 = df_close.rolling(20, min_periods=20).mean()
    sma50 = df_close.rolling(50, min_periods=50).mean()
    sma200 = df_close.rolling(200, min_periods=200).mean()

    curr_row = df_close.iloc[curr_pos]
    prev_row = df_close.iloc[prev_pos]

    # Check against prior snapshot if available
    prior_breadth = prior_snapshot.get("breadth", {}) if prior_snapshot else {}

    # 20 DMA
    p20_curr = float((curr_row > sma20.iloc[curr_pos]).mean() * 100.0)
    if "pct_above_20_dma" in prior_breadth:
        p20_prev = float(prior_breadth["pct_above_20_dma"])
    else:
        p20_prev = float((prev_row > sma20.iloc[prev_pos]).mean() * 100.0)
    pct_above_20 = BreadthMetric(current=p20_curr, previous=p20_prev, change=p20_curr - p20_prev)

    # 50 DMA
    p50_curr = float((curr_row > sma50.iloc[curr_pos]).mean() * 100.0)
    if "pct_above_50_dma" in prior_breadth:
        p50_prev = float(prior_breadth["pct_above_50_dma"])
    else:
        p50_prev = float((prev_row > sma50.iloc[prev_pos]).mean() * 100.0)
    pct_above_50 = BreadthMetric(current=p50_curr, previous=p50_prev, change=p50_curr - p50_prev)

    # 200 DMA
    p200_curr = float((curr_row > sma200.iloc[curr_pos]).mean() * 100.0)
    if "pct_above_200_dma" in prior_breadth:
        p200_prev = float(prior_breadth["pct_above_200_dma"])
    else:
        p200_prev = float((prev_row > sma200.iloc[prev_pos]).mean() * 100.0)
    pct_above_200 = BreadthMetric(current=p200_curr, previous=p200_prev, change=p200_curr - p200_prev)

    # 5. Advance / Decline
    base_row = df_close.iloc[base_pos]
    # Guard against zero base price
    base_valid = base_row.replace(0, np.nan)
    period_returns = (curr_row - base_valid) / base_valid

    advancers = int((period_returns > 0.0).sum())
    decliners = int((period_returns < 0.0).sum())
    unchanged = int((period_returns == 0.0).sum())
    ad_ratio = float(advancers / decliners) if decliners > 0 else float(advancers)

    # Prior A/D ratio
    if "ad_ratio" in prior_breadth:
        prev_ad_ratio = float(prior_breadth["ad_ratio"])
    else:
        prev_base_row = df_close.iloc[prev_base_pos].replace(0, np.nan)
        prev_returns = (prev_row - prev_base_row) / prev_base_row
        prev_adv = int((prev_returns > 0.0).sum())
        prev_dec = int((prev_returns < 0.0).sum())
        prev_ad_ratio = float(prev_adv / prev_dec) if prev_dec > 0 else float(prev_adv)
    delta_ad_ratio = ad_ratio - prev_ad_ratio

    # Cumulative A/D Line (Daily advances - decliners across history)
    daily_diffs = df_close.diff()
    daily_adv = (daily_diffs > 0).astype(int).sum(axis=1)
    daily_dec = (daily_diffs < 0).astype(int).sum(axis=1)
    daily_net = daily_adv - daily_dec
    cum_ad_series = daily_net.cumsum()

    curr_cum_ad = float(cum_ad_series.iloc[curr_pos])
    if "cumulative_ad" in prior_breadth:
        prev_cum_ad = float(prior_breadth["cumulative_ad"])
    else:
        prev_cum_ad = float(cum_ad_series.iloc[prev_pos])
    delta_cum_ad = curr_cum_ad - prev_cum_ad

    # Actionable breadth trend vs 50-day moving average of A/D Line
    if len(cum_ad_series) >= 50:
        cum_ad_sma50 = cum_ad_series.rolling(50, min_periods=30).mean()
        curr_ad_ma = float(cum_ad_sma50.iloc[curr_pos])
        cum_ad_trend = "Above 50-day MA (Expanding)" if curr_cum_ad >= curr_ad_ma else "Below 50-day MA (Deteriorating)"
    else:
        cum_ad_trend = "Steady"

    net_advancers = advancers - decliners

    # Index return for confirmation/divergence
    if spx_return_pct is not None:
        idx_ret = spx_return_pct
    else:
        idx_ret = _extract_period_return(spy_df, curr_dt, base_dt)

    broad_up = (advancers > decliners) or (advancers == decliners and delta_cum_ad > 0)
    broad_down = (decliners > advancers) or (advancers == decliners and delta_cum_ad < 0)

    if idx_ret > 0 and broad_up:
        ad_confirmation = "Confirming Rally"
    elif idx_ret < 0 and broad_down:
        ad_confirmation = "Confirming Decline"
    elif idx_ret > 0 and broad_down:
        ad_confirmation = "Bearish Divergence"
    elif idx_ret < 0 and broad_up:
        ad_confirmation = "Bullish Divergence"
    else:
        ad_confirmation = "Neutral"

    # 6. New 52-Week Highs vs New 52-Week Lows (trailing 252 bars)
    # Check if we have at least 252 bars in the matrix
    if len(df_close) >= 252:
        curr_idx_pos = len(df_close) - 1
        if period.report_type in ("weekly", "monthly") and base_pos < curr_idx_pos - 1:
            rolling_max = df_close.rolling(252, min_periods=200).max()
            rolling_min = df_close.rolling(252, min_periods=200).min()
            p_slice = slice(base_pos + 1, curr_idx_pos + 1)
            hit_high = (df_close.iloc[p_slice] >= rolling_max.iloc[p_slice]).any(axis=0)
            hit_low = (df_close.iloc[p_slice] <= rolling_min.iloc[p_slice]).any(axis=0)
            new_highs = int(hit_high.sum())
            new_lows = int(hit_low.sum())
            net_highs = new_highs - new_lows

            prev_slice = slice(prev_base_pos + 1, prev_pos + 1)
            if prev_base_pos + 1 <= prev_pos:
                p_hit_high = (df_close.iloc[prev_slice] >= rolling_max.iloc[prev_slice]).any(axis=0)
                p_hit_low = (df_close.iloc[prev_slice] <= rolling_min.iloc[prev_slice]).any(axis=0)
                prev_net_highs = int(p_hit_high.sum()) - int(p_hit_low.sum())
            elif "net_new_highs" in prior_breadth:
                prev_net_highs = int(prior_breadth["net_new_highs"])
            else:
                prev_net_highs = 0
        else:
            trailing_window = df_close.iloc[curr_pos - 251 : curr_pos]
            prior_max = trailing_window.max()
            prior_min = trailing_window.min()
            new_highs = int((curr_row >= prior_max).sum())
            new_lows = int((curr_row <= prior_min).sum())
            net_highs = new_highs - new_lows

            if prev_pos >= 251:
                prev_window = df_close.iloc[prev_pos - 251 : prev_pos]
                prev_max = prev_window.max()
                prev_min = prev_window.min()
                p_nh = int((prev_row >= prev_max).sum())
                p_nl = int((prev_row <= prev_min).sum())
                prev_net_highs = p_nh - p_nl
            elif "net_new_highs" in prior_breadth:
                prev_net_highs = int(prior_breadth["net_new_highs"])
            else:
                prev_net_highs = 0
    else:
        new_highs = 0
        new_lows = 0
        net_highs = 0
        prev_net_highs = 0

    delta_net_highs = net_highs - prev_net_highs

    # 7. % of stocks with positive return
    pct_pos_curr = float(advancers / included_count * 100.0) if included_count > 0 else 0.0
    if "pct_positive_return" in prior_breadth:
        pct_pos_prev = float(prior_breadth["pct_positive_return"])
    else:
        pct_pos_prev = float(prev_adv / included_count * 100.0) if "prev_adv" in locals() and included_count > 0 else pct_pos_curr
    pct_positive = BreadthMetric(current=pct_pos_curr, previous=pct_pos_prev, change=pct_pos_curr - pct_pos_prev)

    # 8. Equal-Weight (RSP) vs Cap-Weight (SPY) Divergence
    spy_ret = _extract_period_return(spy_df, curr_dt, base_dt)
    rsp_ret = _extract_period_return(rsp_df, curr_dt, base_dt)
    leadership_spread = spy_ret - rsp_ret
    margin_key = f"narrow_leadership_margin_{period.report_type.lower()}_pct"
    margin = cfg.scoring.thresholds.get(
        margin_key,
        cfg.scoring.thresholds.get("narrow_leadership_margin_pct", 1.0),
    )

    narrow_leadership = bool(leadership_spread >= margin and spy_ret > 0)
    if narrow_leadership:
        leadership_status = (
            f"Narrow Leadership: Cap-weight SPY ({spy_ret:+.2f}%) outperforming equal-weight RSP "
            f"({rsp_ret:+.2f}%) by {leadership_spread:+.2f}%"
        )
    elif leadership_spread <= -margin:
        leadership_status = (
            f"Broad Leadership: Equal-weight RSP ({rsp_ret:+.2f}%) outperforming cap-weight SPY "
            f"({spy_ret:+.2f}%) by {abs(leadership_spread):+.2f}%"
        )
    else:
        leadership_status = (
            f"Balanced Leadership: SPY ({spy_ret:+.2f}%) vs RSP ({rsp_ret:+.2f}%), spread {leadership_spread:+.2f}%"
        )

    # 9. McClellan Oscillator (optional)
    mcclellan_val = None
    prev_mcclellan_val = None
    delta_mcclellan_val = None
    mcclellan_status = None

    if cfg.mcclellan_enabled and len(daily_net) >= 39:
        ema19 = daily_net.ewm(span=19, adjust=False).mean()
        ema39 = daily_net.ewm(span=39, adjust=False).mean()
        osc = ema19 - ema39
        mcclellan_val = float(osc.iloc[curr_pos])

        if "mcclellan_oscillator" in prior_breadth:
            prev_mcclellan_val = float(prior_breadth["mcclellan_oscillator"])
        else:
            prev_mcclellan_val = float(osc.iloc[prev_pos])
        delta_mcclellan_val = mcclellan_val - prev_mcclellan_val

        if mcclellan_val >= 100.0:
            mcclellan_status = "Overbought (+100+)"
        elif mcclellan_val <= -100.0:
            mcclellan_status = "Oversold (-100-)"
        elif mcclellan_val > 0.0:
            mcclellan_status = "Bullish Momentum"
        elif mcclellan_val < 0.0:
            mcclellan_status = "Bearish Momentum"
        else:
            mcclellan_status = "Neutral"

    # 10. Plain-language Breadth Read sentence
    if narrow_leadership:
        breadth_read = (
            f"Narrow leadership: Cap-weight SPY ({spy_ret:+.2f}%) outpaced equal-weight RSP ({rsp_ret:+.2f}%), "
            f"with {p50_curr:.1f}% of stocks above their 50 DMA."
        )
    elif ad_confirmation == "Bearish Divergence":
        breadth_read = (
            f"Divergence warning: Index advanced while market breadth deteriorated, with more decliners than advancers "
            f"({advancers} up vs {decliners} down, A/D ratio {ad_ratio:.2f})."
        )
    elif ad_confirmation == "Bullish Divergence":
        breadth_read = (
            f"Resilient participation (Bullish Divergence): Broad market advanced ({advancers} up vs {decliners} down, "
            f"A/D ratio {ad_ratio:.2f}) despite cap-weighted index dip, with {p50_curr:.1f}% above their 50 DMA."
        )
    elif p50_curr >= 60.0 and advancers >= decliners:
        breadth_read = (
            f"Broad participation: {p50_curr:.1f}% of stocks above their 50 DMA, with advancers outpacing decliners "
            f"(A/D ratio {ad_ratio:.2f})."
        )
    elif p50_curr < 40.0 and net_highs < 0:
        breadth_read = (
            f"Widespread weakness: Only {p50_curr:.1f}% of stocks above their 50 DMA and net new lows dominant "
            f"({net_highs:+d} net highs)."
        )
    else:
        breadth_read = (
            f"Mixed participation: {p50_curr:.1f}% of stocks above their 50 DMA and {p200_curr:.1f}% above their 200 DMA, "
            f"with A/D ratio at {ad_ratio:.2f}."
        )

    return MarketBreadthResult(
        as_of_date=period.session_date,
        prev_date=period.prev_period_end,
        total_constituents=total_constituents,
        included_constituents=included_count,
        coverage_pct=coverage_pct,
        coverage_warning=coverage_warning,
        pct_above_20_dma=pct_above_20,
        pct_above_50_dma=pct_above_50,
        pct_above_200_dma=pct_above_200,
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        net_advancers=net_advancers,
        ad_ratio=ad_ratio,
        prev_ad_ratio=prev_ad_ratio,
        delta_ad_ratio=delta_ad_ratio,
        cumulative_ad=curr_cum_ad,
        prev_cumulative_ad=prev_cum_ad,
        delta_cumulative_ad=delta_cum_ad,
        cum_ad_trend=cum_ad_trend,
        ad_confirmation=ad_confirmation,
        new_52w_highs=new_highs,
        new_52w_lows=new_lows,
        net_new_highs=net_highs,
        prev_net_new_highs=prev_net_highs,
        delta_net_new_highs=delta_net_highs,
        pct_positive_return=pct_positive,
        spy_return_pct=spy_ret,
        rsp_return_pct=rsp_ret,
        leadership_spread_pct=leadership_spread,
        narrow_leadership=narrow_leadership,
        leadership_status=leadership_status,
        mcclellan_oscillator=mcclellan_val,
        prev_mcclellan_oscillator=prev_mcclellan_val,
        delta_mcclellan_oscillator=delta_mcclellan_val,
        mcclellan_status=mcclellan_status,
        breadth_read=breadth_read,
    )
