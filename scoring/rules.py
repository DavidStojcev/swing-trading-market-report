"""Trend scoring rules and vote generation for technical and macro indicators."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from config.settings import BreadthScoringConfig, MacroScoringConfig, ScoringConfig
from indicators.engine import TechnicalSnapshot


@dataclass(frozen=True)
class IndicatorVote:
    """Individual vote or gradient score from an indicator."""
    rule_name: str
    condition: str
    vote: float               # +1.0, 0.0, -1.0 or continuous gradient in [-1.0, +1.0]
    weight: float
    weighted_vote: float
    interpretation: str
    category: str = "general"
    is_direction_based: bool = False


def linear_gradient(val: float, low: float, neutral: float, high: float) -> float:
    """Clamp and linearly interpolate val onto [-1.0, +1.0] without hard cliffs.
    
    If low < high (ascending: higher is more bullish):
        val <= low -> -1.0
        val == neutral -> 0.0
        val >= high -> +1.0
    If low > high (descending: lower is more bullish, e.g. VIX, credit spreads):
        val >= low -> -1.0
        val == neutral -> 0.0
        val <= high -> +1.0
    """
    if low < high:
        if val <= low:
            return -1.0
        elif val >= high:
            return 1.0
        elif val < neutral:
            return (val - neutral) / (neutral - low) if neutral > low else 0.0
        else:
            return (val - neutral) / (high - neutral) if high > neutral else 0.0
    else:
        if val >= low:
            return -1.0
        elif val <= high:
            return 1.0
        elif val > neutral:
            return -(val - neutral) / (low - neutral) if low > neutral else 0.0
        else:
            return (neutral - val) / (neutral - high) if neutral > high else 0.0


def evaluate_technical_votes(
    snapshot: TechnicalSnapshot,
    scoring_cfg: ScoringConfig,
) -> List[IndicatorVote]:
    """Evaluate indicator voting rules for a technical snapshot (e.g. S&P 500)."""
    weights = scoring_cfg.weights
    votes: List[IndicatorVote] = []

    # 1. Price vs 50 DMA
    w_p50 = weights.get("price_above_50_dma", 1.0)
    if snapshot.price > snapshot.dma_50:
        v_p50 = 1
        interp = f"Price ({snapshot.price:,.2f}) > 50 DMA ({snapshot.dma_50:,.2f}) [{snapshot.price_vs_dma50_pct:+.2f}%]"
    elif snapshot.price < snapshot.dma_50:
        v_p50 = -1
        interp = f"Price ({snapshot.price:,.2f}) < 50 DMA ({snapshot.dma_50:,.2f}) [{snapshot.price_vs_dma50_pct:+.2f}%]"
    else:
        v_p50 = 0
        interp = "Price equals 50 DMA"
    votes.append(IndicatorVote("Price vs 50 DMA", interp, v_p50, w_p50, v_p50 * w_p50, "Medium-term trend direction"))

    # 2. Price vs 200 DMA
    w_p200 = weights.get("price_above_200_dma", 1.0)
    if snapshot.price > snapshot.dma_200:
        v_p200 = 1
        interp = f"Price ({snapshot.price:,.2f}) > 200 DMA ({snapshot.dma_200:,.2f}) [{snapshot.price_vs_dma200_pct:+.2f}%]"
    elif snapshot.price < snapshot.dma_200:
        v_p200 = -1
        interp = f"Price ({snapshot.price:,.2f}) < 200 DMA ({snapshot.dma_200:,.2f}) [{snapshot.price_vs_dma200_pct:+.2f}%]"
    else:
        v_p200 = 0
        interp = "Price equals 200 DMA"
    votes.append(IndicatorVote("Price vs 200 DMA", interp, v_p200, w_p200, v_p200 * w_p200, "Long-term secular trend regime"))

    # 3. 50 DMA vs 200 DMA
    w_cross = weights.get("dma_50_above_200", 1.0)
    if snapshot.dma_50 > snapshot.dma_200:
        v_cross = 1
        interp = f"50 DMA ({snapshot.dma_50:,.2f}) > 200 DMA ({snapshot.dma_200:,.2f}) [Bullish Structure]"
    elif snapshot.dma_50 < snapshot.dma_200:
        v_cross = -1
        interp = f"50 DMA ({snapshot.dma_50:,.2f}) < 200 DMA ({snapshot.dma_200:,.2f}) [Bearish Structure]"
    else:
        v_cross = 0
        interp = "50 DMA equals 200 DMA"
    votes.append(IndicatorVote("50 DMA vs 200 DMA", interp, v_cross, w_cross, v_cross * w_cross, "Moving average cross alignment"))

    # 4. MACD vs Signal
    w_macd = weights.get("macd_bullish", 1.0)
    if snapshot.macd > snapshot.macd_signal:
        v_macd = 1
        interp = f"MACD ({snapshot.macd:.2f}) > Signal ({snapshot.macd_signal:.2f}) [Histogram: {snapshot.macd_hist:+.2f}]"
    elif snapshot.macd < snapshot.macd_signal:
        v_macd = -1
        interp = f"MACD ({snapshot.macd:.2f}) < Signal ({snapshot.macd_signal:.2f}) [Histogram: {snapshot.macd_hist:+.2f}]"
    else:
        v_macd = 0
        interp = "MACD equals Signal line"
    votes.append(IndicatorVote("MACD vs Signal", interp, v_macd, w_macd, v_macd * w_macd, "Short-to-medium term momentum"))

    return votes


def evaluate_vix_vote(
    vix_current: float,
    vix_previous: float,
    scoring_cfg: ScoringConfig,
) -> IndicatorVote:
    """Evaluate VIX voting rule aligned with volatility regime boundaries."""
    w_vix = scoring_cfg.weights.get("vix_bullish", 1.0)
    cautious_thresh = scoring_cfg.vix.get("cautious_threshold", 16.5)
    low_thresh = scoring_cfg.vix.get("low_threshold", 20.0)
    high_thresh = scoring_cfg.vix.get("high_threshold", 25.0)

    delta = vix_current - vix_previous
    falling = delta < 0
    rising = delta > 0

    if vix_current < cautious_thresh and delta <= 0.5:
        v_vix = 1
        interp = f"VIX at {vix_current:.2f} (< {cautious_thresh:.1f}) with contained volatility ({delta:+.2f}) [Normal / Risk-on]"
    elif vix_current < low_thresh and delta <= -0.5:
        v_vix = 1
        interp = f"VIX at {vix_current:.2f} (< {low_thresh:.0f}) and compressing ({delta:+.2f}) [Volatility receding / Risk-on]"
    elif (vix_current > high_thresh and rising) or (vix_current >= low_thresh and delta >= 1.5):
        v_vix = -1
        interp = f"VIX at {vix_current:.2f} (> {low_thresh:.0f}) and rising ({delta:+.2f}) [Elevated Volatility / Risk-off]"
    else:
        v_vix = 0
        if vix_current < low_thresh and abs(delta) < 0.5:
            interp = f"VIX at {vix_current:.2f} (steady, {delta:+.2f}) in Cautious regime [{cautious_thresh:.1f}–{low_thresh:.0f}; neutral vote]"
        elif vix_current < low_thresh and rising:
            interp = f"VIX at {vix_current:.2f} (< {low_thresh:.0f}) but rising ({delta:+.2f}) [Hedging demand building; neutral vote]"
        elif vix_current > high_thresh and falling:
            interp = f"VIX at {vix_current:.2f} (> {high_thresh:.0f}) but falling ({delta:+.2f}) [Volatility cooling / relief underway; neutral vote]"
        else:
            status_desc = "falling" if falling else ("rising" if rising else "flat")
            interp = f"VIX at {vix_current:.2f} ({status_desc}, {delta:+.2f}) within transition boundary [{low_thresh:.0f}–{high_thresh:.0f}]"

    return IndicatorVote("VIX Volatility Regime", interp, v_vix, w_vix, v_vix * w_vix, "Market implied volatility & fear index")


def evaluate_macro_votes(
    fed_rates: Any,
    cross_assets: List[Any],
    recent_releases: List[Any],
    macro_scoring_cfg: MacroScoringConfig,
    report_type: str = "daily",
) -> List[IndicatorVote]:
    """Evaluate optional macro voting rules for trend scoring.
    
    Rules:
    - 10Y yield rising sharply (> threshold): -1; falling: +1
    - Yield curve inverted: -1; normal: +1
    - Dollar rising sharply (> threshold): -1
    - Inflation surprise 'hot': -1; 'cool': +1
    - Jobs surprise 'strong' + inflation not hot: +1
    """
    if not macro_scoring_cfg.enabled:
        return []

    weights = macro_scoring_cfg.weights
    thresholds = macro_scoring_cfg.thresholds
    votes: List[IndicatorVote] = []
    rt = report_type.lower()

    # 1. 10Y Yield Shift
    w_10y = weights.get("yield_10y_surge", 0.5)
    if w_10y > 0 and fed_rates:
        thresh_bps = thresholds.get(
            f"yield_10y_surge_{rt}_bps",
            thresholds.get("yield_10y_surge_bps", 15.0),
        )
        thresh_pct = thresh_bps / 100.0  # Convert bps to percentage points
        y10_delta = getattr(fed_rates, "yield_10y_delta", 0.0)
        y10_curr = getattr(fed_rates, "yield_10y", 0.0)

        if y10_delta >= thresh_pct:
            v_10y = -1
            cond = f"10Y yield surged {y10_delta * 100:+.1f} bps to {y10_curr:.2f}% (above +{thresh_bps:.0f} bps threshold)"
        elif y10_delta <= -thresh_pct:
            v_10y = 1
            cond = f"10Y yield declined {y10_delta * 100:+.1f} bps to {y10_curr:.2f}% (below -{thresh_bps:.0f} bps threshold)"
        else:
            v_10y = 0
            cond = f"10Y yield moved {y10_delta * 100:+.1f} bps to {y10_curr:.2f}% (within ±{thresh_bps:.0f} bps boundary)"
        votes.append(IndicatorVote("10Y Treasury Yield Shift", cond, v_10y, w_10y, v_10y * w_10y, "Benchmark cost of capital and discount rate shift"))

    # 2. Yield Curve Inversion (2s10s)
    w_curve = weights.get("curve_inversion", 0.5)
    if w_curve > 0 and fed_rates:
        spread = getattr(fed_rates, "spread_2s10s", 0.0)
        is_inv = getattr(fed_rates, "is_inverted", False)
        if is_inv:
            v_curve = -1
            cond = f"Yield curve is Inverted (2s10s spread at {spread * 100:+.1f} bps) [Recession warning]"
        elif spread < 0.15:
            v_curve = 0
            cond = f"Yield curve is Flat / De-Inverting (2s10s spread at {spread * 100:+.1f} bps) [Cycle transition zone]"
        else:
            v_curve = 1
            cond = f"Yield curve is Positively Sloped (2s10s spread at {spread * 100:+.1f} bps) [Normal term structure]"
        votes.append(IndicatorVote("2s10s Yield Curve Shape", cond, v_curve, w_curve, v_curve * w_curve, "Term structure and economic cycle indicator"))

    # 3. Dollar Surge
    w_dxy = weights.get("dollar_surge", 0.5)
    if w_dxy > 0 and cross_assets:
        dxy_pct = 0.0
        dxy_item = next((ca for ca in cross_assets if "Dollar" in getattr(ca, "name", "") or "DX" in getattr(ca, "symbol", "")), None)
        if dxy_item:
            dxy_pct = getattr(dxy_item, "pct_change", 0.0)
            dxy_thresh = thresholds.get(
                f"dollar_surge_{rt}_pct",
                thresholds.get("dollar_surge_pct", 1.0),
            )
            if dxy_pct >= dxy_thresh:
                v_dxy = -1
                cond = f"US Dollar surged {dxy_pct:+.2f}% over period (above +{dxy_thresh:.2f}% threshold) [Tightening liquidity]"
            else:
                v_dxy = 0
                cond = f"US Dollar moved {dxy_pct:+.2f}% over period (subdued / non-disruptive)"
            votes.append(IndicatorVote("US Dollar Strength", cond, v_dxy, w_dxy, v_dxy * w_dxy, "Global liquidity and FX headwinds"))

    # 4. Inflation Surprise
    w_inf = weights.get("inflation_surprise", 0.5)
    has_hot_inflation = False
    if w_inf > 0:
        inf_events = [e for e in recent_releases if getattr(e, "category", "") == "inflation" and getattr(e, "surprise_flag", "") != "n/a"]
        hot_events = [e for e in inf_events if getattr(e, "surprise_flag", "") == "hot"]
        cool_events = [e for e in inf_events if getattr(e, "surprise_flag", "") == "cool"]

        if hot_events:
            has_hot_inflation = True
            v_inf = -1
            cond = f"Recent inflation release printed Hot ({hot_events[0].title})"
        elif cool_events:
            v_inf = 1
            cond = f"Recent inflation release printed Cool ({cool_events[0].title})"
        else:
            v_inf = 0
            cond = "Inflation releases in-line with expectations or no surprises"
        votes.append(IndicatorVote("Inflation Surprise", cond, v_inf, w_inf, v_inf * w_inf, "Price stability and interest rate path expectations"))

    # 5. Labor Surprise
    w_lab = weights.get("labor_surprise", 0.5)
    if w_lab > 0:
        lab_events = [e for e in recent_releases if getattr(e, "category", "") == "labor" and getattr(e, "surprise_flag", "") != "n/a"]
        strong_events = [e for e in lab_events if getattr(e, "surprise_flag", "") == "strong"]

        if strong_events and not has_hot_inflation:
            v_lab = 1
            cond = f"Strong labor prints ({strong_events[0].title}) with contained inflation pressures"
        elif any(getattr(e, "surprise_flag", "") == "weak" for e in lab_events):
            v_lab = -1
            cond = "Labor market prints missed expectations on the downside"
        else:
            v_lab = 0
            cond = "Labor data in-line with forecasts or no directional surprise"
        votes.append(IndicatorVote("Labor Market Strength", cond, v_lab, w_lab, v_lab * w_lab, "Employment growth and consumer spending support"))

    return votes


def evaluate_breadth_votes(
    breadth_result: Any,
    breadth_scoring_cfg: BreadthScoringConfig,
    report_type: str = "daily",
) -> List[IndicatorVote]:
    """Evaluate optional market breadth voting rules for trend scoring.
    
    Rules:
    - >60% of stocks above 50 DMA: +1; <40%: -1
    - >60% above 200 DMA: +1; <40%: -1
    - Net new highs positive and rising (or strongly positive): +1; strongly negative: -1
    - Narrow leadership flag: -1; broad leadership: +1
    - A/D line confirming rally or bullish divergence: +1; confirming decline or bearish divergence: -1
    """
    if not breadth_scoring_cfg.enabled or breadth_result is None:
        return []

    weights = breadth_scoring_cfg.weights
    thresholds = breadth_scoring_cfg.thresholds
    votes: List[IndicatorVote] = []
    rt = report_type.lower()

    ma_bull = thresholds.get("ma_bullish_pct", 60.0)
    ma_bear = thresholds.get("ma_bearish_pct", 40.0)

    # 1. Stocks above 50 DMA
    w_50 = weights.get("stocks_above_50_dma", 0.5)
    if w_50 > 0:
        p50 = getattr(getattr(breadth_result, "pct_above_50_dma", None), "current", 0.0)
        p50_chg = getattr(getattr(breadth_result, "pct_above_50_dma", None), "change", 0.0)
        if p50 >= ma_bull:
            v_50 = 1
            cond = f"{p50:.1f}% of stocks > 50 DMA (>= {ma_bull:.0f}% threshold, Δ {p50_chg:+.1f}%)"
        elif p50 <= ma_bear:
            v_50 = -1
            cond = f"{p50:.1f}% of stocks > 50 DMA (<= {ma_bear:.0f}% threshold, Δ {p50_chg:+.1f}%)"
        else:
            v_50 = 0
            cond = f"{p50:.1f}% of stocks > 50 DMA (neutral zone {ma_bear:.0f}–{ma_bull:.0f}%, Δ {p50_chg:+.1f}%)"
        votes.append(IndicatorVote("Breadth: % Above 50 DMA", cond, v_50, w_50, v_50 * w_50, "Medium-term broad market participation"))

    # 2. Stocks above 200 DMA
    w_200 = weights.get("stocks_above_200_dma", 0.5)
    if w_200 > 0:
        p200 = getattr(getattr(breadth_result, "pct_above_200_dma", None), "current", 0.0)
        p200_chg = getattr(getattr(breadth_result, "pct_above_200_dma", None), "change", 0.0)
        if p200 >= ma_bull:
            v_200 = 1
            cond = f"{p200:.1f}% of stocks > 200 DMA (>= {ma_bull:.0f}% threshold, Δ {p200_chg:+.1f}%)"
        elif p200 <= ma_bear:
            v_200 = -1
            cond = f"{p200:.1f}% of stocks > 200 DMA (<= {ma_bear:.0f}% threshold, Δ {p200_chg:+.1f}%)"
        else:
            v_200 = 0
            cond = f"{p200:.1f}% of stocks > 200 DMA (neutral zone {ma_bear:.0f}–{ma_bull:.0f}%, Δ {p200_chg:+.1f}%)"
        votes.append(IndicatorVote("Breadth: % Above 200 DMA", cond, v_200, w_200, v_200 * w_200, "Long-term structural market health"))

    # 3. Net New 52-Week Highs
    w_nh = weights.get("net_new_highs", 0.5)
    if w_nh > 0:
        net_nh = getattr(breadth_result, "net_new_highs", 0)
        d_nh = getattr(breadth_result, "delta_net_new_highs", 0)
        strongly_neg = thresholds.get("net_highs_strongly_negative", -10.0)
        if net_nh > 0 and d_nh >= 0:
            v_nh = 1
            cond = f"Net new 52W highs positive ({net_nh:+d}) and expanding (Δ {d_nh:+d})"
        elif net_nh >= 15:
            v_nh = 1
            cond = f"Net new 52W highs strongly positive ({net_nh:+d}, Δ {d_nh:+d})"
        elif net_nh <= strongly_neg:
            v_nh = -1
            cond = f"Net new 52W highs strongly negative ({net_nh:+d} <= {strongly_neg:.0f})"
        else:
            v_nh = 0
            cond = f"Net new 52W highs at {net_nh:+d} (Δ {d_nh:+d})"
        votes.append(IndicatorVote("Breadth: Net New Highs", cond, v_nh, w_nh, v_nh * w_nh, "Expansion of leadership list vs distribution"))

    # 4. Narrow Leadership (Equal-weight vs Cap-weight)
    w_lead = weights.get("narrow_leadership", 0.5)
    if w_lead > 0:
        narrow = getattr(breadth_result, "narrow_leadership", False)
        spread = getattr(breadth_result, "leadership_spread_pct", 0.0)
        margin = thresholds.get(
            f"narrow_leadership_margin_{rt}_pct",
            thresholds.get("narrow_leadership_margin_pct", 1.0),
        )
        if narrow:
            v_lead = -1
            cond = f"Narrow leadership warning: SPY outperforming RSP by {spread:+.2f}% (>= {margin:.2f}%)"
        elif spread <= -margin:
            v_lead = 1
            cond = f"Broad leadership confirmation: Equal-weight RSP outperforming SPY by {abs(spread):+.2f}%"
        else:
            v_lead = 0
            cond = f"Balanced leadership (SPY vs RSP spread {spread:+.2f}%)"
        votes.append(IndicatorVote("Breadth: Leadership Spread", cond, v_lead, w_lead, v_lead * w_lead, "Equal-weight RSP vs cap-weight SPY leadership breadth"))

    # 5. A/D Line Confirmation vs Divergence
    w_ad = weights.get("ad_line_confirmation", 0.5)
    if w_ad > 0:
        ad_conf = getattr(breadth_result, "ad_confirmation", "Neutral")
        ad_ratio = getattr(breadth_result, "ad_ratio", 1.0)
        delta_cad = getattr(breadth_result, "delta_cumulative_ad", 0.0)
        if ad_conf == "Confirming Rally":
            v_ad = 1
            cond = f"A/D line confirms rally ({ad_conf}, A/D ratio {ad_ratio:.2f}, net A/D Δ {delta_cad:+.0f})"
        elif ad_conf == "Bullish Divergence":
            v_ad = 1
            cond = f"Bullish A/D divergence: broad market advancing despite index dip ({ad_conf}, A/D ratio {ad_ratio:.2f})"
        elif ad_conf == "Confirming Decline":
            v_ad = -1
            cond = f"A/D line confirms selloff ({ad_conf}, A/D ratio {ad_ratio:.2f}, net A/D Δ {delta_cad:+.0f})"
        elif ad_conf == "Bearish Divergence":
            v_ad = -1
            cond = f"Bearish A/D divergence warning: index up while breadth negative ({ad_conf}, A/D ratio {ad_ratio:.2f})"
        else:
            v_ad = 0
            cond = f"A/D participation neutral ({ad_conf}, A/D ratio {ad_ratio:.2f})"
        votes.append(IndicatorVote("Breadth: A/D Line Confirmation", cond, v_ad, w_ad, v_ad * w_ad, "Advance/decline participation vs index direction"))

    return votes


# =====================================================================
# Stage 2: Categorical Gradient Scoring Rules
# =====================================================================

def evaluate_trend_price_category(
    spx_snapshot: Optional[TechnicalSnapshot],
    ndx_snapshot: Optional[TechnicalSnapshot] = None,
    scoring_cfg: Optional[ScoringConfig] = None,
) -> Tuple[float, List[IndicatorVote], str]:
    """Score Trend / Price category (30% weight) across S&P 500 and Nasdaq-100.
    
    Scores price vs 20/50/200 DMA, 50/200 cross, MACD, and ADX direction.
    Adopts the weaker of SPX and NDX overall score, highlighting any tech divergence.
    """
    if not spx_snapshot and not ndx_snapshot:
        return 0.0, [], ""

    votes: List[IndicatorVote] = []

    def _score_index_technicals(snap: TechnicalSnapshot, label: str) -> Tuple[float, List[IndicatorVote]]:
        idx_votes: List[IndicatorVote] = []

        # 1. Price vs 20 DMA
        s_p20 = linear_gradient(snap.price_vs_dma20_pct, -2.0, 0.0, 2.0)
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} Price vs 20 DMA",
            condition=f"{label} at {snap.price:,.1f} ({snap.price_vs_dma20_pct:+.2f}% vs 20 DMA {snap.dma_20:,.1f}) [Score: {s_p20:+.2f}]",
            vote=s_p20,
            weight=1.0,
            weighted_vote=s_p20,
            interpretation="Short-term trend direction and momentum hurdle",
            category="trend_price",
        ))

        # 2. Price vs 50 DMA
        s_p50 = linear_gradient(snap.price_vs_dma50_pct, -3.0, 0.0, 3.0)
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} Price vs 50 DMA",
            condition=f"{label} at {snap.price:,.1f} ({snap.price_vs_dma50_pct:+.2f}% vs 50 DMA {snap.dma_50:,.1f}) [Score: {s_p50:+.2f}]",
            vote=s_p50,
            weight=1.0,
            weighted_vote=s_p50,
            interpretation="Medium-term trend regime",
            category="trend_price",
        ))

        # 3. Price vs 200 DMA
        p200_pct = snap.price_vs_dma200_pct if getattr(snap, "dma_200", None) else snap.price_vs_dma50_pct
        s_p200 = linear_gradient(p200_pct, -5.0, 0.0, 5.0)
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} Price vs 200 DMA",
            condition=f"{label} at {snap.price:,.1f} ({p200_pct:+.2f}% vs 200 DMA {getattr(snap, 'dma_200', 0.0):,.1f}) [Score: {s_p200:+.2f}]",
            vote=s_p200,
            weight=1.0,
            weighted_vote=s_p200,
            interpretation="Long-term secular bull/bear boundary",
            category="trend_price",
        ))

        # 4. 50 vs 200 DMA Cross
        dma_50 = getattr(snap, "dma_50", 0.0)
        dma_200 = getattr(snap, "dma_200", 0.0)
        if dma_50 and dma_200:
            s_cross = 1.0 if dma_50 > dma_200 else (-1.0 if dma_50 < dma_200 else 0.0)
            cross_desc = "Golden Cross (50 > 200)" if s_cross > 0 else "Death Cross (50 < 200)"
        else:
            s_cross = 0.0
            cross_desc = "Neutral structure"
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} 50/200 DMA Cross",
            condition=f"{label} {cross_desc} [Score: {s_cross:+.1f}]",
            vote=s_cross,
            weight=1.0,
            weighted_vote=s_cross,
            interpretation="Moving average structural alignment",
            category="trend_price",
        ))

        # 5. MACD vs Signal
        if snap.macd > snap.macd_signal:
            s_macd = min(1.0, max(0.2, snap.macd_hist / 5.0)) if snap.macd_hist > 0 else 0.5
        elif snap.macd < snap.macd_signal:
            s_macd = max(-1.0, min(-0.2, snap.macd_hist / 5.0)) if snap.macd_hist < 0 else -0.5
        else:
            s_macd = 0.0
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} MACD vs Signal",
            condition=f"{label} MACD ({snap.macd:.2f}) {'above' if snap.macd >= snap.macd_signal else 'below'} Signal ({snap.macd_signal:.2f}) [Hist: {snap.macd_hist:+.2f}]",
            vote=s_macd,
            weight=1.0,
            weighted_vote=s_macd,
            interpretation="Momentum cycle and histogram acceleration",
            category="trend_price",
        ))

        # 6. ADX Direction
        if snap.adx >= 20.0:
            if snap.plus_di > snap.minus_di:
                s_adx = min(1.0, 0.5 + (snap.plus_di - snap.minus_di) / 40.0)
                adx_cond = f"{label} ADX at {snap.adx:.1f} (+DI {snap.plus_di:.1f} > -DI {snap.minus_di:.1f}) [Bullish Trend]"
            else:
                s_adx = max(-1.0, -0.5 - (snap.minus_di - snap.plus_di) / 40.0)
                adx_cond = f"{label} ADX at {snap.adx:.1f} (-DI {snap.minus_di:.1f} > +DI {snap.plus_di:.1f}) [Bearish Trend]"
        else:
            s_adx = 0.0
            adx_cond = f"{label} ADX at {snap.adx:.1f} (< 20 threshold) [Ranging / Non-trending]"
        idx_votes.append(IndicatorVote(
            rule_name=f"{label} ADX Trend Strength & Direction",
            condition=adx_cond,
            vote=s_adx,
            weight=1.0,
            weighted_vote=s_adx,
            interpretation="Directional trend velocity (+DI vs -DI)",
            category="trend_price",
        ))

        avg_score = sum(v.weighted_vote for v in idx_votes) / len(idx_votes) if idx_votes else 0.0
        return max(-1.0, min(1.0, avg_score)), idx_votes

    spx_score, spx_votes = _score_index_technicals(spx_snapshot, "S&P 500") if spx_snapshot else (0.0, [])
    ndx_score, ndx_votes = _score_index_technicals(ndx_snapshot, "Nasdaq-100") if ndx_snapshot else (spx_score, [])

    divergence_note = ""
    if spx_snapshot and ndx_snapshot:
        # Score both and use the weaker of the two plus a note if they diverge
        final_score = min(spx_score, ndx_score)
        if abs(spx_score - ndx_score) >= 0.20:
            weaker_name = "Nasdaq-100" if ndx_score < spx_score else "S&P 500"
            divergence_note = (
                f"Index Divergence: S&P 500 trend score is {spx_score:+.2f} while Nasdaq-100 is {ndx_score:+.2f}. "
                f"Adopting weaker score ({final_score:+.2f} via {weaker_name}) for conservative risk gating."
            )
        votes.extend(spx_votes)
        votes.extend(ndx_votes[:3])
    elif spx_snapshot:
        final_score = spx_score
        votes.extend(spx_votes)
    else:
        final_score = ndx_score
        votes.extend(ndx_votes)

    return final_score, votes, divergence_note


def evaluate_breadth_category(
    breadth_result: Any,
    breadth_scoring_cfg: Optional[BreadthScoringConfig] = None,
    report_type: str = "daily",
) -> Tuple[float, List[IndicatorVote], str]:
    """Score Market Breadth category (20% weight) using smooth linear gradients and category cap."""
    if breadth_result is None or not getattr(breadth_result, "is_available", True):
        return 0.0, [], "unavailable"

    votes: List[IndicatorVote] = []

    # 1. % Above 50 DMA (linear gradient: 40% = -1.0, 50% = 0.0, 60% = +1.0)
    p50 = getattr(getattr(breadth_result, "pct_above_50_dma", None), "current", 50.0)
    s_50 = linear_gradient(p50, 40.0, 50.0, 60.0)
    votes.append(IndicatorVote(
        rule_name="Breadth: % Above 50 DMA",
        condition=f"{p50:.1f}% stocks > 50 DMA (gradient score: {s_50:+.2f})",
        vote=s_50,
        weight=1.0,
        weighted_vote=s_50,
        interpretation="Intermediate-term market participation gradient",
        category="breadth",
    ))

    # 2. % Above 200 DMA (linear gradient: 40% = -1.0, 50% = 0.0, 60% = +1.0)
    p200 = getattr(getattr(breadth_result, "pct_above_200_dma", None), "current", 50.0)
    s_200 = linear_gradient(p200, 40.0, 50.0, 60.0)
    votes.append(IndicatorVote(
        rule_name="Breadth: % Above 200 DMA",
        condition=f"{p200:.1f}% stocks > 200 DMA (gradient score: {s_200:+.2f})",
        vote=s_200,
        weight=1.0,
        weighted_vote=s_200,
        interpretation="Secular market foundation breadth",
        category="breadth",
    ))

    # 3. Net New 52-Week Highs (linear gradient: -20 = -1.0, 0 = 0.0, +20 = +1.0)
    net_nh = float(getattr(breadth_result, "net_new_highs", 0))
    s_nh = linear_gradient(net_nh, -20.0, 0.0, 20.0)
    votes.append(IndicatorVote(
        rule_name="Breadth: Net New Highs",
        condition=f"Net new 52W highs at {int(net_nh):+d} (gradient score: {s_nh:+.2f})",
        vote=s_nh,
        weight=1.0,
        weighted_vote=s_nh,
        interpretation="Leadership expansion vs distribution gradient",
        category="breadth",
    ))

    # 4. Equal-Weight RSP vs Cap-Weight SPY Leadership (Stage 2: 2.2 Align vote and label)
    # leadership_spread_pct is (spy_ret - rsp_ret). rsp_excess is (rsp_ret - spy_ret) = -leadership_spread_pct.
    leadership_spread = float(getattr(breadth_result, "leadership_spread_pct", 0.0))
    leadership_status = getattr(breadth_result, "leadership_status", "")
    spy_ret = float(getattr(breadth_result, "spy_return_pct", 0.0))
    rsp_ret = float(getattr(breadth_result, "rsp_return_pct", 0.0))
    rsp_excess = rsp_ret - spy_ret

    # Gradient: -1.5% (narrow / mega-cap dominance) = -1.0, 0 = 0.0, +1.5% (broad participation) = +1.0
    s_rsp = linear_gradient(rsp_excess, -1.5, 0.0, 1.5)

    if rsp_excess > 0 and spy_ret < 0 and rsp_ret < 0:
        # Equal-weight outperformance driven by mega-cap decline (defensive rotation)
        s_rsp = max(0.25, min(s_rsp, 0.50))
        cond_detail = f"Broad Leadership (Defensive Rotation): RSP {rsp_ret:+.2f}% vs SPY {spy_ret:+.2f}% (RSP excess {rsp_excess:+.2f}%)"
    elif "Broad Leadership" in leadership_status or rsp_excess >= 1.0:
        s_rsp = max(0.25, s_rsp)
        cond_detail = f"Broad Leadership: Equal-weight RSP {rsp_ret:+.2f}% outperforming SPY {spy_ret:+.2f}% (excess {rsp_excess:+.2f}%)"
    elif "Narrow Leadership" in leadership_status or rsp_excess <= -1.0:
        s_rsp = min(-0.25, s_rsp)
        cond_detail = f"Narrow Leadership: Cap-weight SPY {spy_ret:+.2f}% outperforming RSP {rsp_ret:+.2f}% (spread {leadership_spread:+.2f}%)"
    else:
        cond_detail = f"Balanced Leadership: SPY {spy_ret:+.2f}% vs RSP {rsp_ret:+.2f}% (spread {leadership_spread:+.2f}%)"

    votes.append(IndicatorVote(
        rule_name="Breadth: RSP vs SPY Leadership",
        condition=f"{cond_detail} (gradient score: {s_rsp:+.2f})",
        vote=s_rsp,
        weight=1.0,
        weighted_vote=s_rsp,
        interpretation="Broad participation vs mega-cap concentration",
        category="breadth",
    ))

    # 5. Advance / Decline Confirmation
    ad_conf = getattr(breadth_result, "ad_confirmation", "Neutral")
    ad_ratio = getattr(breadth_result, "ad_ratio", 1.0)
    if ad_conf in ("Confirming Rally", "Bullish Divergence"):
        s_ad = min(1.0, 0.5 + (ad_ratio - 1.0) * 0.5) if ad_ratio > 1.0 else 0.5
    elif ad_conf in ("Confirming Decline", "Bearish Divergence"):
        s_ad = max(-1.0, -0.5 - (1.0 - ad_ratio) * 0.5) if ad_ratio < 1.0 else -0.5
    else:
        s_ad = linear_gradient(ad_ratio, 0.6, 1.0, 1.5)
    votes.append(IndicatorVote(
        rule_name="Breadth: Advance / Decline Line",
        condition=f"A/D state: {ad_conf} (A/D ratio {ad_ratio:.2f}, score {s_ad:+.2f})",
        vote=s_ad,
        weight=1.0,
        weighted_vote=s_ad,
        interpretation="Advance/Decline volume participation",
        category="breadth",
    ))

    # 6. McClellan Oscillator (if available)
    mcclellan = getattr(breadth_result, "mcclellan_oscillator", None)
    if mcclellan is not None:
        s_mcc = linear_gradient(float(mcclellan), -50.0, 0.0, 50.0)
        votes.append(IndicatorVote(
            rule_name="Breadth: McClellan Oscillator",
            condition=f"McClellan Oscillator at {float(mcclellan):+.1f} (gradient score: {s_mcc:+.2f})",
            vote=s_mcc,
            weight=1.0,
            weighted_vote=s_mcc,
            interpretation="Short-term breadth thrust / overbought-oversold",
            category="breadth",
        ))

    cat_score = sum(v.weighted_vote for v in votes) / len(votes) if votes else 0.0
    return max(-1.0, min(1.0, cat_score)), votes, "active"


def evaluate_volatility_risk_category(
    vix_current: float,
    vix_previous: float,
    macro_data: Optional[Any] = None,
    scoring_cfg: Optional[ScoringConfig] = None,
) -> Tuple[float, List[IndicatorVote], str]:
    """Score Volatility & Risk Appetite category (15% weight).
    
    Includes VIX level, VIX trend, term structure, and HY OAS level and change.
    """
    votes: List[IndicatorVote] = []

    # 1. VIX Level (gradient: +1.0 at VIX 12, 0.0 at VIX 18, -1.0 at VIX 30; Fix 1.6)
    if vix_current <= 18.0:
        s_vix_lvl = round(max(0.0, min(1.0, (18.0 - vix_current) / (18.0 - 12.0))), 2)
    else:
        s_vix_lvl = round(max(-1.0, min(0.0, -(vix_current - 18.0) / (30.0 - 18.0))), 2)

    votes.append(IndicatorVote(
        rule_name="Volatility: VIX Absolute Level",
        condition=f"VIX at {vix_current:.2f} (gradient score: {s_vix_lvl:+.2f})",
        vote=s_vix_lvl,
        weight=1.0,
        weighted_vote=s_vix_lvl,
        interpretation="VIX absolute level gradient (+1.0 at 12, 0 at 18, -1.0 at 30)",
        category="volatility_risk",
    ))

    # 2. VIX Trend (gradient: -2 pts = +1.0, 0 = 0.0, +2 pts = -1.0)
    vix_delta = vix_current - vix_previous
    s_vix_trend = linear_gradient(vix_delta, 2.0, 0.0, -2.0)
    if s_vix_trend > 0.1:
        vix_interp = "Volatility compressing / calming hedging demand (bullish)"
    elif s_vix_trend < -0.1:
        vix_interp = "Volatility expanding / hedging surge (bearish)"
    else:
        vix_interp = "Volatility stable / steady hedging conditions (neutral)"
    votes.append(IndicatorVote(
        rule_name="Volatility: VIX Period Shift",
        condition=f"VIX period Δ {vix_delta:+.2f} pts (gradient score: {s_vix_trend:+.2f})",
        vote=s_vix_trend,
        weight=1.0,
        weighted_vote=s_vix_trend,
        interpretation=vix_interp,
        category="volatility_risk",
    ))

    # 3. VIX Term Structure (1M / 3M ratio)
    intel = getattr(macro_data, "intelligence", None) if macro_data else None
    if intel and getattr(intel, "vol_term", None):
        vt = intel.vol_term
        ratio = getattr(vt, "ratio", 1.0)
        s_vt = linear_gradient(ratio, 1.02, 0.98, 0.94)
        vt_desc = "Normal upward-sloping contango (tail risk discounted)" if s_vt > 0.1 else ("Backwardated term structure / near-term volatility spike" if s_vt < -0.1 else "Flat term structure slope")
        votes.append(IndicatorVote(
            rule_name="Volatility: VIX Term Structure (1M/3M)",
            condition=f"1M/3M ratio at {ratio:.3f} [{vt.structure}] (gradient score: {s_vt:+.2f})",
            vote=s_vt,
            weight=1.0,
            weighted_vote=s_vt,
            interpretation=vt_desc,
            category="volatility_risk",
        ))

    # 4. High-Yield OAS Level & Change
    if intel and getattr(intel, "credit", None):
        cr = intel.credit
        spread_bps = getattr(cr, "spread_bps", 350.0)
        delta_bps = getattr(cr, "delta_bps", 0.0)
        s_oas_lvl = linear_gradient(spread_bps, 450.0, 380.0, 320.0)
        s_oas_chg = linear_gradient(delta_bps, 20.0, 0.0, -20.0)
        s_hy = (s_oas_lvl + s_oas_chg) / 2.0
        votes.append(IndicatorVote(
            rule_name="Credit: High-Yield OAS & Solvency",
            condition=f"HY OAS at {spread_bps:.0f} bps (Δ {delta_bps:+.1f} bps) [{cr.regime}] (score: {s_hy:+.2f})",
            vote=s_hy,
            weight=1.0,
            weighted_vote=s_hy,
            interpretation="Corporate bond credit default and refinancing risk premium",
            category="volatility_risk",
        ))

    cat_score = sum(v.weighted_vote for v in votes) / len(votes) if votes else 0.0
    return max(-1.0, min(1.0, cat_score)), votes, "active"


def evaluate_rates_macro_category(
    macro_data: Optional[Any],
    macro_scoring_cfg: Optional[MacroScoringConfig] = None,
    report_type: str = "daily",
) -> Tuple[float, List[IndicatorVote], str]:
    """Score Rates & Macro category (20% weight).
    
    Includes 10Y level, 4W/13W trend lookbacks for 10Y and 2Y, real yield, curve, dollar, oil, direction-based inflation/labor.
    """
    if macro_data is None or (macro_scoring_cfg is not None and not getattr(macro_scoring_cfg, "enabled", True)):
        return 0.0, [], "unavailable"

    votes: List[IndicatorVote] = []
    fr = getattr(macro_data, "fed_rates", None)
    intel = getattr(macro_data, "intelligence", None)
    metrics = getattr(macro_data, "metrics", {})

    # Detect accelerating inflation state for rates cap (Stage 1: 1.5)
    is_infl_accelerating = False
    if intel and getattr(intel, "inflation_signal", ""):
        is_infl_accelerating = intel.inflation_signal.startswith("Accelerating")
    if not is_infl_accelerating and metrics:
        cpi_snap = metrics.get("core_cpi") or metrics.get("cpi")
        cpi_head = metrics.get("cpi")
        ppi_snap = metrics.get("ppi")
        cpi_mom = getattr(cpi_snap, "mom_pct", 0.0) or 0.0
        cpi_head_mom = getattr(cpi_head, "mom_pct", 0.0) or 0.0
        ppi_mom = getattr(ppi_snap, "mom_pct", 0.0) or 0.0
        if cpi_mom >= 0.40 or cpi_head_mom >= 0.50 or ppi_mom >= 0.80:
            is_infl_accelerating = True

    def _apply_rate_cap(val: float, base_interp: str) -> Tuple[float, str]:
        if is_infl_accelerating and val > 0.50:
            return 0.50, f"{base_interp} (Capped at +0.50 due to accelerating inflation backdrop)"
        return val, base_interp

    if fr:
        y10 = getattr(fr, "yield_10y", 4.25)
        y10_delta_bps = getattr(fr, "yield_10y_delta", 0.0) * 100.0

        # 1. 10Y Period Yield Shift
        s_10y = linear_gradient(y10_delta_bps, 20.0, 0.0, -20.0)
        s_10y, interp_10y = _apply_rate_cap(s_10y, "Benchmark discount rate and borrowing cost shift")
        votes.append(IndicatorVote(
            rule_name="Rates: 10Y Yield Period Shift",
            condition=f"10Y yield at {y10:.2f}% (period Δ {y10_delta_bps:+.1f} bps) [Score: {s_10y:+.2f}]",
            vote=s_10y,
            weight=1.0,
            weighted_vote=s_10y,
            interpretation=interp_10y,
            category="rates_macro",
        ))

        # 2. Multi-Week Rate Trend Lookbacks (Stage 2: 2.1 Rates De-duplication)
        # In monthly mode, the report period is ~4 weeks. To avoid double-counting the same series and window,
        # drop the 4-week lookback in monthly mode. Keep 1 short-window and 1 long-window (13W) per maturity.
        y10_4w = getattr(fr, "yield_10y_4w_delta", None)
        if y10_4w is not None and report_type != "monthly":
            s_4w = linear_gradient(y10_4w * 100.0, 30.0, 0.0, -30.0)
            s_4w, interp_4w = _apply_rate_cap(s_4w, "Trailing 4-week rate momentum lookback")
            votes.append(IndicatorVote(
                rule_name="Rates: 10Y 4-Week Trend",
                condition=f"10Y yield 4-week Δ {y10_4w * 100.0:+.1f} bps [Score: {s_4w:+.2f}]",
                vote=s_4w,
                weight=1.0,
                weighted_vote=s_4w,
                interpretation=interp_4w,
                category="rates_macro",
            ))

        y10_13w = getattr(fr, "yield_10y_13w_delta", None)
        if y10_13w is not None:
            s_13w = linear_gradient(y10_13w * 100.0, 60.0, 0.0, -60.0)
            s_13w, interp_13w = _apply_rate_cap(s_13w, "Trailing 13-week quarterly rate momentum lookback")
            votes.append(IndicatorVote(
                rule_name="Rates: 10Y 13-Week Trend",
                condition=f"10Y yield 13-week Δ {y10_13w * 100.0:+.1f} bps [Score: {s_13w:+.2f}]",
                vote=s_13w,
                weight=1.0,
                weighted_vote=s_13w,
                interpretation=interp_13w,
                category="rates_macro",
            ))

        # 2Y rate votes: Ensure exactly 1 short-window and 1 long-window (13W)
        y2_delta_bps = getattr(fr, "yield_2y_delta", None)
        y2_4w = getattr(fr, "yield_2y_4w_delta", None)
        if report_type == "monthly" and y2_delta_bps is not None:
            s_2y = linear_gradient(y2_delta_bps * 100.0, 20.0, 0.0, -20.0)
            s_2y, interp_2y = _apply_rate_cap(s_2y, "Policy expectations borrowing cost shift")
            votes.append(IndicatorVote(
                rule_name="Rates: 2Y Yield Period Shift",
                condition=f"2Y yield at {getattr(fr, 'yield_2y', 0.0):.2f}% (period Δ {y2_delta_bps * 100.0:+.1f} bps) [Score: {s_2y:+.2f}]",
                vote=s_2y,
                weight=1.0,
                weighted_vote=s_2y,
                interpretation=interp_2y,
                category="rates_macro",
            ))
        elif y2_4w is not None:
            s_2y_4w = linear_gradient(y2_4w * 100.0, 30.0, 0.0, -30.0)
            s_2y_4w, interp_2y_4w = _apply_rate_cap(s_2y_4w, "Trailing 4-week policy expectations momentum lookback")
            votes.append(IndicatorVote(
                rule_name="Rates: 2Y 4-Week Trend",
                condition=f"2Y yield 4-week Δ {y2_4w * 100.0:+.1f} bps [Score: {s_2y_4w:+.2f}]",
                vote=s_2y_4w,
                weight=1.0,
                weighted_vote=s_2y_4w,
                interpretation=interp_2y_4w,
                category="rates_macro",
            ))

        y2_13w = getattr(fr, "yield_2y_13w_delta", None)
        if y2_13w is not None:
            s_2y_13w = linear_gradient(y2_13w * 100.0, 60.0, 0.0, -60.0)
            s_2y_13w, interp_2y_13w = _apply_rate_cap(s_2y_13w, "Trailing 13-week quarterly policy shift lookback")
            votes.append(IndicatorVote(
                rule_name="Rates: 2Y 13-Week Trend",
                condition=f"2Y yield 13-week Δ {y2_13w * 100.0:+.1f} bps [Score: {s_2y_13w:+.2f}]",
                vote=s_2y_13w,
                weight=1.0,
                weighted_vote=s_2y_13w,
                interpretation=interp_2y_13w,
                category="rates_macro",
            ))

        # 3. Yield Curve & Driver (2s10s)
        spread_bps = getattr(fr, "spread_2s10s", 0.0) * 100.0
        curve_status = getattr(fr, "curve_status", "Normal" if not getattr(fr, "is_inverted", False) else "Inverted")
        s_curve = linear_gradient(spread_bps, -15.0, 5.0, 30.0)
        s_curve, interp_curve = _apply_rate_cap(s_curve, "Yield curve slope and monetary policy transmission curve")
        votes.append(IndicatorVote(
            rule_name="Rates: 2s10s Curve Shape",
            condition=f"2s10s spread at {spread_bps:+.1f} bps [{curve_status}] [Score: {s_curve:+.2f}]",
            vote=s_curve,
            weight=1.0,
            weighted_vote=s_curve,
            interpretation=interp_curve,
            category="rates_macro",
        ))

    # 4. Real Yield (10Y TIPS) (Stage 2: 2.4 Show level and direction: Real rate: high but falling)
    if intel and getattr(intel, "rates", None):
        real_y = intel.rates.real_yield_10y
        real_d_bps = getattr(intel.rates, "real_yield_delta_bps", 0.0)
        s_real = linear_gradient(real_y, 2.65, 2.00, 1.40)
        lvl_desc = "Restrictive Level" if real_y >= 2.0 else ("Accommodative Level" if real_y <= 1.5 else "Neutral Level")
        dir_desc = "easing" if real_d_bps < -1.0 else ("tightening" if real_d_bps > 1.0 else "steady")
        tips_label = f"Real rate: {lvl_desc.lower().replace(' level', '')} ({real_y:.2f}%) but {dir_desc}"
        if s_real < -0.1:
            interp_tips = "Restrictive real cost of capital capping valuation multiples"
        elif s_real > 0.1:
            interp_tips = "Accommodative real cost of capital supporting equity valuation multiples"
        else:
            interp_tips = "Neutral real yield backdrop"
        votes.append(IndicatorVote(
            rule_name="Rates: Real Cost of Capital (10Y TIPS)",
            condition=f"10Y TIPS real yield at {real_y:.2f}% [{lvl_desc}, {dir_desc}] ({tips_label}) [Score: {s_real:+.2f}]",
            vote=s_real,
            weight=1.0,
            weighted_vote=s_real,
            interpretation=interp_tips,
            category="rates_macro",
        ))

    # 5. US Dollar & Oil Shock
    cross_assets = getattr(macro_data, "cross_assets", [])
    dxy_item = next((ca for ca in cross_assets if "Dollar" in getattr(ca, "name", "") or "DX" in getattr(ca, "symbol", "")), None)
    if dxy_item:
        dxy_pct = getattr(dxy_item, "pct_change", 0.0)
        s_dxy = linear_gradient(dxy_pct, 1.5, 0.0, -1.5)
        if s_dxy > 0.1:
            dxy_interp = "USD softening / global liquidity easing"
        elif s_dxy < -0.1:
            dxy_interp = "USD strengthening / global liquidity tightening"
        else:
            dxy_interp = "USD neutral / stable global liquidity"
        votes.append(IndicatorVote(
            rule_name="Macro: US Dollar Index (DXY)",
            condition=f"US Dollar moved {dxy_pct:+.2f}% over period [Score: {s_dxy:+.2f}]",
            vote=s_dxy,
            weight=1.0,
            weighted_vote=s_dxy,
            interpretation=dxy_interp,
            category="rates_macro",
        ))

    oil_item = next((ca for ca in cross_assets if "Oil" in getattr(ca, "name", "") or "CL" in getattr(ca, "symbol", "")), None)
    if oil_item:
        oil_pct = getattr(oil_item, "pct_change", 0.0)
        oil_3m = getattr(oil_item, "pct_change_3m", 0.0)
        if oil_3m == 0.0:
            oil_3m = getattr(macro_data, "oil_3m_change_pct", 0.0)
        is_energy_shock = getattr(macro_data, "energy_shock_active", False) or abs(oil_3m) >= 15.0

        s_oil_period = linear_gradient(oil_pct, 5.0, 0.0, -5.0)
        s_oil_3m = linear_gradient(oil_3m, 20.0, 0.0, -20.0)
        s_oil = 0.40 * s_oil_period + 0.60 * s_oil_3m

        if is_energy_shock and oil_3m >= 15.0:
            s_oil = min(-0.50, s_oil)
            cond_oil = f"WTI crude oil at ${getattr(oil_item, 'current_price', 0.0):.2f} (period Δ {oil_pct:+.2f}%, 3M trend {oil_3m:+.2f}%) [Energy Shock Alert Active] [Score: {s_oil:+.2f}]"
        else:
            cond_oil = f"WTI crude oil moved {oil_pct:+.2f}% over period (3M trend {oil_3m:+.2f}%) [Score: {s_oil:+.2f}]"

        votes.append(IndicatorVote(
            rule_name="Macro: Crude Oil (WTI) Shock",
            condition=cond_oil,
            vote=s_oil,
            weight=1.0,
            weighted_vote=s_oil,
            interpretation="Commodity input cost and energy inflation shock monitor",
            category="rates_macro",
        ))

    # 6. Direction-based Inflation (Requirement 1)
    recent_releases = getattr(macro_data, "recent_releases", [])
    inf_events = [e for e in recent_releases if getattr(e, "category", "") == "inflation"]
    consensus_inf = [e for e in inf_events if getattr(e, "surprise_flag", "") not in ("n/a", "n/a (no consensus)", "n/a (unpolled)") and getattr(e, "forecast", None) is not None]
    if consensus_inf:
        ev = consensus_inf[0]
        s_inf = 1.0 if ev.surprise_flag == "cool" else (-1.0 if ev.surprise_flag == "hot" else 0.0)
        cond_inf = f"Inflation release {ev.title} printed {ev.surprise_flag.upper()} vs consensus"
        votes.append(IndicatorVote("Macro: Inflation Dynamics", cond_inf, s_inf, 1.0, s_inf, "Price stability vs consensus", "rates_macro"))
    elif "cpi" in metrics or "core_cpi" in metrics:
        m = metrics.get("cpi") or metrics.get("core_cpi")
        curr_yoy = m.headline_value
        prev_yoy = m.prior_headline
        diff = curr_yoy - prev_yoy
        s_inf = linear_gradient(diff, 0.20, 0.0, -0.20)
        cond_inf = f"{m.name} at {curr_yoy:.2f}% YoY vs prior {prev_yoy:.2f}% YoY (Δ {diff:+.2f}%) [direction-based (no consensus)]"
        votes.append(IndicatorVote("Macro: Inflation Dynamics", cond_inf, s_inf, 1.0, s_inf, "Price stability trajectory", "rates_macro", is_direction_based=True))

    # 7. Direction-based Labor (Requirement 1)
    lab_events = [e for e in recent_releases if getattr(e, "category", "") == "labor"]
    consensus_lab = [e for e in lab_events if getattr(e, "surprise_flag", "") not in ("n/a", "n/a (no consensus)", "n/a (unpolled)") and getattr(e, "forecast", None) is not None]
    if consensus_lab:
        ev = consensus_lab[0]
        s_lab = 1.0 if ev.surprise_flag == "strong" else (-1.0 if ev.surprise_flag == "weak" else 0.0)
        cond_lab = f"Labor release {ev.title} printed {ev.surprise_flag.upper()} vs consensus"
        votes.append(IndicatorVote("Macro: Labor Dynamics", cond_lab, s_lab, 1.0, s_lab, "Employment conditions vs consensus", "rates_macro"))
    elif "payrolls" in metrics:
        m = metrics["payrolls"]
        chg = m.headline_value
        prev_chg = getattr(m, "prior_headline", None)
        s_lab = linear_gradient(chg, 50.0, 150.0, 250.0)
        if s_lab < -0.2:
            status_desc = "Decelerating / Weak Additions"
        elif s_lab > 0.2:
            status_desc = "Accelerating / Robust Additions"
        else:
            status_desc = "Moderate / Balanced Additions"
        cond_lab = f"Nonfarm payrolls monthly change: {chg:+,.0f}k [{status_desc}] [direction-based (no consensus)]"
        if s_lab < -0.1:
            interp_lab = "Cooling payroll trajectory and softening employment conditions"
        elif s_lab > 0.1:
            interp_lab = "Resilient employment growth and labor expansion"
        else:
            interp_lab = "Balanced labor market additions"
        votes.append(IndicatorVote("Macro: Labor Dynamics", cond_lab, s_lab, 1.0, s_lab, interp_lab, "rates_macro", is_direction_based=True))

    cat_score = sum(v.weighted_vote for v in votes) / len(votes) if votes else 0.0
    return max(-1.0, min(1.0, cat_score)), votes, "active"


def evaluate_sentiment_category(
    sentiment_data: Optional[Any] = None,
    scoring_cfg: Optional[ScoringConfig] = None,
) -> Tuple[float, List[IndicatorVote], str]:
    """Score Sentiment & Positioning category (15% weight).
    
    Includes Put/Call ratio percentile, AAII survey, VIX vs realized vol (VRP).
    If any key input is unavailable, status is UNAVAILABLE and it is excluded from active scores.
    """
    if sentiment_data is None:
        return 0.0, [], "unavailable"

    # Per Stage 1.3: If any input is unavailable, status is UNAVAILABLE and it is excluded
    pcr = getattr(sentiment_data, "put_call_ratio", None)
    aaii = getattr(sentiment_data, "aaii_spread", None)
    if aaii is None:
        aaii = getattr(sentiment_data, "aaii_bull_bear_spread", None)
    vol_spread = getattr(sentiment_data, "vix_vs_realized_vol", None)
    if vol_spread is None:
        vol_spread = getattr(sentiment_data, "vol_risk_premium", None)

    # If survey / flow inputs are unpolled or unavailable, mark category unavailable
    # to exclude from active score denominator and avoid partial skew
    if aaii is None and pcr is None:
        return 0.0, [], "unavailable"

    votes: List[IndicatorVote] = []

    # Put/Call ratio: score as percentile if trailing history exists, or drop it
    pcr_percentile = getattr(sentiment_data, "put_call_percentile", None)
    if pcr_percentile is not None:
        s_pcr = linear_gradient(float(pcr_percentile), 80.0, 50.0, 20.0)
        votes.append(IndicatorVote(
            rule_name="Sentiment: Equity Put/Call Ratio",
            condition=f"Put/Call ratio at {pcr:.2f} ({pcr_percentile:.0f}th percentile)",
            vote=s_pcr,
            weight=1.0,
            weighted_vote=s_pcr,
            interpretation="Options positioning percentile",
            category="sentiment_positioning",
        ))

    if aaii is not None:
        s_aaii = linear_gradient(float(aaii), -15.0, 0.0, 15.0)
        votes.append(IndicatorVote(
            rule_name="Sentiment: AAII Bull-Bear Spread",
            condition=f"AAII spread at {aaii:+.1f}%",
            vote=s_aaii,
            weight=1.0,
            weighted_vote=s_aaii,
            interpretation="Retail investor sentiment survey",
            category="sentiment_positioning",
        ))

    if vol_spread is not None:
        # VRP definition: positive = neutral/mildly bullish, negative = bearish
        vs = float(vol_spread)
        if vs >= 2.0:
            s_vol = 0.25
            interp_vrp = "Positive volatility risk premium (healthy options buffer / insurance demand)"
        elif vs >= 0.0:
            s_vol = 0.0
            interp_vrp = "Equilibrium options pricing relative to realized variance"
        elif vs >= -2.0:
            s_vol = -0.50
            interp_vrp = "Realized volatility exceeding options pricing (mild vol discount)"
        else:
            s_vol = -1.00
            interp_vrp = "Severe volatility inversion (realized price swings outstripping implied pricing)"

        votes.append(IndicatorVote(
            rule_name="Sentiment: Implied vs Realized Vol (VRP)",
            condition=f"VRP at {vs:+.2f} pts ({'Substantial Premium' if vs >= 3.0 else 'Equilibrium'})",
            vote=s_vol,
            weight=1.0,
            weighted_vote=s_vol,
            interpretation=interp_vrp,
            category="sentiment_positioning",
        ))

    if not votes:
        return 0.0, [], "unavailable"

    cat_score = sum(v.weighted_vote for v in votes) / len(votes)
    return max(-1.0, min(1.0, cat_score)), votes, "active"
