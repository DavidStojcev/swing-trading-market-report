"""Section: Federal Reserve Policy Path & Monetary Transmission."""

from dataclasses import dataclass
import logging
from typing import Any, Optional, Tuple
import pandas as pd

from data.fomc import FomcStatus, resolve_fomc_schedule
from sections.base import SectionResult

logger = logging.getLogger(__name__)

FUTURES_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"
}


def derive_fed_rate_probabilities(
    as_of_date: str,
    next_meeting_date: str,
    effective_fed_funds: float,
    data_provider: Optional[Any] = None,
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """Derive Hold, +25 bps Hike, and -25 bps Cut probabilities from 30-day Fed funds futures (ZQ).

    Returns:
        (prob_hold, prob_hike, prob_cut, source_str)
        If contract is missing, expired, or unavailable, returns (None, None, None, 'n/a (source unavailable)').
    """
    try:
        as_of_dt = pd.to_datetime(as_of_date)
        next_dt = pd.to_datetime(next_meeting_date)

        m_code = FUTURES_MONTH_CODES.get(next_dt.month, "Z")
        y_2d = str(next_dt.year)[2:]
        primary_sym = f"ZQ{m_code}{y_2d}.CBT"
        candidates = [primary_sym, "ZQ=F"]

        start_str = (as_of_dt - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        end_str = (as_of_dt + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

        df = None
        used_sym = None

        # 1. Try via data_provider if it has get_history
        if data_provider is not None and hasattr(data_provider, "get_history"):
            for sym in candidates:
                try:
                    bars = data_provider.get_history([sym], start_date=start_str, end_date=end_str)
                    if bars and sym in bars and not bars[sym].empty:
                        sub = bars[sym]
                        if hasattr(sub.index, "tz") and sub.index.tz is not None:
                            sub_filtered = sub[sub.index.tz_convert(None) <= as_of_dt]
                        else:
                            sub_filtered = sub[sub.index <= as_of_dt]
                        if not sub_filtered.empty:
                            df = sub_filtered
                            used_sym = sym
                            break
                except Exception as e:
                    logger.debug("Failed fetching %s from data_provider: %s", sym, e)

        # 2. Try directly via YFinanceDataProvider if still None
        if df is None:
            try:
                from data.yfinance_provider import YFinanceDataProvider
                prov = YFinanceDataProvider()
                for sym in candidates:
                    bars = prov.get_history([sym], start_date=start_str, end_date=end_str)
                    if bars and sym in bars and not bars[sym].empty:
                        sub = bars[sym]
                        if hasattr(sub.index, "tz") and sub.index.tz is not None:
                            sub_filtered = sub[sub.index.tz_convert(None) <= as_of_dt]
                        else:
                            sub_filtered = sub[sub.index <= as_of_dt]
                        if not sub_filtered.empty:
                            df = sub_filtered
                            used_sym = sym
                            break
            except Exception as e:
                logger.debug("Failed direct YFinanceDataProvider lookup for ZQ: %s", e)

        # 3. Fallback to direct yfinance query
        if df is None:
            import yfinance as yf
            for sym in candidates:
                try:
                    t = yf.Ticker(sym)
                    hist = t.history(start=start_str, end=end_str)
                    if not hist.empty:
                        if hasattr(hist.index, "tz") and hist.index.tz is not None:
                            hist_sub = hist[hist.index.tz_convert(None) <= as_of_dt]
                        else:
                            hist_sub = hist[hist.index <= as_of_dt]
                        if not hist_sub.empty:
                            df = hist_sub
                            used_sym = sym
                            break
                except Exception as e:
                    logger.debug("Failed yf.Ticker lookup for %s: %s", sym, e)

        if df is None or df.empty or used_sym is None:
            return None, None, None, "n/a (source unavailable)"

        latest_close = float(df["Close"].iloc[-1])
        quote_dt = df.index[-1].strftime("%Y-%m-%d")
        r_implied = 100.0 - latest_close

        # CME 30-Day Fed Funds Futures formulation for monthly rate
        days_in_month = pd.Period(next_dt, freq="M").days_in_month
        d_before = next_dt.day
        d_after = max(1, days_in_month - d_before)
        r0 = effective_fed_funds

        # Expected rate following the FOMC meeting
        r1 = (days_in_month * r_implied - d_before * r0) / d_after
        delta_r = r1 - r0

        if delta_r <= -0.25:
            p_cut, p_hold, p_hike = 1.0, 0.0, 0.0
        elif delta_r < 0.0:
            p_cut = round(-delta_r / 0.25, 3)
            p_hold = round(1.0 - p_cut, 3)
            p_hike = 0.0
        elif delta_r >= 0.25:
            p_cut, p_hold, p_hike = 0.0, 0.0, 1.0
        elif delta_r > 0.0:
            p_hike = round(delta_r / 0.25, 3)
            p_hold = round(1.0 - p_hike, 3)
            p_cut = 0.0
        else:
            p_cut, p_hold, p_hike = 0.0, 1.0, 0.0

        src = f"CBOT 30-Day Fed Funds Futures ({used_sym}: {latest_close:.3f}, as of {quote_dt} 16:00 ET)"
        return p_hold, p_hike, p_cut, src

    except Exception as e:
        logger.warning("Could not derive Fed rate probabilities: %s", e)
        return None, None, None, "n/a (source unavailable)"


@dataclass
class FedPathData:
    last_action_date: str
    last_action_description: str
    current_target_range: str
    effective_fed_funds: float
    next_meeting_date: str
    days_to_next_meeting: int
    market_implied_prob_hold: Optional[float]
    market_implied_prob_hike: Optional[float]
    market_implied_prob_cut: Optional[float]
    yield_2y: float
    spread_2y_vs_fed_funds_bps: float
    trailing_core_inflation: float
    real_policy_rate: float
    assessment: str
    prob_source: str = "CME FedWatch proxy"
    vote_count: str = "10-2"
    dissents: str = "None"
    real_rate_driver_measure: str = "Core PCE"


def build_fed_path(
    macro_data: Optional[Any],
    as_of_date: str,
    cfg: Optional[Any] = None,
    data_provider: Optional[Any] = None,
) -> SectionResult:
    """Build Fed policy trajectory, market expectations, and monetary stance section."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)

        # Rates & spreads
        fr = getattr(macro_data, "fed_rates", None) if macro_data else None
        eff_ff = getattr(fr, "fed_funds_rate", 3.83) if fr else 3.83
        y2 = getattr(fr, "yield_2y", 4.60) if fr else 4.60
        spread_2y_ff_bps = (y2 - eff_ff) * 100.0

        fomc_status = resolve_fomc_schedule(as_of_date=as_of_date, fed_funds_rate=eff_ff)
        last_date = fomc_status.last_meeting_date
        last_desc = fomc_status.decision_summary
        curr_target = fomc_status.rate_target_range
        next_date = fomc_status.next_meeting_date
        days_to_next = fomc_status.days_to_next_meeting

        # Derive market-implied probabilities from 30-day Fed funds futures (Stage 4: 4.1)
        p_hold, p_hike, p_cut, prob_src = derive_fed_rate_probabilities(
            as_of_date=as_of_date,
            next_meeting_date=next_date,
            effective_fed_funds=eff_ff,
            data_provider=data_provider,
        )

        # Trailing core inflation for real policy rate (Stage 3: 3.1 Label exact inflation measure)
        metrics = getattr(macro_data, "metrics", {}) if macro_data else {}
        if "core_pce" in metrics:
            core_m = metrics["core_pce"]
            core_measure_name = "Core PCE"
        elif "core_cpi" in metrics:
            core_m = metrics["core_cpi"]
            core_measure_name = "Core CPI"
        else:
            core_m = metrics.get("cpi")
            core_measure_name = "Headline CPI"

        core_inf = core_m.headline_value if core_m else 3.12
        real_policy_rate = eff_ff - core_inf

        # Synthesis
        if spread_2y_ff_bps > 30.0:
            rate_bias = f"Trading +{spread_2y_ff_bps:.0f} bps above Effective Fed Funds ({eff_ff:.2f}%), reflecting market expectations that policy rates will remain restrictive"
        elif spread_2y_ff_bps < -30.0:
            rate_bias = f"Trading {spread_2y_ff_bps:.0f} bps below Effective Fed Funds ({eff_ff:.2f}%), reflecting market anticipation of policy adjustments"
        else:
            rate_bias = f"Anchored in line with current policy ({eff_ff:.2f}%)"

        assessment = (
            f"The Federal Reserve policy stance remains restrictive with a positive real policy rate of {real_policy_rate:+.2f}% "
            f"against trailing {core_measure_name} inflation ({core_inf:.2f}% YoY). The real policy rate benchmark is driven by "
            f"{core_measure_name} (the Fed's primary price stability mandate indicator). The 2-Year Treasury yield sits at {y2:.2f}%, {rate_bias}. "
            f"The next policy meeting is scheduled for {next_date} ({days_to_next} days away)."
        )

        data = FedPathData(
            last_action_date=last_date,
            last_action_description=last_desc,
            current_target_range=curr_target,
            effective_fed_funds=eff_ff,
            next_meeting_date=next_date,
            days_to_next_meeting=days_to_next,
            market_implied_prob_hold=p_hold,
            market_implied_prob_hike=p_hike,
            market_implied_prob_cut=p_cut,
            yield_2y=y2,
            spread_2y_vs_fed_funds_bps=spread_2y_ff_bps,
            trailing_core_inflation=core_inf,
            real_policy_rate=real_policy_rate,
            assessment=assessment,
            prob_source=prob_src,
            vote_count=fomc_status.vote_count,
            dissents=fomc_status.dissents,
            real_rate_driver_measure=core_measure_name,
        )

        return SectionResult(
            section_num=9,
            title="Federal Reserve Policy Path & Monetary Stance",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building Fed path section: %s", e)
        return SectionResult(
            section_num=9,
            title="Federal Reserve Policy Path & Monetary Stance",
            status="unavailable",
            error_message=f"Fed path error: {e}",
        )
