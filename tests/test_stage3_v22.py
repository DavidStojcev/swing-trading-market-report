"""Stage 3 Task 3.3 tests for Gate-to-Leaders exception candidate feature (Change Request v2.2)."""

import pytest
import pandas as pd
from datetime import date

from config.settings import (
    AppConfig,
    ReportConfig,
    SectorsConfig,
    SwingGateConfig,
    GateConfig,
    load_config,
    SymbolItem,
)
from data.calendar import PeriodInfo
from sections.sectors import (
    DEFENSIVE_EXCEPTION_BANNER,
    SectorBreadthItem,
    SectorLeaderStock,
    SectorPerformanceRow,
    SectorReportData,
    build_sectors,
    evaluate_defensive_exceptions,
)
from render.markdown import render_markdown
from render.html import render_html
from sections.base import SectionResult


def test_config_defensive_exceptions_defaults():
    """Verify defensive_exceptions defaults to False in settings and yaml."""
    cfg = load_config()
    assert cfg.defensive_exceptions is False
    assert cfg.sectors.defensive_exceptions is False
    assert cfg.swing_gate.defensive_exceptions is False

    # Check alias classes
    sec_cfg = SectorsConfig()
    assert sec_cfg.defensive_exceptions is False
    gate_cfg = GateConfig()
    assert gate_cfg.defensive_exceptions is False
    swing_cfg = SwingGateConfig()
    assert swing_cfg.defensive_exceptions is False
    rep_cfg = ReportConfig(
        symbols=cfg.symbols,
        indicators=cfg.indicators,
        scoring=cfg.scoring,
        movers=cfg.movers,
        data=cfg.data,
    )
    assert rep_cfg.defensive_exceptions is False


def test_sector_leader_stock_dataclass_defaults():
    """Verify SectorLeaderStock has exception candidate fields with safe defaults."""
    stock = SectorLeaderStock(
        symbol="AAPL",
        name="Apple Inc.",
        sector="Information Technology",
        close=230.0,
        pct_change=2.5,
        rs_vs_spy_pct=1.8,
        dist_52w_high_pct=-4.0,
        volume_ratio=1.2,
        avg_dollar_volume=500_000_000.0,
    )
    assert stock.is_exception_candidate is False
    assert stock.exception_reason == ""
    assert stock.dma_50 == 0.0


def test_sector_report_data_dataclass_defaults():
    """Verify SectorReportData tracks defensive exceptions and banner."""
    data = SectorReportData(
        spy_pct_change=1.0,
        spy_prev_pct_change=0.5,
        rows=[],
    )
    assert data.has_defensive_exceptions is False
    assert data.defensive_exception_banner is None


def test_exception_candidate_disabled_by_default():
    """When defensive_exceptions=False (default), candidates remain False even if gate is DEFENSIVE."""
    breadth = [
        SectorBreadthItem(
            sector="Technology",
            symbol="XLK",
            pct_above_50dma=85.0,  # >= 70%
            pct_above_20dma=80.0,
            net_new_highs=10,      # > 0
        )
    ]
    leader = SectorLeaderStock(
        symbol="NVDA",
        name="NVIDIA Corporation",
        sector="Technology",
        close=140.0,
        pct_change=5.0,
        rs_vs_spy_pct=4.0,
        dist_52w_high_pct=-2.5,   # within 10%
        volume_ratio=1.5,
        avg_dollar_volume=2_000_000_000.0,
        dma_50=125.0,             # close > dma_50
    )
    leaders = {"Technology": [leader]}

    # Test with default cfg (defensive_exceptions=False) and DEFENSIVE posture
    cfg = load_config()
    assert cfg.defensive_exceptions is False
    has_exc = evaluate_defensive_exceptions(
        sector_leaders=leaders,
        sector_breadth=breadth,
        cfg=cfg,
        gate_posture="DEFENSIVE",
        market_net_new_highs=5,
    )
    assert has_exc is False
    assert leader.is_exception_candidate is False
    assert leader.exception_reason == ""


def test_exception_candidate_non_defensive_gate():
    """When gate is not DEFENSIVE (e.g. FULL, REDUCED, SELECTIVE), candidates remain False."""
    breadth = [
        SectorBreadthItem(
            sector="Technology",
            symbol="XLK",
            pct_above_50dma=85.0,
            pct_above_20dma=80.0,
            net_new_highs=10,
        )
    ]
    for non_def_posture in ["FULL", "REDUCED", "SELECTIVE", "CONSTRUCTIVE"]:
        leader = SectorLeaderStock(
            symbol="NVDA",
            name="NVIDIA Corporation",
            sector="Technology",
            close=140.0,
            pct_change=5.0,
            rs_vs_spy_pct=4.0,
            dist_52w_high_pct=-2.5,
            volume_ratio=1.5,
            avg_dollar_volume=2_000_000_000.0,
            dma_50=125.0,
        )
        leaders = {"Technology": [leader]}
        has_exc = evaluate_defensive_exceptions(
            sector_leaders=leaders,
            sector_breadth=breadth,
            gate_posture=non_def_posture,
            market_net_new_highs=5,
            defensive_exceptions=True,
        )
        assert has_exc is False
        assert leader.is_exception_candidate is False
        assert leader.exception_reason == ""


def test_exception_candidate_all_criteria_met():
    """When enabled AND gate is DEFENSIVE AND all 4 criteria met, marks candidate and populates reason."""
    breadth = [
        SectorBreadthItem(
            sector="Technology",
            symbol="XLK",
            pct_above_50dma=75.0,   # Criterion a: >= 70%
            pct_above_20dma=80.0,
            net_new_highs=5,        # Criterion b: > 0
        )
    ]
    leader = SectorLeaderStock(
        symbol="AAPL",
        name="Apple Inc.",
        sector="Technology",
        close=230.0,
        pct_change=4.0,
        rs_vs_spy_pct=3.5,
        dist_52w_high_pct=-4.0,     # Criterion d: >= -10.0%
        volume_ratio=1.3,
        avg_dollar_volume=800_000_000.0,
        dma_50=215.0,               # Criterion c: close > dma_50
    )
    leaders = {"Technology": [leader]}

    has_exc = evaluate_defensive_exceptions(
        sector_leaders=leaders,
        sector_breadth=breadth,
        gate_posture="DEFENSIVE",
        defensive_exceptions=True,
    )
    assert has_exc is True
    assert leader.is_exception_candidate is True
    assert "Sector 50-DMA breadth 75.0% >= 70.0%" in leader.exception_reason
    assert "Sector net new highs (+5) > 0" in leader.exception_reason
    assert "Close ($230.00) > 50-DMA ($215.00)" in leader.exception_reason
    assert "Dist from 52W high -4.0% >= -10.0%" in leader.exception_reason


def test_exception_candidate_market_net_new_highs_fallback():
    """Criterion b is satisfied if market net new highs > 0 even if sector NNH is 0 or None."""
    breadth = [
        SectorBreadthItem(
            sector="Financials",
            symbol="XLF",
            pct_above_50dma=72.0,   # >= 70%
            pct_above_20dma=75.0,
            net_new_highs=0,        # Sector net new highs is 0
        )
    ]
    leader = SectorLeaderStock(
        symbol="JPM",
        name="JPMorgan Chase & Co.",
        sector="Financials",
        close=220.0,
        pct_change=3.0,
        rs_vs_spy_pct=2.5,
        dist_52w_high_pct=-3.0,
        volume_ratio=1.1,
        avg_dollar_volume=400_000_000.0,
        dma_50=205.0,
    )
    leaders = {"Financials": [leader]}

    # With market_net_new_highs=12 > 0 -> should qualify
    has_exc = evaluate_defensive_exceptions(
        sector_leaders=leaders,
        sector_breadth=breadth,
        gate_posture="DEFENSIVE",
        market_net_new_highs=12,
        defensive_exceptions=True,
    )
    assert has_exc is True
    assert leader.is_exception_candidate is True
    assert "Market net new highs (+12) > 0" in leader.exception_reason


def test_exception_candidate_strict_qualification_failures():
    """Verify that failing ANY of the 4 criteria disqualifies the candidate."""
    # Base qualifying inputs
    base_p50 = 75.0
    base_nnh = 5
    base_close = 150.0
    base_dma50 = 140.0
    base_dist52w = -5.0

    # 1. Fails Criterion a: Sector breadth < 70% (e.g. 69.9%)
    breadth_a = [SectorBreadthItem(sector="Tech", symbol="XLK", pct_above_50dma=69.9, pct_above_20dma=60.0, net_new_highs=base_nnh)]
    leader_a = SectorLeaderStock(symbol="A", name="A", sector="Tech", close=base_close, pct_change=1.0, rs_vs_spy_pct=1.0, dist_52w_high_pct=base_dist52w, volume_ratio=1.0, avg_dollar_volume=5e7, dma_50=base_dma50)
    assert evaluate_defensive_exceptions({"Tech": [leader_a]}, breadth_a, gate_posture="DEFENSIVE", defensive_exceptions=True) is False
    assert leader_a.is_exception_candidate is False

    # 2. Fails Criterion b: Sector and market net new highs <= 0 (e.g. 0 and 0)
    breadth_b = [SectorBreadthItem(sector="Tech", symbol="XLK", pct_above_50dma=base_p50, pct_above_20dma=60.0, net_new_highs=0)]
    leader_b = SectorLeaderStock(symbol="B", name="B", sector="Tech", close=base_close, pct_change=1.0, rs_vs_spy_pct=1.0, dist_52w_high_pct=base_dist52w, volume_ratio=1.0, avg_dollar_volume=5e7, dma_50=base_dma50)
    assert evaluate_defensive_exceptions({"Tech": [leader_b]}, breadth_b, gate_posture="DEFENSIVE", market_net_new_highs=0, defensive_exceptions=True) is False
    assert leader_b.is_exception_candidate is False

    # 3. Fails Criterion c: Close <= 50-DMA (close = 140.0, dma50 = 140.0 or 145.0)
    breadth_c = [SectorBreadthItem(sector="Tech", symbol="XLK", pct_above_50dma=base_p50, pct_above_20dma=60.0, net_new_highs=base_nnh)]
    leader_c1 = SectorLeaderStock(symbol="C1", name="C1", sector="Tech", close=140.0, pct_change=1.0, rs_vs_spy_pct=1.0, dist_52w_high_pct=base_dist52w, volume_ratio=1.0, avg_dollar_volume=5e7, dma_50=140.0)
    assert evaluate_defensive_exceptions({"Tech": [leader_c1]}, breadth_c, gate_posture="DEFENSIVE", defensive_exceptions=True) is False
    assert leader_c1.is_exception_candidate is False

    leader_c2 = SectorLeaderStock(symbol="C2", name="C2", sector="Tech", close=135.0, pct_change=1.0, rs_vs_spy_pct=1.0, dist_52w_high_pct=base_dist52w, volume_ratio=1.0, avg_dollar_volume=5e7, dma_50=140.0)
    assert evaluate_defensive_exceptions({"Tech": [leader_c2]}, breadth_c, gate_posture="DEFENSIVE", defensive_exceptions=True) is False
    assert leader_c2.is_exception_candidate is False

    # 4. Fails Criterion d: dist_52w_high < -10.0% (e.g. -10.1% or -12.0%)
    breadth_d = [SectorBreadthItem(sector="Tech", symbol="XLK", pct_above_50dma=base_p50, pct_above_20dma=60.0, net_new_highs=base_nnh)]
    leader_d = SectorLeaderStock(symbol="D", name="D", sector="Tech", close=base_close, pct_change=1.0, rs_vs_spy_pct=1.0, dist_52w_high_pct=-10.1, volume_ratio=1.0, avg_dollar_volume=5e7, dma_50=base_dma50)
    assert evaluate_defensive_exceptions({"Tech": [leader_d]}, breadth_d, gate_posture="DEFENSIVE", defensive_exceptions=True) is False
    assert leader_d.is_exception_candidate is False


def test_build_sectors_integration_with_defensive_exceptions():
    """Test build_sectors emits banner when defensive_exceptions=True and gate=DEFENSIVE with qualifying constituents."""
    # Synthetic bars
    dates = pd.date_range("2026-01-01", "2026-10-30", freq="B")
    spy_df = pd.DataFrame({
        "Open": 500.0, "High": 505.0, "Low": 495.0, "Close": 500.0, "Volume": 50_000_000
    }, index=dates)
    xlk_df = pd.DataFrame({
        "Open": 200.0, "High": 205.0, "Low": 195.0, "Close": 202.0, "Volume": 10_000_000
    }, index=dates)

    # AAPL stock: strong uptrend, close=240, 50-DMA ~220, close within 5% of 52W high
    close_series = [180.0 + i * 0.3 for i in range(len(dates))]
    aapl_df = pd.DataFrame({
        "Open": close_series, "High": [c + 2.0 for c in close_series],
        "Low": [c - 2.0 for c in close_series], "Close": close_series,
        "Volume": [20_000_000] * len(dates)
    }, index=dates)

    bars = {"SPY": spy_df, "XLK": xlk_df}
    equity_bars = {"AAPL": aapl_df}
    sectors = [SymbolItem(symbol="XLK", name="Technology")]
    benchmark = SymbolItem(symbol="SPY", name="SPDR S&P 500 ETF Trust")
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

    class MockConstituent:
        def __init__(self, symbol, name, sector):
            self.symbol = symbol
            self.name = name
            self.sector = sector

    constituents = [MockConstituent("AAPL", "Apple Inc.", "Technology")]

    # 1. When defensive_exceptions=False (default) -> has_defensive_exceptions is False, banner is None
    res_off = build_sectors(
        bars=bars,
        sectors=sectors,
        benchmark=benchmark,
        period=period,
        constituents=constituents,
        equity_bars=equity_bars,
        gate_posture="DEFENSIVE",
        defensive_exceptions=False,
    )
    assert res_off.is_available
    data_off: SectorReportData = res_off.data
    assert data_off.has_defensive_exceptions is False
    assert data_off.defensive_exception_banner is None
    leaders_off = data_off.sector_leaders.get("Technology", [])
    if leaders_off:
        assert leaders_off[0].is_exception_candidate is False

    # 2. When defensive_exceptions=True and gate=DEFENSIVE -> has_defensive_exceptions is True, banner emitted
    res_on = build_sectors(
        bars=bars,
        sectors=sectors,
        benchmark=benchmark,
        period=period,
        constituents=constituents,
        equity_bars=equity_bars,
        gate_posture="DEFENSIVE",
        defensive_exceptions=True,
    )
    assert res_on.is_available
    data_on: SectorReportData = res_on.data
    assert data_on.has_defensive_exceptions is True
    assert data_on.defensive_exception_banner == DEFENSIVE_EXCEPTION_BANNER
    leaders_on = data_on.sector_leaders.get("Technology", [])
    assert len(leaders_on) > 0
    assert leaders_on[0].is_exception_candidate is True
    assert len(leaders_on[0].exception_reason) > 0


def test_markdown_and_html_render_defensive_exception_banner():
    """Verify banner renders clearly in both Markdown and HTML when present."""
    leader = SectorLeaderStock(
        symbol="AAPL",
        name="Apple Inc.",
        sector="Technology",
        close=230.0,
        pct_change=4.0,
        rs_vs_spy_pct=3.5,
        dist_52w_high_pct=-4.0,
        volume_ratio=1.3,
        avg_dollar_volume=800_000_000.0,
        dma_50=215.0,
        is_exception_candidate=True,
        exception_reason="Qualified defensive exception",
    )
    s_row = SectorPerformanceRow(
        symbol="XLK",
        name="Technology",
        close=210.0,
        pct_change=3.0,
        relative_strength_vs_spy=2.0,
        rank=1,
        prev_rank=1,
        rank_change=0,
        prev_period_change=1.5,
    )
    b_item = SectorBreadthItem(
        sector="Technology",
        symbol="XLK",
        pct_above_50dma=80.0,
        pct_above_20dma=75.0,
        net_new_highs=4,
    )
    data = SectorReportData(
        spy_pct_change=1.0,
        spy_prev_pct_change=0.5,
        rows=[s_row],
        sector_breadth=[b_item],
        sector_leaders={"Technology": [leader]},
        has_defensive_exceptions=True,
        defensive_exception_banner=DEFENSIVE_EXCEPTION_BANNER,
    )
    sec_res = SectionResult(
        section_num=7,
        title="Sector Rotation & Relative Strength",
        status="available",
        data=data,
    )
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

    # Render Markdown
    md = render_markdown(period=period, sections=[sec_res])
    assert DEFENSIVE_EXCEPTION_BANNER in md
    assert "> **⚠️ DEFENSIVE EXCEPTION WARNING" in md

    # Render HTML
    html = render_html(period=period, sections=[sec_res])
    assert DEFENSIVE_EXCEPTION_BANNER in html
    assert "DEFENSIVE EXCEPTION WARNING" in html


def test_end_to_end_generate_market_report_toggle():
    """Verify generate_market_report respects defensive_exceptions toggle."""
    from dataclasses import replace
    from report import generate_market_report

    # 1. Default (False): No exception banner in markdown or HTML
    cfg_default = load_config()
    assert cfg_default.defensive_exceptions is False
    res_default = generate_market_report(report_type="weekly", target_date="2026-10-30", config=cfg_default)
    with open(res_default["markdown"], "r", encoding="utf-8") as f:
        md_default = f.read()
    with open(res_default["html"], "r", encoding="utf-8") as f:
        html_default = f.read()
    assert DEFENSIVE_EXCEPTION_BANNER not in md_default
    assert DEFENSIVE_EXCEPTION_BANNER not in html_default

    # 2. Enabled (True): Gate is DEFENSIVE on 2026-10-30, leaders qualify
    cfg_enabled = replace(cfg_default, defensive_exceptions=True)
    res_enabled = generate_market_report(report_type="weekly", target_date="2026-10-30", config=cfg_enabled)
    with open(res_enabled["markdown"], "r", encoding="utf-8") as f:
        md_enabled = f.read()
    with open(res_enabled["html"], "r", encoding="utf-8") as f:
        html_enabled = f.read()
    assert DEFENSIVE_EXCEPTION_BANNER in md_enabled
    assert DEFENSIVE_EXCEPTION_BANNER in html_enabled
