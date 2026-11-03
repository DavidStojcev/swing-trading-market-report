"""Section 4: Volatility and VIX analysis builder."""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import pandas as pd

from config.settings import SymbolItem
from data.calendar import PeriodInfo
from sections.base import SectionResult


@dataclass
class VolatilityData:
    symbol: str
    name: str
    current_level: float
    prev_level: float
    change: float
    pct_change: float
    period_high: float
    period_low: float
    regime: str
    regime_description: str
    implied_daily_move_pct: float = 0.0


def build_volatility(
    bars: Dict[str, pd.DataFrame],
    vix_symbol: Any,
    period: PeriodInfo,
) -> SectionResult:
    """Build volatility section analyzing VIX levels and regime."""
    sym_str = vix_symbol.symbol if hasattr(vix_symbol, "symbol") else str(vix_symbol)
    df = bars.get(sym_str)
    if df is None or df.empty:
        return SectionResult(
            section_num=4,
            title="Volatility (VIX)",
            status="unavailable",
            error_message="VIX price series unavailable.",
        )

    curr_end_dt = pd.to_datetime(period.session_date)
    sub = df[df.index <= curr_end_dt]
    if sub.empty:
        return SectionResult(
            section_num=4,
            title="Volatility (VIX)",
            status="unavailable",
            error_message="No VIX bars found prior to target date.",
        )

    current_level = float(sub.iloc[-1]["Close"])

    # Baseline / previous period lookup
    prev_dt = pd.to_datetime(period.baseline_date)
    prev_slice = sub[sub.index <= prev_dt]
    if not prev_slice.empty:
        prev_level = float(prev_slice.iloc[-1]["Close"])
    elif len(sub) >= 2:
        prev_level = float(sub.iloc[-2]["Close"])
    else:
        prev_level = current_level

    change = current_level - prev_level
    pct_change = ((current_level - prev_level) / prev_level) * 100.0 if prev_level > 0 else 0.0

    # Period range
    start_dt = pd.to_datetime(period.current_start)
    period_slice = sub[(sub.index >= start_dt) & (sub.index <= curr_end_dt)]
    if not period_slice.empty:
        p_high = float(period_slice["High"].max()) if "High" in period_slice.columns else current_level
        p_low = float(period_slice["Low"].min()) if "Low" in period_slice.columns else current_level
    else:
        p_high = current_level
        p_low = current_level

    # Implied daily move via standard Rule of 16 (VIX / sqrt(252))
    implied_daily = current_level / 15.8745

    # Momentum / direction assessment
    if change > 0.5:
        dir_label = "Rising / Expanding Hedging"
    elif change < -0.5:
        dir_label = "Falling / Volatility Crush"
    else:
        dir_label = "Stable"

    # Multi-tier quant-grade regime classification aligned with config and reference table (Fix 1.6)
    if current_level < 16.5:
        base_regime = "Low / Complacent"
        base_desc = f"Subdued baseline implied volatility (±{implied_daily:.2f}% implied daily move). Low hedging demand; favorable for multi-day breakout setups."
    elif current_level < 20.0:
        base_regime = "Normal"
        base_desc = f"Standard historical baseline volatility (±{implied_daily:.2f}% implied daily move). Orderly price discovery and standard hedging distribution."
    elif current_level <= 26.0:
        base_regime = "Elevated Caution"
        base_desc = f"Elevated put protection demand (±{implied_daily:.2f}% implied daily move). Widening intraday swings and higher overnight gap hazard."
    else:
        base_regime = "High Fear / Tail Risk"
        base_desc = f"Acute volatility spike (±{implied_daily:.2f}% implied daily move). Severe market dislocation or panic liquidation."

    regime = f"{base_regime} ({dir_label})"
    desc = f"{base_desc} [Period &Delta;: {change:+.2f} pts]."

    name_str = vix_symbol.name if hasattr(vix_symbol, "name") else ("CBOE Volatility Index" if sym_str == "^VIX" else sym_str)

    data = VolatilityData(
        symbol=sym_str,
        name=name_str,
        current_level=current_level,
        prev_level=prev_level,
        change=change,
        pct_change=pct_change,
        period_high=p_high,
        period_low=p_low,
        regime=regime,
        regime_description=desc,
        implied_daily_move_pct=implied_daily,
    )

    return SectionResult(
        section_num=4,
        title="Volatility (VIX)",
        status="available",
        data=data,
    )
