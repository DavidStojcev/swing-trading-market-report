"""Compare Old Scorecard vs New Stage 2 Scorecard across the last 8 weekly reports."""

from datetime import datetime
import os
from pathlib import Path
import sys
import pandas as pd
from typing import Any, Dict, List

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import load_config
from data.calendar import MarketCalendar
from data.constituents import ConstituentManager
from data.fred_provider import FredProvider
from data.yfinance_provider import YFinanceDataProvider
from data.calendar_provider import FinnhubCalendarProvider
from indicators.engine import compute_technicals
from indicators.breadth import compute_market_breadth
from sections.macro import build_macro_section
from scoring.engine import TrendScoringEngine
from scoring.rules import evaluate_technical_votes, evaluate_vix_vote, evaluate_breadth_votes, evaluate_macro_votes
from storage.snapshots import SnapshotStore


def compute_old_score(
    spx_snap: Any,
    vix_curr: float,
    vix_prev: float,
    breadth_res: Any,
    macro_data: Any,
    cfg: Any,
) -> Dict[str, Any]:
    """Compute score under the legacy (v1) scoring formula."""
    votes = []
    # 1. Standard technical votes (weight 1.0 each)
    t_votes = evaluate_technical_votes(spx_snap, cfg.scoring)
    votes.extend(t_votes)

    # 2. VIX vote (weight 1.0)
    v_vote = evaluate_vix_vote(vix_curr, vix_prev, cfg.scoring)
    votes.append(v_vote)

    # 3. Breadth votes (weight 0.5 each)
    if breadth_res and cfg.breadth.scoring.enabled:
        b_votes = evaluate_breadth_votes(breadth_res, cfg.breadth.scoring, "weekly")
        votes.extend(b_votes)

    # 4. Macro votes (weight 0.5 each - legacy voted 0 for missing consensus)
    if macro_data and cfg.macro.scoring.enabled:
        fr = getattr(macro_data, "fed_rates", None)
        ca = getattr(macro_data, "cross_assets", [])
        rr = getattr(macro_data, "recent_releases", [])
        m_votes = evaluate_macro_votes(fr, ca, rr, cfg.macro.scoring)
        votes.extend(m_votes)

    total_weight = sum(v.weight for v in votes)
    total_weighted = sum(v.weighted_vote for v in votes)
    norm_score = total_weighted / total_weight if total_weight > 0 else 0.0
    norm_score = round(norm_score, 2)

    if norm_score >= 0.30:
        verdict = "Bullish"
    elif norm_score <= -0.30:
        verdict = "Bearish"
    else:
        verdict = "Neutral"

    return {
        "score": norm_score,
        "verdict": verdict,
        "raw": total_weighted,
        "max": total_weight,
    }


def main():
    cfg = load_config()
    cal = MarketCalendar()
    const_manager = ConstituentManager(
        cache_dir=cfg.data.cache_dir,
        cache_days=cfg.data.constituents_cache_days,
    )
    constituents = const_manager.get_universe()

    provider = YFinanceDataProvider(
        cache_dir=cfg.data.cache_dir,
        batch_size=cfg.data.batch_size,
        request_delay=cfg.data.request_delay_seconds,
        max_retries=cfg.data.max_retries,
        backoff_factor=cfg.data.backoff_factor,
    )
    fred_provider = FredProvider(
        api_key_env=cfg.macro.fred.api_key_env,
        cache_dir=str(Path(cfg.data.cache_dir) / "fred"),
        cache_days=cfg.macro.fred.cache_days,
        max_retries=cfg.data.max_retries,
        backoff_factor=cfg.data.backoff_factor,
    )
    calendar_provider = FinnhubCalendarProvider(
        api_key_env=cfg.macro.calendar.finnhub_api_key_env,
        cache_dir=str(Path(cfg.data.cache_dir) / "calendar"),
        cache_hours=cfg.macro.calendar.cache_hours,
        tolerances=cfg.macro.tolerances,
    )

    scoring_engine = TrendScoringEngine(cfg.scoring, cfg.scorecard_categories)
    snapshots = SnapshotStore(db_path=cfg.data.snapshot_db_path)

    weekly_dates = [
        "2026-09-11",
        "2026-09-18",
        "2026-09-25",
        "2026-10-02",
        "2026-10-09",
        "2026-10-16",
        "2026-10-23",
        "2026-10-30",
    ]

    core_tickers = [
        "^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^VIX3M", "SPY", "RSP", "QQQ",
        "DX-Y.NYB", "CL=F", "GC=F", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY",
        "XLP", "XLU", "XLB", "XLRE", "XLC"
    ]
    core_bars = provider.get_history(core_tickers, start_date="2025-01-01", end_date="2026-10-30")
    equity_tickers = [c.symbol for c in constituents]
    equity_bars = provider.get_history(equity_tickers, start_date="2025-01-01", end_date="2026-10-30")

    results = []

    for w_date in weekly_dates:
        parsed_dt = datetime.strptime(w_date, "%Y-%m-%d").date()
        period_info = cal.resolve_period("weekly", parsed_dt)
        session_dt = pd.to_datetime(period_info.session_date)

        spx_snap = None
        ndx_snap = None
        if "^GSPC" in core_bars and not core_bars["^GSPC"].empty:
            sub = core_bars["^GSPC"][core_bars["^GSPC"].index <= session_dt]
            if not sub.empty:
                spx_snap = compute_technicals(
                    df=sub,
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
            sub_n = core_bars["^NDX"][core_bars["^NDX"].index <= session_dt]
            if not sub_n.empty:
                ndx_snap = compute_technicals(
                    df=sub_n,
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

        vix_df = core_bars.get("^VIX")
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

        sec_macro = build_macro_section(
            fred=fred_provider,
            calendar_provider=calendar_provider,
            cross_asset_bars=core_bars,
            period=period_info,
            cfg=cfg,
            market_calendar=cal,
        )

        prior_snapshot = snapshots.get_snapshot(period_info.report_type, period_info.prev_period_end)
        spx_period_ret = None
        if "^GSPC" in core_bars and not core_bars["^GSPC"].empty:
            s_curr = core_bars["^GSPC"][core_bars["^GSPC"].index <= session_dt]
            s_base = core_bars["^GSPC"][core_bars["^GSPC"].index <= pd.to_datetime(period_info.baseline_date)]
            if not s_curr.empty and not s_base.empty:
                c_now = float(s_curr.iloc[-1]["Close"])
                c_base = float(s_base.iloc[-1]["Close"])
                spx_period_ret = ((c_now - c_base) / c_base) * 100.0

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

        old_res = compute_old_score(
            spx_snap=spx_snap,
            vix_curr=vix_curr,
            vix_prev=vix_prev,
            breadth_res=breadth_res,
            macro_data=sec_macro.data if sec_macro.is_available else None,
            cfg=cfg,
        )

        new_scorecard = scoring_engine.compute_scorecard(
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
        )

        cat_map = {c.category_key: c.score for c in new_scorecard.categories}

        results.append({
            "date": w_date,
            "old_score": old_res["score"],
            "old_verdict": old_res["verdict"],
            "new_score": new_scorecard.normalized_score,
            "new_regime": new_scorecard.regime_label,
            "confidence": new_scorecard.confidence.split()[0] if new_scorecard.confidence else "Mixed",
            "trend_score": cat_map.get("trend_price", 0.0),
            "breadth_score": cat_map.get("breadth", 0.0),
            "vol_score": cat_map.get("volatility_risk", 0.0),
            "rates_score": cat_map.get("rates_macro", 0.0),
            "spx_vs_50": spx_snap.price_vs_dma50_pct if spx_snap else 0.0,
            "ndx_vs_50": ndx_snap.price_vs_dma50_pct if ndx_snap else 0.0,
        })

    print("\n### 8-Week Scorecard Evolution: Old Formula vs. Stage 2 Categorical Engine\n")
    print("| Weekly Date | Old Score | Old Verdict | New Score | New Regime | Confidence | Trend/Price | Breadth | Vol/Risk | Rates/Macro | SPX vs 50d | NDX vs 50d |")
    print("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        print(
            f"| `{r['date']}` | `{r['old_score']:+.2f}` | {r['old_verdict']} | "
            f"`{r['new_score']:+.2f}` | **{r['new_regime']}** | {r['confidence']} | "
            f"`{r['trend_score']:+.2f}` | `{r['breadth_score']:+.2f}` | `{r['vol_score']:+.2f}` | `{r['rates_score']:+.2f}` | "
            f"`{r['spx_vs_50']:+.1f}%` | `{r['ndx_vs_50']:+.1f}%` |"
        )
    print("\n")


if __name__ == "__main__":
    main()
