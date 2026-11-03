"""FRED API client and economic series transformation engine."""

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


@dataclass
class MacroMetricSnapshot:
    """Calculated macro indicators ready for reporting and scoring."""
    series_id: str
    name: str
    latest_date: str
    latest_value: float
    headline_value: float       # Transformed: e.g. YoY % or MoM % or net change
    headline_unit: str          # '% YoY', '% MoM', 'k', '%', 'pts'
    prior_value: float
    prior_headline: float
    mom_pct: Optional[float] = None
    prior_mom_pct: Optional[float] = None
    yoy_pct: Optional[float] = None
    change: Optional[float] = None
    four_week_avg: Optional[float] = None
    prior_four_week_avg: Optional[float] = None
    period_start_value: Optional[float] = None
    period_change: Optional[float] = None
    notes: str = ""


@dataclass
class MacroHistoricalPoint:
    """Historical data observation for monthly and yearly trend tracking."""
    date_str: str          # e.g. "2026-09-01"
    label: str             # e.g. "Sep 2026"
    monthly_val: float     # MoM % or net monthly change
    yearly_val: float      # YoY % or 12M change
    raw_level: float       # Raw observation value


@dataclass
class MacroHistoricalSeries:
    """A series with historical monthly and yearly observations."""
    series_id: str
    name: str
    category: str          # "Inflation", "Labor", "Growth", "Rates"
    monthly_unit: str      # "% MoM", "k", "%", etc.
    yearly_unit: str       # "% YoY", "k", "bps", "%", etc.
    points: List[MacroHistoricalPoint]

    @property
    def latest_point(self) -> Optional[MacroHistoricalPoint]:
        return self.points[-1] if self.points else None

    @property
    def prior_point(self) -> Optional[MacroHistoricalPoint]:
        return self.points[-2] if len(self.points) >= 2 else None

    @property
    def trend_direction(self) -> str:
        """Assess whether trajectory is rising, falling, or steady."""
        if len(self.points) < 2:
            return "Steady"
        lookback_idx = -4 if len(self.points) >= 4 else -2
        if self.category == "Rates & Policy" or self.series_id in ("UNRATE", "UMCSENT"):
            diff = self.points[-1].monthly_val - self.points[lookback_idx].monthly_val
        else:
            diff = self.points[-1].yearly_val - self.points[lookback_idx].yearly_val
        if abs(diff) < 0.05:
            return "Steady"
        return "Rising" if diff > 0 else "Falling"


class FredProvider:
    """Resilient client for Federal Reserve Economic Data (FRED)."""

    BASE_API_URL = "https://api.stlouisfed.org/fred/series/observations"
    PUBLIC_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(
        self,
        api_key_env: str = "FRED_API_KEY",
        cache_dir: str = ".cache/fred",
        cache_days: int = 7,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        allow_public_fallback: bool = True,
    ):
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env, "").strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_days * 86400
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.allow_public_fallback = allow_public_fallback

    def _get_cache_path(self, series_id: str) -> Path:
        return self.cache_dir / f"{series_id}.json"

    def _read_cache(self, series_id: str) -> Optional[pd.DataFrame]:
        path = self._get_cache_path(series_id)
        if not path.exists():
            return None
        try:
            mtime = path.stat().st_mtime
            if (time.time() - mtime) < self.cache_ttl:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
                if not df.empty:
                    df["date"] = pd.to_datetime(df["date"])
                    df["value"] = pd.to_numeric(df["value"], errors="coerce")
                    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
                    return df
        except Exception as e:
            logger.debug("Failed reading cache for series %s: %s", series_id, e)
        return None

    def _write_cache(self, series_id: str, df: pd.DataFrame) -> None:
        path = self._get_cache_path(series_id)
        try:
            export_df = df.copy()
            export_df["date"] = export_df["date"].dt.strftime("%Y-%m-%d")
            records = export_df[["date", "value"]].to_dict(orient="records")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            logger.debug("Failed writing cache for series %s: %s", series_id, e)

    def fetch_series(self, series_id: str, as_of_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Fetch historical observations for a series, respecting cache and as_of_date."""
        df = self._read_cache(series_id)

        if df is None or df.empty:
            df = self._fetch_from_network(series_id)

        if df is None or df.empty:
            return None

        # Filter strictly <= as_of_date to eliminate lookahead bias
        if as_of_date:
            as_of_dt = pd.to_datetime(as_of_date)
            df = df[df["date"] <= as_of_dt].copy()

        return df.reset_index(drop=True) if not df.empty else None

    def _fetch_from_network(self, series_id: str) -> Optional[pd.DataFrame]:
        """Download series from FRED REST API or fallback to public CSV."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarketReport/2.0",
        }

        # 1. Try official API if key provided
        if self.api_key:
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
            }
            for attempt in range(1, self.max_retries + 1):
                try:
                    res = requests.get(self.BASE_API_URL, params=params, headers=headers, timeout=10)
                    if res.status_code == 200:
                        data = res.json().get("observations", [])
                        if data:
                            df = pd.DataFrame(data)[["date", "value"]]
                            df["date"] = pd.to_datetime(df["date"])
                            df["value"] = pd.to_numeric(df["value"], errors="coerce")
                            df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
                            self._write_cache(series_id, df)
                            return df
                except Exception as e:
                    sleep_time = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.4)
                    logger.warning("FRED API error for %s (attempt %d): %s. Retrying in %.2fs", series_id, attempt, e, sleep_time)
                    time.sleep(sleep_time)

        # 2. Try public CSV fallback if enabled
        if self.allow_public_fallback:
            csv_url = f"{self.PUBLIC_CSV_URL}?id={series_id}"
            for attempt in range(1, self.max_retries + 1):
                try:
                    res = requests.get(csv_url, headers=headers, timeout=10)
                    if res.status_code == 200 and len(res.text) > 20:
                        lines = [line.strip().split(",") for line in res.text.strip().splitlines() if "," in line]
                        if len(lines) >= 2:
                            df = pd.DataFrame(lines[1:], columns=["date", "value"])
                            df["date"] = pd.to_datetime(df["date"], errors="coerce")
                            df["value"] = pd.to_numeric(df["value"], errors="coerce")
                            df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
                            if not df.empty:
                                self._write_cache(series_id, df)
                                return df
                except Exception as e:
                    sleep_time = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.4)
                    logger.debug("FRED CSV fallback error for %s (attempt %d): %s", series_id, attempt, e)
                    time.sleep(sleep_time)

        logger.warning("Unable to fetch FRED series %s (API key present: %s)", series_id, bool(self.api_key))
        return None

    # --- Financial and Macro Transformation Calculations ---

    @staticmethod
    def compute_inflation_metrics(
        df: pd.DataFrame,
        series_id: str,
        name: str,
    ) -> Optional[MacroMetricSnapshot]:
        """Convert raw price index levels (CPI, Core CPI, PCE, Core PCE, PPI) to MoM % and YoY %."""
        if df is None or len(df) < 13:
            return None

        latest_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        yoy_row = df.iloc[-13]

        latest_level = float(latest_row["value"])
        prev_level = float(prev_row["value"])
        yoy_level = float(yoy_row["value"])

        mom = ((latest_level - prev_level) / prev_level) * 100.0 if prev_level > 0 else 0.0
        yoy = ((latest_level - yoy_level) / yoy_level) * 100.0 if yoy_level > 0 else 0.0

        # Prior month MoM and YoY
        if len(df) >= 14:
            p_prev_level = float(df.iloc[-3]["value"])
            p_yoy_level = float(df.iloc[-14]["value"])
            prior_mom = ((prev_level - p_prev_level) / p_prev_level) * 100.0 if p_prev_level > 0 else 0.0
            prior_yoy = ((prev_level - p_yoy_level) / p_yoy_level) * 100.0 if p_yoy_level > 0 else 0.0
        else:
            prior_mom = mom
            prior_yoy = yoy

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=latest_row["date"].strftime("%Y-%m-%d"),
            latest_value=latest_level,
            headline_value=yoy,
            headline_unit="% YoY",
            prior_value=prev_level,
            prior_headline=prior_yoy,
            mom_pct=mom,
            prior_mom_pct=prior_mom,
            yoy_pct=yoy,
            notes=f"MoM: {mom:+.2f}%, YoY: {yoy:.2f}% (Index: {latest_level:.2f})",
        )

    @staticmethod
    def compute_payrolls_metrics(
        df: pd.DataFrame,
        series_id: str = "PAYEMS",
        name: str = "Nonfarm Payrolls",
    ) -> Optional[MacroMetricSnapshot]:
        """Compute monthly change in thousands for Nonfarm Payrolls."""
        if df is None or len(df) < 3:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"])
        prev_prev = float(df.iloc[-3]["value"])

        diff_curr = curr - prev
        diff_prev = prev - prev_prev

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=diff_curr,
            headline_unit="k",
            prior_value=prev,
            prior_headline=diff_prev,
            change=diff_curr - diff_prev,
            notes=f"Net change: {diff_curr:+.0f}k (Total: {curr:,.0f}k)",
        )

    @staticmethod
    def compute_jobless_claims_metrics(
        df: pd.DataFrame,
        series_id: str = "ICSA",
        name: str = "Initial Jobless Claims",
    ) -> Optional[MacroMetricSnapshot]:
        """Compute weekly initial claims and 4-week moving average."""
        if df is None or len(df) < 5:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"])

        rolling_4w_curr = float(df["value"].tail(4).mean())
        rolling_4w_prev = float(df["value"].iloc[-5:-1].mean())

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=curr,
            headline_unit="claims",
            prior_value=prev,
            prior_headline=prev,
            change=curr - prev,
            four_week_avg=rolling_4w_curr,
            prior_four_week_avg=rolling_4w_prev,
            notes=f"Weekly: {curr:,.0f} (4-week Avg: {rolling_4w_curr:,.0f})",
        )

    @staticmethod
    def compute_jolts_metrics(
        df: pd.DataFrame,
        series_id: str = "JTSJOL",
        name: str = "JOLTS Job Openings",
    ) -> Optional[MacroMetricSnapshot]:
        """Compute monthly JOLTS job openings in thousands."""
        if df is None or len(df) < 2:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"])

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=curr,
            headline_unit="k",
            prior_value=prev,
            prior_headline=prev,
            change=curr - prev,
            notes=f"Total: {curr:,.0f}k (Change: {curr - prev:+,.0f}k)",
        )

    @staticmethod
    def compute_rate_metrics(
        df: pd.DataFrame,
        series_id: str,
        name: str,
        period_start_date: Optional[str] = None,
    ) -> Optional[MacroMetricSnapshot]:
        """Compute level and period change for interest rates and yields."""
        if df is None or df.empty:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"]) if len(df) >= 2 else curr

        # Period start lookup
        period_change = None
        period_start_val = prev
        if period_start_date:
            dt_start = pd.to_datetime(period_start_date)
            p_slice = df[df["date"] <= dt_start]
            if not p_slice.empty:
                period_start_val = float(p_slice.iloc[-1]["value"])
                period_change = curr - period_start_val

        if period_change is None:
            period_change = curr - prev

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=curr,
            headline_unit="%",
            prior_value=prev,
            prior_headline=prev,
            change=curr - prev,
            period_start_value=period_start_val,
            period_change=period_change,
            notes=f"Current: {curr:.2f}%, Period Δ: {period_change:+.2f}%",
        )

    @staticmethod
    def compute_gdp_metrics(
        df: pd.DataFrame,
        series_id: str = "GDPC1",
        name: str = "Real GDP",
    ) -> Optional[MacroMetricSnapshot]:
        """Compute annualized QoQ % growth for Real GDP."""
        if df is None or len(df) < 3:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"])
        prev_prev = float(df.iloc[-3]["value"])

        ann_growth = (((curr / prev) ** 4) - 1.0) * 100.0 if prev > 0 else 0.0
        ann_growth_prev = (((prev / prev_prev) ** 4) - 1.0) * 100.0 if prev_prev > 0 else 0.0

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=ann_growth,
            headline_unit="% QoQ Ann.",
            prior_value=prev,
            prior_headline=ann_growth_prev,
            notes=f"Annualized QoQ: {ann_growth:+.1f}% (Level: ${curr:,.1f}B)",
        )

    @staticmethod
    def compute_mom_general_metrics(
        df: pd.DataFrame,
        series_id: str,
        name: str,
        unit: str = "% MoM",
    ) -> Optional[MacroMetricSnapshot]:
        """Compute simple MoM % for series like Retail Sales."""
        if df is None or len(df) < 2:
            return None

        curr = float(df.iloc[-1]["value"])
        prev = float(df.iloc[-2]["value"])

        mom = ((curr - prev) / prev) * 100.0 if prev > 0 else 0.0
        prev_mom = 0.0
        if len(df) >= 3:
            p_prev = float(df.iloc[-3]["value"])
            prev_mom = ((prev - p_prev) / p_prev) * 100.0 if p_prev > 0 else 0.0

        return MacroMetricSnapshot(
            series_id=series_id,
            name=name,
            latest_date=df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            latest_value=curr,
            headline_value=mom,
            headline_unit=unit,
            prior_value=prev,
            prior_headline=prev_mom,
            mom_pct=mom,
            notes=f"MoM: {mom:+.2f}%",
        )

    def get_historical_trend(
        self,
        series_id: str,
        name: str,
        category: str,
        calculation_type: str,
        months: int = 12,
        as_of_date: Optional[str] = None,
    ) -> Optional[MacroHistoricalSeries]:
        """Compute trailing historical observations with monthly and yearly values."""
        df = self.fetch_series(series_id, as_of_date=as_of_date)
        if df is None or df.empty:
            return None

        # Daily series like interest rates, TIPS, and credit spreads: resample to month-end
        if len(df) > 100 and ("DGS" in series_id or "DFF" in series_id or "T10Y" in series_id or "DFII" in series_id or "BAML" in series_id or calculation_type == "rate"):
            df_proc = df.set_index("date").resample("ME").last().dropna().reset_index()
        else:
            df_proc = df.copy()

        lookback = 4 if calculation_type == "gdp" else 12
        if len(df_proc) < lookback + 1:
            return None

        # Set default units based on calculation type
        if calculation_type in ("inflation", "pct_index", "retail_sales"):
            m_unit = "% MoM"
            y_unit = "% YoY"
        elif calculation_type == "payrolls":
            m_unit = "k"
            y_unit = "k (12M)"
        elif calculation_type == "rate":
            m_unit = "%"
            y_unit = "%"
        elif calculation_type == "sentiment":
            m_unit = "index"
            y_unit = "pts (12M Δ)"
        elif calculation_type == "gdp":
            m_unit = "% QoQ Ann."
            y_unit = "% YoY"
        else:
            m_unit = "%"
            y_unit = "%"

        points: List[MacroHistoricalPoint] = []
        n_pts = min(months, len(df_proc) - lookback)

        for i in range(len(df_proc) - n_pts, len(df_proc)):
            curr = df_proc.iloc[i]
            prev = df_proc.iloc[i - 1]
            yoy_row = df_proc.iloc[i - lookback]

            c_val = float(curr["value"])
            p_val = float(prev["value"])
            y_val = float(yoy_row["value"])

            dt: datetime = curr["date"]
            if calculation_type == "gdp":
                q_num = ((dt.month - 1) // 3) + 1
                date_label = f"Q{q_num} {dt.year}"
            else:
                date_label = dt.strftime("%b %Y")

            if calculation_type in ("inflation", "pct_index", "retail_sales"):
                m_calc = ((c_val - p_val) / p_val) * 100.0 if p_val > 0 else 0.0
                y_calc = ((c_val - y_val) / y_val) * 100.0 if y_val > 0 else 0.0
            elif calculation_type == "payrolls":
                m_calc = c_val - p_val
                y_calc = c_val - y_val
            elif calculation_type == "rate":
                m_calc = c_val
                y_calc = c_val - y_val
            elif calculation_type == "sentiment":
                m_calc = c_val
                y_calc = c_val - y_val
            elif calculation_type == "gdp":
                m_calc = (((c_val / p_val) ** 4) - 1.0) * 100.0 if p_val > 0 else 0.0
                y_calc = ((c_val - y_val) / y_val) * 100.0 if y_val > 0 else 0.0
            else:
                m_calc = c_val
                y_calc = y_val

            points.append(
                MacroHistoricalPoint(
                    date_str=dt.strftime("%Y-%m-%d"),
                    label=date_label,
                    monthly_val=m_calc,
                    yearly_val=y_calc,
                    raw_level=c_val,
                )
            )

        if not points:
            return None

        return MacroHistoricalSeries(
            series_id=series_id,
            name=name,
            category=category,
            monthly_unit=m_unit,
            yearly_unit=y_unit,
            points=points,
        )

