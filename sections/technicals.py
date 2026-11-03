"""Section 3: Technical Indicators builder for S&P 500 and Nasdaq-100."""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd

from config.settings import IndicatorsConfig, SymbolItem
from data.calendar import PeriodInfo
from indicators.engine import TechnicalSnapshot, compute_technicals
from sections.base import SectionResult


@dataclass
class TechnicalsData:
    snapshots: List[TechnicalSnapshot]


def build_technicals(
    bars: Dict[str, pd.DataFrame],
    tech_indices: List[SymbolItem],
    period: PeriodInfo,
    ind_cfg: IndicatorsConfig,
) -> SectionResult:
    """Build technical indicator tables for key benchmarks (SPX and NDX)."""
    snapshots: List[TechnicalSnapshot] = []

    for item in tech_indices:
        df = bars.get(item.symbol)
        if df is None or df.empty:
            continue

        snap = compute_technicals(
            df=df,
            symbol=item.symbol,
            name=item.name,
            as_of_date=period.session_date,
            prev_date=period.prev_period_end,
            dma_fast=ind_cfg.dma_fast,
            dma_medium=ind_cfg.dma_medium,
            dma_slow=ind_cfg.dma_slow,
            rsi_period=ind_cfg.rsi_period,
            rsi_overbought=ind_cfg.rsi_overbought,
            rsi_oversold=ind_cfg.rsi_oversold,
            macd_fast=ind_cfg.macd_fast,
            macd_slow=ind_cfg.macd_slow,
            macd_signal=ind_cfg.macd_signal,
            adx_period=ind_cfg.adx_period,
        )
        if snap:
            snapshots.append(snap)

    if not snapshots:
        return SectionResult(
            section_num=3,
            title="Technical Indicators",
            status="unavailable",
            error_message="Technical calculations could not be completed for benchmark indices.",
        )

    return SectionResult(
        section_num=3,
        title="Technical Indicators",
        status="available",
        data=TechnicalsData(snapshots=snapshots),
    )
