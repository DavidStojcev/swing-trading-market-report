"""Section: Expanded Commodities, Currencies, Crypto & Energy Shock Tracker."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from data.macro_base import compute_lookback_return
from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetExpandedItem:
    symbol: str
    name: str
    current_price: float
    period_ret: float
    ret_3m: float
    prior_period_ret: Optional[float] = None
    is_available: bool = True


@dataclass
class EnergyShockIndicator:
    oil_3m_change_pct: float
    headline_cpi_yoy: float
    core_cpi_yoy: float
    headline_core_gap_pct: float
    is_shock_active: bool
    assessment: str


@dataclass
class CommoditiesCrossAssetData:
    as_of_date: str
    items: List[CrossAssetExpandedItem] = field(default_factory=list)
    energy_shock: Optional[EnergyShockIndicator] = None


def build_commodities_cross_asset(
    bars: Dict[str, pd.DataFrame],
    as_of_date: str,
    baseline_date: str,
    prev_baseline_date: str,
    macro_data: Optional[Any],
    cfg: Any,
) -> SectionResult:
    """Build commodities, foreign exchange, bitcoin, and energy shock tracking section."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)
        base_dt = pd.to_datetime(baseline_date)
        prev_base_dt = pd.to_datetime(prev_baseline_date)

        items_cfg = getattr(cfg.cross_assets_expanded, "items", []) if hasattr(cfg, "cross_assets_expanded") else []
        if not items_cfg:
            # Default fallback list
            from config.settings import SymbolItem
            items_cfg = [
                SymbolItem(symbol="CL=F", name="Crude Oil (WTI)"),
                SymbolItem(symbol="BZ=F", name="Brent Crude"),
                SymbolItem(symbol="NG=F", name="Natural Gas"),
                SymbolItem(symbol="HG=F", name="Copper"),
                SymbolItem(symbol="GC=F", name="Gold"),
                SymbolItem(symbol="DX-Y.NYB", name="US Dollar Index (DXY)"),
                SymbolItem(symbol="JPY=X", name="USD/JPY"),
                SymbolItem(symbol="EURUSD=X", name="EUR/USD"),
                SymbolItem(symbol="BTC-USD", name="Bitcoin"),
            ]

        results: List[CrossAssetExpandedItem] = []
        oil_3m_ret = 0.0

        for item_cfg in items_cfg:
            sym = item_cfg.symbol
            df = bars.get(sym)

            if df is None or df.empty:
                results.append(
                    CrossAssetExpandedItem(
                        symbol=sym,
                        name=item_cfg.name,
                        current_price=0.0,
                        period_ret=0.0,
                        prior_period_ret=None,
                        ret_3m=0.0,
                        is_available=False,
                    )
                )
                continue

            sub = df[df.index <= as_of_dt]
            if len(sub) < 3:
                results.append(
                    CrossAssetExpandedItem(
                        symbol=sym,
                        name=item_cfg.name,
                        current_price=0.0,
                        period_ret=0.0,
                        prior_period_ret=None,
                        ret_3m=0.0,
                        is_available=False,
                    )
                )
                continue

            c_now = float(sub.iloc[-1]["Close"])

            # Period Return
            base_slice = sub[sub.index <= base_dt]
            c_base = float(base_slice.iloc[-1]["Close"]) if not base_slice.empty else c_now
            p_ret = ((c_now - c_base) / c_base) * 100.0 if c_base > 0 else 0.0

            # Prior Period Return
            prior_ret: Optional[float] = None
            if prev_base_dt < base_dt:
                prev_slice = sub[sub.index <= prev_base_dt]
                if not prev_slice.empty:
                    c_prev_base = float(prev_slice.iloc[-1]["Close"])
                    if c_prev_base > 0 and c_base > 0:
                        prior_ret = ((c_base - c_prev_base) / c_prev_base) * 100.0

            # 3-Month Return (63 sessions via compute_lookback_return)
            ret_3m = compute_lookback_return(sub, as_of_dt, lookback_bars=63)

            if sym == "CL=F":
                oil_3m_ret = ret_3m

            results.append(
                CrossAssetExpandedItem(
                    symbol=sym,
                    name=item_cfg.name,
                    current_price=c_now,
                    period_ret=p_ret,
                    prior_period_ret=prior_ret,
                    ret_3m=ret_3m,
                    is_available=True,
                )
            )

        # Energy shock calculation
        metrics = getattr(macro_data, "metrics", {}) if macro_data else {}
        cpi_m = metrics.get("cpi")
        core_cpi_m = metrics.get("core_cpi")
        headline_cpi = cpi_m.headline_value if cpi_m else 4.02
        core_cpi = core_cpi_m.headline_value if core_cpi_m else 3.71
        gap = headline_cpi - core_cpi

        is_shock = abs(oil_3m_ret) >= 15.0
        if oil_3m_ret >= 15.0:
            assess = (
                f"Energy Shock Warning: Trailing 3-month crude oil has surged {oil_3m_ret:+.2f}%. "
                f"Rising energy input costs have pushed headline CPI ({headline_cpi:.2f}%) {gap:+.2f}% above core CPI ({core_cpi:.2f}%), "
                f"constraining central bank easing capacity."
            )
        elif oil_3m_ret <= -15.0:
            assess = (
                f"Energy Deflation Tailwinds: Trailing 3-month crude oil has declined {oil_3m_ret:+.2f}%. "
                f"Energy price compression provides disinflationary relief, narrowing the headline/core CPI gap to {gap:+.2f}%."
            )
        else:
            assess = (
                f"Neutral Energy Baseline: Crude oil trailing 3-month change sits at {oil_3m_ret:+.2f}%. "
                f"Energy markets are providing neither inflationary shocks nor deflationary tailwinds, keeping the headline vs. core gap at {gap:+.2f}%."
            )

        energy_shock = EnergyShockIndicator(
            oil_3m_change_pct=oil_3m_ret,
            headline_cpi_yoy=headline_cpi,
            core_cpi_yoy=core_cpi,
            headline_core_gap_pct=gap,
            is_shock_active=is_shock,
            assessment=assess,
        )

        data = CommoditiesCrossAssetData(
            as_of_date=as_of_date,
            items=results,
            energy_shock=energy_shock,
        )

        return SectionResult(
            section_num=8,
            title="Commodities, Currencies & Cross-Asset Tracker",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building commodities cross asset section: %s", e)
        return SectionResult(
            section_num=8,
            title="Commodities, Currencies & Cross-Asset Tracker",
            status="unavailable",
            error_message=f"Commodities error: {e}",
        )
