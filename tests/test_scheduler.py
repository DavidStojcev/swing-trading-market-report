"""Unit tests for market trading session scheduling and holiday detection."""

from datetime import date
import pytest

from data.calendar import MarketCalendar
from report import generate_market_report


@pytest.fixture
def market_calendar() -> MarketCalendar:
    return MarketCalendar()


def test_standard_week_and_month_sessions(market_calendar):
    """Test standard Friday is last day of week and last day of month on a weekday."""
    # Friday April 26, 2024 is the last session of its week
    fri = date(2024, 4, 26)
    assert market_calendar.is_trading_day(fri) is True
    assert market_calendar.is_last_trading_day_of_week(fri) is True
    assert market_calendar.is_last_trading_day_of_month(fri) is False

    # Tuesday April 30, 2024 is the last session of the month
    tue = date(2024, 4, 30)
    assert market_calendar.is_trading_day(tue) is True
    assert market_calendar.is_last_trading_day_of_week(tue) is False
    assert market_calendar.is_last_trading_day_of_month(tue) is True


def test_holiday_week_and_month_edge_cases(market_calendar):
    """Test Good Friday 2024 holiday where Thursday March 28 was the last trading day of week and month."""
    # March 29, 2024 was Good Friday (NYSE market holiday)
    good_fri = date(2024, 3, 29)
    assert market_calendar.is_trading_day(good_fri) is False

    # Thursday March 28, 2024 should be recognized as BOTH last day of week and last day of month
    thu = date(2024, 3, 28)
    assert market_calendar.is_trading_day(thu) is True
    assert market_calendar.is_last_trading_day_of_week(thu) is True
    assert market_calendar.is_last_trading_day_of_month(thu) is True


def test_weekend_not_trading_session(market_calendar):
    """Verify Saturday and Sunday are never recognized as trading sessions."""
    sat = date(2024, 3, 30)
    sun = date(2024, 3, 31)
    assert market_calendar.is_trading_day(sat) is False
    assert market_calendar.is_trading_day(sun) is False
    assert market_calendar.is_last_trading_day_of_week(sat) is False
    assert market_calendar.is_last_trading_day_of_month(sun) is False


def test_is_scheduled_day_for_report(market_calendar):
    """Verify is_scheduled_day_for_report decisions across daily, weekly, and monthly."""
    # Mid-week trading day (Wed April 24, 2024)
    wed = date(2024, 4, 24)
    due_daily, _ = market_calendar.is_scheduled_day_for_report("daily", wed)
    due_weekly, _ = market_calendar.is_scheduled_day_for_report("weekly", wed)
    due_monthly, _ = market_calendar.is_scheduled_day_for_report("monthly", wed)

    assert due_daily is True
    assert due_weekly is False
    assert due_monthly is False

    # Weekend (Sunday April 28, 2024)
    sun = date(2024, 4, 28)
    due_sun, reason_sun = market_calendar.is_scheduled_day_for_report("daily", sun)
    assert due_sun is False
    assert "not an open market session" in reason_sun


def test_if_scheduled_day_cli_exit(tmp_path):
    """Test that generate_market_report with if_scheduled_day=True skips cleanly when not due."""
    # Wednesday is not weekly report day
    result = generate_market_report(
        report_type="weekly",
        target_date="2026-10-21",  # Wednesday
        output_dir=str(tmp_path),
        if_scheduled_day=True,
    )
    assert result.get("status") == "skipped"
    assert "Weekly report not due" in result.get("reason", "")
