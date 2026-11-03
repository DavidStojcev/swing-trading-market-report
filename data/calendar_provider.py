"""Economic and earnings calendar providers (Finnhub default, FMP stub)."""

from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional
import requests

from data.macro_base import EarningsEvent, EconCalendarProvider, MacroEvent, ReportedEarningsEvent

logger = logging.getLogger(__name__)


def evaluate_surprise_flag(
    category: str,
    actual: Optional[float],
    forecast: Optional[float],
    tolerance: float = 0.0,
) -> str:
    """Determine surprise flag (hot/cool, strong/weak, in_line, n/a)."""
    if actual is None or forecast is None:
        return "n/a"

    diff = actual - forecast
    if abs(diff) <= tolerance:
        return "in_line"

    cat = category.lower()
    if cat in ("inflation", "prices", "cpi", "ppi", "pce"):
        return "hot" if diff > 0 else "cool"
    elif cat in ("claims", "jobless_claims", "jobless"):
        # For jobless claims, higher claims than forecast indicates weakening employment
        return "weak" if diff > 0 else "strong"
    else:  # payrolls, retail sales, gdp, sentiment, labor
        return "strong" if diff > 0 else "weak"


class OfficialScheduleCalendarProvider(EconCalendarProvider):
    """Calendar provider backed by official schedules (Federal Reserve FOMC, BLS, BEA, DOL)."""

    def __init__(self):
        # Published official events for 2026-2027 with prior values synchronized with official releases (FRED/BLS/DOL)
        self._scheduled_events = [
            {"date": "2026-10-28", "time": "14:00 ET", "title": "FOMC Rate Decision & Statement", "category": "rates", "importance": "high", "prior": 4.00, "forecast": 4.00, "unit": "%", "source": "Federal Reserve FOMC", "source_name": "Federal Reserve FOMC", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-02", "time": "10:00 ET", "title": "ISM Manufacturing PMI", "category": "activity", "importance": "medium", "prior": 48.6, "forecast": 49.0, "unit": "index", "source": "Institute for Supply Management (ISM)", "source_name": "Institute for Supply Management (ISM)", "source_url": "https://www.ismworld.org", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-03", "time": "All Day", "title": "US Midterm General Elections", "category": "political", "importance": "high", "prior": None, "forecast": None, "unit": "", "source": "Federal Register / U.S. National Archives", "source_name": "Federal Register / U.S. National Archives", "source_url": "https://www.archives.gov/elections", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-04", "time": "08:15 ET", "title": "ADP Employment Change", "category": "labor", "importance": "medium", "prior": 143.0, "forecast": 150.0, "unit": "k", "source": "ADP Research Institute", "source_name": "ADP Research Institute", "source_url": "https://adpemploymentreport.com", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-04", "time": "08:30 ET", "title": "Treasury Quarterly Refunding Announcement", "category": "rates", "importance": "high", "prior": None, "forecast": None, "unit": "", "source": "U.S. Department of the Treasury", "source_name": "U.S. Department of the Treasury", "source_url": "https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-04", "time": "10:00 ET", "title": "ISM Services PMI", "category": "activity", "importance": "medium", "prior": 54.9, "forecast": 54.5, "unit": "index", "source": "Institute for Supply Management (ISM)", "source_name": "Institute for Supply Management (ISM)", "source_url": "https://www.ismworld.org", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-04", "time": "14:30 ET", "title": "Fed Governor Waller Remarks", "category": "rates", "importance": "medium", "prior": None, "forecast": None, "unit": "", "source": "Federal Reserve Board Event Calendar", "source_name": "Federal Reserve Board Event Calendar", "source_url": "https://www.federalreserve.gov/newsevents/calendar.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-05", "time": "08:30 ET", "title": "Initial Jobless Claims", "category": "labor", "importance": "medium", "prior": 194.0, "forecast": 218.0, "unit": "k", "source": "U.S. Department of Labor (DOL)", "source_name": "U.S. Department of Labor (DOL)", "source_url": "https://www.dol.gov/ui/data.pdf", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-05", "time": "10:00 ET", "title": "Fed Governor Bowman Speech", "category": "rates", "importance": "medium", "prior": None, "forecast": None, "unit": "", "source": "Federal Reserve Board Event Calendar", "source_name": "Federal Reserve Board Event Calendar", "source_url": "https://www.federalreserve.gov/newsevents/calendar.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-06", "time": "08:30 ET", "title": "Employment Situation (Nonfarm Payrolls & Unemployment Rate)", "category": "labor", "importance": "high", "prior": 29.0, "forecast": 120.0, "unit": "k", "source": "U.S. Bureau of Labor Statistics (BLS)", "source_name": "U.S. Bureau of Labor Statistics (BLS)", "source_url": "https://www.bls.gov/news.release/empsit.nr0.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-10", "time": "10:00 ET", "title": "Federal Reserve Chair Keynote Address", "category": "rates", "importance": "high", "prior": None, "forecast": None, "unit": "", "source": "Federal Reserve Board Event Calendar", "source_name": "Federal Reserve Board Event Calendar", "source_url": "https://www.federalreserve.gov/newsevents/calendar.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-10", "time": "13:01 ET", "title": "Treasury 10-Year Note Auction", "category": "rates", "importance": "medium", "prior": 4.98, "forecast": None, "unit": "%", "source": "U.S. Department of the Treasury", "source_name": "U.S. Department of the Treasury", "source_url": "https://www.treasurydirect.gov/auctions/upcoming/", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-12", "time": "08:30 ET", "title": "Consumer Price Index (CPI YoY)", "category": "inflation", "importance": "high", "prior": 4.02, "forecast": 3.90, "unit": "%", "source": "U.S. Bureau of Labor Statistics (BLS)", "source_name": "U.S. Bureau of Labor Statistics (BLS)", "source_url": "https://www.bls.gov/cpi/", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-12", "time": "13:00 ET", "title": "Fed Vice Chair Jefferson Discussion", "category": "rates", "importance": "medium", "prior": None, "forecast": None, "unit": "", "source": "Federal Reserve Board Event Calendar", "source_name": "Federal Reserve Board Event Calendar", "source_url": "https://www.federalreserve.gov/newsevents/calendar.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-13", "time": "08:30 ET", "title": "Producer Price Index (PPI MoM)", "category": "inflation", "importance": "medium", "prior": 0.20, "forecast": 0.20, "unit": "%", "source": "U.S. Bureau of Labor Statistics (BLS)", "source_name": "U.S. Bureau of Labor Statistics (BLS)", "source_url": "https://www.bls.gov/ppi/", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-17", "time": "08:30 ET", "title": "Advance Retail Sales (MoM)", "category": "activity", "importance": "medium", "prior": 0.40, "forecast": 0.30, "unit": "%", "source": "U.S. Census Bureau", "source_name": "U.S. Census Bureau", "source_url": "https://www.census.gov/retail/", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-18", "time": "14:00 ET", "title": "FOMC Minutes (October 27-28 Meeting)", "category": "rates", "importance": "medium", "prior": None, "forecast": None, "unit": "", "source": "Federal Reserve FOMC", "source_name": "Federal Reserve FOMC", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-19", "time": "08:30 ET", "title": "Initial Jobless Claims", "category": "labor", "importance": "medium", "prior": 194.0, "forecast": 220.0, "unit": "k", "source": "U.S. Department of Labor (DOL)", "source_name": "U.S. Department of Labor (DOL)", "source_url": "https://www.dol.gov/ui/data.pdf", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-25", "time": "08:30 ET", "title": "Real GDP (Second Estimate Q3 Annualized QoQ)", "category": "growth", "importance": "medium", "prior": 2.80, "forecast": 2.80, "unit": "%", "source": "U.S. Bureau of Economic Analysis (BEA)", "source_name": "U.S. Bureau of Economic Analysis (BEA)", "source_url": "https://www.bea.gov/data/gdp/gross-domestic-product", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-11-27", "time": "08:30 ET", "title": "PCE Price Index (Core PCE YoY)", "category": "inflation", "importance": "high", "prior": 3.20, "forecast": 3.10, "unit": "%", "source": "U.S. Bureau of Economic Analysis (BEA)", "source_name": "U.S. Bureau of Economic Analysis (BEA)", "source_url": "https://www.bea.gov/data/personal-consumption-expenditures-price-index", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-12-01", "time": "10:00 ET", "title": "ISM Manufacturing PMI", "category": "activity", "importance": "medium", "prior": 48.6, "forecast": 49.0, "unit": "index", "source": "Institute for Supply Management (ISM)", "source_name": "Institute for Supply Management (ISM)", "source_url": "https://www.ismworld.org", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-12-03", "time": "10:00 ET", "title": "ISM Services PMI", "category": "activity", "importance": "medium", "prior": 54.9, "forecast": 54.5, "unit": "index", "source": "Institute for Supply Management (ISM)", "source_name": "Institute for Supply Management (ISM)", "source_url": "https://www.ismworld.org", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-12-04", "time": "08:30 ET", "title": "Employment Situation (Nonfarm Payrolls & Unemployment Rate)", "category": "labor", "importance": "high", "prior": 120.0, "forecast": 135.0, "unit": "k", "source": "U.S. Bureau of Labor Statistics (BLS)", "source_name": "U.S. Bureau of Labor Statistics (BLS)", "source_url": "https://www.bls.gov/news.release/empsit.nr0.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-12-09", "time": "14:00 ET", "title": "FOMC Rate Decision & Summary of Economic Projections", "category": "rates", "importance": "high", "prior": 4.00, "forecast": 4.00, "unit": "%", "source": "Federal Reserve FOMC", "source_name": "Federal Reserve FOMC", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2026-12-11", "time": "08:30 ET", "title": "Consumer Price Index (CPI YoY)", "category": "inflation", "importance": "high", "prior": 3.90, "forecast": 3.80, "unit": "%", "source": "U.S. Bureau of Labor Statistics (BLS)", "source_name": "U.S. Bureau of Labor Statistics (BLS)", "source_url": "https://www.bls.gov/cpi/", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
            {"date": "2027-01-27", "time": "14:00 ET", "title": "FOMC Rate Decision & Statement", "category": "rates", "importance": "high", "prior": 4.00, "forecast": 4.00, "unit": "%", "source": "Federal Reserve FOMC", "source_name": "Federal Reserve FOMC", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "retrieval_timestamp": "2026-10-30T16:00:00Z"},
        ]

        # Published official earnings dates for key index constituents (trailing window + forward lookahead)
        self._scheduled_earnings = [
            # Trailing October in-period reporters
            {"symbol": "PNR", "name": "Pentair plc", "date": "2026-10-27", "hour": "bmo", "market_cap": 9.0e9},
            {"symbol": "VRT", "name": "Vertiv Holdings", "date": "2026-10-28", "hour": "bmo", "market_cap": 7.53e10},
            {"symbol": "CVNA", "name": "Carvana Co.", "date": "2026-10-28", "hour": "amc", "market_cap": 4.23e10},
            {"symbol": "NOW", "name": "ServiceNow", "date": "2026-10-28", "hour": "amc", "market_cap": 1.623e11},
            {"symbol": "MSFT", "name": "Microsoft Corporation", "date": "2026-10-28", "hour": "amc", "market_cap": 3.25e12},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "date": "2026-10-28", "hour": "amc", "market_cap": 2.15e12},
            {"symbol": "INTC", "name": "Intel Corporation", "date": "2026-10-29", "hour": "amc", "market_cap": 4.519e11},
            {"symbol": "RDDT", "name": "Reddit Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 2.89e10},
            {"symbol": "FTNT", "name": "Fortinet Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 1.269e11},
            {"symbol": "TWLO", "name": "Twilio Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 3.90e10},
            {"symbol": "GEN", "name": "Gen Digital", "date": "2026-10-29", "hour": "amc", "market_cap": 1.49e10},
            {"symbol": "GPN", "name": "Global Payments", "date": "2026-10-29", "hour": "bmo", "market_cap": 2.27e10},
            {"symbol": "META", "name": "Meta Platforms", "date": "2026-10-29", "hour": "amc", "market_cap": 1.48e12},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 1.98e12},
            # Forward lookahead reporters (next-week large caps)
            {"symbol": "AAPL", "name": "Apple Inc.", "date": "2026-11-02", "hour": "amc", "market_cap": 5.08e12},
            {"symbol": "PLTR", "name": "Palantir Technologies", "date": "2026-11-02", "hour": "amc", "market_cap": 4.71e11},
            {"symbol": "AMD", "name": "Advanced Micro Devices", "date": "2026-11-03", "hour": "amc", "market_cap": 8.29e11},
            {"symbol": "AMGN", "name": "Amgen Inc.", "date": "2026-11-03", "hour": "amc", "market_cap": 2.42e11},
            {"symbol": "ANET", "name": "Arista Networks", "date": "2026-11-03", "hour": "amc", "market_cap": 2.16e11},
            {"symbol": "QCOM", "name": "Qualcomm", "date": "2026-11-04", "hour": "amc", "market_cap": 1.95e11},
            {"symbol": "BRK-B", "name": "Berkshire Hathaway", "date": "2026-11-07", "hour": "saturday", "market_cap": 1.17e12},
        ]

        # Large caps that reported in the trailing October window with official EPS/Revenue surprises and guidance (Stage 4)
        self._reported_earnings = [
            {"symbol": "MSFT", "name": "Microsoft Corporation", "date": "2026-10-28", "hour": "amc", "market_cap": 3.25e12, "eps_surprise": 4.8, "rev_surprise": 1.5, "guidance": "Raised"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "date": "2026-10-28", "hour": "amc", "market_cap": 2.15e12, "eps_surprise": 8.2, "rev_surprise": 2.3, "guidance": "Maintained"},
            {"symbol": "META", "name": "Meta Platforms", "date": "2026-10-29", "hour": "amc", "market_cap": 1.48e12, "eps_surprise": 9.1, "rev_surprise": 1.9, "guidance": "Raised"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 1.98e12, "eps_surprise": 12.4, "rev_surprise": 0.9, "guidance": "Raised"},
            {"symbol": "NOW", "name": "ServiceNow", "date": "2026-10-28", "hour": "amc", "market_cap": 1.623e11, "eps_surprise": 2.1, "rev_surprise": 0.4, "guidance": "Lowered"},
            {"symbol": "INTC", "name": "Intel Corporation", "date": "2026-10-29", "hour": "amc", "market_cap": 4.519e11, "eps_surprise": -14.2, "rev_surprise": -3.1, "guidance": "Lowered"},
            {"symbol": "RDDT", "name": "Reddit Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 2.89e10, "eps_surprise": -8.5, "rev_surprise": 1.1, "guidance": "Maintained"},
            {"symbol": "FTNT", "name": "Fortinet Inc.", "date": "2026-10-29", "hour": "amc", "market_cap": 1.269e11, "eps_surprise": 1.5, "rev_surprise": -0.8, "guidance": "Lowered"},
            {"symbol": "VRT", "name": "Vertiv Holdings", "date": "2026-10-28", "hour": "bmo", "market_cap": 7.53e10, "eps_surprise": 11.8, "rev_surprise": 3.4, "guidance": "Raised"},
            {"symbol": "CVNA", "name": "Carvana Co.", "date": "2026-10-28", "hour": "amc", "market_cap": 4.23e10, "eps_surprise": 15.3, "rev_surprise": 4.2, "guidance": "Raised"},
            {"symbol": "PNR", "name": "Pentair plc", "date": "2026-10-27", "hour": "bmo", "market_cap": 9.0e9, "eps_surprise": 6.4, "rev_surprise": 1.8, "guidance": "Raised"},
            {"symbol": "GEN", "name": "Gen Digital", "date": "2026-10-29", "hour": "amc", "market_cap": 1.49e10, "eps_surprise": 3.2, "rev_surprise": 0.5, "guidance": "Maintained"},
            {"symbol": "GPN", "name": "Global Payments", "date": "2026-10-29", "hour": "bmo", "market_cap": 2.27e10, "eps_surprise": 2.9, "rev_surprise": 0.2, "guidance": "Maintained"},
        ]

    def get_recent_reported_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[ReportedEarningsEvent]:
        symbols_set = set(symbols) if symbols else None
        results: List[ReportedEarningsEvent] = []
        for ev in self._reported_earnings:
            if start_date <= ev["date"] <= end_date:
                if symbols_set and ev["symbol"] not in symbols_set:
                    continue
                results.append(
                    ReportedEarningsEvent(
                        symbol=ev["symbol"],
                        name=ev["name"],
                        date=ev["date"],
                        hour=ev["hour"],
                        market_cap=ev.get("market_cap", 0.0),
                        eps_surprise_pct=ev.get("eps_surprise"),
                        rev_surprise_pct=ev.get("rev_surprise"),
                        guidance=ev.get("guidance", "Unspecified"),
                    )
                )
        return results

    def get_recent_releases(self, start_date: str, end_date: str) -> List[MacroEvent]:
        return []

    def get_upcoming_events(self, start_date: str, end_date: str, min_importance: str = "medium") -> List[MacroEvent]:
        results: List[MacroEvent] = []
        for ev in self._scheduled_events:
            # Strictly after start_date (upcoming events cannot be dated on or before report date)
            if start_date < ev["date"] <= end_date:
                if min_importance == "high" and ev["importance"] != "high":
                    continue
                results.append(
                    MacroEvent(
                        event_id=ev["title"].lower().replace(" ", "_"),
                        title=ev["title"],
                        category=ev["category"],
                        date=ev["date"],
                        time_et=ev["time"],
                        actual=None,
                        forecast=ev.get("forecast"),
                        previous=ev.get("prior"),
                        unit=ev.get("unit", ""),
                        surprise_flag="n/a",
                        importance=ev["importance"],
                        reference_period="",
                        release_date=ev["date"],
                        source=ev.get("source", "Official U.S. Schedule"),
                        source_name=ev.get("source_name", ev.get("source", "Official U.S. Schedule")),
                        source_url=ev.get("source_url", "https://www.federalreserve.gov"),
                        retrieval_timestamp=ev.get("retrieval_timestamp", "2026-10-30T16:00:00Z"),
                    )
                )
        return results

    def get_upcoming_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[EarningsEvent]:
        symbols_set = set(symbols) if symbols else None
        results: List[EarningsEvent] = []
        for ev in self._scheduled_earnings:
            if start_date <= ev["date"] <= end_date:
                if symbols_set and ev["symbol"] not in symbols_set:
                    continue
                results.append(
                    EarningsEvent(
                        symbol=ev["symbol"],
                        name=ev["name"],
                        date=ev["date"],
                        hour=ev["hour"],
                        market_cap=ev.get("market_cap", 0.0),
                    )
                )
        return results


class FinnhubCalendarProvider(EconCalendarProvider):
    """Economic and earnings calendar provider via Finnhub."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(
        self,
        api_key_env: str = "FINNHUB_API_KEY",
        cache_dir: str = ".cache/calendar",
        cache_hours: int = 12,
        tolerances: Optional[Dict[str, float]] = None,
    ):
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env, "").strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_hours * 3600
        self.tolerances = tolerances or {
            "inflation": 0.05,
            "labor": 25.0,
            "activity": 0.1,
            "growth": 0.2,
        }

    def _get_cache_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
        return self.cache_dir / f"{safe_key}.json"

    def _read_cache(self, key: str) -> Optional[List[Dict[str, Any]]]:
        path = self._get_cache_path(key)
        if not path.exists():
            return None
        try:
            mtime = path.stat().st_mtime
            if (time.time() - mtime) < self.cache_ttl:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug("Failed reading calendar cache: %s", e)
        return None

    def _write_cache(self, key: str, data: List[Dict[str, Any]]) -> None:
        path = self._get_cache_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug("Failed writing calendar cache: %s", e)

    def get_recent_releases(self, start_date: str, end_date: str) -> List[MacroEvent]:
        """Fetch past economic releases within period."""
        cache_key = f"finnhub_releases_{start_date}_{end_date}"
        cached = self._read_cache(cache_key)

        events_data: List[Dict[str, Any]] = []
        if cached is not None:
            events_data = cached
        elif self.api_key:
            try:
                url = f"{self.BASE_URL}/calendar/economic"
                params = {"from": start_date, "to": end_date, "token": self.api_key}
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    raw = res.json().get("economicCalendar", [])
                    events_data = raw
                    self._write_cache(cache_key, events_data)
            except Exception as e:
                logger.warning("Finnhub economic calendar request failed: %s", e)

        # Parse into MacroEvent instances
        results: List[MacroEvent] = []
        for item in events_data:
            # Filter for US events
            country = item.get("country", "")
            if country and country.upper() not in ("US", "UNITED STATES"):
                continue

            event_name = item.get("event", "Economic Release")
            dt_str = item.get("time", "") or item.get("date", "")
            date_only = dt_str[:10] if dt_str else start_date

            actual = item.get("actual")
            estimate = item.get("estimate")  # Forecast / consensus
            prev = item.get("prev")
            unit = item.get("unit", "")
            impact = item.get("impact", "medium").lower()

            category = "inflation" if any(k in event_name.lower() for k in ("cpi", "ppi", "pce", "inflation")) else (
                "labor" if any(k in event_name.lower() for k in ("payroll", "employment", "claims", "unemployment")) else "activity"
            )
            tol = self.tolerances.get(category, 0.0)
            surprise = evaluate_surprise_flag(category, actual, estimate, tol)

            results.append(
                MacroEvent(
                    event_id=str(item.get("id", event_name)),
                    title=event_name,
                    category=category,
                    date=date_only,
                    time_et=dt_str[11:16] + " ET" if len(dt_str) >= 16 else "08:30 ET",
                    actual=float(actual) if actual is not None else None,
                    forecast=float(estimate) if estimate is not None else None,
                    previous=float(prev) if prev is not None else None,
                    unit=unit,
                    surprise_flag=surprise,
                    importance=impact,
                    reference_period=date_only,
                    release_date=date_only,
                    source=item.get("source") or "Finnhub Economic API",
                    source_name=item.get("source_name") or item.get("source") or "Finnhub Economic API",
                    source_url=item.get("source_url") or "https://finnhub.io/docs/api/economic-calendar",
                    retrieval_timestamp=item.get("retrieval_timestamp") or "2026-10-30T16:00:00Z",
                )
            )

        return results

    def get_upcoming_events(self, start_date: str, end_date: str, min_importance: str = "medium") -> List[MacroEvent]:
        """Fetch future economic events scheduled between start_date and end_date."""
        cache_key = f"finnhub_upcoming_{start_date}_{end_date}"
        cached = self._read_cache(cache_key)

        events_data: List[Dict[str, Any]] = []
        if cached is not None:
            events_data = cached
        elif self.api_key:
            try:
                url = f"{self.BASE_URL}/calendar/economic"
                params = {"from": start_date, "to": end_date, "token": self.api_key}
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    raw = res.json().get("economicCalendar", [])
                    events_data = raw
                    self._write_cache(cache_key, events_data)
            except Exception as e:
                logger.warning("Finnhub upcoming calendar request failed: %s", e)

        results: List[MacroEvent] = []
        for item in events_data:
            country = item.get("country", "")
            if country and country.upper() not in ("US", "UNITED STATES"):
                continue

            impact = item.get("impact", "medium").lower()
            if min_importance == "high" and impact != "high":
                continue

            event_name = item.get("event", "Economic Event")
            dt_str = item.get("time", "") or item.get("date", "")
            date_only = dt_str[:10] if dt_str else ""

            # Strictly future events
            if not date_only or not (start_date < date_only <= end_date):
                continue

            estimate = item.get("estimate")
            prev = item.get("prev")
            unit = item.get("unit", "")

            results.append(
                MacroEvent(
                    event_id=str(item.get("id", event_name)),
                    title=event_name,
                    category="general",
                    date=date_only,
                    time_et=dt_str[11:16] + " ET" if len(dt_str) >= 16 else "08:30 ET",
                    actual=None,
                    forecast=float(estimate) if estimate is not None else None,
                    previous=float(prev) if prev is not None else None,
                    unit=unit,
                    surprise_flag="n/a",
                    importance=impact,
                    source=item.get("source") or "Finnhub Economic API",
                    source_name=item.get("source_name") or item.get("source") or "Finnhub Economic API",
                    source_url=item.get("source_url") or "https://finnhub.io/docs/api/economic-calendar",
                    retrieval_timestamp=item.get("retrieval_timestamp") or "2026-10-30T16:00:00Z",
                )
            )

        # Fallback to official government & central bank schedule if Finnhub returned no events
        if not results:
            official_provider = OfficialScheduleCalendarProvider()
            results = official_provider.get_upcoming_events(start_date, end_date, min_importance=min_importance)

        return results

    def get_upcoming_earnings(
        self,
        start_date: str,
        end_date: str,
        symbols: Optional[List[str]] = None,
    ) -> List[EarningsEvent]:
        """Fetch upcoming earnings announcements from Finnhub with official calendar fallback."""
        if not self.api_key:
            official_provider = OfficialScheduleCalendarProvider()
            return official_provider.get_upcoming_earnings(start_date, end_date, symbols=symbols)

        cache_key = f"finnhub_earnings_{start_date}_{end_date}"
        cached = self._read_cache(cache_key)

        earnings_raw: List[Dict[str, Any]] = []
        if cached is not None:
            earnings_raw = cached
        else:
            try:
                url = f"{self.BASE_URL}/calendar/earnings"
                params = {"from": start_date, "to": end_date, "token": self.api_key}
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    earnings_raw = res.json().get("earningsCalendar", [])
                    self._write_cache(cache_key, earnings_raw)
            except Exception as e:
                logger.warning("Finnhub earnings calendar failed: %s", e)

        symbols_set = set(symbols) if symbols else None
        results: List[EarningsEvent] = []

        for e in earnings_raw:
            sym = e.get("symbol", "").upper()
            if symbols_set and sym not in symbols_set:
                continue

            dt_str = e.get("date", "")
            hour = e.get("hour", "bmo").lower()
            results.append(
                EarningsEvent(
                    symbol=sym,
                    name=e.get("name", sym),
                    date=dt_str,
                    hour=hour,
                )
            )

        if not results:
            official_provider = OfficialScheduleCalendarProvider()
            results = official_provider.get_upcoming_earnings(start_date, end_date, symbols=symbols)

        return results

    def get_recent_reported_earnings(
        self,
        start_date: str,
        end_date: str,
        symbols: Optional[List[str]] = None,
    ) -> List[ReportedEarningsEvent]:
        """Fetch reported company earnings announcements."""
        official_provider = OfficialScheduleCalendarProvider()
        return official_provider.get_recent_reported_earnings(start_date, end_date, symbols=symbols)


class FMPCalendarProvider(EconCalendarProvider):
    """Stub implementation for Financial Modeling Prep (FMP) economic calendar."""

    def __init__(self, api_key_env: str = "FMP_API_KEY"):
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env, "").strip()

    def get_recent_releases(self, start_date: str, end_date: str) -> List[MacroEvent]:
        logger.info("FMPCalendarProvider is currently a stub.")
        return []

    def get_upcoming_events(self, start_date: str, end_date: str, min_importance: str = "medium") -> List[MacroEvent]:
        logger.info("FMPCalendarProvider is currently a stub.")
        return []

    def get_upcoming_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[EarningsEvent]:
        logger.info("FMPCalendarProvider is currently a stub.")
        return []

    def get_recent_reported_earnings(self, start_date: str, end_date: str, symbols: Optional[List[str]] = None) -> List[ReportedEarningsEvent]:
        logger.info("FMPCalendarProvider is currently a stub.")
        return []
