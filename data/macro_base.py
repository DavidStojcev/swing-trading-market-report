"""Abstract base definitions for economic calendar and macro event providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class MacroEvent:
    """Standardized economic release / event."""
    event_id: str = ""
    title: str = ""
    category: str = ""         # 'inflation', 'labor', 'activity', 'rates', 'sentiment'
    date: str = ""             # YYYY-MM-DD
    time_et: str = ""          # e.g., '08:30 ET'
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    unit: str = ""             # '%', 'k', 'index', etc.
    surprise_flag: str = "n/a" # 'hot', 'cool', 'strong', 'weak', 'in_line', 'n/a'
    importance: str = "high"   # 'high', 'medium', 'low'
    revised: bool = False
    notes: str = ""
    reference_period: str = ""
    release_date: str = ""
    source: str = ""
    source_name: str = ""
    source_url: str = ""
    retrieval_timestamp: str = ""


def compute_lookback_return(df: Any, as_of_date: Any, lookback_bars: int = 63) -> float:
    """Compute percentage return over exact trading sessions up to as_of_date (Fix 1.5)."""
    if df is None or getattr(df, "empty", True):
        return 0.0
    import pandas as pd
    dt = pd.to_datetime(as_of_date)
    sub = df[df.index <= dt]
    if len(sub) < 2:
        return 0.0
    c_col = "Close" if "Close" in sub.columns else ("close" if "close" in sub.columns else None)
    if not c_col:
        return 0.0
    c_now = float(sub[c_col].iloc[-1])
    idx = max(0, len(sub) - (lookback_bars + 1))
    c_base = float(sub[c_col].iloc[idx])
    if c_base <= 0:
        return 0.0
    return ((c_now - c_base) / c_base) * 100.0


@dataclass
class EarningsEvent:
    """Earnings release announcement."""
    symbol: str
    name: str
    date: str                  # YYYY-MM-DD
    hour: str                  # 'bmo' (before market open), 'amc' (after market close), etc.
    market_cap: float = 0.0


@dataclass
class ReportedEarningsEvent:
    """Historical/reported earnings announcement with results (Stage 4)."""
    symbol: str
    name: str
    date: str                  # YYYY-MM-DD
    hour: str                  # 'bmo' or 'amc'
    market_cap: float = 0.0
    eps_surprise_pct: Optional[float] = None
    rev_surprise_pct: Optional[float] = None
    guidance: str = "Unspecified" # 'Raised', 'Lowered', 'Maintained', 'Unspecified'


class EconCalendarProvider(ABC):
    """Abstract interface for economic and earnings calendar providers."""

    @abstractmethod
    def get_recent_releases(self, start_date: str, end_date: str) -> List[MacroEvent]:
        """Fetch economic data releases that occurred within date window."""
        pass

    @abstractmethod
    def get_upcoming_events(self, start_date: str, end_date: str, min_importance: str = "medium") -> List[MacroEvent]:
        """Fetch upcoming scheduled economic events."""
        pass

    @abstractmethod
    def get_upcoming_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[EarningsEvent]:
        """Fetch upcoming company earnings releases."""
        pass

    def get_recent_reported_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[ReportedEarningsEvent]:
        """Fetch reported company earnings releases with surprise metrics."""
        return []
