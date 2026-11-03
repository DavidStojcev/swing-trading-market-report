"""Report sections package."""

from sections.base import SectionResult
from sections.breadth import BreadthSectionData, build_breadth_section
from sections.conclusion import DataSourceInfo, build_conclusion, build_footer
from sections.executive_summary import build_executive_summary
from sections.index_snapshot import build_index_snapshot
from sections.macro import CrossAssetItem, FedRatesSummary, MacroSectionData, build_macro_section
from sections.movers import build_movers
from sections.sectors import (
    DEFENSIVE_EXCEPTION_BANNER,
    SectorBreadthItem,
    SectorLeaderStock,
    SectorPerformanceRow,
    SectorReportData,
    build_sectors,
    evaluate_defensive_exceptions,
)
from sections.technicals import build_technicals
from sections.valuation import (
    Sp500ValuationRates,
    ValuationData,
    ValuationRatesData,
    build_valuation_section,
    compute_valuation_vs_rates,
)
from sections.volatility import build_volatility
from sections.watchlist import WatchlistData, WatchlistItem, build_watchlist_section

__all__ = [
    "SectionResult",
    "build_executive_summary",
    "build_index_snapshot",
    "build_technicals",
    "build_volatility",
    "build_macro_section",
    "MacroSectionData",
    "FedRatesSummary",
    "CrossAssetItem",
    "build_sectors",
    "evaluate_defensive_exceptions",
    "DEFENSIVE_EXCEPTION_BANNER",
    "SectorLeaderStock",
    "SectorReportData",
    "SectorBreadthItem",
    "SectorPerformanceRow",
    "build_breadth_section",
    "BreadthSectionData",
    "build_movers",
    "build_conclusion",
    "build_footer",
    "DataSourceInfo",
    "build_watchlist_section",
    "WatchlistData",
    "WatchlistItem",
    "ValuationData",
    "ValuationRatesData",
    "Sp500ValuationRates",
    "build_valuation_section",
    "compute_valuation_vs_rates",
]
