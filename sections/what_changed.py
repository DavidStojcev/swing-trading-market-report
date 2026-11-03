"""Section: 'What Changed' Executive Delta Box & Primary Forward Risk (Top of Report)."""

from dataclasses import dataclass, field
from datetime import datetime, date
import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class DeltaMetric:
    name: str
    current_val: str
    prior_val: str
    delta_str: str
    valence: str              # 'positive', 'negative', 'neutral'
    detail: str


@dataclass
class WhatChangedData:
    as_of_date: str
    deltas: List[DeltaMetric] = field(default_factory=list)
    single_biggest_risk: str = ""


def build_what_changed(
    scorecard: Optional[Any],
    prior_scorecard: Optional[Any],
    macro_data: Optional[Any],
    breadth_res: Optional[Any],
    sector_rotation: Optional[Any],
    spx_snap: Optional[Any],
    ndx_snap: Optional[Any],
    as_of_date: str,
    spx_snap_prior: Optional[Any] = None,
    ndx_snap_prior: Optional[Any] = None,
    upcoming_events: Optional[List[Any]] = None,
) -> SectionResult:
    """Extract the 5 largest market deltas versus prior report and synthesize single biggest risk."""
    try:
        deltas: List[DeltaMetric] = []

        # 1. Trend Score Delta (Fix 1.1)
        curr_score = getattr(scorecard, "normalized_score", 0.0) if scorecard else 0.0
        if prior_scorecard is not None and getattr(prior_scorecard, "normalized_score", None) is not None:
            prior_score = float(prior_scorecard.normalized_score)
            score_diff = curr_score - prior_score
            prior_score_str = f"{prior_score:+.2f}"
            delta_score_str = f"{score_diff:+.2f} pts"
            val_score = "positive" if score_diff > 0.05 else ("negative" if score_diff < -0.05 else "neutral")
            detail_score = f"Score shifted {score_diff:+.2f} points; regime verdict is {getattr(scorecard, 'verdict', 'Neutral')}."
        else:
            prior_score_str = "n/a (source unavailable)"
            delta_score_str = "—"
            val_score = "neutral"
            detail_score = f"Prior period baseline unavailable; current regime verdict is {getattr(scorecard, 'verdict', 'Neutral')}."

        deltas.append(
            DeltaMetric(
                name="Macro & Micro Trend Score",
                current_val=f"{curr_score:+.2f} ({getattr(scorecard, 'verdict', 'Neutral')})",
                prior_val=prior_score_str,
                delta_str=delta_score_str,
                valence=val_score,
                detail=detail_score,
            )
        )

        # 2. Sector Leadership Movers (Largest rank changes)
        if sector_rotation and hasattr(sector_rotation, "biggest_gainers") and sector_rotation.biggest_gainers:
            top_up = sector_rotation.biggest_gainers[0]
            deltas.append(
                DeltaMetric(
                    name="Top Sector Momentum Surge",
                    current_val=f"{top_up.name} ({top_up.symbol}) Rank #{top_up.rank}",
                    prior_val=f"Rank #{top_up.prev_rank}",
                    delta_str=f"{top_up.rank_delta:+d} ranks",
                    valence="positive",
                    detail=f"{top_up.name} advanced {top_up.rank_delta:+d} places in leadership ranking with {top_up.period_return:+.2f}% return.",
                )
            )

        if sector_rotation and hasattr(sector_rotation, "biggest_losers") and sector_rotation.biggest_losers:
            top_down = sector_rotation.biggest_losers[0]
            deltas.append(
                DeltaMetric(
                    name="Sharpest Sector Contraction",
                    current_val=f"{top_down.name} ({top_down.symbol}) Rank #{top_down.rank}",
                    prior_val=f"Rank #{top_down.prev_rank}",
                    delta_str=f"{top_down.rank_delta:+d} ranks",
                    valence="negative",
                    detail=f"{top_down.name} fell {abs(top_down.rank_delta)} places to rank #{top_down.rank} with {top_down.period_return:+.2f}% return.",
                )
            )

        # 3. Credit Spreads & Solvency Delta
        intel = getattr(macro_data, "intelligence", None) if macro_data else None
        if intel and getattr(intel, "credit", None):
            cr = intel.credit
            prior_spread = cr.spread_bps - cr.delta_bps
            deltas.append(
                DeltaMetric(
                    name="High-Yield Credit OAS Spread",
                    current_val=f"{cr.spread_bps:.0f} bps",
                    prior_val=f"{prior_spread:.0f} bps",
                    delta_str=f"{cr.delta_bps:+.1f} bps",
                    valence="positive" if cr.delta_bps <= 0 else "negative",
                    detail=f"Corporate credit spreads are {cr.regime.lower()} at {cr.spread_bps:.0f} bps ({cr.delta_bps:+.1f} bps shift).",
                )
            )

        # 4. Market Participation / Breadth Delta
        if breadth_res:
            p50 = getattr(getattr(breadth_res, "pct_above_50_dma", None), "current", 50.0)
            p50_chg = getattr(getattr(breadth_res, "pct_above_50_dma", None), "change", 0.0)
            p50_prev = p50 - p50_chg
            deltas.append(
                DeltaMetric(
                    name="S&P 500 % Above 50-Day Moving Average",
                    current_val=f"{p50:.1f}%",
                    prior_val=f"{p50_prev:.1f}%",
                    delta_str=f"{p50_chg:+.1f}%",
                    valence="positive" if p50_chg > 0 else "negative",
                    detail=f"Broad market participation shifted {p50_chg:+.1f}% with {p50:.1f}% of constituent stocks holding above 50-DMA.",
                )
            )

        # 5. Volatility / Index Divergence Delta (Stage 1: 1.7 Numeric prior & delta)
        if ndx_snap and spx_snap:
            ndx_dist = ndx_snap.price_vs_dma50_pct
            spx_dist = spx_snap.price_vs_dma50_pct
            curr_gap = abs(spx_dist - ndx_dist)

            if spx_snap_prior is not None and ndx_snap_prior is not None:
                prior_spx_dist = getattr(spx_snap_prior, "price_vs_dma50_pct", 0.0)
                prior_ndx_dist = getattr(ndx_snap_prior, "price_vs_dma50_pct", 0.0)
                prior_gap = abs(prior_spx_dist - prior_ndx_dist)
                gap_change = curr_gap - prior_gap
                prior_gap_val = f"{prior_gap:.2f}% gap"
                gap_delta_str = f"{gap_change:+.2f}%"
                val_gap = "negative" if ndx_dist < -2.0 else "neutral"
                detail_gap = f"Nasdaq-100 / S&P 500 50-DMA divergence shifted from {prior_gap:.2f}% to {curr_gap:.2f}% ({gap_change:+.2f}% {'widening' if gap_change > 0 else 'narrowing'})."
            else:
                prior_gap_val = "n/a (source unavailable)"
                gap_delta_str = "—"
                val_gap = "neutral"
                detail_gap = f"Prior divergence baseline unavailable; current divergence is {curr_gap:.2f}%."

            deltas.append(
                DeltaMetric(
                    name="Tech vs. Broad Market Divergence",
                    current_val=f"{curr_gap:.2f}% gap",
                    prior_val=prior_gap_val,
                    delta_str=gap_delta_str,
                    valence=val_gap,
                    detail=detail_gap,
                )
            )

        # Keep strictly top 5
        top_5_deltas = deltas[:5]

        # Dynamically rank candidate risks from config (Stage 1: 1.8)
        # Candidates:
        # 1. next HIGH event within 5 sessions
        # 2. largest technical breakdown
        # 3. rate/Fed-path shift
        # 4. credit widening
        # 5. energy shock

        candidates = []

        # Find next HIGH-impact event from upcoming_events
        next_high_event = None
        next_high_days = 999
        if upcoming_events:
            for ev in upcoming_events:
                ev_imp = str(getattr(ev, "importance", "")).lower()
                ev_title = str(getattr(ev, "title", "")).lower()
                is_high = (
                    ev_imp == "high"
                    or any(k in ev_title for k in [
                        "fomc", "payrolls", "employment situation", "cpi", "consumer price index",
                        "chair keynote", "chair speech", "refunding", "election"
                    ])
                )
                if is_high:
                    ev_date_str = getattr(ev, "date", "")
                    if ev_date_str:
                        try:
                            ev_dt = pd.to_datetime(ev_date_str).date()
                            curr_dt = pd.to_datetime(as_of_date).date()
                            if ev_dt > curr_dt:
                                b_days = len(pd.bdate_range(start=curr_dt + pd.Timedelta(days=1), end=ev_dt))
                                if b_days < next_high_days:
                                    next_high_days = b_days
                                    next_high_event = ev
                        except Exception:
                            pass

        # 1. Next HIGH event candidate
        if next_high_event and next_high_days <= 5:
            ev_score = 95.0 - (next_high_days * 3.0)
            is_reset_qualified = any(k in next_high_event.title.lower() for k in ["fomc", "cpi", "consumer price index"])
            risk_clause = "with the potential to abruptly reset rate expectations and equity risk premia" if is_reset_qualified else "carrying elevated volatility and binary event risk for asset markets"
            candidates.append({
                "type": "event_risk",
                "score": ev_score,
                "text": (
                    f"Imminent High-Impact Macro Catalyst: The upcoming '{next_high_event.title}' on {next_high_event.date} "
                    f"({next_high_days} session{'s' if next_high_days > 1 else ''} away) {risk_clause}."
                ),
            })

        # 2. Technical breakdown candidate
        if ndx_snap and ndx_snap.price_vs_dma50_pct <= -2.5:
            tech_score = 70.0 + min(25.0, abs(ndx_snap.price_vs_dma50_pct) * 4.0)
            candidates.append({
                "type": "tech_breakdown",
                "score": tech_score,
                "text": (
                    f"Mega-Cap Tech Leadership Breakdown: Nasdaq-100 is pressured {abs(ndx_snap.price_vs_dma50_pct):.2f}% below its 50-day moving average "
                    f"({ndx_snap.dma_50:,.1f}), threatening to drag the broader market into technical de-risking and test key 200-DMA support levels."
                ),
            })

        # 3. Rate / Fed-path shift candidate
        fr = getattr(macro_data, "fed_rates", None) if macro_data else None
        y10_val = getattr(fr, "yield_10y", 0.0) if fr else 0.0
        y2_val = getattr(fr, "yield_2y", 0.0) if fr else 0.0
        eff_ff = getattr(fr, "fed_funds_rate", 3.83) if fr else 3.83
        spread_2y_ff = (y2_val - eff_ff) * 100.0 if (y2_val and eff_ff) else 0.0
        if y10_val >= 4.90 or spread_2y_ff >= 40.0:
            rate_score = 75.0 + (min(20.0, spread_2y_ff / 5.0) if spread_2y_ff > 0 else 0.0)
            candidates.append({
                "type": "fed_rates_shift",
                "score": rate_score,
                "text": (
                    f"Restrictive Rates & Constrained Fed Flexibility: 2-Year Treasury yields trading +{spread_2y_ff:.0f} bps above fed funds "
                    f"alongside FOMC hike dissents confirm that monetary easing remains off the table, capping broad valuation multiple expansion."
                ),
            })

        # 4. Credit spread widening candidate
        if intel and getattr(intel, "credit", None) and intel.credit.delta_bps > 10.0:
            credit_score = 65.0 + min(30.0, intel.credit.delta_bps * 2.0)
            candidates.append({
                "type": "credit_widening",
                "score": credit_score,
                "text": (
                    f"Corporate Credit Solvency Widening: High-yield OAS spreads widened +{intel.credit.delta_bps:.1f} bps to {intel.credit.spread_bps:.0f} bps, "
                    f"signaling emerging corporate refinancing frictions and balance sheet pressure."
                ),
            })

        # 5. Energy shock candidate
        oil_3m = getattr(macro_data, "oil_3m_change_pct", 0.0) if macro_data else 0.0
        is_oil_shock = getattr(macro_data, "energy_shock_active", False) if macro_data else (abs(oil_3m) >= 15.0)
        if is_oil_shock and oil_3m >= 15.0:
            oil_score = 75.0 + min(20.0, oil_3m * 0.5)
            candidates.append({
                "type": "energy_shock",
                "score": oil_score,
                "text": (
                    f"Energy Price Shock: Crude oil has surged +{oil_3m:.1f}% over the trailing 3 months, reigniting cost-push inflation and "
                    f"widening the headline vs. core CPI spread."
                ),
            })

        # Sort candidate risks by severity score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        winner_text = candidates[0]["text"] if candidates else (
            "Cross-asset macro volatility and monetary policy uncertainty testing key moving average support levels."
        )

        # Print the winner plus the next HIGH event and its date (Stage 1: 1.8)
        if next_high_event:
            single_risk = f"The single biggest forward risk is {winner_text} Key Immediate Catalyst: Next HIGH-impact event is '{next_high_event.title}' scheduled for {next_high_event.date} ({next_high_days} session{'s' if next_high_days > 1 else ''} away)."
        else:
            single_risk = f"The single biggest forward risk is {winner_text}"

        data = WhatChangedData(
            as_of_date=as_of_date,
            deltas=top_5_deltas,
            single_biggest_risk=single_risk,
        )

        return SectionResult(
            section_num=3,
            title="What Changed: Key Deltas vs. Prior Period",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building what changed section: %s", e)
        return SectionResult(
            section_num=3,
            title="What Changed: Key Deltas vs. Prior Period",
            status="unavailable",
            error_message=f"What changed error: {e}",
        )
