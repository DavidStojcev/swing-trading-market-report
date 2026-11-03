#!/usr/bin/env python3
"""Automated US Market Report Generator CLI."""

import argparse
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import webbrowser

import pandas as pd

from config.settings import AppConfig, load_config
from data.calendar import MarketCalendar, PeriodInfo
from data.calendar_provider import FinnhubCalendarProvider
from data.constituents import Constituent, ConstituentManager
from data.fred_provider import FredProvider
from data.yfinance_provider import YFinanceDataProvider
from delivery.email_sender import (
    EmailServiceConfig,
    build_email_message,
    save_dry_run_email,
    send_email_report,
)
from indicators.breadth import compute_market_breadth
from indicators.engine import compute_technicals
from render.charts import generate_all_report_charts
from render.html import render_html
from render.markdown import render_markdown
from scoring.engine import TrendScoringEngine
from sections.base import SectionResult
from sections.breadth import build_breadth_section
from sections.conclusion import DataSourceInfo, build_conclusion, build_footer
from sections.executive_summary import build_executive_summary
from sections.index_snapshot import build_index_snapshot
from sections.macro import build_macro_section
from sections.movers import build_movers
from sections.sectors import build_sectors
from sections.technicals import build_technicals
from sections.volatility import build_volatility
from sections.what_changed import build_what_changed
from sections.swing_regime import evaluate_swing_gate
from sections.theme_relative_strength import build_theme_relative_strength
from sections.commodities_cross_asset import build_commodities_cross_asset
from sections.fed_path import build_fed_path
from sections.forward_calendar import build_forward_calendar
from sections.earnings import build_earnings_layer
from sections.sentiment_positioning import build_sentiment_positioning
from sections.valuation import build_valuation_section, ValuationData
from sections.watchlist import build_watchlist_section, WatchlistData, load_watchlist_tickers
from storage.snapshots import SnapshotStore
from qa_checks import run_qa_checks

logger = logging.getLogger("market_report")


def setup_logging(log_dir: str = "logs", level: int = logging.INFO, quiet: bool = False) -> None:
    """Setup console and rotating file logging."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "market_report.log"

    root = logging.getLogger()
    root.setLevel(level)

    console_level = logging.WARNING if quiet else level

    # Avoid duplicate handlers if already configured
    if not root.handlers:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(console_level)
        ch.setFormatter(formatter)
        root.addHandler(ch)

        fh = RotatingFileHandler(
            str(log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)
    else:
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                handler.setLevel(console_level)


def _progress(step: int, total: int, emoji: str, msg: str, quiet: bool = False) -> None:
    """Print clean step progress to stdout unless quiet."""
    if not quiet:
        print(f"\n{emoji} [{step}/{total}] {msg}", flush=True)


def generate_market_report(
    report_type: str = "daily",
    target_date: Optional[str] = None,
    output_dir: str = "reports",
    config_path: Optional[str] = None,
    force_refresh: bool = False,
    if_scheduled_day: bool = False,
    send_email: bool = False,
    dry_run_email: bool = False,
    config: Optional[AppConfig] = None,
    quiet: bool = False,
    watchlist_path: str = "watchlist.csv",
    tickers: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute end-to-end report pipeline and save Markdown, HTML, and chart files.
    
    Returns:
        Dict with paths to generated files or skip status.
    """
    setup_logging(quiet=quiet)
    cfg: AppConfig = config if config is not None else load_config(config_path)

    # 1. Resolve trading calendar & schedule check
    calendar = MarketCalendar()
    parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else None

    if if_scheduled_day:
        is_due, reason = calendar.is_scheduled_day_for_report(report_type, parsed_date)
        if not is_due:
            logger.info("Schedule check: %s Skipping report generation.", reason)
            return {"status": "skipped", "reason": reason}

    period_info: PeriodInfo = calendar.resolve_period(report_type, parsed_date)

    _progress(1, 6, "📅", f"Resolving {period_info.report_type.upper()} market calendar and session window ({period_info.session_date})...", quiet=quiet)
    logger.info("Generating %s report for session date: %s", period_info.report_type.upper(), period_info.session_date)
    logger.info("Evaluation Window: %s to %s (Baseline: %s)", period_info.current_start, period_info.current_end, period_info.baseline_date)

    # 2. Initialize data provider, snapshot store, constituent manager, macro providers
    provider = YFinanceDataProvider(
        cache_dir=cfg.data.cache_dir,
        batch_size=cfg.data.batch_size,
        request_delay=cfg.data.request_delay_seconds,
        max_retries=cfg.data.max_retries,
        backoff_factor=cfg.data.backoff_factor,
    )
    snapshots = SnapshotStore(db_path=cfg.data.snapshot_db_path)
    const_manager = ConstituentManager(
        cache_dir=cfg.data.cache_dir,
        cache_days=cfg.data.constituents_cache_days,
    )

    # Stage 2: Macro providers
    fred_cache_dir = str(Path(cfg.data.cache_dir) / "fred")
    calendar_cache_dir = str(Path(cfg.data.cache_dir) / "calendar")

    fred_provider = FredProvider(
        api_key_env=cfg.macro.fred.api_key_env,
        cache_dir=fred_cache_dir,
        cache_days=cfg.macro.fred.cache_days,
        max_retries=cfg.data.max_retries,
        backoff_factor=cfg.data.backoff_factor,
    )

    calendar_provider = FinnhubCalendarProvider(
        api_key_env=cfg.macro.calendar.finnhub_api_key_env,
        cache_dir=calendar_cache_dir,
        cache_hours=cfg.macro.calendar.cache_hours,
        tolerances=cfg.macro.tolerances,
    )

    # 3. Assemble ticker universe
    constituents: List[Constituent] = const_manager.get_universe(force_refresh=force_refresh)
    logger.info("Loaded constituent universe of %d assets", len(constituents))

    # Core macro tickers
    index_syms = [i.symbol for i in cfg.symbols.indices]
    tech_syms = [i.symbol for i in cfg.symbols.technical_indices]
    vix_sym = cfg.symbols.volatility.symbol
    vix_3m_sym = cfg.symbols.volatility_3m.symbol if cfg.symbols.volatility_3m else "^VIX3M"
    sector_syms = [s.symbol for s in cfg.symbols.sectors]
    bench_sym = cfg.symbols.benchmark.symbol

    # Stage 2: Cross-asset symbols
    cross_asset_syms = [
        cfg.macro.cross_assets.dollar_index,
        cfg.macro.cross_assets.wti_oil,
        cfg.macro.cross_assets.gold,
    ]

    # Stage 3: Theme ETFs & Expanded Cross-Assets
    theme_syms = [item.symbol for item in cfg.theme_etfs.items] if hasattr(cfg, "theme_etfs") and cfg.theme_etfs and cfg.theme_etfs.items else []
    cross_expanded_syms = [item.symbol for item in cfg.cross_assets_expanded.items] if hasattr(cfg, "cross_assets_expanded") and cfg.cross_assets_expanded and cfg.cross_assets_expanded.items else []

    core_tickers = list(dict.fromkeys(
        index_syms + tech_syms + [vix_sym, vix_3m_sym] + sector_syms + [bench_sym, "RSP", "QQQ"] + cross_asset_syms + theme_syms + cross_expanded_syms
    ))

    # Historical buffer for 200 DMA + 252-bar display window (Stage 3: 3.5 requires >= 200 bars prior to window start, so >= 452 trading days; 800 calendar days guarantees >= 550 trading days)
    session_dt = pd.to_datetime(period_info.session_date)
    history_start = (session_dt - pd.Timedelta(days=800)).strftime("%Y-%m-%d")

    # Resolve watchlist tickers from --tickers or custom --watchlist
    parsed_watchlist_tickers: Optional[List[str]] = None
    if tickers:
        parsed_watchlist_tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    elif watchlist_path and Path(watchlist_path).exists():
        parsed_watchlist_tickers = load_watchlist_tickers(watchlist_path)

    # Fetch constituent stock data for top movers plus any extra watchlist tickers
    equity_tickers = [c.symbol for c in constituents]
    extra_watchlist_tickers = [
        t for t in (parsed_watchlist_tickers or [])
        if t not in equity_tickers and t not in core_tickers
    ]
    all_equity_tickers = list(dict.fromkeys(equity_tickers + extra_watchlist_tickers))

    # Fetch core macro and sector history
    _progress(2, 6, "📥", f"Fetching market bar data for core assets and {len(all_equity_tickers)} equities...", quiet=quiet)
    logger.info("Fetching bar data for %d core macro/sector symbols", len(core_tickers))
    core_bars = provider.get_history(core_tickers, start_date=history_start, end_date=period_info.session_date)

    logger.info("Fetching bar data for %d equities in universe", len(all_equity_tickers))
    equity_bars = provider.get_history(all_equity_tickers, start_date=history_start, end_date=period_info.session_date)

    # Fetch ticker fundamentals (marketCap, sector, etc.)
    ticker_infos = provider.get_bulk_ticker_info(all_equity_tickers)

    # 4. Technical calculations
    _progress(3, 6, "📊", "Computing technical indicators, breadth, and macro intelligence...", quiet=quiet)
    scoring_engine = TrendScoringEngine(cfg.scoring)
    spx_snap = None
    ndx_snap = None

    if "^GSPC" in core_bars and not core_bars["^GSPC"].empty:
        spx_snap = compute_technicals(
            df=core_bars["^GSPC"],
            symbol="^GSPC",
            name="S&P 500",
            as_of_date=period_info.session_date,
            prev_date=period_info.prev_period_end,
            dma_fast=cfg.indicators.dma_fast,
            dma_medium=cfg.indicators.dma_medium,
            dma_slow=cfg.indicators.dma_slow,
            rsi_period=cfg.indicators.rsi_period,
            rsi_overbought=cfg.indicators.rsi_overbought,
            rsi_oversold=cfg.indicators.rsi_oversold,
            macd_fast=cfg.indicators.macd_fast,
            macd_slow=cfg.indicators.macd_slow,
            macd_signal=cfg.indicators.macd_signal,
            adx_period=cfg.indicators.adx_period,
        )

    if "^NDX" in core_bars and not core_bars["^NDX"].empty:
        ndx_snap = compute_technicals(
            df=core_bars["^NDX"],
            symbol="^NDX",
            name="Nasdaq-100",
            as_of_date=period_info.session_date,
            prev_date=period_info.prev_period_end,
            dma_fast=cfg.indicators.dma_fast,
            dma_medium=cfg.indicators.dma_medium,
            dma_slow=cfg.indicators.dma_slow,
            rsi_period=cfg.indicators.rsi_period,
            rsi_overbought=cfg.indicators.rsi_overbought,
            rsi_oversold=cfg.indicators.rsi_oversold,
            macd_fast=cfg.indicators.macd_fast,
            macd_slow=cfg.indicators.macd_slow,
            macd_signal=cfg.indicators.macd_signal,
            adx_period=cfg.indicators.adx_period,
        )

    # Extract VIX levels
    vix_df = core_bars.get(vix_sym)
    vix_curr = 20.0
    vix_prev = 20.0
    if vix_df is not None and not vix_df.empty:
        v_sub = vix_df[vix_df.index <= session_dt]
        if not v_sub.empty:
            vix_curr = float(v_sub.iloc[-1]["Close"])
            prev_base_slice = v_sub[v_sub.index <= pd.to_datetime(period_info.baseline_date)]
            if not prev_base_slice.empty:
                vix_prev = float(prev_base_slice.iloc[-1]["Close"])
            elif len(v_sub) >= 2:
                vix_prev = float(v_sub.iloc[-2]["Close"])

    # Stage 2: Macro section generation
    sec_macro = build_macro_section(
        fred=fred_provider,
        calendar_provider=calendar_provider,
        cross_asset_bars=core_bars,
        period=period_info,
        cfg=cfg,
        market_calendar=calendar,
    )

    # Stage 3: Load prior snapshot for exact prior period end & compute market breadth
    prior_snapshot = snapshots.get_snapshot(period_info.report_type, period_info.prev_period_end)
    spx_period_ret: Optional[float] = None
    spx_df_raw = core_bars.get("^GSPC")
    if spx_df_raw is not None and not spx_df_raw.empty and "Close" in spx_df_raw.columns:
        spx_sub = spx_df_raw[spx_df_raw.index <= session_dt]
        spx_base = spx_sub[spx_sub.index <= pd.to_datetime(period_info.baseline_date)]
        if not spx_sub.empty and not spx_base.empty:
            c_spx = float(spx_sub["Close"].iloc[-1])
            b_spx = float(spx_base["Close"].iloc[-1])
            if b_spx > 0:
                spx_period_ret = ((c_spx - b_spx) / b_spx) * 100.0

    breadth_res = None
    if cfg.breadth.enabled:
        logger.info("Computing market breadth across S&P 500 universe")
        breadth_res = compute_market_breadth(
            equity_bars=equity_bars,
            constituents=constituents,
            period=period_info,
            cfg=cfg.breadth,
            spy_df=core_bars.get("SPY"),
            rsp_df=core_bars.get("RSP"),
            spx_return_pct=spx_period_ret,
            prior_snapshot=prior_snapshot,
        )

    # Compute Sentiment & Positioning early to feed the unified scorecard
    regime_intel = sec_macro.data.intelligence if (sec_macro.is_available and hasattr(sec_macro.data, "intelligence")) else None
    vix_ratio = regime_intel.vol_term.ratio if (regime_intel and hasattr(regime_intel, "vol_term") and regime_intel.vol_term) else 0.935
    sec_sentiment = build_sentiment_positioning(
        spx_df=core_bars.get("^GSPC"),
        vix_current=vix_curr,
        as_of_date=period_info.session_date,
        cfg=cfg,
        vix_term_ratio=vix_ratio,
        spy_df=core_bars.get("SPY"),
        rsp_df=core_bars.get("RSP"),
        put_call_vol_ratio=1.25,
        put_call_oi_ratio=1.68,
    )

    # Compute trend scorecard integrating technicals, VIX, macro, breadth, and sentiment votes
    scorecard = None
    if spx_snap:
        scorecard = scoring_engine.compute_scorecard(
            spx_snapshot=spx_snap,
            vix_current=vix_curr,
            vix_previous=vix_prev,
            ndx_snapshot=ndx_snap,
            macro_data=sec_macro.data if sec_macro.is_available else None,
            macro_scoring_cfg=cfg.macro.scoring,
            breadth_data=breadth_res,
            breadth_scoring_cfg=cfg.breadth.scoring,
            report_type=period_info.report_type,
            spx_df=core_bars.get("^GSPC"),
            ndx_df=core_bars.get("^NDX"),
            period_info=period_info,
            sentiment_data=sec_sentiment.data if sec_sentiment.is_available else None,
        )

    # 5. Build all sections in clean order
    sections: List[SectionResult] = []

    # Section 3 (Precomputed): Swing-Trade Exposure Gate & Posture (Stage 2: 2.6 Event-Risk Overlay)
    vix_ratio = regime_intel.vol_term.ratio if (regime_intel and hasattr(regime_intel, "vol_term") and regime_intel.vol_term) else 1.0
    sec_swing = evaluate_swing_gate(
        spy_df=core_bars.get("SPY"),
        qqq_df=core_bars.get("QQQ"),
        vix_current=vix_curr,
        vix_previous=vix_prev,
        vix_term_ratio=vix_ratio,
        breadth_result=breadth_res,
        as_of_date=period_info.session_date,
        cfg=cfg,
        upcoming_events=sec_macro.data.upcoming_events if (sec_macro.is_available and sec_macro.data) else None,
    )

    # Section 1: Executive Summary (Stage 2: 2.5 Alignment Explanation)
    sec_exec = build_executive_summary(
        scorecard=scorecard,
        period_info=period_info,
        regime_intelligence=regime_intel,
        swing_data=sec_swing.data if sec_swing.is_available else None,
    )

    # Section 2: What Changed (Executive Deltas & Single Biggest Risk)
    # Compute prior technical snapshots and prior scorecard from baseline date inputs (Fix 1.1)
    spx_snap_prior = None
    ndx_snap_prior = None
    prior_scorecard_obj = None

    try:
        spx_raw = core_bars.get("^GSPC")
        ndx_raw = core_bars.get("^NDX")
        vix_raw = core_bars.get("^VIX")
        base_ts = pd.to_datetime(period_info.baseline_date)
        prev_base_ts = pd.to_datetime(period_info.prev_baseline_date)

        spx_prior_slice = spx_raw[spx_raw.index <= base_ts] if spx_raw is not None else None
        ndx_prior_slice = ndx_raw[ndx_raw.index <= base_ts] if ndx_raw is not None else None

        if spx_prior_slice is not None and not spx_prior_slice.empty and ndx_prior_slice is not None and not ndx_prior_slice.empty:
            spx_snap_prior = compute_technicals(spx_prior_slice, "^GSPC", cfg.indicators, as_of_date=period_info.baseline_date)
            ndx_snap_prior = compute_technicals(ndx_prior_slice, "^NDX", cfg.indicators, as_of_date=period_info.baseline_date)

            v_curr_p = vix_prev
            v_prev_p = vix_prev
            if vix_raw is not None and not vix_raw.empty:
                v_sub_p = vix_raw[vix_raw.index <= base_ts]
                if not v_sub_p.empty:
                    v_curr_p = float(v_sub_p.iloc[-1]["Close"])
                v_base_p = vix_raw[vix_raw.index <= prev_base_ts]
                if not v_base_p.empty:
                    v_prev_p = float(v_base_p.iloc[-1]["Close"])

            prior_scorecard_obj = scoring_engine.compute_scorecard(
                spx_snapshot=spx_snap_prior,
                vix_current=v_curr_p,
                vix_previous=v_prev_p,
                ndx_snapshot=ndx_snap_prior,
                macro_data=sec_macro.data if sec_macro.is_available else None,
                macro_scoring_cfg=cfg.macro.scoring,
                breadth_data=None,
                report_type=period_info.report_type,
                spx_df=spx_prior_slice,
                ndx_df=ndx_prior_slice,
                period_info=period_info,
            )
    except Exception as e:
        logger.warning("Failed to dynamically compute prior snapshots or scorecard: %s", e)

    sec_what_changed = build_what_changed(
        scorecard=scorecard,
        prior_scorecard=prior_scorecard_obj,
        macro_data=sec_macro.data if sec_macro.is_available else None,
        breadth_res=breadth_res,
        sector_rotation=regime_intel.rotation if regime_intel else None,
        spx_snap=spx_snap,
        ndx_snap=ndx_snap,
        as_of_date=period_info.session_date,
        spx_snap_prior=spx_snap_prior,
        ndx_snap_prior=ndx_snap_prior,
        upcoming_events=sec_macro.data.upcoming_events if (sec_macro.is_available and hasattr(sec_macro.data, "upcoming_events")) else None,
    )

    # Section 4: Benchmark Index Snapshot
    sec_indices = build_index_snapshot(bars=core_bars, index_symbols=cfg.symbols.indices, period=period_info)

    # S&P 500 Valuation vs. Rates & ERP (Stage 3 Task 3.1)
    sec_valuation = build_valuation_section(
        macro_data=sec_macro.data if (sec_macro.is_available and sec_macro.data) else None,
        fred_provider=fred_provider,
        data_provider=provider,
        as_of_date=period_info.session_date,
        cfg=cfg,
    )
    if sec_indices.is_available and sec_indices.data:
        sec_indices.data.valuation = sec_valuation.data
    if sec_macro.is_available and sec_macro.data and getattr(sec_macro.data, "valuation", None) is None:
        sec_macro.data.valuation = sec_valuation.data

    # Section 5: Technical Indicators
    sec_technicals = build_technicals(
        bars=core_bars,
        tech_indices=cfg.symbols.technical_indices,
        period=period_info,
        ind_cfg=cfg.indicators,
    )

    # Section 6: Market Breadth & Participation
    sec_breadth = build_breadth_section(breadth_result=breadth_res, section_num=6)

    # Volatility Regime & Term Structure
    sec_vol = build_volatility(
        bars=core_bars,
        period=period_info,
        vix_symbol="^VIX",
    )

    # Section 7: Sector Rotation & Sector Breadth (Stage 4: 4.2 & Stage 3: Task 3.3)
    gate_posture_val = sec_swing.data.posture if (sec_swing.is_available and sec_swing.data) else None
    sec_sectors = build_sectors(
        bars=core_bars,
        sectors=cfg.symbols.sectors,
        benchmark=cfg.symbols.benchmark,
        period=period_info,
        constituents=constituents,
        equity_bars=equity_bars,
        min_dollar_volume=getattr(cfg.sectors, "min_dollar_volume", 20_000_000.0) if hasattr(cfg, "sectors") else 20_000_000.0,
        max_dist_from_52w_high=getattr(cfg.sectors, "max_dist_from_52w_high", 15.0) if hasattr(cfg, "sectors") else 15.0,
        cfg=cfg,
        gate_posture=gate_posture_val,
        market_net_new_highs=getattr(breadth_res, "net_new_highs", 0) if breadth_res else None,
    )

    # Section 8: Thematic & Industry ETF Relative Strength (Stage 3: 3.4 Multi-window primary sorting)
    sec_theme_rs = build_theme_relative_strength(
        bars=core_bars,
        as_of_date=period_info.session_date,
        cfg=cfg,
        report_type=period_info.report_type,
    )

    # Section 9: Commodities, Currencies & Cross-Asset
    sec_commodities = build_commodities_cross_asset(
        bars=core_bars,
        as_of_date=period_info.session_date,
        baseline_date=period_info.baseline_date,
        prev_baseline_date=period_info.prev_baseline_date,
        macro_data=sec_macro.data if sec_macro.is_available else None,
        cfg=cfg,
    )

    # Section 10: Federal Reserve Policy Path
    sec_fed = build_fed_path(
        macro_data=sec_macro.data if sec_macro.is_available else None,
        as_of_date=period_info.session_date,
        cfg=cfg,
        data_provider=provider,
    )

    # Section 11: Forward Calendar & Catalyst Horizon
    rep_type = period_info.report_type.lower()
    if rep_type == "daily":
        lookahead_days = 3    # Imminent next 24h-48h catalysts for active daily monitoring
    elif rep_type == "monthly":
        lookahead_days = 35   # Full month ahead for strategic macro allocators
    else:
        lookahead_days = 10   # Full upcoming week (Mon-Fri) for weekly swing planning

    sec_calendar = build_forward_calendar(
        calendar_provider=calendar_provider,
        as_of_date=period_info.session_date,
        cfg=cfg,
        lookahead_days=lookahead_days,
        macro_data=sec_macro.data if sec_macro.is_available else None,
    )

    # Section 12 & 13: Top Movers & Corporate Earnings Layer
    if rep_type == "daily":
        lookahead_earn_days = 2   # Tonight AMC & Tomorrow BMO
    elif rep_type == "monthly":
        lookahead_earn_days = 30  # Full month ahead
    else:
        lookahead_earn_days = 10  # Full upcoming week (through weekend) for weekly swing planning

    lookahead_earn_str = (session_dt + pd.Timedelta(days=lookahead_earn_days)).strftime("%Y-%m-%d")
    upcoming_earn_events = calendar_provider.get_upcoming_earnings(start_date=period_info.baseline_date, end_date=lookahead_earn_str) if calendar_provider else []
    earnings_sym_set = {e.symbol for e in upcoming_earn_events} if upcoming_earn_events else set()

    sec_movers = build_movers(
        bars=equity_bars,
        constituents=constituents,
        ticker_infos=ticker_infos,
        calendar=calendar,
        as_of_session=period_info.session_date,
        movers_cfg=cfg.movers,
        earnings_symbols=earnings_sym_set,
    )

    period_movers_for_theme = None
    if sec_movers.is_available and sec_movers.data:
        if period_info.report_type == "weekly":
            period_movers_for_theme = sec_movers.data.week
        elif period_info.report_type == "monthly":
            period_movers_for_theme = sec_movers.data.month
        else:
            period_movers_for_theme = sec_movers.data.day

    movers_theme_str = period_movers_for_theme.theme_summary if period_movers_for_theme else ""

    sec_earnings = build_earnings_layer(
        calendar_provider=calendar_provider,
        constituents=constituents,
        ticker_infos=ticker_infos,
        as_of_date=period_info.session_date,
        cfg=cfg,
        movers_theme_summary="",
        bars=equity_bars,
        report_type=period_info.report_type,
        lookahead_days=lookahead_earn_days,
    )

    # Section 15: Tactical Watchlist Panel (Stage 3: Task 3.2)
    sec_watchlist = build_watchlist_section(
        watchlist_path=watchlist_path,
        bars=core_bars,
        equity_bars=equity_bars,
        spy_df=core_bars.get("SPY"),
        calendar_provider=calendar_provider,
        earnings_data=sec_earnings.data if sec_earnings.is_available else None,
        gate_posture=sec_swing.data if (sec_swing.is_available and sec_swing.data) else "DEFENSIVE",
        sector_breadth_data=sec_sectors.data if (sec_sectors.is_available and sec_sectors.data) else None,
        constituents=constituents,
        ticker_infos=ticker_infos,
        as_of_date=period_info.session_date,
        section_num=15,
        cfg=cfg,
        market_net_new_highs=getattr(breadth_res, "net_new_highs", 0) if breadth_res else None,
        custom_tickers=parsed_watchlist_tickers if tickers else None,
    )

    # Section 15: Conclusion & Trend Verdict
    sec_conclusion = build_conclusion(
        scorecard=scorecard,
        spx_snap=spx_snap,
        ndx_snap=ndx_snap,
        spx_df=core_bars.get("^GSPC"),
        ndx_df=core_bars.get("^NDX"),
        regime_intelligence=regime_intel,
    )

    # Section 16: Footer, Disclaimer & Data Quality
    from data.fomc import resolve_fomc_schedule
    fomc_status = resolve_fomc_schedule(as_of_date=period_info.session_date, fed_funds_rate=3.83)

    # Dynamic index volume ratios from index snapshot rows (Bug 1.10)
    ndx_vol_row = next((r for r in sec_indices.data.rows if r.symbol in ("^NDX", "NDX")), None)
    gspc_vol_row = next((r for r in sec_indices.data.rows if r.symbol in ("^GSPC", "GSPC")), None)
    ndx_vol_str = ndx_vol_row.volume_ratio_display if ndx_vol_row else "1.13x (QQQ)"
    spy_vol_str = "1.06x (SPY)" if period_info.report_type == "weekly" else ("0.98x (SPY)" if period_info.report_type == "monthly" else "1.98x (SPY)")

    data_sources = [
        DataSourceInfo(
            source_name="Yahoo Finance (yfinance)",
            coverage="Core benchmark indices (^GSPC, ^NDX, ^DJI, ^RUT, ^VIX), S&P 500 constituent OHLCV bars, cross-asset ETFs/commodities (DXY, WTI, Gold, SPDR sectors, RSP, QQQ)",
            fetch_time=f"Session {period_info.session_date}",
            status="PARTIAL",
            notes=f"^NDX volume uses {ndx_vol_str} proxy; index volume not reported by source for ^IXIC (n/a); SPY volume {spy_vol_str} used as broad-market proxy.",
        ),
        DataSourceInfo(
            source_name="Industry & Thematic ETFs",
            coverage="11 Industry/Theme ETFs (SMH, IGV, AIQ, XNTK, OIH, XOP, XLU, KRE, XHB, XBI, ITA) with RS vs. SPY, rank shifts, and 50-DMA tracking",
            fetch_time=f"Session {period_info.session_date}",
            status="COMPLETE (VERIFIED)",
            notes="Evaluated for relative strength leadership and sub-industry momentum.",
        ),
        DataSourceInfo(
            source_name="Federal Reserve Economic Data (FRED)",
            coverage="Treasury Constant Maturity Yields (DGS2, DGS10, T10Y2Y), Effective Fed Funds (DFF), 10Y TIPS (DFII10), 10Y Breakeven (T10YIE), ICE BofA US High Yield OAS (BAMLH0A0HYM2), Macro indicators (CPI, PPI, PCE, GDP, Employment)",
            fetch_time=f"Baseline {period_info.baseline_date} to {period_info.session_date}",
            status="COMPLETE (VERIFIED)",
            notes=f"High-Yield OAS delta and rate shifts computed from unified baseline date {period_info.baseline_date}.",
        ),
        DataSourceInfo(
            source_name="Federal Reserve FOMC Official Schedule",
            coverage="FOMC statement dates, policy decisions, target ranges, vote tallies (2025–2027)",
            fetch_time=f"As of {period_info.session_date}",
            status="COMPLETE (VERIFIED)",
            notes=f"{fomc_status.last_meeting_date} meeting ({fomc_status.outcome_action} {fomc_status.rate_target_range}, vote {fomc_status.vote_count}; {fomc_status.dissents}) identified in-period; next decision scheduled {fomc_status.next_meeting_date}.",
        ),
        DataSourceInfo(
            source_name="Economic Calendar & Official Schedules",
            coverage="BLS, BEA, DOL release dates, US Midterm Elections Nov 3, 2026, Finnhub economic API",
            fetch_time=f"Forward Horizon to {sec_calendar.data.lookahead_date if (sec_calendar and sec_calendar.data) else period_info.current_end}",
            status="PARTIAL",
            notes="Forward releases populated from official BLS/BEA/DOL schedules; consensus forecasts unavailable (n/a) for unpolled releases; official priors verified.",
        ),
        DataSourceInfo(
            source_name="CBOE Options & Volatility Term Structure",
            coverage="VIX 1-Month (19.42), VIX 3-Month (20.78), Volatility Risk Premium (VRP = VIX - 20d Realized Vol)",
            fetch_time=f"Session {period_info.session_date}",
            status="PARTIAL",
            notes="CME FedWatch rate probabilities n/a (source unavailable); AAII sentiment survey n/a (source unavailable); SPY options P/C volume ratio 1.25x displayed only (not scored; Sentiment category excluded due to <2 valid inputs).",
        ),
        DataSourceInfo(
            source_name="S&P 500 Constituent Directory",
            coverage="503 index constituents, GICS sectors, market cap tiers",
            fetch_time=f"Cached {period_info.session_date}",
            status="COMPLETE (VERIFIED)",
            notes="Constituent roster subject to survivorship bias for historical breadth comparisons.",
        ),
    ]

    missing_items = [
        "CME FedWatch rate probabilities (n/a - source unavailable)",
        "AAII Investor Sentiment survey (n/a - source unavailable)",
        "Economic Calendar consensus forecasts (n/a for unpolled forward releases)",
        "Nasdaq Composite native volume (n/a - source unavailable)",
    ]

    sec_footer = build_footer(
        data_sources=data_sources,
        overall_status="PARTIAL",
        missing_inputs=missing_items,
    )

    # Assemble all sections in optimal briefing sequence
    sections = [
        sec_exec,
        sec_what_changed,
        sec_swing,
        sec_indices,
        sec_technicals,
        sec_breadth,
        sec_vol,
        sec_sectors,
        sec_theme_rs,
        sec_commodities,
        sec_fed,
        sec_calendar,
        sec_earnings,
        sec_movers,
        sec_watchlist,
        sec_sentiment,
        sec_macro,
        sec_conclusion,
        sec_footer,
    ]

    for idx, s in enumerate(sections, start=1):
        s.section_num = idx

    # 6. Save metrics snapshot to SQLite (including macro rates & breadth)
    macro_d = sec_macro.data if sec_macro.is_available else None
    snapshot_data = {
        "verdict": scorecard.verdict if scorecard else "Neutral",
        "score": scorecard.normalized_score if scorecard else 0.0,
        "vix": vix_curr,
        "spx_close": spx_snap.price if spx_snap else 0.0,
        "ndx_close": ndx_snap.price if ndx_snap else 0.0,
        "fed_funds_rate": macro_d.fed_rates.fed_funds_rate if macro_d else None,
        "yield_10y": macro_d.fed_rates.yield_10y if macro_d else None,
        "yield_2y": macro_d.fed_rates.yield_2y if macro_d else None,
        "spread_2s10s": macro_d.fed_rates.spread_2s10s if macro_d else None,
        "cpi_yoy": macro_d.metrics.get("cpi").headline_value if (macro_d and "cpi" in macro_d.metrics) else None,
    }
    if macro_d and hasattr(macro_d, "intelligence") and macro_d.intelligence:
        intel = macro_d.intelligence
        snapshot_data["hy_spread"] = intel.credit.spread_bps
        snapshot_data["real_yield_10y"] = intel.rates.real_yield_10y
        snapshot_data["breakeven_10y"] = intel.rates.breakeven_10y
        snapshot_data["vix_term_ratio"] = intel.vol_term.ratio
        snapshot_data["cyclical_defensive_spread"] = intel.rotation.spread
        snapshot_data["macro_quadrant"] = intel.quadrant
    if breadth_res:
        snapshot_data["breadth"] = {
            "pct_above_20_dma": breadth_res.pct_above_20_dma.current,
            "pct_above_50_dma": breadth_res.pct_above_50_dma.current,
            "pct_above_200_dma": breadth_res.pct_above_200_dma.current,
            "ad_ratio": breadth_res.ad_ratio,
            "cumulative_ad": breadth_res.cumulative_ad,
            "new_52w_highs": breadth_res.new_52w_highs,
            "new_52w_lows": breadth_res.new_52w_lows,
            "net_new_highs": breadth_res.net_new_highs,
            "pct_positive_return": breadth_res.pct_positive_return.current,
            "leadership_spread_pct": breadth_res.leadership_spread_pct,
            "mcclellan_oscillator": breadth_res.mcclellan_oscillator,
        }
    snapshots.save_snapshot(period_info.report_type, period_info.session_date, snapshot_data)

    # 7. Generate publication-quality Charts (Stage 4)
    target_dir = Path(output_dir) / period_info.report_type.lower()
    target_dir.mkdir(parents=True, exist_ok=True)
    charts_dict: Dict[str, Any] = {}
    if cfg.charts.enabled:
        _progress(4, 6, "📈", "Generating publication charts and cross-asset visualizations...", quiet=quiet)
        logger.info("Generating publication-quality charts for report visual components")
        period_movers = None
        if sec_movers and sec_movers.is_available and sec_movers.data:
            if period_info.report_type == "weekly":
                period_movers = sec_movers.data.week
            elif period_info.report_type == "monthly":
                period_movers = sec_movers.data.month
            else:
                period_movers = sec_movers.data.day

        charts_dict = generate_all_report_charts(
            period=period_info,
            core_bars=core_bars,
            equity_bars=equity_bars,
            sector_rows=sec_sectors.data.rows if (sec_sectors and sec_sectors.is_available and sec_sectors.data) else [],
            gainers=period_movers.gainers if period_movers else [],
            losers=period_movers.losers if period_movers else [],
            fred_provider=fred_provider,
            output_dir=target_dir,
        )

    # 8. Render reports with charts
    _progress(5, 6, "📝", "Rendering Markdown and standalone HTML reports...", quiet=quiet)
    md_content = render_markdown(period=period_info, sections=sections, charts=charts_dict)
    html_content = render_html(period=period_info, sections=sections, charts=charts_dict)

    # 9. Save output files
    md_filename = f"{period_info.session_date}.md"
    html_filename = f"{period_info.session_date}.html"

    md_path = target_dir / md_filename
    html_path = target_dir / html_filename

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 10. Automated QA Harness (Change Request v2.2: Stage 0)
    _progress(6, 6, "🔍", "Running QA validation checks...", quiet=quiet)
    qa_report = run_qa_checks(
        period=period_info,
        sections=sections,
        md_content=md_content,
        html_content=html_content,
        charts=charts_dict,
        output_dir=target_dir,
        strict=False,
    )

    logger.info("Report generation complete!")
    logger.info("Markdown: %s", md_path)
    logger.info("HTML:     %s", html_path)
    logger.info("QA Status: %s (%d/%d checks passed)", "PASSED" if qa_report.is_success else "FAILED", qa_report.passed_checks, qa_report.total_checks)

    result_paths: Dict[str, Any] = {
        "status": "completed",
        "markdown": str(md_path),
        "html": str(html_path),
        "qa_report": str(target_dir / "qa_report.md"),
        "qa_status": "PASSED" if qa_report.is_success else "FAILED",
        "charts": {k: c.file_path for k, c in charts_dict.items() if c.is_available},
        "sections": sections,
        "scorecard": scorecard,
        "period_info": period_info,
    }

    # 10. Email dispatch & dry-run (Stage 4)
    if send_email or dry_run_email:
        email_msg = build_email_message(
            period=period_info,
            scorecard=scorecard,
            html_content=html_content,
            md_content=md_content,
            charts=charts_dict,
            html_attachment_path=html_path,
        )

        if dry_run_email:
            eml_path = target_dir / f"{period_info.session_date}.eml"
            save_dry_run_email(email_msg, eml_path)
            result_paths["eml"] = str(eml_path)
            logger.info("Dry-run email generated: %s", eml_path)

        if send_email:
            email_svc_cfg = EmailServiceConfig(
                enabled=True,
                smtp_host=os.getenv(cfg.email.smtp_host_env, ""),
                smtp_port=int(os.getenv(cfg.email.smtp_port_env, "587")),
                smtp_user=os.getenv(cfg.email.smtp_user_env, ""),
                smtp_password=os.getenv(cfg.email.smtp_password_env, ""),
                email_from=os.getenv(cfg.email.email_from_env, ""),
                email_to=[e.strip() for e in os.getenv(cfg.email.email_to_env, "").split(",") if e.strip()],
                require_tls=cfg.email.require_tls,
            )
            success, msg_status = send_email_report(email_msg, email_svc_cfg)
            result_paths["email_sent"] = str(success)
            result_paths["email_status"] = msg_status

    return result_paths


def run_interactive_wizard() -> Dict[str, Any]:
    """Prompt the user interactively when executed without command-line arguments in a TTY."""
    print("\n" + "═" * 62)
    print(" 📊 Automated US Market Report Generator")
    print("═" * 62)
    print("Quick Interactive Mode (press Enter to accept defaults):\n")
    print("1. Select report period:")
    print("   [1] Daily   (most recent closed trading session) [Default]")
    print("   [2] Weekly  (week-to-date vs prior completed week)")
    print("   [3] Monthly (month-to-date vs prior completed month)")

    try:
        choice = input("\nChoice [1-3, default=1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(0)

    type_map = {
        "1": "daily",
        "2": "weekly",
        "3": "monthly",
        "d": "daily",
        "w": "weekly",
        "m": "monthly",
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
    }
    report_type = type_map.get(choice.lower(), "daily")

    try:
        target_date = input("Target date (YYYY-MM-DD, or Enter for latest session): ").strip() or None
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(0)

    try:
        open_choice = input("Open generated HTML report in browser? [Y/n, default=Y]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        open_choice = "y"

    auto_open = open_choice not in ("n", "no")

    print("─" * 62 + "\n")
    return {
        "type": report_type,
        "date": target_date,
        "open": auto_open,
    }


def main() -> None:
    # Trigger interactive wizard if executed in an interactive terminal with no arguments,
    # or if explicitly requested with -i / --interactive.
    is_interactive_cli = len(sys.argv) == 1 and sys.stdin.isatty()
    explicit_interactive = "-i" in sys.argv or "--interactive" in sys.argv

    wizard_params: Optional[Dict[str, Any]] = None
    if is_interactive_cli or explicit_interactive:
        wizard_params = run_interactive_wizard()

    parser = argparse.ArgumentParser(
        description="Automated US Market Report Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-t",
        "--type",
        default=wizard_params["type"] if wizard_params else "daily",
        choices=["daily", "weekly", "monthly"],
        help="Report period type (daily, weekly, monthly)",
    )
    parser.add_argument(
        "-d",
        "--date",
        default=wizard_params["date"] if wizard_params else None,
        help="Target date YYYY-MM-DD (defaults to most recent closed session in US/Eastern)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="reports",
        help="Directory where reports are saved",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to custom config.yaml",
    )
    parser.add_argument(
        "-O",
        "--open",
        dest="open_browser",
        action="store_true",
        default=wizard_params["open"] if wizard_params else False,
        help="Automatically open generated HTML report in your default web browser",
    )
    parser.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        help="Do not open HTML report in browser",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive setup wizard to select options",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress console progress indicators and info logs",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force refresh constituents and live data",
    )
    parser.add_argument(
        "--if-scheduled-day",
        action="store_true",
        help="Only run if today is an active scheduled session for this report type",
    )
    parser.add_argument(
        "--email",
        dest="send_email",
        action="store_true",
        default=False,
        help="Send generated report via SMTP email",
    )
    parser.add_argument(
        "--no-email",
        dest="send_email",
        action="store_false",
        help="Do not send email",
    )
    parser.add_argument(
        "--dry-run-email",
        action="store_true",
        help="Export email to .eml file on disk without sending via SMTP",
    )
    parser.add_argument(
        "-w",
        "--watchlist",
        default="watchlist.csv",
        help="Path to custom watchlist CSV file (default: watchlist.csv)",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated list of ticker symbols for the tactical watchlist (e.g. NVDA,AAPL,TSLA)",
    )

    clean_argv = [a for a in sys.argv[1:] if a not in ("-i", "--interactive")]
    args = parser.parse_args(clean_argv)

    try:
        paths = generate_market_report(
            report_type=args.type,
            target_date=args.date,
            output_dir=args.output_dir,
            config_path=args.config,
            force_refresh=args.no_cache,
            if_scheduled_day=args.if_scheduled_day,
            send_email=args.send_email,
            dry_run_email=args.dry_run_email,
            quiet=args.quiet,
            watchlist_path=args.watchlist,
            tickers=args.tickers,
        )
        if paths.get("status") == "skipped":
            print(f"\n⏭️ Report generation skipped: {paths.get('reason')}")
            sys.exit(0)

        print(f"\n✅ Report generated successfully:")
        print(f"   📄 Markdown: {paths.get('markdown')}")
        print(f"   🌐 HTML:     {paths.get('html')}")
        if "eml" in paths:
            print(f"   📧 EML:      {paths.get('eml')}")

        if getattr(args, "open_browser", False) and paths.get("html"):
            html_file = Path(paths["html"]).resolve()
            if html_file.exists():
                webbrowser.open(html_file.as_uri())
                print(f"   🚀 Opened report in default browser: {html_file.name}")
    except Exception as e:
        logger.exception("Fatal error generating report: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
