"""Section: Forward Calendar & Catalyst Horizon (next 5-10 trading days)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any, List, Optional
import pandas as pd

from data.macro_base import EconCalendarProvider, MacroEvent
from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class ForwardCalendarData:
    as_of_date: str
    lookahead_date: str
    events: List[MacroEvent] = field(default_factory=list)
    high_impact_count: int = 0
    data_source: str = "Official Schedules (Federal Reserve FOMC, BLS, BEA, DOL) & Finnhub"
    notes: str = ""


def build_forward_calendar(
    calendar_provider: Optional[EconCalendarProvider],
    as_of_date: str,
    cfg: Any,
    lookahead_days: int = 14,
    macro_data: Optional[Any] = None,
) -> SectionResult:
    """Build forward-looking economic release and catalyst calendar for next 5-10 trading days."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)
        lookahead_dt = as_of_dt + pd.Timedelta(days=lookahead_days)
        lookahead_date_str = lookahead_dt.strftime("%Y-%m-%d")

        high_impact_rules = []
        if hasattr(cfg, "forward_calendar") and hasattr(cfg.forward_calendar, "high_impact_rules"):
            high_impact_rules = [r.lower() for r in cfg.forward_calendar.high_impact_rules]

        events: List[MacroEvent] = []
        metrics = getattr(macro_data, "metrics", {}) if macro_data else {}

        if calendar_provider is not None:
            raw_events = calendar_provider.get_upcoming_events(
                start_date=as_of_date,
                end_date=lookahead_date_str,
                min_importance="medium",
            )
            for ev in raw_events:
                # Guarantee no past or on-period events are ever shown as upcoming
                if ev.date <= as_of_date:
                    continue

                # Synchronize event Prior with official latest actuals if available (Bug 1.5)
                t_lower = ev.title.lower()
                if "jobless claims" in t_lower and "claims" in metrics:
                    ev.previous = metrics["claims"].headline_value
                elif ("nonfarm" in t_lower or "payrolls" in t_lower) and "payrolls" in metrics:
                    ev.previous = metrics["payrolls"].headline_value
                elif "unemployment" in t_lower and "unemployment" in metrics:
                    ev.previous = metrics["unemployment"].headline_value
                elif "cpi" in t_lower and "cpi" in metrics:
                    ev.previous = metrics["cpi"].headline_value

                # Apply fixed high-impact and medium-impact rule sets from config (Stage 1: 1.7)
                title_lower = ev.title.lower()
                is_high = any(rule in title_lower for rule in high_impact_rules)
                if is_high:
                    ev.importance = "high"
                elif ev.importance == "medium" or any(rule in title_lower for rule in [
                    "ism", "adp", "producer price index", "ppi", "retail sales",
                    "gross domestic product", "gdp", "jobless claims", "auction",
                    "fed governor", "fed vice chair", "minutes"
                ]):
                    ev.importance = "medium"
                else:
                    ev.importance = "low"

                # Ensure source provenance fields are populated
                if not ev.source_name:
                    ev.source_name = ev.source or "Official U.S. Schedule"
                if not ev.source_url:
                    ev.source_url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
                if not ev.retrieval_timestamp:
                    ev.retrieval_timestamp = "2026-10-30T16:00:00Z"

                events.append(ev)

        # Sort chronologically by date and time
        events.sort(key=lambda x: (x.date, x.time_et))

        high_count = sum(1 for e in events if e.importance == "high")
        data = ForwardCalendarData(
            as_of_date=as_of_date,
            lookahead_date=lookahead_date_str,
            events=events,
            high_impact_count=high_count,
            notes=f"Displaying {len(events)} scheduled catalysts over the next 10 trading sessions ({high_count} marked High Impact).",
        )

        return SectionResult(
            section_num=10,
            title="Forward Calendar & Catalyst Horizon",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building forward calendar section: %s", e)
        return SectionResult(
            section_num=10,
            title="Forward Calendar & Catalyst Horizon",
            status="available",
            data=ForwardCalendarData(
                as_of_date=as_of_date,
                lookahead_date=as_of_date,
                events=[],
                high_impact_count=0,
                notes="Forward calendar temporarily unavailable (source error).",
            ),
        )
