"""Section 1: Executive Summary builder."""

from dataclasses import dataclass
from typing import Any, List, Optional
from data.calendar import PeriodInfo
from scoring.engine import Scorecard
from sections.base import SectionResult


@dataclass
class ExecutiveSummaryData:
    verdict: str
    normalized_score: float
    raw_score: float
    max_score: float
    reasons: List[str]
    report_type: str
    as_of_date: str
    session_date: str
    is_partial: bool
    notes: str
    regime_summary: Optional[str] = None
    forward_outlook: Optional[str] = None
    confidence: str = ""
    alignment_note: str = ""


def build_executive_summary(
    scorecard: Optional[Scorecard],
    period_info: PeriodInfo,
    regime_intelligence: Optional[Any] = None,
    swing_data: Optional[Any] = None,
) -> SectionResult:
    """Construct Executive Summary section result."""
    if not scorecard:
        return SectionResult(
            section_num=1,
            title="Executive Summary",
            status="unavailable",
            error_message="Trend scorecard calculation failed or was omitted.",
        )

    regime_summary = None
    forward_outlook = None
    if regime_intelligence is not None:
        regime_summary = getattr(regime_intelligence, "summary_badge", None)
        forward_outlook = getattr(regime_intelligence, "forward_outlook", None)

    # Generate Regime vs Posture Alignment Explanation (Fix 1.3)
    alignment_note = ""
    if swing_data is not None:
        verdict = scorecard.verdict
        posture = getattr(swing_data, "posture", "DEFENSIVE").capitalize()
        triggered = getattr(swing_data, "triggered_rule", "benchmark moving averages")
        if " [Event-Risk Overlay:" in triggered:
            triggered_clean = triggered.split(" [Event-Risk Overlay:")[0].rstrip(".") + " (see Section 3 for catalyst overlay)"
        else:
            triggered_clean = triggered

        active_cats = [c for c in getattr(scorecard, "categories", []) if c.status == "active"]
        pos_cats = [c for c in active_cats if c.weighted_score > 0]
        neg_cats = [c for c in active_cats if c.weighted_score < 0]
        top_pos = max(pos_cats, key=lambda c: c.weighted_score) if pos_cats else None
        top_neg = min(neg_cats, key=lambda c: c.weighted_score) if neg_cats else None

        if top_pos and top_neg:
            v_reason = f"cross-asset signals are conflicted: supportive {top_pos.name} ({top_pos.score:+.2f}) is offset by restrictive {top_neg.name} ({top_neg.score:+.2f})"
        elif top_pos:
            v_reason = f"driven primarily by supportive {top_pos.name} ({top_pos.score:+.2f})"
        elif top_neg:
            v_reason = f"pressured primarily by restrictive {top_neg.name} ({top_neg.score:+.2f})"
        else:
            v_reason = "category signals remain balanced around neutral baselines"

        alignment_note = f"Regime is {verdict} because {v_reason}; posture is {posture} because {triggered_clean}"

    data = ExecutiveSummaryData(
        verdict=scorecard.verdict,
        normalized_score=scorecard.normalized_score,
        raw_score=scorecard.raw_score,
        max_score=scorecard.max_score,
        reasons=scorecard.summary_reasons,
        report_type=period_info.report_type.capitalize(),
        as_of_date=period_info.as_of_date,
        session_date=period_info.session_date,
        is_partial=period_info.is_partial,
        notes=period_info.notes,
        regime_summary=regime_summary,
        forward_outlook=forward_outlook,
        confidence=scorecard.confidence,
        alignment_note=alignment_note,
    )

    return SectionResult(
        section_num=1,
        title="Executive Summary",
        status="available",
        data=data,
    )
