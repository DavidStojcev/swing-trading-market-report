"""Trend scoring engine aggregating indicator votes into categories and generating regime verdicts."""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional
import pandas as pd

from config.settings import BreadthScoringConfig, MacroScoringConfig, ScorecardCategoriesConfig, ScoringConfig
from indicators.engine import TechnicalSnapshot
from scoring.rules import (
    IndicatorVote,
    evaluate_breadth_category,
    evaluate_breadth_votes,
    evaluate_macro_votes,
    evaluate_rates_macro_category,
    evaluate_sentiment_category,
    evaluate_technical_votes,
    evaluate_trend_price_category,
    evaluate_vix_vote,
    evaluate_volatility_risk_category,
)


@dataclass(frozen=True)
class CategoryScore:
    """Grouped category score with cap and active/dropped status."""
    name: str
    category_key: str
    weight: float
    score: float
    weighted_score: float
    status: str                   # 'active' or 'unavailable'
    components: List[IndicatorVote]
    notes: str = ""
    effective_weight: float = 0.0


@dataclass(frozen=True)
class DailyReturnContext:
    """Intraperiod daily session return context for highlighting large intra-period moves."""
    date: str
    spx_close: float
    spx_change_pct: float
    ndx_close: float
    ndx_change_pct: float
    is_large_move: bool
    flag_note: str = ""


@dataclass(frozen=True)
class VerdictSensitivityItem:
    """Scorecard sensitivity test with one active category excluded."""
    excluded_category: str
    score_ex: float
    verdict_ex: str
    delta_vs_baseline: float


@dataclass(frozen=True)
class VerdictSensitivity:
    """Regime verdict sensitivity and borderline assessment."""
    baseline_score: float
    baseline_verdict: str
    is_borderline: bool
    borderline_label: str
    items: List[VerdictSensitivityItem] = field(default_factory=list)


@dataclass(frozen=True)
class Scorecard:
    """Consolidated market trend verdict and voting scorecard."""
    raw_score: float
    max_score: float
    normalized_score: float          # Scale from -1.0 to +1.0
    verdict: str                     # 'Risk-on', 'Constructive', 'Neutral', 'Cautious', 'Risk-off'
    votes: List[IndicatorVote]
    caution_flags: List[str]
    top_bullish_factors: List[str]
    top_bearish_factors: List[str]
    summary_reasons: List[str]
    regime_label: str = "Neutral"    # Risk-on / Constructive / Neutral / Cautious / Risk-off
    confidence: str = ""             # e.g. "High (4 of 4 categories agree)"
    categories: List[CategoryScore] = field(default_factory=list)
    intraperiod_context: List[DailyReturnContext] = field(default_factory=list)
    divergence_note: str = ""
    sensitivity: Optional[VerdictSensitivity] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize scorecard and all category components to dictionary."""
        return {
            "raw_score": self.raw_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "verdict": self.verdict,
            "regime_label": self.regime_label,
            "confidence": self.confidence,
            "divergence_note": self.divergence_note,
            "caution_flags": list(self.caution_flags),
            "top_bullish_factors": list(self.top_bullish_factors),
            "top_bearish_factors": list(self.top_bearish_factors),
            "summary_reasons": list(self.summary_reasons),
            "sensitivity": {
                "baseline_score": self.sensitivity.baseline_score,
                "baseline_verdict": self.sensitivity.baseline_verdict,
                "is_borderline": self.sensitivity.is_borderline,
                "borderline_label": self.sensitivity.borderline_label,
                "items": [
                    {
                        "excluded_category": it.excluded_category,
                        "score_ex": it.score_ex,
                        "verdict_ex": it.verdict_ex,
                        "delta_vs_baseline": it.delta_vs_baseline,
                    }
                    for it in self.sensitivity.items
                ],
            } if self.sensitivity else None,
            "confidence": self.confidence,
            "divergence_note": self.divergence_note,
            "caution_flags": list(self.caution_flags),
            "top_bullish_factors": list(self.top_bullish_factors),
            "top_bearish_factors": list(self.top_bearish_factors),
            "summary_reasons": list(self.summary_reasons),
            "categories": [
                {
                    "name": c.name,
                    "category_key": c.category_key,
                    "weight": c.weight,
                    "effective_weight": c.effective_weight,
                    "score": c.score,
                    "weighted_score": c.weighted_score,
                    "status": c.status,
                    "notes": c.notes,
                }
                for c in self.categories
            ],
            "intraperiod_context": [
                {
                    "date": d.date,
                    "spx_close": d.spx_close,
                    "spx_change_pct": d.spx_change_pct,
                    "ndx_close": d.ndx_close,
                    "ndx_change_pct": d.ndx_change_pct,
                    "is_large_move": d.is_large_move,
                    "flag_note": d.flag_note,
                }
                for d in self.intraperiod_context
            ],
        }

    def to_json(self) -> str:
        """Serialize scorecard to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class TrendScoringEngine:
    """Calculates explainable market trend scores based on technical, macro, and breadth categories."""

    def __init__(
        self,
        scoring_cfg: ScoringConfig,
        cat_cfg: Optional[ScorecardCategoriesConfig] = None,
    ):
        self.cfg = scoring_cfg
        self.cat_cfg = cat_cfg or ScorecardCategoriesConfig()

    def compute_scorecard(
        self,
        spx_snapshot: TechnicalSnapshot,
        vix_current: float,
        vix_previous: float,
        ndx_snapshot: Optional[TechnicalSnapshot] = None,
        macro_data: Optional[Any] = None,
        macro_scoring_cfg: Optional[MacroScoringConfig] = None,
        breadth_data: Optional[Any] = None,
        breadth_scoring_cfg: Optional[BreadthScoringConfig] = None,
        report_type: str = "daily",
        spx_df: Optional[Any] = None,
        ndx_df: Optional[Any] = None,
        period_info: Optional[Any] = None,
        sentiment_data: Optional[Any] = None,
    ) -> Scorecard:
        """Compute transparent trend scorecard grouped into 5 categories with gradients and regime verdict."""
        cat_weights = self.cat_cfg.weights if self.cat_cfg else {
            "trend_price": 0.30,
            "breadth": 0.20,
            "volatility_risk": 0.15,
            "rates_macro": 0.20,
            "sentiment_positioning": 0.15,
        }

        # 1. Trend / Price Category (30% cap) - S&P 500 and Nasdaq-100 weaker of two
        s_trend, votes_trend, div_note = evaluate_trend_price_category(spx_snapshot, ndx_snapshot, self.cfg)
        w_trend = cat_weights.get("trend_price", 0.30)
        cat_trend = CategoryScore(
            name="Trend / Price",
            category_key="trend_price",
            weight=w_trend,
            score=s_trend,
            weighted_score=s_trend * w_trend,
            status="active",
            components=votes_trend,
            notes=div_note,
        )

        # 2. Breadth Category (20% cap) - Linear gradient across 50/200 DMA, net highs, RSP/SPY, A/D, McClellan
        s_breadth, votes_breadth, st_breadth = evaluate_breadth_category(breadth_data, breadth_scoring_cfg, report_type)
        w_breadth = cat_weights.get("breadth", 0.20)
        cat_breadth = CategoryScore(
            name="Market Breadth",
            category_key="breadth",
            weight=w_breadth,
            score=s_breadth,
            weighted_score=s_breadth * w_breadth if st_breadth == "active" else 0.0,
            status=st_breadth,
            components=votes_breadth,
            notes="",
        )

        # 3. Volatility / Risk Appetite Category (15% cap) - VIX level/trend, term structure, HY OAS level/delta
        s_vol, votes_vol, st_vol = evaluate_volatility_risk_category(vix_current, vix_previous, macro_data, self.cfg)
        w_vol = cat_weights.get("volatility_risk", 0.15)
        cat_vol = CategoryScore(
            name="Volatility / Risk Appetite",
            category_key="volatility_risk",
            weight=w_vol,
            score=s_vol,
            weighted_score=s_vol * w_vol if st_vol == "active" else 0.0,
            status=st_vol,
            components=votes_vol,
            notes="",
        )

        # 4. Rates & Macro Category (20% cap) - 10Y shift, 4W/13W lookbacks, curve, dollar, oil, direction-based inflation/jobs
        s_rates, votes_rates, st_rates = evaluate_rates_macro_category(macro_data, macro_scoring_cfg, report_type)
        w_rates = cat_weights.get("rates_macro", 0.20)
        cat_rates = CategoryScore(
            name="Rates & Macro",
            category_key="rates_macro",
            weight=w_rates,
            score=s_rates,
            weighted_score=s_rates * w_rates if st_rates == "active" else 0.0,
            status=st_rates,
            components=votes_rates,
            notes="",
        )

        # 5. Sentiment & Positioning Category (15% cap) - If unavailable, drop and renormalize
        s_sent, votes_sent, st_sent = evaluate_sentiment_category(sentiment_data, self.cfg)
        w_sent = cat_weights.get("sentiment_positioning", 0.15)
        cat_sent = CategoryScore(
            name="Sentiment & Positioning",
            category_key="sentiment_positioning",
            weight=w_sent,
            score=s_sent,
            weighted_score=s_sent * w_sent if st_sent == "active" else 0.0,
            status=st_sent,
            components=votes_sent,
            notes="Source unavailable (renormalized)" if st_sent != "active" else "",
        )

        # Enforce min_inputs_per_category (Fix 1.4)
        min_inputs = getattr(self.cfg, "min_inputs_per_category", 2)
        filtered_categories = []
        for cat in [cat_trend, cat_breadth, cat_vol, cat_rates, cat_sent]:
            valid_inputs = [v for v in cat.components if v.vote is not None]
            if len(valid_inputs) < min_inputs and cat.status == "active":
                filtered_categories.append(
                    CategoryScore(
                        name=cat.name,
                        category_key=cat.category_key,
                        weight=cat.weight,
                        score=cat.score,
                        weighted_score=0.0,
                        status="unavailable",
                        components=cat.components,
                        notes=f"Source unavailable (<{min_inputs} valid inputs, renormalized)",
                        effective_weight=0.0,
                    )
                )
            else:
                filtered_categories.append(cat)

        categories = filtered_categories
        active_categories = [c for c in categories if c.status == "active"]

        # Renormalize active categories
        active_weight_sum = sum(c.weight for c in active_categories)
        total_weighted_score = sum(c.weighted_score for c in active_categories)
        normalized_score = (total_weighted_score / active_weight_sum) if active_weight_sum > 0 else 0.0
        normalized_score = max(-1.0, min(1.0, round(normalized_score, 2)))

        # Compute effective renormalized weight for display (Stage 2: 2.7)
        updated_categories = []
        for c in categories:
            eff_w = (c.weight / active_weight_sum) if (c.status == "active" and active_weight_sum > 0) else 0.0
            updated_categories.append(CategoryScore(
                name=c.name,
                category_key=c.category_key,
                weight=c.weight,
                score=c.score,
                weighted_score=c.weighted_score,
                status=c.status,
                components=c.components,
                notes=c.notes,
                effective_weight=eff_w,
            ))
        categories = updated_categories
        active_categories = [c for c in categories if c.status == "active"]

        # Determine regime verdict (Requirement 5)
        reg_cfg = getattr(self.cat_cfg, "regimes", {})
        r_on = reg_cfg.get("risk_on", 0.40)
        r_const = reg_cfg.get("constructive", 0.15)
        r_caut = reg_cfg.get("neutral_lower", -0.15)
        r_off = reg_cfg.get("cautious_lower", -0.40)

        def _get_verdict(score_val: float) -> str:
            if score_val >= r_on:
                return "Risk-on"
            elif score_val >= r_const:
                return "Constructive"
            elif score_val > r_caut:
                return "Neutral"
            elif score_val > r_off:
                return "Cautious"
            else:
                return "Risk-off"

        verdict = _get_verdict(normalized_score)

        # Borderline evaluation: within 0.03 of a band edge (Stage 1: 1.3)
        is_borderline = False
        borderline_label = ""
        if abs(normalized_score - r_caut) <= 0.03 or abs(normalized_score - (-0.10)) <= 0.03:
            is_borderline = True
            borderline_label = "Borderline Neutral / Cautious"
        elif abs(normalized_score - r_const) <= 0.03:
            is_borderline = True
            borderline_label = "Borderline Neutral / Constructive"
        elif abs(normalized_score - r_on) <= 0.03:
            is_borderline = True
            borderline_label = "Borderline Constructive / Risk-on"
        elif abs(normalized_score - r_off) <= 0.03:
            is_borderline = True
            borderline_label = "Borderline Cautious / Risk-off"

        # Verdict sensitivity: evaluate verdict with each active category removed in turn (Stage 1: 1.3)
        sens_items: List[VerdictSensitivityItem] = []
        for c in active_categories:
            rem = [x for x in active_categories if x.category_key != c.category_key]
            rem_w = sum(x.weight for x in rem)
            rem_ws = sum(x.weighted_score for x in rem)
            sc_ex = round(rem_ws / rem_w, 2) if rem_w > 0 else 0.0
            sens_items.append(
                VerdictSensitivityItem(
                    excluded_category=c.name,
                    score_ex=sc_ex,
                    verdict_ex=_get_verdict(sc_ex),
                    delta_vs_baseline=round(sc_ex - normalized_score, 2),
                )
            )

        sensitivity = VerdictSensitivity(
            baseline_score=normalized_score,
            baseline_verdict=verdict,
            is_borderline=is_borderline,
            borderline_label=borderline_label,
            items=sens_items,
        )

        # Check for Mixed / Conflicted verdict state (Fix 1.3)
        band_ranks = {"Risk-off": 0, "Cautious": 1, "Neutral": 2, "Constructive": 3, "Risk-on": 4}
        base_rank = band_ranks.get(verdict, 2)
        has_2_band_flip = any(abs(band_ranks.get(it.verdict_ex, 2) - base_rank) >= 2 for it in sens_items)
        scores = [c.score for c in active_categories]
        cat_spread = (max(scores) - min(scores)) if scores else 0.0
        spread_threshold = getattr(self.cfg, "mixed_verdict_spread_threshold", 0.8)

        if verdict == "Neutral" and (cat_spread >= spread_threshold or has_2_band_flip):
            verdict = "Neutral (Mixed)"

        # Calculate Agreement Ratio (Stage 2: 2.5 "Agreement: N of M categories match the verdict")
        def _matches(s: float, norm: float) -> bool:
            if norm >= 0.15:
                return s > 0.0
            elif norm <= -0.15:
                return s < 0.0
            else:
                return abs(s) <= 0.15

        agree_count = sum(1 for c in active_categories if _matches(c.score, normalized_score))
        total_active = len(active_categories)
        confidence = f"Agreement: {agree_count} of {total_active} active categories match the verdict"

        # Flatten all component votes for detail table
        all_votes: List[IndicatorVote] = []
        for c in categories:
            all_votes.extend(c.components)

        # Caution flags
        caution_flags: List[str] = []
        if spx_snapshot.rsi >= 70.0:
            caution_flags.append(f"S&P 500 RSI(14) is Overbought at {spx_snapshot.rsi:.1f} (> 70)")
        elif spx_snapshot.rsi <= 30.0:
            caution_flags.append(f"S&P 500 RSI(14) is Oversold at {spx_snapshot.rsi:.1f} (< 30)")

        if ndx_snapshot:
            if ndx_snapshot.rsi >= 70.0:
                caution_flags.append(f"Nasdaq-100 RSI(14) is Overbought at {ndx_snapshot.rsi:.1f} (> 70)")
            elif ndx_snapshot.rsi <= 30.0:
                caution_flags.append(f"Nasdaq-100 RSI(14) is Oversold at {ndx_snapshot.rsi:.1f} (< 30)")

        if div_note:
            caution_flags.append(div_note)

        # Bullish and bearish factor ranking across ALL categories (Fix 1.2)
        cat_name_map = {
            "trend_price": "Trend / Price",
            "breadth": "Market Breadth",
            "volatility_risk": "Volatility / Risk Appetite",
            "rates_macro": "Rates & Macro",
            "sentiment_positioning": "Sentiment & Positioning",
        }
        for c in categories:
            cat_name_map[c.category_key] = c.name
        cat_weight_map = {c.category_key: c.weight for c in categories}

        bull_candidates = [v for v in all_votes if v.weighted_vote > 0.05]
        bull_candidates.sort(
            key=lambda v: (round(v.weighted_vote, 4), round(cat_weight_map.get(v.category, 0.0), 4), round(v.vote, 4)),
            reverse=True,
        )
        top_bullish = [
            f"[{cat_name_map.get(v.category, v.category)}] {v.rule_name}: {v.condition}"
            for v in bull_candidates[:3]
        ] if bull_candidates else ["No major bullish indicator signals active"]

        bear_candidates = [v for v in all_votes if v.weighted_vote < -0.05]
        bear_candidates.sort(
            key=lambda v: (round(v.weighted_vote, 4), -round(cat_weight_map.get(v.category, 0.0), 4), round(v.vote, 4)),
            reverse=False,
        )
        top_bearish = [
            f"[{cat_name_map.get(v.category, v.category)}] {v.rule_name}: {v.condition}"
            for v in bear_candidates[:3]
        ] if bear_candidates else ["No major bearish indicator signals active"]

        # Executive summary bullet reasons
        summary_reasons: List[str] = []
        regime_desc = f"{verdict} ({borderline_label})" if is_borderline else verdict
        summary_reasons.append(
            f"Overall market regime is {regime_desc} with a normalized score of {normalized_score:+.2f} [{confidence}]."
        )
        if spx_snapshot.price > spx_snapshot.dma_50:
            summary_reasons.append(f"S&P 500 trades {spx_snapshot.price_vs_dma50_pct:+.2f}% above its 50-day moving average ({spx_snapshot.dma_50:,.1f}).")
        else:
            summary_reasons.append(f"S&P 500 is pressured {abs(spx_snapshot.price_vs_dma50_pct):.2f}% below its 50-day moving average ({spx_snapshot.dma_50:,.1f}).")

        summary_reasons.append(
            f"MACD momentum indicator sits at {spx_snapshot.macd:.2f} ({'above' if spx_snapshot.macd >= spx_snapshot.macd_signal else 'below'} signal line {spx_snapshot.macd_signal:.2f})."
        )
        vix_daily_implied = vix_current / 15.8745
        vix_regime_label = "Low / Complacent" if vix_current < 16.5 else ("Normal" if vix_current <= 20.0 else ("Elevated / Caution" if vix_current <= 26.0 else "High Fear"))
        vix_dir = "rising" if (vix_current - vix_previous) > 0.5 else ("falling" if (vix_current - vix_previous) < -0.5 else "steady")
        summary_reasons.append(
            f"Volatility regime: VIX closed at {vix_current:.2f} ({vix_current - vix_previous:+.2f} period change; {vix_regime_label} & {vix_dir}, ±{vix_daily_implied:.2f}% implied daily move)."
        )

        if div_note:
            summary_reasons.append(div_note)
        elif breadth_data and getattr(breadth_data, "breadth_read", ""):
            summary_reasons.append(f"Market Breadth: {breadth_data.breadth_read}")
        elif caution_flags:
            summary_reasons.append(f"Caution: {caution_flags[0]}.")

        # Intraperiod context (Requirement 6)
        intraperiod_context: List[DailyReturnContext] = []
        if spx_df is not None and not spx_df.empty and period_info is not None:
            p_start = pd.to_datetime(period_info.current_start)
            p_end = pd.to_datetime(period_info.current_end)
            spx_sub = spx_df[(spx_df.index >= p_start - pd.Timedelta(days=7)) & (spx_df.index <= p_end)]
            ndx_sub = ndx_df[(ndx_df.index >= p_start - pd.Timedelta(days=7)) & (ndx_df.index <= p_end)] if ndx_df is not None else None

            curr_sessions = [d for d in spx_sub.index if p_start <= d <= p_end]
            for sess_dt in curr_sessions:
                dt_str = sess_dt.strftime("%Y-%m-%d")
                s_idx = spx_sub.index.get_loc(sess_dt)
                if s_idx > 0:
                    c_now = float(spx_sub.iloc[s_idx]["Close"])
                    c_prev = float(spx_sub.iloc[s_idx - 1]["Close"])
                    spx_ret = ((c_now - c_prev) / c_prev) * 100.0 if c_prev > 0 else 0.0
                else:
                    c_now = float(spx_sub.iloc[s_idx]["Close"])
                    spx_ret = 0.0

                ndx_ret = 0.0
                c_ndx_now = 0.0
                if ndx_sub is not None and sess_dt in ndx_sub.index:
                    n_idx = ndx_sub.index.get_loc(sess_dt)
                    c_ndx_now = float(ndx_sub.iloc[n_idx]["Close"])
                    if n_idx > 0:
                        c_ndx_prev = float(ndx_sub.iloc[n_idx - 1]["Close"])
                        ndx_ret = ((c_ndx_now - c_ndx_prev) / c_ndx_prev) * 100.0 if c_ndx_prev > 0 else 0.0

                is_large = abs(spx_ret) >= 1.5 or abs(ndx_ret) >= 1.5
                flag_note = ""
                if is_large:
                    flag_note = f"⚠️ Volatility Alert: Single-session move >= 1.5% (S&P 500 {spx_ret:+.2f}%, Nasdaq-100 {ndx_ret:+.2f}%)"

                intraperiod_context.append(
                    DailyReturnContext(
                        date=dt_str,
                        spx_close=c_now,
                        spx_change_pct=spx_ret,
                        ndx_close=c_ndx_now,
                        ndx_change_pct=ndx_ret,
                        is_large_move=is_large,
                        flag_note=flag_note,
                    )
                )

        return Scorecard(
            raw_score=total_weighted_score,
            max_score=active_weight_sum,
            normalized_score=normalized_score,
            verdict=verdict,
            regime_label=verdict,
            confidence=confidence,
            votes=all_votes,
            caution_flags=caution_flags,
            top_bullish_factors=top_bullish,
            top_bearish_factors=top_bearish,
            summary_reasons=summary_reasons[:5],
            categories=categories,
            intraperiod_context=intraperiod_context,
            divergence_note=div_note,
            sensitivity=sensitivity,
        )

    @staticmethod
    def export_inputs(
        spx_snapshot: TechnicalSnapshot,
        vix_current: float,
        vix_previous: float,
        ndx_snapshot: Optional[TechnicalSnapshot] = None,
        breadth_data: Optional[Any] = None,
        macro_rates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Export scorecard input payload to dictionary for JSON persistence and reproducibility testing."""
        return {
            "spx_price": spx_snapshot.price,
            "spx_dma20": spx_snapshot.dma_20,
            "spx_dma50": spx_snapshot.dma_50,
            "spx_dma200": spx_snapshot.dma_200,
            "spx_macd": spx_snapshot.macd,
            "spx_macd_signal": spx_snapshot.macd_signal,
            "spx_macd_hist": spx_snapshot.macd_hist,
            "spx_adx": spx_snapshot.adx,
            "spx_plus_di": spx_snapshot.plus_di,
            "spx_minus_di": spx_snapshot.minus_di,
            "spx_rsi": spx_snapshot.rsi,
            "vix_current": vix_current,
            "vix_previous": vix_previous,
            "ndx_price": ndx_snapshot.price if ndx_snapshot else None,
            "ndx_dma20": ndx_snapshot.dma_20 if ndx_snapshot else None,
            "ndx_dma50": ndx_snapshot.dma_50 if ndx_snapshot else None,
            "ndx_dma200": ndx_snapshot.dma_200 if ndx_snapshot else None,
            "ndx_macd": ndx_snapshot.macd if ndx_snapshot else None,
            "ndx_macd_signal": ndx_snapshot.macd_signal if ndx_snapshot else None,
            "ndx_adx": ndx_snapshot.adx if ndx_snapshot else None,
            "breadth_pct_50": getattr(getattr(breadth_data, "pct_above_50_dma", None), "current", None) if breadth_data else None,
            "breadth_pct_200": getattr(getattr(breadth_data, "pct_above_200_dma", None), "current", None) if breadth_data else None,
            "net_new_highs": getattr(breadth_data, "net_new_highs", None) if breadth_data else None,
            "leadership_spread": getattr(breadth_data, "leadership_spread_pct", None) if breadth_data else None,
            "ad_confirmation": getattr(breadth_data, "ad_confirmation", None) if breadth_data else None,
            "ad_ratio": getattr(breadth_data, "ad_ratio", None) if breadth_data else None,
            "macro_rates": macro_rates or {},
        }
