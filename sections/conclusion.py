"""Sections 7 & 8: Conclusion and Legal Disclaimer."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import pandas as pd

from indicators.engine import TechnicalSnapshot
from scoring.engine import Scorecard
from sections.base import SectionResult


@dataclass
class KeyLevel:
    label: str
    price: float
    distance_pct: float
    level_type: str  # 'Support' or 'Resistance'


@dataclass
class AssetLevels:
    symbol: str
    name: str
    current_price: float
    levels: List[KeyLevel]


@dataclass
class ConclusionData:
    verdict: str
    normalized_score: float
    top_bullish_factors: List[str]
    top_bearish_factors: List[str]
    caution_flags: List[str]
    scorecard: Scorecard
    asset_levels: List[AssetLevels]
    disclaimer: str = "For informational purposes only. Not financial advice."
    regime_intelligence: Optional[Any] = None


def compute_key_levels(
    snap: TechnicalSnapshot,
    df: Optional[pd.DataFrame] = None,
) -> AssetLevels:
    """Calculate key support and resistance levels to watch."""
    levels: List[KeyLevel] = []
    p = snap.price

    # 1. 20 DMA
    if snap.dma_20 > 0:
        l_type = "Support" if p >= snap.dma_20 else "Resistance"
        dist = ((snap.dma_20 - p) / p) * 100.0
        levels.append(KeyLevel("20-Day DMA", snap.dma_20, dist, l_type))

    # 2. 50 DMA
    if snap.dma_50 > 0:
        l_type = "Support" if p >= snap.dma_50 else "Resistance"
        dist = ((snap.dma_50 - p) / p) * 100.0
        levels.append(KeyLevel("50-Day DMA", snap.dma_50, dist, l_type))

    # 3. 200 DMA
    if snap.dma_200 > 0:
        l_type = "Support" if p >= snap.dma_200 else "Resistance"
        dist = ((snap.dma_200 - p) / p) * 100.0
        levels.append(KeyLevel("200-Day DMA", snap.dma_200, dist, l_type))

    # 4. 20-day High / Low if df available
    if df is not None and len(df) >= 20:
        recent = df.tail(20)
        h20 = float(recent["High"].max()) if "High" in recent.columns else p
        l20 = float(recent["Low"].min()) if "Low" in recent.columns else p

        if h20 > p:
            levels.append(KeyLevel("20-Day Range High", h20, ((h20 - p) / p) * 100.0, "Resistance"))
        if l20 < p:
            levels.append(KeyLevel("20-Day Range Low", l20, ((l20 - p) / p) * 100.0, "Support"))

    levels.sort(key=lambda x: x.price, reverse=True)
    return AssetLevels(
        symbol=snap.symbol,
        name=snap.name,
        current_price=p,
        levels=levels,
    )


def build_conclusion(
    scorecard: Optional[Scorecard],
    spx_snap: Optional[TechnicalSnapshot],
    ndx_snap: Optional[TechnicalSnapshot],
    spx_df: Optional[pd.DataFrame] = None,
    ndx_df: Optional[pd.DataFrame] = None,
    regime_intelligence: Optional[Any] = None,
) -> SectionResult:
    """Build conclusion section with transparent scorecard and key price levels."""
    if not scorecard:
        return SectionResult(
            section_num=7,
            title="Conclusion & Market Outlook",
            status="unavailable",
            error_message="Scorecard unavailable.",
        )

    asset_levels: List[AssetLevels] = []
    if spx_snap:
        asset_levels.append(compute_key_levels(spx_snap, spx_df))
    if ndx_snap:
        asset_levels.append(compute_key_levels(ndx_snap, ndx_df))

    data = ConclusionData(
        verdict=scorecard.verdict,
        normalized_score=scorecard.normalized_score,
        top_bullish_factors=scorecard.top_bullish_factors,
        top_bearish_factors=scorecard.top_bearish_factors,
        caution_flags=scorecard.caution_flags,
        scorecard=scorecard,
        asset_levels=asset_levels,
        regime_intelligence=regime_intelligence,
    )

    return SectionResult(
        section_num=7,
        title="Conclusion & Market Outlook",
        status="available",
        data=data,
    )


@dataclass
class DataSourceInfo:
    source_name: str
    coverage: str
    fetch_time: str
    status: str
    notes: str


def build_footer(
    data_sources: Optional[List[DataSourceInfo]] = None,
    disclaimer: Optional[str] = None,
    overall_status: str = "PARTIAL",
    missing_inputs: Optional[List[str]] = None,
) -> SectionResult:
    """Build Footer with legal disclaimer, constituent survivorship bias notice, and Data Quality provenance table."""
    default_disclaimer = (
        "For informational purposes only. Not financial advice. "
        "Market breadth calculations use the current S&P 500 constituent roster "
        "(subject to survivorship bias for historical comparisons)."
    )
    return SectionResult(
        section_num=10,
        title="Footer & Disclaimer",
        status="available",
        data={
            "disclaimer": disclaimer or default_disclaimer,
            "data_sources": data_sources or [],
            "overall_status": overall_status,
            "missing_inputs": missing_inputs or [],
        },
    )
