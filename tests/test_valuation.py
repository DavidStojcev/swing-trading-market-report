"""Unit tests for S&P 500 Valuation vs. Rates & Equity Risk Premium (Change Request v2.2 Stage 3 Task 3.1)."""

from typing import Optional
import pytest

from sections.base import SectionResult
from sections.valuation import (
    Sp500ValuationRates,
    ValuationData,
    ValuationRatesData,
    build_valuation_section,
    compute_valuation_vs_rates,
    fetch_sp500_forward_pe,
)


def test_valuation_dataclass_fields():
    """Verify dataclass has all 6 required fields with correct types."""
    val = ValuationData(
        forward_pe=21.5,
        earnings_yield_pct=4.6512,
        nominal_erp_bps=35.12,
        real_erp_bps=270.12,
        eps_revision_trend="+1.2% (last 30d)",
        source="SPY Fundamentals (yfinance)",
    )

    assert hasattr(val, "forward_pe")
    assert hasattr(val, "earnings_yield_pct")
    assert hasattr(val, "nominal_erp_bps")
    assert hasattr(val, "real_erp_bps")
    assert hasattr(val, "eps_revision_trend")
    assert hasattr(val, "source")

    assert val.forward_pe == 21.5
    assert val.earnings_yield_pct == 4.6512
    assert val.nominal_erp_bps == 35.12
    assert val.real_erp_bps == 270.12
    assert val.eps_revision_trend == "+1.2% (last 30d)"
    assert val.source == "SPY Fundamentals (yfinance)"

    # Verify type aliases
    assert ValuationRatesData is ValuationData
    assert Sp500ValuationRates is ValuationData


def test_valuation_vs_rates_live_math():
    """Test exact mathematical derivation of earnings yield and ERP in bps."""
    # PE = 20.0 -> Earnings Yield = 1 / 20 * 100 = 5.0%
    # Nominal 10Y = 4.25% -> Nominal ERP = (5.0 - 4.25) * 100 = +75.0 bps
    # Real 10Y = 1.95% -> Real ERP = (5.0 - 1.95) * 100 = +305.0 bps
    val = compute_valuation_vs_rates(
        forward_pe=20.0,
        nominal_10y=4.25,
        real_10y=1.95,
        eps_revision_trend="Upward revisions +2.1%",
        source="SPY Fundamentals (yfinance)",
    )

    assert val.forward_pe == 20.0
    assert val.earnings_yield_pct == pytest.approx(5.0, abs=0.0001)
    assert val.nominal_erp_bps == pytest.approx(75.0, abs=0.01)
    assert val.real_erp_bps == pytest.approx(305.0, abs=0.01)
    assert val.eps_revision_trend == "Upward revisions +2.1%"
    assert val.source == "SPY Fundamentals (yfinance)"
    assert "S&P 500 forward P/E is 20.00x" in val.assessment
    assert "Nominal ERP sits at +75.0 bps" in val.assessment
    assert "Real ERP stands at +305.0 bps" in val.assessment


def test_valuation_consensus_forward_eps_derivation():
    """Test derivation from consensus forward EPS and index price."""
    # Price = 5800, EPS = 290 -> PE = 20.0
    val = compute_valuation_vs_rates(
        spx_price=5800.0,
        consensus_forward_eps=290.0,
        nominal_10y=4.00,
        real_10y=1.80,
    )

    assert val.forward_pe == 20.0
    assert val.earnings_yield_pct == pytest.approx(5.0, abs=0.0001)
    assert val.nominal_erp_bps == pytest.approx(100.0, abs=0.01)
    assert val.real_erp_bps == pytest.approx(320.0, abs=0.01)
    assert val.source == "Consensus Forward EPS"


def test_valuation_unavailable_graceful_fallback():
    """Verify clean 'n/a (source unavailable)' path without crashing or fabricating numbers."""
    val = compute_valuation_vs_rates(
        forward_pe=None,
        nominal_10y=4.25,
        real_10y=1.95,
        data_provider=None,
    )

    # When live yfinance has no forward P/E for SPY/^GSPC, clean n/a fallback is returned
    assert val.forward_pe is None
    assert val.earnings_yield_pct is None
    assert val.nominal_erp_bps is None
    assert val.real_erp_bps is None
    assert val.eps_revision_trend == "n/a (source unavailable)"
    assert val.source == "n/a (source unavailable)"
    assert "unavailable" in val.assessment


def test_valuation_invalid_or_negative_pe_handled():
    """Verify invalid or non-positive forward P/E does not crash with division by zero."""
    for bad_pe in [0.0, -15.0, -0.001]:
        val = compute_valuation_vs_rates(
            forward_pe=bad_pe,
            nominal_10y=4.25,
            real_10y=1.95,
        )
        assert val.forward_pe is None
        assert val.earnings_yield_pct is None
        assert val.nominal_erp_bps is None
        assert val.real_erp_bps is None
        assert val.source == "n/a (source unavailable)"


def test_valuation_missing_yields_handled():
    """Verify missing nominal or real yield does not crash and leaves corresponding ERP as None."""
    val = compute_valuation_vs_rates(
        forward_pe=22.0,
        nominal_10y=4.25,
        real_10y=None,  # TIPS unavailable
    )

    assert val.forward_pe == 22.0
    assert val.earnings_yield_pct == pytest.approx(100.0 / 22.0, abs=0.001)
    assert val.nominal_erp_bps is not None
    assert val.real_erp_bps is None


def test_valuation_extraction_from_macro_data():
    """Verify extraction of yields from macro_data.fed_rates."""
    class MockFedRates:
        yield_10y = 4.38
        real_yield_10y = 2.05

    class MockMacroData:
        fed_rates = MockFedRates()
        metrics = {}

    macro_mock = MockMacroData()
    val = compute_valuation_vs_rates(
        forward_pe=20.0,
        macro_data=macro_mock,
    )

    assert val.nominal_10y_yield == 4.38
    assert val.real_10y_yield == 2.05
    assert val.nominal_erp_bps == pytest.approx((5.0 - 4.38) * 100.0, abs=0.01)
    assert val.real_erp_bps == pytest.approx((5.0 - 2.05) * 100.0, abs=0.01)


def test_build_valuation_section():
    """Verify build_valuation_section returns standardized SectionResult."""
    sec = build_valuation_section(
        forward_pe=22.5,
        nominal_10y=4.20,
        real_10y=1.90,
        section_num=5,
    )

    assert isinstance(sec, SectionResult)
    assert sec.section_num == 5
    assert sec.status == "available"
    assert isinstance(sec.data, ValuationData)
    assert sec.data.forward_pe == 22.5
    assert sec.data.earnings_yield_pct == pytest.approx(100.0 / 22.5, abs=0.001)


def test_build_valuation_section_fallback_result():
    """Verify build_valuation_section handles fallback data cleanly as an available SectionResult."""
    sec = build_valuation_section(
        forward_pe=None,
        nominal_10y=4.20,
        real_10y=1.90,
    )

    assert isinstance(sec, SectionResult)
    assert sec.status == "available"
    assert sec.data.forward_pe is None
    assert sec.data.earnings_yield_pct is None
    assert sec.data.source == "n/a (source unavailable)"


def test_valuation_markdown_and_html_render():
    """Verify markdown and HTML rendering for both available data and n/a fallback."""
    from data.calendar import PeriodInfo
    from render.html import render_html
    from render.markdown import render_markdown

    period = PeriodInfo(
        report_type="weekly",
        as_of_date="2026-10-30",
        session_date="2026-10-30",
        current_start="2026-10-26",
        current_end="2026-10-30",
        baseline_date="2026-10-23",
        prev_period_start="2026-10-19",
        prev_period_end="2026-10-23",
        prev_baseline_date="2026-10-16",
        is_partial=False,
        session_count=5,
    )

    # 1. Available valuation section
    sec_avail = build_valuation_section(
        forward_pe=21.5,
        nominal_10y=4.25,
        real_10y=1.95,
        eps_revision_trend="Upward revisions +1.5%",
        source="SPY Fundamentals (yfinance)",
        section_num=1,
    )

    md_avail = render_markdown(period=period, sections=[sec_avail])
    html_avail = render_html(period=period, sections=[sec_avail])

    assert "S&P 500 Valuation vs. Rates & Equity Risk Premium" in md_avail
    assert "21.50x" in md_avail
    assert "4.65%" in md_avail
    assert "+40.1 bps" in md_avail or "+40.1" in md_avail
    assert "21.50x" in html_avail

    # 2. Unavailable valuation section (clean n/a fallback)
    sec_unavail = build_valuation_section(
        forward_pe=None,
        nominal_10y=4.25,
        real_10y=1.95,
        section_num=1,
    )

    md_unavail = render_markdown(period=period, sections=[sec_unavail])
    html_unavail = render_html(period=period, sections=[sec_unavail])

    assert "n/a (source unavailable)" in md_unavail
    assert "n/a (source unavailable)" in html_unavail

