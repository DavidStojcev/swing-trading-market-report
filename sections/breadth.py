"""Section 7: Market Breadth builder across S&P 500 constituents."""

from dataclasses import dataclass
from typing import Optional

from indicators.breadth import MarketBreadthResult
from sections.base import SectionResult


@dataclass
class BreadthSectionData:
    """Container for Market Breadth section data."""
    result: MarketBreadthResult


def build_breadth_section(
    breadth_result: Optional[MarketBreadthResult],
    section_num: int = 7,
) -> SectionResult:
    """Build Section 7: Market Breadth report."""
    if breadth_result is None:
        return SectionResult(
            section_num=section_num,
            title="Market Breadth",
            status="unavailable",
            error_message="Market breadth data unavailable.",
        )

    if breadth_result.included_constituents == 0:
        return SectionResult(
            section_num=section_num,
            title="Market Breadth",
            status="unavailable",
            error_message=breadth_result.coverage_warning or "No constituent price data available.",
        )

    return SectionResult(
        section_num=section_num,
        title="Market Breadth",
        status="available",
        data=BreadthSectionData(result=breadth_result),
    )
