"""Base definitions and protocols for report sections."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SectionResult:
    """Standardized result wrapper for each report section."""
    section_num: int
    title: str
    status: str = "available"  # 'available' or 'unavailable'
    data: Optional[Any] = None
    error_message: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self.status == "available"
