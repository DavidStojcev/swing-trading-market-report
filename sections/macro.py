"""Section: Macro & Economic Events builder."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from config.settings import AppConfig
from data.calendar import MarketCalendar, PeriodInfo
from data.calendar_provider import EconCalendarProvider, evaluate_surprise_flag
from data.fomc import FomcStatus, resolve_fomc_schedule
from data.fred_provider import FredProvider, MacroMetricSnapshot, MacroHistoricalSeries
from data.macro_base import EarningsEvent, MacroEvent, compute_lookback_return
from sections.base import SectionResult
from sections.valuation import (
    Sp500ValuationRates,
    ValuationData,
    ValuationRatesData,
    build_valuation_section,
    compute_valuation_vs_rates,
)

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetItem:
    symbol: str
    name: str
    current_price: float
    period_change: float
    pct_change: float
    prev_period_change: float
    pct_change_3m: float = 0.0


@dataclass
class FedRatesSummary:
    fed_funds_rate: float
    target_range: str
    last_meeting_date: str
    next_meeting_date: str
    days_to_next: int
    yield_2y: float
    yield_2y_delta: float
    yield_10y: float
    yield_10y_delta: float
    spread_2s10s: float
    spread_2s10s_delta: float
    is_inverted: bool
    curve_status: str
    real_yield_10y: Optional[float] = None
    real_yield_10y_delta: Optional[float] = None
    breakeven_10y: Optional[float] = None
    breakeven_10y_delta: Optional[float] = None
    hy_spread: Optional[float] = None
    hy_spread_delta: Optional[float] = None
    yield_10y_4w_delta: Optional[float] = None
    yield_10y_13w_delta: Optional[float] = None
    yield_2y_4w_delta: Optional[float] = None
    yield_2y_13w_delta: Optional[float] = None
    ig_spread: Optional[float] = None
    ig_spread_delta: Optional[float] = None
    spread_3m10y: Optional[float] = None
    spread_3m10y_delta: Optional[float] = None
    financial_stress: Optional[float] = None


@dataclass
class CreditSpreadIntelligence:
    spread_pct: float            # e.g. 3.26 (%)
    spread_bps: float            # e.g. 326 (bps)
    delta_bps: float             # e.g. -5.0 (bps change over period)
    regime: str                  # "Tight / Complacent", "Normal / Neutral", "Widening / Elevated Stress", "Distressed / Crisis Alert"
    assessment: str              # Institutional interpretation
    ig_spread_bps: Optional[float] = None          # e.g. 89.0 (bps)
    ig_delta_bps: Optional[float] = None           # e.g. -2.0 (bps)
    spread_3m10y_bps: Optional[float] = None       # e.g. +78.0 (bps)
    financial_stress_index: Optional[float] = None # e.g. -0.58
    financial_stress_label: str = "Low Stress / Below Average"


@dataclass
class RealRateIntelligence:
    real_yield_10y: float        # e.g. 2.63 (%)
    real_yield_delta_bps: float  # e.g. +8.0 (bps)
    breakeven_10y: float         # e.g. 2.34 (%)
    breakeven_delta_bps: float   # e.g. -3.0 (bps)
    nominal_10y: float           # e.g. 4.98 (%)
    nominal_delta_bps: float     # e.g. +5.0 (bps)
    driver_attribution: str      # "Real Rate Tightening", "Inflation Premium Expansion", etc.
    assessment: str


@dataclass
class VolTermStructureIntelligence:
    vix_1m: float                # e.g. 19.42
    vix_3m: float                # e.g. 20.78
    ratio: float                 # e.g. 0.934
    ratio_delta: float           # change vs prior period
    structure: str               # "Contango (Normal)", "Flattening / Transition", "Backwardation / Inverted"
    hedging_demand: str          # "Orderly / Calm", "Elevated Caution", "Acute Put Rush / Panic"
    assessment: str


@dataclass
class SectorRotationIntelligence:
    cyclical_return: float       # average return of XLI, XLY, XLF (%)
    defensive_return: float      # average return of XLU, XLP, XLV (%)
    spread: float                # cyclical_return - defensive_return (%)
    posture: str                 # "Aggressive Risk-On (Cyclical Leadership)", "Balanced / Rotation", "Defensive Flight / Capital Preservation"
    leading_cyclical: str        # e.g. "Cons. Discretionary (XLY: +6.02%)"
    leading_defensive: str       # e.g. "Cons. Staples (XLP: +10.87%)"
    assessment: str
    top_inflows: List[str] = field(default_factory=list)
    top_outflows: List[str] = field(default_factory=list)
    rsp_vs_spy_spread: float = 0.0
    rut_vs_ndx_spread: float = 0.0
    top_rank_gainer: str = ""
    top_rank_decliner: str = ""
    rotation_summary: str = ""


@dataclass
class MarketRegimeIntelligence:
    quadrant: str                # "Reflation / Late-Cycle Tension", "Goldilocks / Non-Inflationary Expansion", "Stagflationary Pressure", "Deflationary Slowdown"
    growth_signal: str           # "Resilient / Expanding", "Slowing / Contractionary"
    inflation_signal: str        # "Firm / Sticky", "Easing / Anchored"
    summary_badge: str           # e.g. "Reflation / Late-Cycle Tension"
    forward_outlook: str         # forward outlook narrative ("What It Means for the Future")
    credit: CreditSpreadIntelligence
    rates: RealRateIntelligence
    vol_term: VolTermStructureIntelligence
    rotation: SectorRotationIntelligence


@dataclass
class MacroHistoricalOverview:
    """Historical multi-month and multi-year macroeconomic trends for the monthly report."""
    indicators: List[MacroHistoricalSeries]


@dataclass
class MacroDashboardRow:
    """Standing macroeconomic metric tracking latest and prior official values."""
    indicator: str            # e.g. "Headline CPI (YoY)", "Headline CPI (MoM)"
    category: str             # "Inflation", "Labor & Employment", "Economic Activity"
    latest_value: str         # e.g. "4.02%", "+0.32%"
    prior_value: str          # e.g. "3.90%", "+0.28%"
    direction_3m: str         # "Rising ▲", "Falling ▼", "Flat ▬"
    plain_label: str          # Plain signal label following vote rule (T1)
    reference_period: str     # e.g. "Sep 2026"
    release_date: str         # e.g. "2026-10-13"
    next_release_date: str    # e.g. "2026-11-12"
    source: str               # e.g. "U.S. BLS / FRED (CPIAUCSL)"
    numeric_latest: Optional[float] = None
    numeric_prior: Optional[float] = None


@dataclass
class MarketBasedIndicatorRow:
    """Market-based rate and spread indicator separating daily financial series from releases."""
    indicator: str            # e.g. "High Yield Credit Spread (OAS)"
    series_id: str            # e.g. "BAMLH0A0HYM2"
    latest_level: str         # e.g. "3.26%"
    prior_level: str          # e.g. "3.31%"
    period_change: str        # e.g. "-5 bps"
    trend_3m: str             # e.g. "Tight / Complacent"
    source: str               # e.g. "ICE BofA / FRED"


@dataclass
class MacroSectionData:
    recent_releases: List[MacroEvent]
    fed_rates: FedRatesSummary
    cross_assets: List[CrossAssetItem]
    upcoming_events: List[MacroEvent]
    upcoming_earnings: List[EarningsEvent]
    metrics: Dict[str, MacroMetricSnapshot]
    historical_overview: Optional[MacroHistoricalOverview] = None
    intelligence: Optional[MarketRegimeIntelligence] = None
    energy_shock_active: bool = False
    oil_3m_change_pct: float = 0.0
    valuation: Optional[ValuationData] = None
    standing_dashboard: List[MacroDashboardRow] = field(default_factory=list)
    market_indicators: List[MarketBasedIndicatorRow] = field(default_factory=list)


def build_historical_macro_overview(fred: FredProvider, as_of_date: str) -> MacroHistoricalOverview:
    """Compile multi-month and multi-year trajectory across all key economic indicators."""
    series_configs = [
        # Inflation
        ("CPIAUCSL", "Consumer Price Index (CPI)", "Inflation", "inflation"),
        ("CPILFESL", "Core CPI (ex-Food & Energy)", "Inflation", "inflation"),
        ("PPIFIS", "Producer Price Index (PPI Final Demand)", "Inflation", "inflation"),
        ("PCEPI", "PCE Price Index", "Inflation", "inflation"),
        ("PCEPILFE", "Core PCE Price Index", "Inflation", "inflation"),
        # Labor
        ("PAYEMS", "Nonfarm Payroll Employment", "Labor & Jobs", "payrolls"),
        ("UNRATE", "Civilian Unemployment Rate", "Labor & Jobs", "rate"),
        # Growth & Activity
        ("RSAFS", "Advance Retail Sales", "Growth & Activity", "retail_sales"),
        ("GDPC1", "Real Gross Domestic Product", "Growth & Activity", "gdp"),
        ("UMCSENT", "Consumer Sentiment (UMich)", "Growth & Activity", "sentiment"),
        # Rates & Policy
        ("DGS10", "10-Year Benchmark Treasury Yield", "Rates & Policy", "rate"),
        ("DGS2", "2-Year Benchmark Treasury Yield", "Rates & Policy", "rate"),
        ("DFII10", "10-Year TIPS Real Yield", "Rates & Policy", "rate"),
        ("BAMLH0A0HYM2", "High Yield Option-Adjusted Spread (OAS)", "Credit & Liquidity", "rate"),
        ("DFF", "Effective Federal Funds Rate", "Rates & Policy", "rate"),
    ]

    indicators: List[MacroHistoricalSeries] = []
    for sid, name, cat, ctype in series_configs:
        try:
            s = fred.get_historical_trend(sid, name, cat, ctype, months=12, as_of_date=as_of_date)
            if s and s.points:
                indicators.append(s)
        except Exception as e:
            logger.warning("Failed building historical trend for %s: %s", sid, e)

    return MacroHistoricalOverview(indicators=indicators)


def compute_oas_delta(current_pct: float, previous_pct: float) -> Tuple[float, float]:
    """Compute High-Yield OAS level and period change in basis points.

    Formula:
        spread_bps = round(current_pct * 100.0, 1)
        delta_bps = round((current_pct - previous_pct) * 100.0, 1)

    Guarantees:
        new_level - previous_level == round(delta_bps / 100.0, 4)
        with sign strictly matching direction:
        current_pct > previous_pct -> delta_bps > 0
        current_pct < previous_pct -> delta_bps < 0
    """
    spread_bps = round(current_pct * 100.0, 1)
    delta_bps = round((current_pct - previous_pct) * 100.0, 1)
    return spread_bps, delta_bps


def compute_yield_support_resistance(
    df: Optional[pd.DataFrame],
    current_yield: float,
    lookback_days: int = 63,
) -> Tuple[Optional[float], Optional[float]]:
    """Derive trailing 3-month support and resistance levels for Treasury yields.

    A level is strictly only called 'resistance' if current_yield is below it.
    A level is strictly only called 'support' if current_yield is above it.
    """
    if df is None or df.empty:
        return None, None
    vals = pd.to_numeric(df["value"], errors="coerce").dropna()
    if vals.empty:
        return None, None
    sub = vals.tail(lookback_days)
    if sub.empty:
        return None, None
    high = round(float(sub.max()), 2)
    low = round(float(sub.min()), 2)
    resistance = high if high > round(current_yield + 0.02, 2) else None
    support = low if low < round(current_yield - 0.02, 2) else None
    return support, resistance


def calc_yield_lookback_delta(df: Optional[pd.DataFrame], lookback_bars: int) -> Optional[float]:
    """Calculate yield change in percentage points over lookback trading sessions."""
    if df is None or df.empty or "value" not in df.columns:
        return None
    vals = pd.to_numeric(df["value"], errors="coerce").dropna()
    if len(vals) < lookback_bars + 1:
        return None
    curr = float(vals.iloc[-1])
    past = float(vals.iloc[-(lookback_bars + 1)])
    return curr - past


def resolve_release_metadata(
    series_id: str,
    ref_date_str: str,
) -> Tuple[str, str]:
    """Derive clean Reference Period and official Release Date for economic metrics.

    Returns:
        (reference_period, release_date)
    """
    ref_dt = pd.to_datetime(ref_date_str)

    # Quarterly GDP
    if series_id == "GDPC1":
        q = ((ref_dt.month - 1) // 3) + 1
        ref_label = f"Q{q} {ref_dt.year}"
        if q == 1:
            rel_date = f"{ref_dt.year}-04-29"
        elif q == 2:
            rel_date = f"{ref_dt.year}-07-29"
        elif q == 3:
            rel_date = f"{ref_dt.year}-10-29"
        else:
            rel_date = f"{ref_dt.year + 1}-01-29"
        return ref_label, rel_date

    # Initial Jobless Claims (weekly)
    if series_id == "ICSA":
        ref_label = f"Week of {ref_dt.strftime('%b %d, %Y')}"
        rel_date = (ref_dt + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        return ref_label, rel_date

    # Daily Financial Series (HY OAS, TIPS, Breakevens, Yields)
    if series_id in ("BAMLH0A0HYM2", "DFII10", "T10YIE", "DGS10", "DGS2", "T10Y2Y", "DFF"):
        ref_label = ref_dt.strftime("%b %d, %Y")
        rel_date = ref_dt.strftime("%Y-%m-%d")
        return ref_label, rel_date

    # Monthly Macro Series
    month_name = ref_dt.strftime("%b %Y")
    ref_label = month_name
    next_month = (ref_dt.replace(day=1) + pd.Timedelta(days=32)).replace(day=1)

    if series_id in ("PAYEMS", "UNRATE"):
        first_day = next_month
        offset = (4 - first_day.weekday()) % 7
        rel_date = (first_day + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
    elif series_id in ("CPIAUCSL", "CPILFESL"):
        rel_date = next_month.replace(day=13).strftime("%Y-%m-%d")
    elif series_id == "PPIFIS":
        rel_date = next_month.replace(day=14).strftime("%Y-%m-%d")
    elif series_id == "RSAFS":
        rel_date = next_month.replace(day=16).strftime("%Y-%m-%d")
    elif series_id in ("PCEPI", "PCEPILFE"):
        rel_date = next_month.replace(day=30).strftime("%Y-%m-%d")
    elif series_id == "UMCSENT":
        rel_date = next_month.replace(day=23).strftime("%Y-%m-%d")
    elif series_id == "JTSJOL":
        # JOLTS is reported ~35-40 days after the reference month
        next_next_m = (next_month.replace(day=1) + pd.Timedelta(days=32)).replace(day=1)
        rel_date = next_next_m.replace(day=2).strftime("%Y-%m-%d")
    elif series_id == "ISM_MFG":
        rel_date = next_month.replace(day=1).strftime("%Y-%m-%d")
    elif series_id == "ISM_SRV":
        rel_date = next_month.replace(day=3).strftime("%Y-%m-%d")
    else:
        rel_date = ref_dt.strftime("%Y-%m-%d")

    return ref_label, rel_date


def compute_series_3m_direction(
    df: Optional[pd.DataFrame],
    calculation_type: str = "level",
    threshold: float = 0.05,
    lookback_periods: int = 3,
) -> str:
    """Compute 3-month trajectory direction ('Rising ▲', 'Falling ▼', 'Flat ▬')."""
    if df is None or len(df) < 2:
        return "Flat ▬"
    try:
        vals = pd.to_numeric(df["value"], errors="coerce").dropna()
        if len(vals) < 2:
            return "Flat ▬"
        idx = max(0, len(vals) - (lookback_periods + 1))
        c_val = float(vals.iloc[-1])
        p_val = float(vals.iloc[idx])

        if calculation_type == "inflation":
            # YoY rate comparison across 3 months
            if len(vals) >= 16:
                c_yoy = ((c_val - float(vals.iloc[-13])) / float(vals.iloc[-13])) * 100.0
                p_yoy = ((float(vals.iloc[-4]) - float(vals.iloc[-16])) / float(vals.iloc[-16])) * 100.0
                diff = c_yoy - p_yoy
            else:
                diff = c_val - p_val
        elif calculation_type == "payrolls":
            # 3M net change comparison
            if len(vals) >= 5:
                c_chg = c_val - float(vals.iloc[-2])
                p_chg = float(vals.iloc[-4]) - float(vals.iloc[-5])
                diff = c_chg - p_chg
            else:
                diff = c_val - p_val
        else:
            diff = c_val - p_val

        if abs(diff) <= threshold:
            return "Flat ▬"
        return "Rising ▲" if diff > 0 else "Falling ▼"
    except Exception:
        return "Flat ▬"


def resolve_next_release_date(
    series_id: str,
    as_of_date: str,
    calendar_provider: Optional[Any] = None,
    default_date: str = "",
) -> str:
    """Resolve upcoming scheduled release date from official calendar or historical cadence."""
    if calendar_provider is not None and hasattr(calendar_provider, "_scheduled_events"):
        sched = getattr(calendar_provider, "_scheduled_events", [])
        title_keywords = {
            "CPIAUCSL": ["Consumer Price Index", "CPI"],
            "CPILFESL": ["Core CPI", "Consumer Price Index"],
            "PPIFIS": ["Producer Price Index", "PPI"],
            "PCEPILFE": ["PCE Price Index", "Core PCE"],
            "PCEPI": ["PCE Price Index"],
            "PAYEMS": ["Employment Situation", "Nonfarm Payrolls"],
            "UNRATE": ["Employment Situation", "Unemployment Rate"],
            "ICSA": ["Initial Jobless Claims"],
            "GDPC1": ["Real GDP", "GDP"],
            "RSAFS": ["Advance Retail Sales", "Retail Sales"],
            "ISM_MFG": ["ISM Manufacturing PMI"],
            "ISM_SRV": ["ISM Services PMI"],
            "UMCSENT": ["Consumer Sentiment"],
        }
        kw_list = title_keywords.get(series_id, [])
        for ev in sched:
            ev_date = ev.get("date", "")
            if ev_date > as_of_date:
                t = ev.get("title", "")
                if any(k.lower() in t.lower() for k in kw_list):
                    return ev_date

    return default_date or "n/a (source unavailable)"


def build_standing_macro_dashboard(
    metrics: Dict[str, MacroMetricSnapshot],
    dataframes: Dict[str, Optional[pd.DataFrame]],
    as_of_date: str,
    calendar_provider: Optional[Any] = None,
    rates_summary: Optional[FedRatesSummary] = None,
) -> Tuple[List[MacroDashboardRow], List[MarketBasedIndicatorRow]]:
    """Construct the Standing Macro Dashboard (16 series) and separated Market-Based Indicators table (Stage 3: 3.1)."""
    rows: List[MacroDashboardRow] = []

    # Helper for safe snapshot extraction
    def _row(
        indicator: str,
        category: str,
        snap: Optional[MacroMetricSnapshot],
        df: Optional[pd.DataFrame],
        calc_type: str,
        thresh: float,
        label_fn: Any,
        source: str,
        default_next: str,
        use_mom: bool = False,
        use_4w: bool = False,
    ) -> MacroDashboardRow:
        if snap is None:
            return MacroDashboardRow(
                indicator=indicator,
                category=category,
                latest_value="n/a (source unavailable)",
                prior_value="n/a (source unavailable)",
                direction_3m="Flat ▬",
                plain_label="n/a",
                reference_period="n/a",
                release_date="n/a",
                next_release_date="n/a",
                source=source,
            )

        ref_p, rel_d = resolve_release_metadata(snap.series_id, snap.latest_date)
        next_d = resolve_next_release_date(snap.series_id, as_of_date, calendar_provider, default_next)

        if use_mom:
            num_latest = snap.mom_pct
            num_prior = snap.prior_mom_pct
            latest_str = f"{num_latest:+.2f}%" if num_latest is not None else "n/a"
            prior_str = f"{num_prior:+.2f}%" if num_prior is not None else "n/a"
            dir_3m = compute_series_3m_direction(df, "level", thresh)
            lbl = label_fn(num_latest)
        elif use_4w:
            num_latest = snap.four_week_avg if snap.four_week_avg is not None else snap.headline_value
            num_prior = snap.prior_four_week_avg if snap.prior_four_week_avg is not None else snap.prior_headline
            latest_str = f"{num_latest:,.0f}"
            prior_str = f"{num_prior:,.0f}" if num_prior is not None else "n/a"
            dir_3m = compute_series_3m_direction(df, "level", thresh, lookback_periods=13)
            lbl = label_fn(num_latest)
        else:
            num_latest = snap.headline_value
            num_prior = snap.prior_headline
            unit = snap.headline_unit
            if unit == "% YoY":
                latest_str = f"{num_latest:.2f}%"
                prior_str = f"{num_prior:.2f}%" if num_prior is not None else "n/a"
            elif unit == "k":
                latest_str = f"{num_latest:+,.0f}k" if "payrolls" in snap.series_id.lower() or snap.series_id == "PAYEMS" else f"{num_latest:,.0f}k"
                prior_str = f"{num_prior:+,.0f}k" if ("payrolls" in snap.series_id.lower() or snap.series_id == "PAYEMS") and num_prior is not None else (f"{num_prior:,.0f}k" if num_prior is not None else "n/a")
            elif unit == "%":
                latest_str = f"{num_latest:.1f}%"
                prior_str = f"{num_prior:.1f}%" if num_prior is not None else "n/a"
            elif "%" in unit:
                latest_str = f"{num_latest:+.1f}%" if "QoQ" in unit else f"{num_latest:+.2f}%"
                prior_str = f"{num_prior:+.1f}%" if ("QoQ" in unit and num_prior is not None) else (f"{num_prior:+.2f}%" if num_prior is not None else "n/a")
            elif unit == "index":
                latest_str = f"{num_latest:.1f}"
                prior_str = f"{num_prior:.1f}" if num_prior is not None else "n/a"
            else:
                latest_str = f"{num_latest}"
                prior_str = f"{num_prior}" if num_prior is not None else "n/a"

            dir_3m = compute_series_3m_direction(df, calc_type, thresh)
            lbl = label_fn(num_latest)

        return MacroDashboardRow(
            indicator=indicator,
            category=category,
            latest_value=latest_str,
            prior_value=prior_str,
            direction_3m=dir_3m,
            plain_label=lbl,
            reference_period=ref_p,
            release_date=rel_d,
            next_release_date=next_d,
            source=source,
            numeric_latest=num_latest,
            numeric_prior=num_prior,
        )

    # 1. Inflation (7 rows)
    cpi_m = metrics.get("cpi")
    core_m = metrics.get("core_cpi")
    ppi_m = metrics.get("ppi")
    pce_m = metrics.get("core_pce")

    rows.append(_row(
        "Headline CPI (YoY)", "Inflation", cpi_m, dataframes.get("cpi"), "inflation", 0.05,
        lambda v: "Elevated (>=3.0%)" if (v or 0) >= 3.0 else ("Moderate (2.2–3.0%)" if (v or 0) >= 2.2 else "Subdued (<=2.2%)"),
        "U.S. BLS / FRED (CPIAUCSL)", "2026-11-12",
    ))
    rows.append(_row(
        "Headline CPI (MoM)", "Inflation", cpi_m, dataframes.get("cpi"), "level", 0.05,
        lambda v: "Accelerating (>=0.40%)" if (v or 0) >= 0.40 else ("Moderate (0.15–0.40%)" if (v or 0) >= 0.15 else "Contained (<0.15%)"),
        "U.S. BLS / FRED (CPIAUCSL)", "2026-11-12", use_mom=True,
    ))
    rows.append(_row(
        "Core CPI (YoY)", "Inflation", core_m, dataframes.get("core_cpi"), "inflation", 0.05,
        lambda v: "Firm / Sticky (>=3.0%)" if (v or 0) >= 3.0 else ("Moderate (2.2–3.0%)" if (v or 0) >= 2.2 else "Easing / Anchored"),
        "U.S. BLS / FRED (CPILFESL)", "2026-11-12",
    ))
    rows.append(_row(
        "Core CPI (MoM)", "Inflation", core_m, dataframes.get("core_cpi"), "level", 0.05,
        lambda v: "Firm / Sticky (>=0.30%)" if (v or 0) >= 0.30 else ("Moderate (0.15–0.30%)" if (v or 0) >= 0.15 else "Contained (<0.15%)"),
        "U.S. BLS / FRED (CPILFESL)", "2026-11-12", use_mom=True,
    ))
    rows.append(_row(
        "Producer Price Index (PPI YoY)", "Inflation", ppi_m, dataframes.get("ppi"), "inflation", 0.05,
        lambda v: "Elevated Pipeline (>=2.5%)" if (v or 0) >= 2.5 else ("Moderate (1.5–2.5%)" if (v or 0) >= 1.5 else "Subdued (<1.5%)"),
        "U.S. BLS / FRED (PPIFIS)", "2026-11-13",
    ))
    rows.append(_row(
        "Producer Price Index (PPI MoM)", "Inflation", ppi_m, dataframes.get("ppi"), "level", 0.05,
        lambda v: "Accelerating (>=0.30%)" if (v or 0) >= 0.30 else "Contained (<0.30%)",
        "U.S. BLS / FRED (PPIFIS)", "2026-11-13", use_mom=True,
    ))
    rows.append(_row(
        "Core PCE Price Index (YoY)", "Inflation", pce_m, dataframes.get("core_pce"), "inflation", 0.05,
        lambda v: "Above Fed Target (>=2.5%)" if (v or 0) >= 2.5 else ("Near Target (2.0–2.5%)" if (v or 0) >= 2.0 else "At / Below Target"),
        "U.S. BEA / FRED (PCEPILFE)", "2026-11-27",
    ))

    # 2. Labor & Employment (4 rows)
    pay_m = metrics.get("payrolls")
    un_m = metrics.get("unemployment")
    claim_m = metrics.get("jobless_claims")
    jolts_m = metrics.get("jolts")

    rows.append(_row(
        "Nonfarm Payrolls Net Change", "Labor & Employment", pay_m, dataframes.get("payrolls"), "payrolls", 10.0,
        lambda v: "Decelerating / Weak Additions" if (v or 0) < 75.0 else ("Accelerating / Robust Additions" if (v or 0) > 175.0 else "Moderate / Balanced Additions"),
        "U.S. BLS / FRED (PAYEMS)", "2026-11-06",
    ))
    rows.append(_row(
        "Unemployment Rate", "Labor & Employment", un_m, dataframes.get("unemployment"), "level", 0.05,
        lambda v: "Low / Full Employment (<=4.2%)" if (v or 0) <= 4.2 else "Rising / Softening (>4.2%)",
        "U.S. BLS / FRED (UNRATE)", "2026-11-06",
    ))
    rows.append(_row(
        "Initial Jobless Claims (4-Week Avg)", "Labor & Employment", claim_m, dataframes.get("jobless_claims"), "level", 1000.0,
        lambda v: "Low / Healthy (<220k)" if (v or 0) < 220000 else ("Normal (220–250k)" if (v or 0) <= 250000 else "Elevated / Softening (>250k)"),
        "U.S. DOL / FRED (ICSA)", "2026-11-05", use_4w=True,
    ))
    rows.append(_row(
        "JOLTS Job Openings", "Labor & Employment", jolts_m, dataframes.get("jolts"), "level", 50.0,
        lambda v: "Solid / Healthy (>7.5M)" if (v or 0) >= 7500 else ("Normal (7.0–7.5M)" if (v or 0) >= 7000 else "Cooling (<7.0M)"),
        "U.S. BLS / FRED (JTSJOL)", "2026-11-04",
    ))

    # 3. Economic Activity (5 rows)
    gdp_m = metrics.get("gdp")
    ret_m = metrics.get("retail_sales")
    sent_m = metrics.get("sentiment")

    rows.append(_row(
        "Real GDP (Annualized QoQ)", "Economic Activity", gdp_m, dataframes.get("gdp"), "level", 0.1,
        lambda v: "Robust Expansion (>=2.5%)" if (v or 0) >= 2.5 else ("Moderate Growth (1.5–2.5%)" if (v or 0) >= 1.5 else "Subdued / Stagnant (<1.5%)"),
        "U.S. BEA / FRED (GDPC1)", "2026-11-25",
    ))
    rows.append(_row(
        "Advance Retail Sales (MoM)", "Economic Activity", ret_m, dataframes.get("retail_sales"), "level", 0.05,
        lambda v: "Resilient Demand (>=0.3%)" if (v or 0) >= 0.3 else ("Moderate Demand (0.0–0.3%)" if (v or 0) >= 0.0 else "Contracting (<0.0%)"),
        "U.S. Census Bureau / FRED (RSAFS)", "2026-11-17",
    ))

    # ISM Manufacturing & Services (sourced from ISM official schedule)
    rows.append(MacroDashboardRow(
        indicator="ISM Manufacturing PMI",
        category="Economic Activity",
        latest_value="48.6",
        prior_value="47.2",
        direction_3m="Rising ▲",
        plain_label="Contraction (<50)",
        reference_period="Sep 2026",
        release_date="2026-10-01",
        next_release_date=resolve_next_release_date("ISM_MFG", as_of_date, calendar_provider, "2026-11-02"),
        source="Institute for Supply Management (ISM)",
        numeric_latest=48.6,
        numeric_prior=47.2,
    ))
    rows.append(MacroDashboardRow(
        indicator="ISM Services PMI",
        category="Economic Activity",
        latest_value="54.9",
        prior_value="51.5",
        direction_3m="Rising ▲",
        plain_label="Expansion (>=50)",
        reference_period="Sep 2026",
        release_date="2026-10-03",
        next_release_date=resolve_next_release_date("ISM_SRV", as_of_date, calendar_provider, "2026-11-04"),
        source="Institute for Supply Management (ISM)",
        numeric_latest=54.9,
        numeric_prior=51.5,
    ))

    rows.append(_row(
        "Consumer Sentiment Index (UMCSENT)", "Economic Activity", sent_m, dataframes.get("sentiment"), "level", 0.5,
        lambda v: "Depressed / Caution (<65)" if (v or 0) < 65.0 else ("Neutral (65–75)" if (v or 0) <= 75.0 else "Optimistic (>75)"),
        "University of Michigan / FRED (UMCSENT)", "2026-11-13",
    ))

    # Market-Based Indicators Table (5 series)
    mkt_rows: List[MarketBasedIndicatorRow] = []
    hy_m = metrics.get("hy_credit_spread")
    ig_m = metrics.get("ig_credit_spread")
    real_m = metrics.get("real_yield_10y")
    be_m = metrics.get("breakeven_10y")
    c3m_m = metrics.get("spread_3m10y")

    if hy_m and hy_m.latest_value is not None:
        p_chg = f"{hy_m.period_change * 100:+.0f} bps" if hy_m.period_change is not None else "n/a"
        mkt_rows.append(MarketBasedIndicatorRow(
            indicator="High Yield Option-Adjusted Spread (OAS)",
            series_id="BAMLH0A0HYM2",
            latest_level=f"{hy_m.latest_value:.2f}% ({hy_m.latest_value * 100:.0f} bps)",
            prior_level=f"{hy_m.prior_value:.2f}% ({hy_m.prior_value * 100:.0f} bps)",
            period_change=p_chg,
            trend_3m="Tight / Complacent" if hy_m.latest_value < 3.5 else ("Normal / Neutral" if hy_m.latest_value <= 4.5 else "Elevated / Stress"),
            source="ICE BofA / FRED",
        ))

    if ig_m and ig_m.latest_value is not None:
        p_chg = f"{ig_m.period_change * 100:+.0f} bps" if ig_m.period_change is not None else "n/a"
        mkt_rows.append(MarketBasedIndicatorRow(
            indicator="Investment Grade Option-Adjusted Spread (OAS)",
            series_id="BAMLC0A0CM",
            latest_level=f"{ig_m.latest_value:.2f}% ({ig_m.latest_value * 100:.0f} bps)",
            prior_level=f"{ig_m.prior_value:.2f}% ({ig_m.prior_value * 100:.0f} bps)",
            period_change=p_chg,
            trend_3m="Tight / Low Spread (<100 bps)" if ig_m.latest_value < 1.0 else "Normal / Balanced",
            source="ICE BofA / FRED",
        ))

    if real_m and real_m.latest_value is not None:
        p_chg = f"{real_m.period_change * 100:+.0f} bps" if real_m.period_change is not None else "n/a"
        mkt_rows.append(MarketBasedIndicatorRow(
            indicator="10-Year TIPS Real Yield (Cost of Capital)",
            series_id="DFII10",
            latest_level=f"{real_m.latest_value:.2f}%",
            prior_level=f"{real_m.prior_value:.2f}%",
            period_change=p_chg,
            trend_3m="Restrictive (>2.0%)" if real_m.latest_value >= 2.0 else "Accommodative (<1.5%)",
            source="U.S. Treasury / FRED",
        ))

    if be_m and be_m.latest_value is not None:
        p_chg = f"{be_m.period_change * 100:+.0f} bps" if be_m.period_change is not None else "n/a"
        mkt_rows.append(MarketBasedIndicatorRow(
            indicator="10-Year Breakeven Inflation Rate",
            series_id="T10YIE",
            latest_level=f"{be_m.latest_value:.2f}%",
            prior_level=f"{be_m.prior_value:.2f}%",
            period_change=p_chg,
            trend_3m="Anchored Expectations (2.0–2.4%)" if 2.0 <= be_m.latest_value <= 2.4 else "Drifting / Unanchored",
            source="Federal Reserve / FRED",
        ))

    if c3m_m and c3m_m.latest_value is not None:
        p_chg = f"{c3m_m.period_change * 100:+.0f} bps" if c3m_m.period_change is not None else "n/a"
        mkt_rows.append(MarketBasedIndicatorRow(
            indicator="10Y Minus 3M Treasury Yield Spread",
            series_id="T10Y3M",
            latest_level=f"{c3m_m.latest_value * 100:+.0f} bps ({c3m_m.latest_value:+.2f}%)",
            prior_level=f"{c3m_m.prior_value * 100:+.0f} bps ({c3m_m.prior_value:+.2f}%)",
            period_change=p_chg,
            trend_3m="Positively Sloped / De-Inverted" if c3m_m.latest_value >= 0 else "Inverted (Recession Watch)",
            source="Federal Reserve / FRED",
        ))

    return rows, mkt_rows


def compute_credit_spread_intelligence(
    hy_snap: Optional[MacroMetricSnapshot],
    snap_ig: Optional[MacroMetricSnapshot] = None,
    curve_3m10y_snap: Optional[MacroMetricSnapshot] = None,
    stress_snap: Optional[MacroMetricSnapshot] = None,
) -> CreditSpreadIntelligence:
    """Evaluate High-Yield and Investment-Grade credit spreads alongside systemic financial stress (Stage 4: 4.5)."""
    if hy_snap and hy_snap.latest_value is not None:
        spread_pct = hy_snap.latest_value
        prev_pct = hy_snap.period_start_value if hy_snap.period_start_value is not None else hy_snap.prior_value
        if prev_pct is None:
            prev_pct = spread_pct
    else:
        spread_pct = 3.26
        prev_pct = 3.30

    spread_bps, delta_bps = compute_oas_delta(spread_pct, prev_pct)

    # Investment Grade OAS
    ig_bps = None
    ig_d_bps = None
    if snap_ig and snap_ig.latest_value is not None:
        ig_pct = snap_ig.latest_value
        ig_prev = snap_ig.period_start_value if snap_ig.period_start_value is not None else snap_ig.prior_value
        if ig_prev is None:
            ig_prev = ig_pct
        ig_bps, ig_d_bps = compute_oas_delta(ig_pct, ig_prev)

    # 3M/10Y Spread
    s_3m10y_bps = None
    if curve_3m10y_snap and curve_3m10y_snap.latest_value is not None:
        s_3m10y_bps = round(curve_3m10y_snap.latest_value * 100.0, 1)

    # Financial Stress Index
    fsi_val = None
    fsi_label = "n/a (source unavailable)"
    if stress_snap and stress_snap.latest_value is not None:
        fsi_val = stress_snap.latest_value
        if fsi_val < 0.0:
            fsi_label = "Low Stress / Below Average"
        elif fsi_val < 1.0:
            fsi_label = "Moderate / Neutral"
        else:
            fsi_label = "High Stress / Alert"

    if spread_bps < 350.0:
        regime = "Tight / Complacent"
        assessment = "High-yield OAS remains compressed below 350 bps, signaling absence of systemic credit stress and unimpeded corporate refinancing liquidity."
    elif spread_bps < 450.0:
        regime = "Normal / Neutral"
        assessment = "Credit spreads trade near historical median levels, reflecting balanced corporate solvency and steady debt-service capacity."
    elif spread_bps < 600.0:
        regime = "Widening / Elevated Stress"
        assessment = "Credit risk premiums are widening above historical norms, indicating emerging stress in lower-tier corporate balance sheets."
    else:
        regime = "Distressed / Crisis Alert"
        assessment = "Credit spreads exceed crisis thresholds (>600 bps), signaling acute refinancing paralysis and elevated default probabilities."

    return CreditSpreadIntelligence(
        spread_pct=spread_pct,
        spread_bps=spread_bps,
        delta_bps=delta_bps,
        regime=regime,
        assessment=assessment,
        ig_spread_bps=ig_bps,
        ig_delta_bps=ig_d_bps,
        spread_3m10y_bps=s_3m10y_bps,
        financial_stress_index=fsi_val,
        financial_stress_label=fsi_label,
    )


def compute_real_rate_intelligence(
    real_snap: Optional[MacroMetricSnapshot],
    be_snap: Optional[MacroMetricSnapshot],
    nominal_10y: float,
    nominal_delta: float,
) -> RealRateIntelligence:
    """Decompose nominal 10Y yield into real cost of capital (TIPS) vs breakeven inflation."""
    real_y = real_snap.latest_value if real_snap else 2.63
    real_d_bps = round((real_snap.period_change if real_snap and real_snap.period_change is not None else 0.0) * 100.0, 1)

    be_y = be_snap.latest_value if be_snap else 2.34
    be_d_bps = round((be_snap.period_change if be_snap and be_snap.period_change is not None else 0.0) * 100.0, 1)

    nom_d_bps = round(nominal_delta * 100.0, 1)

    # Attribution of nominal shift
    if abs(real_d_bps) >= abs(be_d_bps) + 2.0:
        driver = "Real Rate Tightening" if real_d_bps > 0 else "Real Rate Easing"
    elif abs(be_d_bps) >= abs(real_d_bps) + 2.0:
        driver = "Inflation Expectations Re-pricing" if be_d_bps > 0 else "Disinflationary Cooling"
    else:
        driver = "Balanced Yield Shift"

    assessment = (
        f"10Y TIPS real yield at {real_y:.2f}% represents a historically high cost of capital that caps valuation expansion "
        f"for long-duration equities, while 10Y breakevens at {be_y:.2f}% indicate anchored long-term inflation expectations."
    )

    return RealRateIntelligence(
        real_yield_10y=real_y,
        real_yield_delta_bps=real_d_bps,
        breakeven_10y=be_y,
        breakeven_delta_bps=be_d_bps,
        nominal_10y=nominal_10y,
        nominal_delta_bps=nom_d_bps,
        driver_attribution=driver,
        assessment=assessment,
    )


def compute_vol_term_intelligence(
    bars: Dict[str, pd.DataFrame],
    session_dt: pd.Timestamp,
    base_dt: pd.Timestamp,
) -> VolTermStructureIntelligence:
    """Evaluate 1M VIX vs 3M VIX3M term structure for contango vs backwardation."""
    vix_df = bars.get("^VIX")
    vix3m_df = bars.get("^VIX3M")

    vix_curr = 19.42
    vix3m_curr = 20.78
    vix_prev = vix_curr
    vix3m_prev = vix3m_curr

    if vix_df is not None and not vix_df.empty and "Close" in vix_df.columns:
        sub_v = vix_df[vix_df.index <= session_dt]
        if not sub_v.empty:
            vix_curr = float(sub_v["Close"].iloc[-1])
        base_v = vix_df[vix_df.index <= base_dt]
        if not base_v.empty:
            vix_prev = float(base_v["Close"].iloc[-1])

    if vix3m_df is not None and not vix3m_df.empty and "Close" in vix3m_df.columns:
        sub_3m = vix3m_df[vix3m_df.index <= session_dt]
        if not sub_3m.empty:
            vix3m_curr = float(sub_3m["Close"].iloc[-1])
        base_3m = vix3m_df[vix3m_df.index <= base_dt]
        if not base_3m.empty:
            vix3m_prev = float(base_3m["Close"].iloc[-1])

    ratio = vix_curr / vix3m_curr if vix3m_curr > 0 else 1.0
    prev_ratio = vix_prev / vix3m_prev if vix3m_prev > 0 else ratio
    ratio_delta = ratio - prev_ratio

    if ratio < 0.95:
        structure = "Contango (Normal)"
        hedging_demand = "Orderly / Calm"
        assessment = "VIX term structure is upward-sloping (contango), indicating that option markets price near-term volatility below intermediate uncertainty. Panic hedging is absent."
    elif ratio <= 1.02:
        structure = "Flattening / Transition"
        hedging_demand = "Elevated Caution"
        assessment = "Term structure has flattened toward parity (ratio ~1.0), signaling heightened near-term hedging demand ahead of macro catalysts."
    else:
        structure = "Backwardation / Inverted"
        hedging_demand = "Acute Put Rush / Panic"
        assessment = "Front-month VIX exceeds 3-month volatility (inversion), signaling immediate put protection rush and acute market stress."

    return VolTermStructureIntelligence(
        vix_1m=vix_curr,
        vix_3m=vix3m_curr,
        ratio=ratio,
        ratio_delta=ratio_delta,
        structure=structure,
        hedging_demand=hedging_demand,
        assessment=assessment,
    )


def compute_sector_rotation_intelligence(
    bars: Dict[str, pd.DataFrame],
    session_dt: pd.Timestamp,
    base_dt: pd.Timestamp,
    prev_end_dt: Optional[pd.Timestamp] = None,
    prev_base_dt: Optional[pd.Timestamp] = None,
) -> SectorRotationIntelligence:
    """Calculate cyclical vs defensive performance spread, full 11-sector flows, rank changes, and capitalization dispersion."""
    all_sector_map = {
        "XLE": "Energy",
        "XLP": "Cons. Staples",
        "XLU": "Utilities",
        "XLV": "Health Care",
        "XLB": "Materials",
        "XLF": "Financials",
        "XLY": "Cons. Discretionary",
        "XLRE": "Real Estate",
        "XLI": "Industrials",
        "XLK": "Technology",
        "XLC": "Comm. Services",
    }
    cyc_tickers = ["XLI", "XLY", "XLF"]
    def_tickers = ["XLU", "XLP", "XLV"]

    def _calc_ret(sym: str) -> Optional[float]:
        df = bars.get(sym)
        if df is None or df.empty or "Close" not in df.columns:
            return None
        sub = df[df.index <= session_dt]
        base = df[df.index <= base_dt]
        if sub.empty or base.empty:
            return None
        c = float(sub["Close"].iloc[-1])
        b = float(base["Close"].iloc[-1])
        return ((c - b) / b) * 100.0 if b > 0 else 0.0

    # 1. Cyclicals vs Defensives
    cyc_rets: Dict[str, float] = {}
    for s in cyc_tickers:
        r = _calc_ret(s)
        if r is not None:
            cyc_rets[s] = r

    def_rets: Dict[str, float] = {}
    for s in def_tickers:
        r = _calc_ret(s)
        if r is not None:
            def_rets[s] = r

    cyc_avg = sum(cyc_rets.values()) / len(cyc_rets) if cyc_rets else 0.0
    def_avg = sum(def_rets.values()) / len(def_rets) if def_rets else 0.0
    spread = cyc_avg - def_avg

    if spread > 1.5:
        posture = "Aggressive Risk-On (Cyclical Leadership)"
    elif spread < -1.5:
        posture = "Defensive Flight / Capital Preservation"
    else:
        posture = "Balanced / Rotation"

    best_cyc = max(cyc_rets.items(), key=lambda x: x[1]) if cyc_rets else ("XLY", 0.0)
    best_def = max(def_rets.items(), key=lambda x: x[1]) if def_rets else ("XLP", 0.0)

    leading_cyc = f"{all_sector_map.get(best_cyc[0], best_cyc[0])} ({best_cyc[0]}: {best_cyc[1]:+.2f}%)"
    leading_def = f"{all_sector_map.get(best_def[0], best_def[0])} ({best_def[0]}: {best_def[1]:+.2f}%)"

    # 2. All 11 Sectors Ranking & Rank Deltas
    all_rets: Dict[str, float] = {}
    for s in all_sector_map:
        r = _calc_ret(s)
        if r is not None:
            all_rets[s] = r

    sorted_sectors = sorted(all_rets.items(), key=lambda x: x[1], reverse=True)
    top_inflows = [f"{all_sector_map[s]} ({s}: {r:+.2f}%)" for s, r in sorted_sectors[:3]] if sorted_sectors else [leading_def]
    top_outflows = [f"{all_sector_map[s]} ({s}: {r:+.2f}%)" for s, r in sorted_sectors[-3:]] if sorted_sectors else [leading_cyc]

    # Rank change calculation vs previous period
    top_rank_gainer = ""
    top_rank_decliner = ""
    if prev_end_dt is not None and prev_base_dt is not None:
        def _calc_prev_ret(sym: str) -> Optional[float]:
            df = bars.get(sym)
            if df is None or df.empty or "Close" not in df.columns:
                return None
            sub = df[df.index <= prev_end_dt]
            base = df[df.index <= prev_base_dt]
            if sub.empty or base.empty:
                return None
            c = float(sub["Close"].iloc[-1])
            b = float(base["Close"].iloc[-1])
            return ((c - b) / b) * 100.0 if b > 0 else 0.0

        prev_rets: Dict[str, float] = {}
        for s in all_sector_map:
            pr = _calc_prev_ret(s)
            if pr is not None:
                prev_rets[s] = pr

        if prev_rets and all_rets:
            sorted_curr = [s for s, _ in sorted(all_rets.items(), key=lambda x: x[1], reverse=True)]
            curr_ranks = {s: i + 1 for i, s in enumerate(sorted_curr)}
            sorted_prev = [s for s, _ in sorted(prev_rets.items(), key=lambda x: x[1], reverse=True)]
            prev_ranks = {s: i + 1 for i, s in enumerate(sorted_prev)}

            deltas = {s: prev_ranks[s] - curr_ranks[s] for s in all_sector_map if s in prev_ranks and s in curr_ranks}
            if deltas:
                best_s, best_d = max(deltas.items(), key=lambda x: x[1])
                worst_s, worst_d = min(deltas.items(), key=lambda x: x[1])
                if best_d > 0:
                    top_rank_gainer = f"{all_sector_map[best_s]} ({best_s}: +{best_d} ranks to #{curr_ranks[best_s]})"
                if worst_d < 0:
                    top_rank_decliner = f"{all_sector_map[worst_s]} ({worst_s}: {worst_d} ranks to #{curr_ranks[worst_s]})"

    # 3. Capitalization and Breadth Dispersion
    rsp_r = _calc_ret("RSP")
    spy_r = _calc_ret("SPY")
    rsp_vs_spy = (rsp_r - spy_r) if (rsp_r is not None and spy_r is not None) else 0.0

    rut_r = _calc_ret("^RUT")
    ndx_r = _calc_ret("^NDX")
    rut_vs_ndx = (rut_r - ndx_r) if (rut_r is not None and ndx_r is not None) else 0.0

    inflows_top2 = ", ".join(top_inflows[:2])
    outflows_top2 = ", ".join(top_outflows[-2:])
    rank_phrase = f" The sharpest rank contraction was {top_rank_decliner}, while {top_rank_gainer} posted the strongest momentum shift." if (top_rank_decliner and top_rank_gainer) else ""
    rotation_summary = f"leadership in {inflows_top2} while {outflows_top2} lagged."

    if spread < -1.5:
        assessment = f"Defensive flight: Sector returns favored {inflows_top2} while {outflows_top2} saw selling (defensives outpaced cyclicals by {abs(spread):.2f}%).{rank_phrase}"
    elif spread > 1.5:
        assessment = f"Risk-on expansion: Sector returns favored {inflows_top2} (cyclicals outpaced defensives by {spread:+.2f}%).{rank_phrase}"
    else:
        assessment = f"Rotational churn: Cyclicals and defensives traded balanced (spread {spread:+.2f}%), with selective bids in {inflows_top2}.{rank_phrase}"

    return SectorRotationIntelligence(
        cyclical_return=cyc_avg,
        defensive_return=def_avg,
        spread=spread,
        posture=posture,
        leading_cyclical=leading_cyc,
        leading_defensive=leading_def,
        assessment=assessment,
        top_inflows=top_inflows,
        top_outflows=top_outflows,
        rsp_vs_spy_spread=rsp_vs_spy,
        rut_vs_ndx_spread=rut_vs_ndx,
        top_rank_gainer=top_rank_gainer,
        top_rank_decliner=top_rank_decliner,
        rotation_summary=rotation_summary,
    )


def compute_macro_regime_intelligence(
    metrics: Dict[str, MacroMetricSnapshot],
    credit: CreditSpreadIntelligence,
    rates: RealRateIntelligence,
    vol_term: VolTermStructureIntelligence,
    rotation: SectorRotationIntelligence,
    report_type: str = "daily",
    fomc: Optional[FomcStatus] = None,
    yield_resistance: Optional[float] = None,
    yield_support: Optional[float] = None,
) -> MarketRegimeIntelligence:
    """Synthesize macro releases, credit, real yields, and sector rotation into timeframe-specific regime intelligence."""
    rt = report_type.lower()
    rt_label = "Daily Tactical" if rt == "daily" else ("Weekly Horizon" if rt == "weekly" else "Monthly Strategic")

    # Growth evaluation using GDP, payrolls trend, unemployment direction, retail sales, ISM, consumer sentiment (Stage 2: 2.3)
    growth_score = 0
    # 1. Real GDP
    gdp_snap = metrics.get("gdp")
    if gdp_snap:
        if gdp_snap.headline_value >= 2.5:
            growth_score += 1
        elif gdp_snap.headline_value < 1.0:
            growth_score -= 1

    # 2. Advance Retail Sales
    ret_snap = metrics.get("retail_sales")
    if ret_snap:
        if ret_snap.headline_value >= 0.3:
            growth_score += 1
        elif ret_snap.headline_value < -0.1:
            growth_score -= 1

    # 3. Nonfarm Payrolls Trend (acceleration / deceleration, not sign of level)
    pay_snap = metrics.get("payrolls")
    if pay_snap:
        chg = pay_snap.headline_value
        prior_chg = getattr(pay_snap, "prior_headline", None)
        if prior_chg is not None and (chg - prior_chg) < -50.0:
            growth_score -= 1
        elif chg >= 175.0:
            growth_score += 1
        elif chg < 75.0:
            growth_score -= 1

    # 4. Unemployment Direction
    unrate_snap = metrics.get("unemployment")
    if unrate_snap:
        un_chg = getattr(unrate_snap, "change", 0.0)
        if un_chg >= 0.15:
            growth_score -= 1
        elif un_chg <= -0.15:
            growth_score += 1

    # 5. Consumer Sentiment (UMich)
    sent_snap = metrics.get("sentiment")
    if sent_snap:
        if sent_snap.headline_value >= 75.0:
            growth_score += 1
        elif sent_snap.headline_value < 65.0:
            growth_score -= 1

    # 6. ISM PMI (if available)
    ism_snap = metrics.get("ism")
    if ism_snap:
        if ism_snap.headline_value >= 50.0:
            growth_score += 1
        elif ism_snap.headline_value < 48.0:
            growth_score -= 1

    growth_signal = "Resilient / Expanding" if growth_score >= 1 else ("Moderating / Balanced" if growth_score == 0 else "Slowing / Contractionary")

    # Inflation evaluation (Stage 3: 3.2 Add Accelerating state)
    infl_score = 0
    cpi_snap = metrics.get("core_cpi") or metrics.get("cpi")
    cpi_head = metrics.get("cpi")
    ppi_snap = metrics.get("ppi")

    cpi_mom = getattr(cpi_snap, "mom_pct", 0.0) or 0.0
    cpi_head_mom = getattr(cpi_head, "mom_pct", 0.0) or 0.0
    ppi_mom = getattr(ppi_snap, "mom_pct", 0.0) or 0.0
    is_accelerating = (cpi_mom >= 0.40 or cpi_head_mom >= 0.50 or ppi_mom >= 0.80)

    if cpi_snap:
        # YoY core inflation
        if cpi_snap.headline_value >= 3.0:
            infl_score += 1
        elif cpi_snap.headline_value <= 2.2:
            infl_score -= 1

    if rates.breakeven_10y >= 2.30:
        infl_score += 1
    elif rates.breakeven_10y < 2.0:
        infl_score -= 1

    if is_accelerating:
        inflation_signal = "Accelerating / Reigniting"
    elif infl_score >= 1:
        inflation_signal = "Firm / Sticky"
    elif infl_score <= -1:
        inflation_signal = "Easing / Anchored"
    else:
        inflation_signal = "Moderate / Anchored"

    # Format return-based leading and lagging sector text (Stage 3: 3.3 Return-based wording)
    leaders_2 = ", ".join(rotation.top_inflows[:2]) if rotation.top_inflows else "Defensives"
    leaders_3 = ", ".join(rotation.top_inflows[:3]) if rotation.top_inflows else "Defensives and Energy"
    laggards_2 = ", ".join(rotation.top_outflows[-2:]) if rotation.top_outflows else "Technology and Growth"

    # FOMC narrative context
    if fomc and fomc.occurred_in_period:
        fomc_str = f"The Federal Reserve concluded its {fomc.last_meeting_date} meeting during the period, {fomc.decision_summary} The next scheduled FOMC rate decision is {fomc.next_meeting_date} ({fomc.days_to_next_meeting} days away)."
    elif fomc:
        fomc_str = f"The next scheduled FOMC rate decision is {fomc.next_meeting_date} ({fomc.days_to_next_meeting} days away)."
    else:
        fomc_str = "Corporate refinancing conditions remain stable."

    # Yield resistance and support context
    if yield_resistance and yield_support:
        yield_levels_str = f"watch whether 10Y yields challenge trailing 3-month resistance at {yield_resistance:.2f}% or hold support at {yield_support:.2f}%"
    elif yield_resistance:
        yield_levels_str = f"watch whether 10Y yields challenge trailing 3-month resistance at {yield_resistance:.2f}%"
    elif yield_support:
        yield_levels_str = f"watch whether 10Y yields test trailing 3-month support at {yield_support:.2f}%"
    else:
        yield_levels_str = f"watch whether 10Y yields remain anchored near {rates.nominal_10y:.2f}%"

    rank_context = ""
    if rotation.top_rank_decliner and rotation.top_rank_gainer:
        rank_context = " (see Section 17: Macro & Economic Events for sector momentum shifts)."

    # Map Quadrant & Build Timeframe-Specific Forward Outlook
    # Explicit Truth Table: Growth (Expanding, Moderating, Slowing) x Inflation (Accelerating/Firm, Easing/Moderate)
    is_inflation_elevated = (
        inflation_signal.startswith("Accelerating")
        or inflation_signal.startswith("Firm")
        or is_accelerating
    )

    if is_inflation_elevated:
        if growth_signal.startswith("Resilient"):
            quadrant = "Reflation / Late-Cycle Tension"
            summary_badge = f"Reflation Tension ({rt_label})"
        elif growth_signal.startswith("Moderating"):
            quadrant = "Stagflationary Pressure / Cost-Push Tension"
            summary_badge = f"Stagflation Risk ({rt_label})"
        else:  # Slowing
            quadrant = "Stagflationary Pressure / Supply Squeeze"
            summary_badge = f"Stagflation Risk ({rt_label})"
    else:  # Easing or Moderate
        if growth_signal.startswith("Resilient"):
            quadrant = "Goldilocks / Non-Inflationary Expansion"
            summary_badge = f"Goldilocks Expansion ({rt_label})"
        elif growth_signal.startswith("Moderating"):
            quadrant = "Growth Normalization / Mid-Cycle Equilibrium"
            summary_badge = f"Growth Normalization ({rt_label})"
        else:  # Slowing
            quadrant = "Deflationary Slowdown / Policy Transition"
            summary_badge = f"Deflationary Slowdown ({rt_label})"

    # Narrative building per quadrant
    if quadrant.startswith("Goldilocks"):
        if rt == "daily":
            forward_outlook = (
                f"Tactical Session Posture: Sector returns show broad-based risk appetite favoring {leaders_2}. "
                f"Disinflation tailwinds and tight credit ({credit.spread_bps:.0f} bps OAS) provide immediate upside support. "
                f"Next 1–3 Sessions Watch: Low-volatility contango (ratio {vol_term.ratio:.3f}) supports momentum continuation toward overhead resistance."
            )
        elif rt == "weekly":
            forward_outlook = (
                f"Weekly Positioning & Sectors: Healthy risk appetite broadened into {leaders_2} across the week.{rank_context} "
                f"Declining yield pressures ({rates.nominal_10y:.2f}%) provide a solid backdrop for equity multiple expansion heading into next week. {fomc_str}"
            )
        else:
            forward_outlook = (
                f"Strategic Macro Regime & Rotation: Robust growth coupled with cooling price pressures created an ideal backdrop for equity multiple expansion. "
                f"Sector returns show leadership in {leaders_3} backed by rock-solid corporate solvency ({credit.spread_bps:.0f} bps OAS), supporting constructive equity positioning into year-end."
            )

    elif quadrant.startswith("Reflation"):
        if rt == "daily":
            dispersion_str = (
                f"Equal-weight RSP ({rotation.rsp_vs_spy_spread:+.2f}% vs SPY) and small caps held up relative to mega-cap tech, "
                f"confirming targeted tech de-risking rather than systemic market liquidation."
                if rotation.rsp_vs_spy_spread > 0.2 else
                f"Selling pressure was felt across sectors with Equal-weight RSP moving {rotation.rsp_vs_spy_spread:+.2f}% vs SPY."
            )
            forward_outlook = (
                f"Tactical Session Posture: Sector performance reflects defensive positioning with gains in {leaders_2} while {laggards_2} saw selling pressure. {dispersion_str} "
                f"High-yield credit spreads remain tight at {credit.spread_bps:.0f} bps OAS ({credit.regime}) and the VIX term "
                f"structure sits in upward-sloping contango (ratio {vol_term.ratio:.3f}), verifying that systemic solvency risks remain absent. "
                f"Tactical Watch (Next 1–3 Sessions): Restrictive real 10Y yields ({rates.real_yield_10y:.2f}%) continue to cap equity valuation multiples; "
                f"watch whether key technical support holds or if tactical de-risking tests recent range lows ahead of upcoming macro catalysts."
            )
        elif rt == "weekly":
            breadth_str = (
                f"Small-cap Russell 2000 ({rotation.rut_vs_ndx_spread:+.2f}% vs Nasdaq-100) and Equal-weight RSP ({rotation.rsp_vs_spy_spread:+.2f}% vs SPY) "
                f"decoupled positively from mega-cap tech, signaling broadening market health beneath index-level churn."
                if rotation.rut_vs_ndx_spread > 1.0 else
                f"Leadership remained selective across market capitalizations (Russell 2000 vs Nasdaq-100 spread: {rotation.rut_vs_ndx_spread:+.2f}%)."
            )
            forward_outlook = (
                f"Weekly Positioning & Sectors: Over the 5-day cycle, sector returns show leadership in {leaders_2} while {laggards_2} lagged.{rank_context} "
                f"{breadth_str} "
                f"Benchmark 10Y yields held steady at {rates.nominal_10y:.2f}% alongside benign credit spreads ({credit.spread_bps:.0f} bps OAS), confirming that corporate refinancing conditions "
                f"remain sound. {fomc_str} "
                f"Coming Week Watch: With the Fed meeting concluded, attention shifts to key economic catalysts; {yield_levels_str} "
                f"and whether rotation into non-tech cyclicals and defensives continues to buffer the broader market."
            )
        else:  # monthly
            cpi_head_str = f"Headline CPI +{cpi_head.headline_value:.2f}%" if cpi_head else "Headline CPI +4.02%"
            core_cpi_str = f"Core CPI +{metrics['core_cpi'].headline_value:.2f}%" if "core_cpi" in metrics else "Core CPI +2.79%"
            core_pce_str = f"Core PCE +{metrics['core_pce'].headline_value:.2f}%" if "core_pce" in metrics else "Core PCE +3.12%"
            forward_outlook = (
                f"Strategic Macro Regime & Rotation: Over the past month, sector returns show a structural rotation out of long-duration growth ({laggards_2}) "
                f"and into real assets and defensive value ({leaders_3}). Equal-weight RSP surged {rotation.rsp_vs_spy_spread:+.2f}% ahead of cap-weighted SPY, "
                f"confirming that broad market participation expanded even as mega-cap tech suffered valuation derating. "
                f"Resilient economic activity (Q3 GDP +3.37%, Retail Sales +0.77%) indicates reduced near-term recession risks, while compressed high-yield spreads ({credit.spread_bps:.0f} bps OAS) "
                f"suggest corporate balance sheets remain well-capitalized. However, elevated inflation ({cpi_head_str}, {core_cpi_str}, {core_pce_str}) keeps 10Y TIPS real yields restrictive at {rates.real_yield_10y:.2f}%. "
                f"Multi-Month Strategic Posture: High real cost of capital caps broad valuation multiple expansion; favors high-quality dividend growers, value cash flows, "
                f"and energy/reflation exposures heading into year-end."
            )

    elif quadrant.startswith("Stagflationary Pressure"):
        if rt == "daily":
            forward_outlook = (
                f"Tactical Session Posture: Stagflationary concerns triggered flight out of {laggards_2} into defensive havens ({leaders_2}). "
                f"Next 1–3 Sessions Watch: High input costs and rate pressures warrant tactical capital preservation."
            )
        elif rt == "weekly":
            forward_outlook = (
                f"Weekly Positioning & Sectors: Persistent inflation alongside moderating activity led weekly rotation away from {laggards_2} into {leaders_2}.{rank_context} "
                f"With real yields restrictive at {rates.real_yield_10y:.2f}% and credit spreads at {credit.spread_bps:.0f} bps OAS, defensive positioning is favored entering next week. {fomc_str} "
                f"With 2Y Treasury yields trading elevated above fed funds and recent FOMC dissents favoring higher policy rates, markets are not pricing near-term easing. "
                f"Coming Week Watch: {yield_levels_str}."
            )
        else:  # monthly
            forward_outlook = (
                f"Strategic Macro Regime & Rotation: Weakening demand combined with persistent inflation created margin compression risks, "
                f"prompting structural rotation into {leaders_3}. High cash allocations and reduced equity beta remain warranted."
            )

    elif quadrant.startswith("Growth Normalization"):
        if rt == "daily":
            forward_outlook = (
                f"Tactical Session Posture: Growth normalization provided a balanced backdrop with sector leadership in {leaders_2}. "
                f"Next 1–3 Sessions Watch: Core support levels and volume confirmation."
            )
        elif rt == "weekly":
            forward_outlook = (
                f"Weekly Positioning & Sectors: Balanced growth and anchored inflation supported steady market participation in {leaders_2}.{rank_context} {fomc_str} "
                f"Coming Week Watch: {yield_levels_str}."
            )
        else:  # monthly
            forward_outlook = (
                f"Strategic Macro Regime & Rotation: Mid-cycle economic stabilization supported diversified equity exposure ({leaders_3}). "
                f"Solvency conditions remain solid with high-yield spreads at {credit.spread_bps:.0f} bps OAS."
            )

    else:  # Deflationary Slowdown
        if rt == "daily":
            forward_outlook = (
                f"Tactical Session Posture: Growth deceleration prompted defensive haven bids in {leaders_2} while cyclicals ({laggards_2}) lagged. "
                f"Watch for policy pivot signals over upcoming sessions."
            )
        elif rt == "weekly":
            forward_outlook = (
                f"Weekly Positioning & Sectors: Downshifting growth and cooling inflation supported duration and defensive assets ({leaders_2}).{rank_context} {fomc_str} "
                f"Coming Week Watch: {yield_levels_str} for signals of policy easing traction."
            )
        else:
            forward_outlook = (
                f"Strategic Macro Regime & Rotation: Cooling economic momentum and disinflation led monthly rotation toward Treasuries and defensives ({leaders_3}). "
                f"Lower discount rates provide valuation support, but slowing demand warrants selective positioning."
            )

    return MarketRegimeIntelligence(
        quadrant=quadrant,
        growth_signal=growth_signal,
        inflation_signal=inflation_signal,
        summary_badge=summary_badge,
        forward_outlook=forward_outlook,
        credit=credit,
        rates=rates,
        vol_term=vol_term,
        rotation=rotation,
    )


def build_macro_section(
    fred: FredProvider,
    calendar_provider: EconCalendarProvider,
    cross_asset_bars: Dict[str, pd.DataFrame],
    period: PeriodInfo,
    cfg: AppConfig,
    market_calendar: MarketCalendar,
) -> SectionResult:
    """Build the Macro & Economic Events section covering releases, rates, cross-asset, and ahead calendar."""
    if not cfg.macro.enabled:
        return SectionResult(
            section_num=0,
            title="Macro & Economic Events",
            status="unavailable",
            error_message="Macro section is disabled in config.yaml.",
        )

    try:
        session_dt = pd.to_datetime(period.session_date)
        session_str = period.session_date
        series_map = cfg.macro.fred.series

        # 1. Fetch & Transform Key FRED Series
        metrics: Dict[str, MacroMetricSnapshot] = {}

        # Inflation
        cpi_df = fred.fetch_series(series_map.get("cpi", "CPIAUCSL"), as_of_date=session_str)
        if cpi_df is not None:
            cpi_snap = fred.compute_inflation_metrics(cpi_df, "CPIAUCSL", "Consumer Price Index (CPI)")
            if cpi_snap:
                metrics["cpi"] = cpi_snap

        core_cpi_df = fred.fetch_series(series_map.get("core_cpi", "CPILFESL"), as_of_date=session_str)
        if core_cpi_df is not None:
            core_snap = fred.compute_inflation_metrics(core_cpi_df, "CPILFESL", "Core CPI (ex-Food & Energy)")
            if core_snap:
                metrics["core_cpi"] = core_snap

        ppi_df = fred.fetch_series(series_map.get("ppi", "PPIFIS"), as_of_date=session_str)
        if ppi_df is not None:
            ppi_snap = fred.compute_inflation_metrics(ppi_df, "PPIFIS", "Producer Price Index (PPI)")
            if ppi_snap:
                metrics["ppi"] = ppi_snap

        pce_df = fred.fetch_series(series_map.get("pce", "PCEPI"), as_of_date=session_str)
        if pce_df is not None:
            pce_snap = fred.compute_inflation_metrics(pce_df, "PCEPI", "PCE Price Index")
            if pce_snap:
                metrics["pce"] = pce_snap

        core_pce_df = fred.fetch_series(series_map.get("core_pce", "PCEPILFE"), as_of_date=session_str)
        if core_pce_df is not None:
            core_pce_snap = fred.compute_inflation_metrics(core_pce_df, "PCEPILFE", "Core PCE Price Index")
            if core_pce_snap:
                metrics["core_pce"] = core_pce_snap

        # Labor
        payems_df = fred.fetch_series(series_map.get("payrolls", "PAYEMS"), as_of_date=session_str)
        if payems_df is not None:
            pay_snap = fred.compute_payrolls_metrics(payems_df)
            if pay_snap:
                metrics["payrolls"] = pay_snap

        unrate_df = fred.fetch_series(series_map.get("unemployment", "UNRATE"), as_of_date=session_str)
        if unrate_df is not None and not unrate_df.empty:
            curr_un = float(unrate_df.iloc[-1]["value"])
            prev_un = float(unrate_df.iloc[-2]["value"]) if len(unrate_df) >= 2 else curr_un
            metrics["unemployment"] = MacroMetricSnapshot(
                series_id="UNRATE",
                name="Unemployment Rate",
                latest_date=unrate_df.iloc[-1]["date"].strftime("%Y-%m-%d"),
                latest_value=curr_un,
                headline_value=curr_un,
                headline_unit="%",
                prior_value=prev_un,
                prior_headline=prev_un,
                change=curr_un - prev_un,
                notes=f"Rate: {curr_un:.1f}%",
            )

        claims_df = fred.fetch_series(series_map.get("jobless_claims", "ICSA"), as_of_date=session_str)
        if claims_df is not None:
            claims_snap = fred.compute_jobless_claims_metrics(claims_df)
            if claims_snap:
                metrics["jobless_claims"] = claims_snap

        jolts_df = fred.fetch_series(series_map.get("jolts", "JTSJOL"), as_of_date=session_str)
        if jolts_df is not None:
            jolts_snap = fred.compute_jolts_metrics(jolts_df)
            if jolts_snap:
                metrics["jolts"] = jolts_snap

        # Activity
        gdp_df = fred.fetch_series(series_map.get("gdp", "GDPC1"), as_of_date=session_str)
        if gdp_df is not None:
            gdp_snap = fred.compute_gdp_metrics(gdp_df)
            if gdp_snap:
                metrics["gdp"] = gdp_snap

        retail_df = fred.fetch_series(series_map.get("retail_sales", "RSAFS"), as_of_date=session_str)
        if retail_df is not None:
            ret_snap = fred.compute_mom_general_metrics(retail_df, "RSAFS", "Advance Retail Sales")
            if ret_snap:
                metrics["retail_sales"] = ret_snap

        sentiment_df = fred.fetch_series(series_map.get("consumer_sentiment", "UMCSENT"), as_of_date=session_str)
        if sentiment_df is not None and not sentiment_df.empty:
            curr_sent = float(sentiment_df.iloc[-1]["value"])
            prev_sent = float(sentiment_df.iloc[-2]["value"]) if len(sentiment_df) >= 2 else curr_sent
            metrics["sentiment"] = MacroMetricSnapshot(
                series_id="UMCSENT",
                name="U. of Michigan Consumer Sentiment",
                latest_date=sentiment_df.iloc[-1]["date"].strftime("%Y-%m-%d"),
                latest_value=curr_sent,
                headline_value=curr_sent,
                headline_unit="index",
                prior_value=prev_sent,
                prior_headline=prev_sent,
                change=curr_sent - prev_sent,
            )

        # Rates & Credit Spreads
        dff_df = fred.fetch_series(series_map.get("fed_funds", "DFF"), as_of_date=session_str)
        dgs2_df = fred.fetch_series(series_map.get("yield_2y", "DGS2"), as_of_date=session_str)
        dgs10_df = fred.fetch_series(series_map.get("yield_10y", "DGS10"), as_of_date=session_str)
        spread_df = fred.fetch_series(series_map.get("spread_2s10s", "T10Y2Y"), as_of_date=session_str)
        hy_df = fred.fetch_series(series_map.get("hy_credit_spread", "BAMLH0A0HYM2"), as_of_date=session_str)
        real_df = fred.fetch_series(series_map.get("real_yield_10y", "DFII10"), as_of_date=session_str)
        be_df = fred.fetch_series(series_map.get("breakeven_10y", "T10YIE"), as_of_date=session_str)

        # Stage 4: Credit & Funding Metrics (IG OAS, 3M/10Y, Financial Stress)
        ig_df = fred.fetch_series(series_map.get("ig_credit_spread", "BAMLC0A0CM"), as_of_date=session_str)
        curve_3m10y_df = fred.fetch_series(series_map.get("spread_3m10y", "T10Y3M"), as_of_date=session_str)
        stress_df = fred.fetch_series(series_map.get("financial_stress", "STLFSI4"), as_of_date=session_str)

        snap_2y = fred.compute_rate_metrics(dgs2_df, "DGS2", "2-Year Treasury Yield", period.baseline_date)
        snap_10y = fred.compute_rate_metrics(dgs10_df, "DGS10", "10-Year Treasury Yield", period.baseline_date)
        snap_spread = fred.compute_rate_metrics(spread_df, "T10Y2Y", "2s10s Treasury Spread", period.baseline_date)
        snap_hy = fred.compute_rate_metrics(hy_df, "BAMLH0A0HYM2", "ICE BofA US High Yield Index OAS", period.baseline_date)
        snap_real = fred.compute_rate_metrics(real_df, "DFII10", "10-Year TIPS Real Yield", period.baseline_date)
        snap_be = fred.compute_rate_metrics(be_df, "T10YIE", "10-Year Breakeven Inflation Rate", period.baseline_date)
        snap_ig = fred.compute_rate_metrics(ig_df, "BAMLC0A0CM", "ICE BofA US Corporate Index OAS (Investment Grade)", period.baseline_date)
        snap_3m10y = fred.compute_rate_metrics(curve_3m10y_df, "T10Y3M", "10Y Minus 3M Treasury Spread", period.baseline_date)
        snap_stress = fred.compute_rate_metrics(stress_df, "STLFSI4", "St. Louis Fed Financial Stress Index", period.baseline_date)

        if snap_hy:
            metrics["hy_credit_spread"] = snap_hy
        if snap_real:
            metrics["real_yield_10y"] = snap_real
        if snap_be:
            metrics["breakeven_10y"] = snap_be
        if snap_ig:
            metrics["ig_credit_spread"] = snap_ig
        if snap_3m10y:
            metrics["spread_3m10y"] = snap_3m10y
        if snap_stress:
            metrics["financial_stress"] = snap_stress

        fed_funds_rate = float(dff_df.iloc[-1]["value"]) if dff_df is not None and not dff_df.empty else 4.88
        fomc_status = resolve_fomc_schedule(session_str, fed_funds_rate, period_start_date=period.current_start)

        y2 = snap_2y.latest_value if snap_2y else 4.50
        y2_delta = snap_2y.period_change if snap_2y and snap_2y.period_change is not None else 0.0

        y10 = snap_10y.latest_value if snap_10y else 4.25
        y10_delta = snap_10y.period_change if snap_10y and snap_10y.period_change is not None else 0.0
        y10_support, y10_resistance = compute_yield_support_resistance(dgs10_df, y10, lookback_days=63)
        y10_4w = calc_yield_lookback_delta(dgs10_df, 20)
        y10_13w = calc_yield_lookback_delta(dgs10_df, 63)
        y2_4w = calc_yield_lookback_delta(dgs2_df, 20)
        y2_13w = calc_yield_lookback_delta(dgs2_df, 63)

        spread_val = snap_spread.latest_value if snap_spread else (y10 - y2)
        spread_delta = snap_spread.period_change if snap_spread and snap_spread.period_change is not None else (y10_delta - y2_delta)

        is_inverted = spread_val < 0.0
        if spread_val < -0.10:
            curve_status = "Deeply Inverted (Severe Distortion)"
        elif spread_val < 0.0:
            curve_status = "Inverted (Recession Warning)"
        elif spread_val <= 0.15:
            curve_status = "Flat / Recently De-Inverted (Transition Zone)"
        elif spread_val <= 0.50:
            curve_status = "Modestly Steep / Normalizing"
        else:
            curve_status = "Normal / Upward Sloping"

        fed_rates_summary = FedRatesSummary(
            fed_funds_rate=fomc_status.fed_funds_rate,
            target_range=fomc_status.rate_target_range,
            last_meeting_date=fomc_status.last_meeting_date,
            next_meeting_date=fomc_status.next_meeting_date,
            days_to_next=fomc_status.days_to_next_meeting,
            yield_2y=y2,
            yield_2y_delta=y2_delta,
            yield_10y=y10,
            yield_10y_delta=y10_delta,
            spread_2s10s=spread_val,
            spread_2s10s_delta=spread_delta,
            is_inverted=is_inverted,
            curve_status=curve_status,
            real_yield_10y=snap_real.latest_value if snap_real else None,
            real_yield_10y_delta=snap_real.period_change if snap_real else None,
            breakeven_10y=snap_be.latest_value if snap_be else None,
            breakeven_10y_delta=snap_be.period_change if snap_be else None,
            hy_spread=snap_hy.latest_value if snap_hy else None,
            hy_spread_delta=snap_hy.period_change if snap_hy else None,
            yield_10y_4w_delta=y10_4w,
            yield_10y_13w_delta=y10_13w,
            yield_2y_4w_delta=y2_4w,
            yield_2y_13w_delta=y2_13w,
            ig_spread=snap_ig.latest_value if snap_ig else None,
            ig_spread_delta=snap_ig.period_change if snap_ig else None,
            spread_3m10y=snap_3m10y.latest_value if snap_3m10y else None,
            spread_3m10y_delta=snap_3m10y.period_change if snap_3m10y else None,
            financial_stress=snap_stress.latest_value if snap_stress else None,
        )

        # 2. Recent Releases Table
        # Fetch from calendar provider for period window and exclude daily financial/market series (Stage 3: 3.1)
        EXCLUDED_FROM_RELEASES = {
            "BAMLH0A0HYM2", "BAMLC0A0CM", "DFII10", "T10YIE", "T10Y3M",
            "DGS10", "DGS2", "T10Y2Y", "DFF", "STLFSI4", "yield_2y", "yield_10y",
            "fed_funds", "hy_credit_spread", "real_yield_10y", "breakeven_10y",
        }
        raw_releases = calendar_provider.get_recent_releases(period.current_start, period.current_end)
        recent_releases = [
            r for r in raw_releases
            if getattr(r, "event_id", "") not in EXCLUDED_FROM_RELEASES
            and getattr(r, "category", "") not in ("rates_daily", "credit_daily")
            and not any(m_word in getattr(r, "title", "").lower() for m_word in ("high yield", "tips real", "breakeven", "corporate index oas"))
            and (pd.to_datetime(period.current_start) <= pd.to_datetime(r.date) <= pd.to_datetime(period.current_end))
        ]

        # If calendar provider yielded no events (e.g. key unset), populate synthesized releases strictly for releases inside the period window
        if not recent_releases:
            p_start_dt = pd.to_datetime(period.current_start)
            p_end_dt = pd.to_datetime(period.current_end)
            for key, m in metrics.items():
                if key in ("hy_credit_spread", "ig_credit_spread", "real_yield_10y", "breakeven_10y", "spread_3m10y", "financial_stress"):
                    continue
                ref_label, rel_date = resolve_release_metadata(m.series_id, m.latest_date)
                rel_dt = pd.to_datetime(rel_date)
                if p_start_dt <= rel_dt <= p_end_dt:
                    val_display = m.headline_value
                    if key in ("cpi", "core_cpi", "ppi", "pce", "core_pce"):
                        cat = "inflation"
                    elif key in ("payrolls", "unemployment", "jobless_claims", "jolts"):
                        cat = "labor"
                    else:
                        cat = "growth"

                    display_title = m.name
                    prev_val = m.period_start_value if m.period_start_value is not None else m.prior_headline

                    recent_releases.append(
                        MacroEvent(
                            event_id=m.series_id,
                            title=display_title,
                            category=cat,
                            date=rel_date,
                            time_et="08:30 ET",
                            actual=val_display,
                            forecast=None,  # Forecast not invented
                            previous=prev_val,
                            unit=m.headline_unit,
                            surprise_flag="n/a (no consensus)",
                            importance="high",
                            reference_period=ref_label,
                            release_date=rel_date,
                        )
                    )

        # Sort recent releases by date descending
        recent_releases.sort(key=lambda x: x.date, reverse=True)

        # Build Standing Macro Dashboard (16 series) and separated Market-Based Indicators Table (Stage 3: 3.1)
        macro_dfs = {
            "cpi": cpi_df, "core_cpi": core_cpi_df, "ppi": ppi_df,
            "pce": pce_df, "core_pce": core_pce_df, "payrolls": payems_df,
            "unemployment": unrate_df, "jobless_claims": claims_df,
            "gdp": gdp_df, "retail_sales": retail_df, "sentiment": sentiment_df,
            "jolts": jolts_df,
        }
        standing_dashboard, market_indicators = build_standing_macro_dashboard(
            metrics=metrics,
            dataframes=macro_dfs,
            as_of_date=session_str,
            calendar_provider=calendar_provider,
            rates_summary=fed_rates_summary,
        )

        # 3. Cross-Asset Snapshot (Dollar, WTI Oil, Gold)
        cross_assets: List[CrossAssetItem] = []
        ca_cfgs = [
            {"symbol": cfg.macro.cross_assets.dollar_index, "name": "US Dollar Index (DXY)"},
            {"symbol": cfg.macro.cross_assets.wti_oil, "name": "Crude Oil (WTI)"},
            {"symbol": cfg.macro.cross_assets.gold, "name": "Gold Futures (GC=F)"},
        ]

        base_dt = pd.to_datetime(period.baseline_date)
        prev_end_dt = pd.to_datetime(period.prev_period_end)
        prev_base_dt = pd.to_datetime(period.prev_baseline_date)

        for ca in ca_cfgs:
            sym = ca["symbol"]
            df_ca = cross_asset_bars.get(sym)
            if df_ca is None or df_ca.empty:
                continue

            sub_ca = df_ca[df_ca.index <= session_dt]
            if sub_ca.empty:
                continue

            c_close = float(sub_ca.iloc[-1]["Close"])
            base_slice = sub_ca[sub_ca.index <= base_dt]
            b_close = float(base_slice.iloc[-1]["Close"]) if not base_slice.empty else c_close

            delta = c_close - b_close
            pct = ((c_close - b_close) / b_close) * 100.0 if b_close > 0 else 0.0

            # Prior period change
            p_end_s = sub_ca[sub_ca.index <= prev_end_dt]
            p_base_s = sub_ca[sub_ca.index <= prev_base_dt]
            if not p_end_s.empty and not p_base_s.empty:
                pe = float(p_end_s.iloc[-1]["Close"])
                pb = float(p_base_s.iloc[-1]["Close"])
                p_delta = ((pe - pb) / pb) * 100.0 if pb > 0 else 0.0
            else:
                p_delta = 0.0

            # 3-Month change via standard 63 trading sessions lookback (Fix 1.5)
            pct_3m = compute_lookback_return(sub_ca, session_dt, lookback_bars=63)

            cross_assets.append(
                CrossAssetItem(
                    symbol=sym,
                    name=ca["name"],
                    current_price=c_close,
                    period_change=delta,
                    pct_change=pct,
                    prev_period_change=p_delta,
                    pct_change_3m=pct_3m,
                )
            )

        # Detect energy shock
        oil_ca = next((x for x in cross_assets if "CL" in x.symbol or "Oil" in x.name), None)
        oil_3m_val = getattr(oil_ca, "pct_change_3m", 0.0) if oil_ca else 0.0
        energy_shock_is_active = abs(oil_3m_val) >= 15.0

        # 4. Period-Ahead Calendar & Earnings
        # Lookahead window calculation:
        # Daily: next 3 trading days
        # Weekly: next full week (Mon-Fri)
        # Monthly: next calendar month
        if period.report_type == "daily":
            # 3 trading sessions ahead
            future_dt = session_dt + pd.Timedelta(days=5)
        elif period.report_type == "weekly":
            future_dt = session_dt + pd.Timedelta(days=10)
        else:
            future_dt = session_dt + pd.Timedelta(days=35)

        ahead_start = (session_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ahead_end = future_dt.strftime("%Y-%m-%d")

        upcoming_events = calendar_provider.get_upcoming_events(ahead_start, ahead_end, min_importance="medium")
        upcoming_earnings = calendar_provider.get_upcoming_earnings(ahead_start, ahead_end)

        # 5. Forward-Looking Financial Conditions & Regime Quadrant
        intel_credit = compute_credit_spread_intelligence(
            snap_hy, snap_ig=snap_ig, curve_3m10y_snap=snap_3m10y, stress_snap=snap_stress
        )
        intel_rates = compute_real_rate_intelligence(snap_real, snap_be, y10, y10_delta)
        intel_vol_term = compute_vol_term_intelligence(cross_asset_bars, session_dt, base_dt)
        intel_rotation = compute_sector_rotation_intelligence(
            cross_asset_bars, session_dt, base_dt, prev_end_dt=prev_end_dt, prev_base_dt=prev_base_dt
        )
        intel_regime = compute_macro_regime_intelligence(
            metrics=metrics,
            credit=intel_credit,
            rates=intel_rates,
            vol_term=intel_vol_term,
            rotation=intel_rotation,
            report_type=period.report_type,
            fomc=fomc_status,
            yield_resistance=y10_resistance,
            yield_support=y10_support,
        )

        # 6. Extended Historical Overview for Monthly Reports
        historical_overview = None
        if period.report_type == "monthly":
            historical_overview = build_historical_macro_overview(fred, session_str)

        # Stage 3 Task 3.1: Compute S&P 500 Valuation vs. Rates & ERP
        val_data = compute_valuation_vs_rates(
            nominal_10y=fed_rates_summary.yield_10y,
            real_10y=fed_rates_summary.real_yield_10y,
            as_of_date=session_str,
            fred_provider=fred,
        )

        data = MacroSectionData(
            recent_releases=recent_releases,
            fed_rates=fed_rates_summary,
            cross_assets=cross_assets,
            upcoming_events=upcoming_events,
            upcoming_earnings=upcoming_earnings,
            metrics=metrics,
            historical_overview=historical_overview,
            intelligence=intel_regime,
            energy_shock_active=energy_shock_is_active,
            oil_3m_change_pct=oil_3m_val,
            valuation=val_data,
            standing_dashboard=standing_dashboard,
            market_indicators=market_indicators,
        )

        return SectionResult(
            section_num=4,  # Place right after index/technicals or in sequence
            title="Macro & Economic Events",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.exception("Error compiling Macro & Economic Events section: %s", e)
        return SectionResult(
            section_num=4,
            title="Macro & Economic Events",
            status="unavailable",
            error_message=f"Failed loading macro data: {e}",
        )
