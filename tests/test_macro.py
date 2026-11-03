"""Unit tests for macroeconomic calculations, transformations, and surprise flags."""

import numpy as np
import pandas as pd
import pytest

from data.calendar_provider import evaluate_surprise_flag
from data.fred_provider import FredProvider


def test_inflation_mom_and_yoy_calculations():
    """Verify MoM % and YoY % calculated from price index levels."""
    # 13 monthly index levels: start at 100.0, grow 0.5% per month
    dates = pd.date_range("2025-01-01", periods=13, freq="MS")
    levels = [100.0 * (1.005 ** i) for i in range(13)]
    df = pd.DataFrame({"date": dates, "value": levels})

    snap = FredProvider.compute_inflation_metrics(df, "CPIAUCSL", "Test CPI")
    assert snap is not None
    # MoM should be approx 0.5%
    assert snap.mom_pct == pytest.approx(0.5, abs=0.01)
    # YoY should be (1.005^12 - 1) * 100 = 6.1678%
    expected_yoy = ((levels[-1] - levels[0]) / levels[0]) * 100.0
    assert snap.yoy_pct == pytest.approx(expected_yoy, abs=0.01)
    assert snap.headline_value == pytest.approx(expected_yoy, abs=0.01)


def test_payrolls_monthly_change_not_total_level():
    """Nonfarm Payrolls headline must report net monthly change in thousands."""
    dates = pd.date_range("2026-01-01", periods=3, freq="MS")
    # 158000k, 158200k (+200k), 158350k (+150k)
    df = pd.DataFrame({"date": dates, "value": [158000.0, 158200.0, 158350.0]})

    snap = FredProvider.compute_payrolls_metrics(df)
    assert snap is not None
    # Latest headline must be +150 (not 158,350!)
    assert snap.headline_value == pytest.approx(150.0)
    assert snap.headline_unit == "k"
    assert snap.prior_headline == pytest.approx(200.0)
    assert snap.change == pytest.approx(-50.0)


def test_jobless_claims_4w_average():
    """Weekly jobless claims and 4-week moving average calculation."""
    dates = pd.date_range("2026-09-01", periods=5, freq="W-SAT")
    # Weekly claims: 210k, 220k, 215k, 225k, 200k
    df = pd.DataFrame({"date": dates, "value": [210000.0, 220000.0, 215000.0, 225000.0, 200000.0]})

    snap = FredProvider.compute_jobless_claims_metrics(df)
    assert snap is not None
    assert snap.headline_value == 200000.0
    # 4-week average of [220k, 215k, 225k, 200k] = 215,000
    expected_4w = (220000.0 + 215000.0 + 225000.0 + 200000.0) / 4.0
    assert "215,000" in snap.notes


def test_real_gdp_annualized_qoq():
    """Real GDP annualized quarterly growth rate calculation."""
    dates = pd.date_range("2025-01-01", periods=3, freq="QS")
    # Grow by 0.5% in quarter: annualized rate is ((1.005)^4 - 1) * 100 = 2.015%
    df = pd.DataFrame({"date": dates, "value": [22000.0, 22110.0, 22220.55]})

    snap = FredProvider.compute_gdp_metrics(df)
    assert snap is not None
    # 22220.55 / 22110.0 = 1.005
    expected_ann = (((22220.55 / 22110.0) ** 4) - 1.0) * 100.0
    assert snap.headline_value == pytest.approx(expected_ann, abs=0.05)
    assert snap.headline_unit == "% QoQ Ann."


def test_surprise_flag_classification():
    # Inflation: actual > forecast + tol -> hot
    assert evaluate_surprise_flag("inflation", actual=3.5, forecast=3.2, tolerance=0.05) == "hot"
    # Inflation: actual < forecast - tol -> cool
    assert evaluate_surprise_flag("inflation", actual=2.9, forecast=3.2, tolerance=0.05) == "cool"
    # Inflation: within tolerance -> in_line
    assert evaluate_surprise_flag("inflation", actual=3.22, forecast=3.2, tolerance=0.05) == "in_line"

    # Jobs: actual > forecast -> strong
    assert evaluate_surprise_flag("labor", actual=250.0, forecast=180.0, tolerance=25.0) == "strong"
    # Jobs: actual < forecast -> weak
    assert evaluate_surprise_flag("labor", actual=120.0, forecast=180.0, tolerance=25.0) == "weak"

    # Jobless claims (inverse metric): actual > forecast -> weak
    assert evaluate_surprise_flag("claims", actual=240.0, forecast=215.0, tolerance=5.0) == "weak"
    # Jobless claims: actual < forecast -> strong
    assert evaluate_surprise_flag("claims", actual=200.0, forecast=215.0, tolerance=5.0) == "strong"

    # Missing forecast -> n/a (NEVER invent consensus numbers)
    assert evaluate_surprise_flag("inflation", actual=3.1, forecast=None) == "n/a"
    assert evaluate_surprise_flag("labor", actual=None, forecast=180.0) == "n/a"


def test_missing_data_and_failure_resilience(tmp_path):
    """FredProvider must gracefully return None on invalid series without raising exceptions."""
    provider = FredProvider(
        api_key_env="NON_EXISTENT_KEY_FOR_TESTING",
        cache_dir=str(tmp_path / "fred_cache"),
        allow_public_fallback=False,  # Force offline/key-only mode to test failure path
    )
    res = provider.fetch_series("INVALID_SERIES_ID_XYZ")
    assert res is None


def test_get_historical_trend_calculation(tmp_path):
    """Verify historical monthly and yearly trend calculation for inflation and payrolls."""
    provider = FredProvider(cache_dir=str(tmp_path / "fred_cache"))
    
    # Mock CPI series: 15 monthly observations
    dates = pd.date_range("2025-01-01", periods=15, freq="MS")
    levels = [100.0 * (1.01 ** i) for i in range(15)]
    df_cpi = pd.DataFrame({"date": dates, "value": levels})
    provider._write_cache("MOCK_CPI", df_cpi)

    trend = provider.get_historical_trend("MOCK_CPI", "Mock CPI", "Inflation", "inflation", months=3)
    assert trend is not None
    assert len(trend.points) == 3
    assert trend.monthly_unit == "% MoM"
    assert trend.yearly_unit == "% YoY"
    # MoM should be approx 1.0%
    assert trend.latest_point.monthly_val == pytest.approx(1.0, abs=0.01)
    # YoY vs 12 months ago: (1.01^12 - 1) * 100 = 12.68%
    assert trend.latest_point.yearly_val == pytest.approx(((levels[-1] - levels[-13]) / levels[-13]) * 100.0, abs=0.01)


def test_svg_charts_generation():
    """Verify inline SVG charts generate valid XML structure without remote dependencies."""
    import xml.etree.ElementTree as ET
    from data.fred_provider import MacroHistoricalPoint, MacroHistoricalSeries
    from render.svg_charts import render_inflation_chart, render_labor_chart, render_rates_chart, render_activity_chart

    pts = [
        MacroHistoricalPoint(date_str=f"2026-{m:02d}-01", label=f"M{m}", monthly_val=0.3, yearly_val=3.0 + m * 0.1, raw_level=300.0 + m)
        for m in range(1, 13)
    ]
    s_cpi = MacroHistoricalSeries("CPIAUCSL", "CPI", "Inflation", "% MoM", "% YoY", pts)
    s_core = MacroHistoricalSeries("CPILFESL", "Core CPI", "Inflation", "% MoM", "% YoY", pts)
    s_pay = MacroHistoricalSeries("PAYEMS", "Payrolls", "Labor", "k", "k", [
        MacroHistoricalPoint(f"2026-{m:02d}-01", f"M{m}", 150.0, 1500.0, 158000.0) for m in range(1, 13)
    ])
    s_un = MacroHistoricalSeries("UNRATE", "Unemployment", "Labor", "%", "%", [
        MacroHistoricalPoint(f"2026-{m:02d}-01", f"M{m}", 4.1, 0.1, 4.1) for m in range(1, 13)
    ])
    s_y10 = MacroHistoricalSeries("DGS10", "10Y Yield", "Rates", "%", "%", [
        MacroHistoricalPoint(f"2026-{m:02d}-01", f"M{m}", 4.5, 0.5, 4.5) for m in range(1, 13)
    ])
    s_dff = MacroHistoricalSeries("DFF", "Fed Funds", "Rates", "%", "%", [
        MacroHistoricalPoint(f"2026-{m:02d}-01", f"M{m}", 5.0, 0.0, 5.0) for m in range(1, 13)
    ])
    s_ret = MacroHistoricalSeries("RSAFS", "Retail Sales", "Growth", "% MoM", "% YoY", pts)
    s_sent = MacroHistoricalSeries("UMCSENT", "Sentiment", "Growth", "index", "pts", [
        MacroHistoricalPoint(f"2026-{m:02d}-01", f"M{m}", 65.0, 5.0, 65.0) for m in range(1, 13)
    ])

    inds = [s_cpi, s_core, s_pay, s_un, s_y10, s_dff, s_ret, s_sent]

    for chart_fn in [render_inflation_chart, render_labor_chart, render_rates_chart, render_activity_chart]:
        svg_str = chart_fn(inds)
        assert "<svg" in svg_str
        assert "</svg>" in svg_str
        root = ET.fromstring(svg_str)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"

