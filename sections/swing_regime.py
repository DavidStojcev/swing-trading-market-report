"""Section: Swing-Trade Market Gate & Exposure Posture (Top of Report)."""

from dataclasses import dataclass
import logging
from typing import Any, List, Optional
import pandas as pd

from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class SwingGateData:
    as_of_date: str
    posture: str                      # 'FULL', 'REDUCED', 'SELECTIVE', 'DEFENSIVE'
    posture_badge_class: str          # 'badge-green', 'badge-primary', 'badge-yellow', 'badge-red'
    triggered_rule: str
    spy_price: float
    spy_20ema: float
    spy_20ema_dist_pct: float
    spy_20ema_pass: bool
    spy_50dma: float
    spy_50dma_dist_pct: float
    spy_50dma_pass: bool
    qqq_price: float
    qqq_20ema: float
    qqq_20ema_dist_pct: float
    qqq_20ema_pass: bool
    qqq_50dma: float
    qqq_50dma_dist_pct: float
    qqq_50dma_pass: bool
    vix_level: float
    vix_5d_trend: float
    vix_term_structure: str           # e.g., 'Contango (Normal)' or 'Backwardation / Inversion'
    breadth_pct_above_50dma: float
    breadth_ad_state: str
    net_new_highs: int
    execution_guidance: str


def classify_event_impact(title: str, declared_importance: str = "") -> str:
    """Classify calendar event into strict HIGH, MEDIUM, LOW impact tiers per Stage 1: 1.6."""
    t = title.lower()
    # HIGH = FOMC decision, Nonfarm Payrolls, CPI, Chair speech/press conference, Treasury refunding announcement, elections.
    if any(k in t for k in [
        "fomc", "rate decision", "nonfarm payrolls", "employment situation",
        "consumer price index", "cpi", "chair keynote", "chair speech",
        "chair press conference", "treasury quarterly refunding",
        "quarterly refunding announcement", "general election", "midterm election", "presidential election"
    ]):
        return "HIGH"

    # MEDIUM = ISM, ADP, PPI, retail sales, GDP, claims, major auctions, other Fed speakers.
    if any(k in t for k in [
        "ism manufacturing", "ism services", "adp employment", "producer price index",
        "ppi", "retail sales", "gross domestic product", "gdp", "jobless claims",
        "treasury 10-year note auction", "treasury 30-year bond auction",
        "fed governor", "fed vice chair", "fed president"
    ]):
        return "MEDIUM"

    if declared_importance.upper() == "HIGH":
        return "HIGH"
    elif declared_importance.upper() == "MEDIUM":
        return "MEDIUM"
    return "LOW"


def evaluate_swing_gate(
    spy_df: Optional[pd.DataFrame],
    qqq_df: Optional[pd.DataFrame],
    vix_current: float,
    vix_previous: float,
    vix_term_ratio: float,
    breadth_result: Optional[Any],
    as_of_date: str,
    cfg: Optional[Any] = None,
    upcoming_events: Optional[List[Any]] = None,
    event_risk_window_days: Optional[int] = None,
) -> SectionResult:
    """Evaluate objective swing-trading exposure gate answering 'How aggressively can I be long?'."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)

        # 1. SPY technical gates
        spy_sub = spy_df[spy_df.index <= as_of_dt] if spy_df is not None and not spy_df.empty else pd.DataFrame()
        if not spy_sub.empty and len(spy_sub) >= 50:
            spy_price = float(spy_sub.iloc[-1]["Close"])
            spy_20ema = float(spy_sub["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            spy_50dma = float(spy_sub["Close"].rolling(window=50).mean().iloc[-1])
            spy_20_dist = ((spy_price - spy_20ema) / spy_20ema) * 100.0
            spy_50_dist = ((spy_price - spy_50dma) / spy_50dma) * 100.0
            spy_20_pass = spy_price >= spy_20ema
            spy_50_pass = spy_price >= spy_50dma
        else:
            spy_price, spy_20ema, spy_50dma = 0.0, 0.0, 0.0
            spy_20_dist, spy_50_dist = 0.0, 0.0
            spy_20_pass, spy_50_pass = False, False

        # 2. QQQ technical gates
        qqq_sub = qqq_df[qqq_df.index <= as_of_dt] if qqq_df is not None and not qqq_df.empty else pd.DataFrame()
        if not qqq_sub.empty and len(qqq_sub) >= 50:
            qqq_price = float(qqq_sub.iloc[-1]["Close"])
            qqq_20ema = float(qqq_sub["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            qqq_50dma = float(qqq_sub["Close"].rolling(window=50).mean().iloc[-1])
            qqq_20_dist = ((qqq_price - qqq_20ema) / qqq_20ema) * 100.0
            qqq_50_dist = ((qqq_price - qqq_50dma) / qqq_50dma) * 100.0
            qqq_20_pass = qqq_price >= qqq_20ema
            qqq_50_pass = qqq_price >= qqq_50dma
        else:
            qqq_price, qqq_20ema, qqq_50dma = 0.0, 0.0, 0.0
            qqq_20_dist, qqq_50_dist = 0.0, 0.0
            qqq_20_pass, qqq_50_pass = False, False

        # 3. Volatility metrics
        vix_trend = vix_current - vix_previous
        term_str = "Contango (Normal)" if vix_term_ratio <= 1.00 else "Backwardation (Inversion)"

        # 4. Breadth metrics
        p50 = getattr(getattr(breadth_result, "pct_above_50_dma", None), "current", 50.0) if breadth_result else 50.0
        ad_state = getattr(breadth_result, "ad_confirmation", "Neutral") if breadth_result else "Neutral"
        net_highs = getattr(breadth_result, "net_new_highs", 0) if breadth_result else 0

        # 5. Strict Gate Evaluation Rules (Identical to Apex Scanner Market Gate)
        # DEFENSIVE: Dual 50-DMA break, extreme VIX (>26), or severe breadth breakdown (<40%)
        if (not spy_50_pass and not qqq_50_pass) or vix_current >= 26.0 or p50 < 40.0:
            posture = "DEFENSIVE"
            badge_class = "badge-red"
            triggered_rule = f"Gate Rule 4 (Defensive): Dual benchmark break of 50-DMA (SPY {spy_50_dist:+.2f}%, QQQ {qqq_50_dist:+.2f}%) or elevated risk regime."
            guidance = "Quantitative model criteria indicate capital preservation under elevated distribution risk. Benchmark averages trade below key moving average thresholds; new breakout setups remain inactive."

        # SELECTIVE: Divergence with one index below 50-DMA, VIX 22-26, or breadth 40-50%
        elif (not spy_50_pass or not qqq_50_pass) or vix_current >= 22.0 or p50 < 50.0:
            posture = "SELECTIVE"
            badge_class = "badge-yellow"
            triggered_rule = f"Gate Rule 3 (Selective): Benchmark divergence or breakdown below 50-DMA (SPY {spy_50_dist:+.2f}%, QQQ {qqq_50_dist:+.2f}%)."
            guidance = "Quantitative model criteria reflect selective exposure. Technical parameters prioritize leading relative-strength themes showing independent accumulation under conservative risk baselines."

        # REDUCED: Both above 50-DMA, but one below 20-EMA or VIX 19.5-22.0
        elif (not spy_20_pass or not qqq_20_pass) or vix_current >= 19.5:
            posture = "REDUCED"
            badge_class = "badge-primary"
            triggered_rule = f"Gate Rule 2 (Reduced): Benchmark pullback below 20-EMA with 50-DMA support intact (SPY {spy_20_dist:+.2f}%, QQQ {qqq_20_dist:+.2f}%)."
            guidance = "Quantitative model criteria reflect measured exposure. Technical parameters identify constructive pullbacks to primary moving average support while broader indexes digest recent advances."

        # FULL: Both above 20-EMA & 50-DMA, VIX < 19.5, Breadth >= 50%
        else:
            posture = "FULL"
            badge_class = "badge-green"
            triggered_rule = f"Gate Rule 1 (Full): SPY and QQQ holding above 20-EMA and 50-DMA with low volatility and supportive breadth."
            guidance = "Quantitative model criteria reflect broad market expansion. Favorable technical momentum with SPY and QQQ holding above primary moving averages and low implied volatility."

        # 6. Event-Risk Overlay (Stage 2: 2.6)
        # Within configurable window (default: 3 trading days) before HIGH-impact event,
        # cap posture one step more conservative and log reason.
        if event_risk_window_days is None:
            if cfg and hasattr(cfg, "swing_gate") and hasattr(cfg.swing_gate, "event_risk_window_days"):
                event_risk_window_days = getattr(cfg.swing_gate, "event_risk_window_days", 3)
            elif cfg and hasattr(cfg, "scoring") and hasattr(cfg.scoring, "thresholds"):
                event_risk_window_days = int(cfg.scoring.thresholds.get("event_risk_window_days", 3))
            else:
                event_risk_window_days = 3

        imminent_catalyst = None
        min_catalyst_days = 999
        if upcoming_events:
            for ev in upcoming_events:
                ev_imp = str(getattr(ev, "importance", ""))
                ev_title = str(getattr(ev, "title", ""))
                tier = classify_event_impact(ev_title, ev_imp)
                # Overlay considers HIGH only (Stage 1: 1.6)
                if tier != "HIGH":
                    continue

                ev_date_str = getattr(ev, "date", "")
                if not ev_date_str:
                    continue
                try:
                    ev_dt = pd.to_datetime(ev_date_str).date()
                    curr_dt = as_of_dt.date()
                    if ev_dt > curr_dt:
                        b_days = len(pd.bdate_range(start=curr_dt + pd.Timedelta(days=1), end=ev_dt))
                        if 1 <= b_days <= event_risk_window_days:
                            if b_days < min_catalyst_days:
                                min_catalyst_days = b_days
                                imminent_catalyst = (ev, b_days)
                except Exception:
                    continue

        if imminent_catalyst:
            ev_obj, b_days = imminent_catalyst
            if posture == "DEFENSIVE":
                # Apply T10: if already at the most conservative tier, state "no change (already Defensive)"
                overlay_rule = f"Event-Risk Overlay: no change (already Defensive; upcoming HIGH event '{ev_obj.title}' on {ev_obj.date})"
                triggered_rule = f"{triggered_rule} [{overlay_rule}]."
                guidance = f"Upcoming macro catalyst: '{ev_obj.title}' on {ev_obj.date}. " + guidance
            elif posture == "FULL":
                posture = "REDUCED"
                badge_class = "badge-primary"
                overlay_rule = f"Event-Risk Overlay: Capped 1-tier more conservative (FULL -> REDUCED) ahead of HIGH-impact catalyst '{ev_obj.title}' on {ev_obj.date} ({b_days} session{'s' if b_days > 1 else ''} away)"
                triggered_rule = f"{triggered_rule} [{overlay_rule}]."
                guidance = f"Upcoming macro catalyst: '{ev_obj.title}' on {ev_obj.date}. " + guidance
            elif posture == "REDUCED":
                posture = "SELECTIVE"
                badge_class = "badge-yellow"
                overlay_rule = f"Event-Risk Overlay: Capped 1-tier more conservative (REDUCED -> SELECTIVE) ahead of HIGH-impact catalyst '{ev_obj.title}' on {ev_obj.date} ({b_days} session{'s' if b_days > 1 else ''} away)"
                triggered_rule = f"{triggered_rule} [{overlay_rule}]."
                guidance = f"Upcoming macro catalyst: '{ev_obj.title}' on {ev_obj.date}. " + guidance
            elif posture == "SELECTIVE":
                posture = "DEFENSIVE"
                badge_class = "badge-red"
                overlay_rule = f"Event-Risk Overlay: Capped 1-tier more conservative (SELECTIVE -> DEFENSIVE) ahead of HIGH-impact catalyst '{ev_obj.title}' on {ev_obj.date} ({b_days} session{'s' if b_days > 1 else ''} away)"
                triggered_rule = f"{triggered_rule} [{overlay_rule}]."
                guidance = f"Upcoming macro catalyst: '{ev_obj.title}' on {ev_obj.date}. " + guidance

        data = SwingGateData(
            as_of_date=as_of_date,
            posture=posture,
            posture_badge_class=badge_class,
            triggered_rule=triggered_rule,
            spy_price=spy_price,
            spy_20ema=spy_20ema,
            spy_20ema_dist_pct=spy_20_dist,
            spy_20ema_pass=spy_20_pass,
            spy_50dma=spy_50dma,
            spy_50dma_dist_pct=spy_50_dist,
            spy_50dma_pass=spy_50_pass,
            qqq_price=qqq_price,
            qqq_20ema=qqq_20ema,
            qqq_20ema_dist_pct=qqq_20_dist,
            qqq_20ema_pass=qqq_20_pass,
            qqq_50dma=qqq_50dma,
            qqq_50dma_dist_pct=qqq_50_dist,
            qqq_50dma_pass=qqq_50_pass,
            vix_level=vix_current,
            vix_5d_trend=vix_trend,
            vix_term_structure=term_str,
            breadth_pct_above_50dma=p50,
            breadth_ad_state=ad_state,
            net_new_highs=net_highs,
            execution_guidance=guidance,
        )

        return SectionResult(
            section_num=2,
            title="Swing-Trade Market Gate & Exposure Posture",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed evaluating swing gate: %s", e)
        return SectionResult(
            section_num=2,
            title="Swing-Trade Market Gate & Exposure Posture",
            status="unavailable",
            error_message=f"Swing gate evaluation error: {e}",
        )
