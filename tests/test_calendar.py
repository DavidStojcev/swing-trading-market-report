"""Tests for market calendar and trading session resolution."""

from datetime import date
import pytest
from data.calendar import MarketCalendar


def test_trading_day_detection():
    cal = MarketCalendar()
    # Wednesday 2026-10-21 is a trading day
    assert cal.is_trading_day(date(2026, 10, 21)) is True
    # Saturday 2026-10-24 is not a trading day
    assert cal.is_trading_day(date(2026, 10, 24)) is False
    # Sunday 2026-10-25 is not a trading day
    assert cal.is_trading_day(date(2026, 10, 25)) is False


def test_weekend_date_resolves_to_prior_friday():
    cal = MarketCalendar()
    # Sunday 2026-10-25 should resolve to Friday 2026-10-23
    resolved = cal.get_latest_session(date(2026, 10, 25))
    assert resolved == date(2026, 10, 23)
    assert cal.is_trading_day(resolved) is True


def test_daily_period_resolution():
    cal = MarketCalendar()
    period = cal.resolve_period("daily", date(2026, 10, 22))
    assert period.report_type == "daily"
    assert period.session_date == "2026-10-22"
    # Baseline for daily is previous trading session
    assert period.baseline_date == "2026-10-21"
    assert period.prev_period_end == "2026-10-21"
    assert period.prev_baseline_date == "2026-10-20"
    assert period.is_partial is False


def test_weekly_period_resolution():
    cal = MarketCalendar()
    # Thursday 2026-10-22
    period = cal.resolve_period("weekly", date(2026, 10, 22))
    assert period.report_type == "weekly"
    assert period.session_date == "2026-10-22"
    # Current week starts on Monday 2026-10-19
    assert period.current_start == "2026-10-19"
    # Prior week baseline is Friday 2026-10-16
    assert period.baseline_date == "2026-10-16"
    assert period.prev_period_end == "2026-10-16"
    # Mid-week is marked partial
    assert period.is_partial is True


def test_monthly_period_resolution():
    cal = MarketCalendar()
    # 2026-10-22 is in October
    period = cal.resolve_period("monthly", date(2026, 10, 22))
    assert period.report_type == "monthly"
    assert period.session_date == "2026-10-22"
    # Current month starts on first trading day of October (2026-10-01)
    assert period.current_start == "2026-10-01"
    # Baseline is last trading day of September 2026 (2026-09-30)
    assert period.baseline_date == "2026-09-30"
    assert period.prev_period_end == "2026-09-30"
    # Mid-month is partial
    assert period.is_partial is True
