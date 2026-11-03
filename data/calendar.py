"""Market calendar and trading session resolution module."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
import zoneinfo
import pandas as pd
import exchange_calendars as xcals

US_EASTERN = zoneinfo.ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PeriodInfo:
    """Encapsulates resolved date ranges and trading sessions for a report."""
    report_type: str                 # 'daily', 'weekly', 'monthly'
    as_of_date: str                  # Input or resolved target date (YYYY-MM-DD)
    session_date: str                # Current period latest trading session (YYYY-MM-DD)
    current_start: str               # Start date of current evaluation window (YYYY-MM-DD)
    current_end: str                 # End date of current evaluation window (YYYY-MM-DD)
    baseline_date: str               # Prior close used as denominator for current period return
    prev_period_start: str           # Prior period evaluation start (YYYY-MM-DD)
    prev_period_end: str             # Prior period evaluation end (YYYY-MM-DD)
    prev_baseline_date: str          # Denominator for prior period return
    is_partial: bool                 # True if period has not reached standard completion
    session_count: int               # Number of trading sessions in current period
    notes: str = ""


class MarketCalendar:
    """NYSE / US Equity market trading calendar wrapper."""

    def __init__(self, exchange: str = "XNYS"):
        self.cal = xcals.get_calendar(exchange)

    def is_trading_day(self, dt: date) -> bool:
        """Check if a date is a valid trading session."""
        ts = pd.Timestamp(dt)
        return self.cal.is_session(ts)

    def get_latest_session(self, dt: Optional[date] = None) -> date:
        """Get the most recent closed trading session on or before dt."""
        if dt is None:
            now_et = datetime.now(US_EASTERN)
            # If before 16:00 ET on a trading day, latest completed session is previous session
            if now_et.time() < datetime.strptime("16:00", "%H:%M").time():
                dt = (now_et - timedelta(days=1)).date()
            else:
                dt = now_et.date()

        ts = pd.Timestamp(dt)
        session_ts = self.cal.date_to_session(ts, direction="previous")
        return session_ts.date()

    def get_sessions_between(self, start: date, end: date) -> List[date]:
        """Get all trading sessions between start and end (inclusive)."""
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts > end_ts:
            return []
        sessions = self.cal.sessions_in_range(start_ts, end_ts)
        return [s.date() for s in sessions]

    def get_previous_session(self, dt: date) -> date:
        """Get the trading session strictly prior to dt."""
        ts = pd.Timestamp(dt)
        session_ts = self.cal.date_to_session(ts - pd.Timedelta(days=1), direction="previous")
        return session_ts.date()

    def is_last_trading_day_of_week(self, dt: date) -> bool:
        """Check if dt is the final active trading session of its calendar week (Mon-Sun).
        
        Correctly accounts for holiday closures (e.g. Good Friday making Thursday the last session).
        """
        if not self.is_trading_day(dt):
            return False
        mon = dt - timedelta(days=dt.weekday())
        sun = mon + timedelta(days=6)
        sessions_in_week = self.get_sessions_between(mon, sun)
        return bool(sessions_in_week and sessions_in_week[-1] == dt)

    def is_last_trading_day_of_month(self, dt: date) -> bool:
        """Check if dt is the final active trading session of its calendar month.
        
        Correctly accounts for months ending on weekends or market holidays.
        """
        if not self.is_trading_day(dt):
            return False
        _, last_day = calendar.monthrange(dt.year, dt.month)
        start_m = date(dt.year, dt.month, 1)
        end_m = date(dt.year, dt.month, last_day)
        sessions_in_month = self.get_sessions_between(start_m, end_m)
        return bool(sessions_in_month and sessions_in_month[-1] == dt)

    def is_scheduled_day_for_report(
        self,
        report_type: str,
        dt: Optional[date] = None,
    ) -> Tuple[bool, str]:
        """Verify whether target dt is scheduled to generate the requested report type.
        
        - daily: Runs on every open market trading session.
        - weekly: Runs only on the final trading session of the week (usually Friday, or Thursday before holiday).
        - monthly: Runs only on the final trading session of the calendar month.
        
        Returns:
            Tuple of (is_due: bool, reason: str)
        """
        if dt is None:
            now_et = datetime.now(US_EASTERN)
            dt = now_et.date()

        rep = report_type.lower()
        if not self.is_trading_day(dt):
            return False, f"Date {dt} is not an open market session (weekend or holiday)."

        if rep == "daily":
            return True, f"Date {dt} is an active trading session (Daily report due)."
        elif rep == "weekly":
            if self.is_last_trading_day_of_week(dt):
                return True, f"Date {dt} is the final trading session of the week (Weekly report due)."
            return False, f"Date {dt} is not the final trading session of the week (Weekly report not due)."
        elif rep == "monthly":
            if self.is_last_trading_day_of_month(dt):
                return True, f"Date {dt} is the final trading session of the month (Monthly report due)."
            return False, f"Date {dt} is not the final trading session of the month (Monthly report not due)."
        else:
            return False, f"Unknown report type: {report_type}"

    def resolve_period(self, report_type: str, target_date: Optional[date] = None) -> PeriodInfo:
        """Resolve full period boundaries and baseline dates for a report type.
        
        Args:
            report_type: 'daily', 'weekly', or 'monthly'
            target_date: Optional date. Defaults to current US/Eastern trading date.
            
        Returns:
            PeriodInfo with all required boundary dates.
        """
        report_type = report_type.lower()
        if report_type not in ("daily", "weekly", "monthly"):
            raise ValueError(f"Invalid report_type: {report_type}. Must be daily, weekly, or monthly.")

        session_date = self.get_latest_session(target_date)
        as_of_str = target_date.isoformat() if target_date else session_date.isoformat()

        if report_type == "daily":
            prev_session = self.get_previous_session(session_date)
            prev_prev_session = self.get_previous_session(prev_session)
            
            return PeriodInfo(
                report_type="daily",
                as_of_date=as_of_str,
                session_date=session_date.isoformat(),
                current_start=session_date.isoformat(),
                current_end=session_date.isoformat(),
                baseline_date=prev_session.isoformat(),
                prev_period_start=prev_session.isoformat(),
                prev_period_end=prev_session.isoformat(),
                prev_baseline_date=prev_prev_session.isoformat(),
                is_partial=False,
                session_count=1,
                notes=f"Daily session: {session_date.isoformat()} vs previous session: {prev_session.isoformat()}",
            )

        elif report_type == "weekly":
            weekday = session_date.weekday()  # Mon = 0, Sun = 6
            mon_this_week = session_date - timedelta(days=weekday)
            fri_this_week = mon_this_week + timedelta(days=4)

            sessions_this_week = self.get_sessions_between(mon_this_week, session_date)
            sun_prev_week = mon_this_week - timedelta(days=1)
            mon_prev_week = mon_this_week - timedelta(days=7)
            sessions_prev_week = self.get_sessions_between(mon_prev_week, sun_prev_week)
            
            baseline_for_this_week = sessions_prev_week[-1] if sessions_prev_week else self.get_previous_session(mon_this_week)

            prev_period_start = sessions_prev_week[0] if sessions_prev_week else mon_prev_week
            prev_period_end = sessions_prev_week[-1] if sessions_prev_week else sun_prev_week

            sun_two_weeks_ago = mon_prev_week - timedelta(days=1)
            mon_two_weeks_ago = mon_prev_week - timedelta(days=7)
            sessions_two_weeks_ago = self.get_sessions_between(mon_two_weeks_ago, sun_two_weeks_ago)
            prev_baseline_date = sessions_two_weeks_ago[-1] if sessions_two_weeks_ago else self.get_previous_session(mon_prev_week)

            all_possible_week_sessions = self.get_sessions_between(mon_this_week, fri_this_week)
            is_partial = session_date < fri_this_week or len(sessions_this_week) < len(all_possible_week_sessions)

            return PeriodInfo(
                report_type="weekly",
                as_of_date=as_of_str,
                session_date=session_date.isoformat(),
                current_start=sessions_this_week[0].isoformat() if sessions_this_week else mon_this_week.isoformat(),
                current_end=session_date.isoformat(),
                baseline_date=baseline_for_this_week.isoformat(),
                prev_period_start=prev_period_start.isoformat(),
                prev_period_end=prev_period_end.isoformat(),
                prev_baseline_date=prev_baseline_date.isoformat(),
                is_partial=is_partial,
                session_count=len(sessions_this_week),
                notes=f"Week-to-date ({len(sessions_this_week)} sessions) vs previous full week ({len(sessions_prev_week)} sessions)",
            )

        else:  # monthly
            first_of_month = session_date.replace(day=1)
            sessions_this_month = self.get_sessions_between(first_of_month, session_date)
            last_day_prev_month = first_of_month - timedelta(days=1)
            first_day_prev_month = last_day_prev_month.replace(day=1)

            sessions_prev_month = self.get_sessions_between(first_day_prev_month, last_day_prev_month)
            baseline_for_this_month = sessions_prev_month[-1] if sessions_prev_month else self.get_previous_session(first_of_month)

            last_day_two_months_ago = first_day_prev_month - timedelta(days=1)
            first_day_two_months_ago = last_day_two_months_ago.replace(day=1)
            sessions_two_months_ago = self.get_sessions_between(first_day_two_months_ago, last_day_two_months_ago)
            prev_baseline_date = sessions_two_months_ago[-1] if sessions_two_months_ago else self.get_previous_session(first_day_prev_month)

            next_month = (first_of_month + timedelta(days=32)).replace(day=1)
            last_day_this_month = next_month - timedelta(days=1)
            all_month_sessions = self.get_sessions_between(first_of_month, last_day_this_month)
            is_partial = session_date < all_month_sessions[-1] if all_month_sessions else True

            return PeriodInfo(
                report_type="monthly",
                as_of_date=as_of_str,
                session_date=session_date.isoformat(),
                current_start=sessions_this_month[0].isoformat() if sessions_this_month else first_of_month.isoformat(),
                current_end=session_date.isoformat(),
                baseline_date=baseline_for_this_month.isoformat(),
                prev_period_start=sessions_prev_month[0].isoformat() if sessions_prev_month else first_day_prev_month.isoformat(),
                prev_period_end=sessions_prev_month[-1].isoformat() if sessions_prev_month else last_day_prev_month.isoformat(),
                prev_baseline_date=prev_baseline_date.isoformat(),
                is_partial=is_partial,
                session_count=len(sessions_this_month),
                notes=f"Month-to-date ({len(sessions_this_month)} sessions) vs previous full month ({len(sessions_prev_month)} sessions)",
            )
