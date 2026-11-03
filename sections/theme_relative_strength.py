"""Section: Industry & Thematic ETF Relative Strength Ranking."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class ThemeItem:
    symbol: str
    name: str
    category: str
    close: float
    ret_1w: float
    ret_1m: float
    ret_3m: float
    rs_vs_spy: float
    rank: int
    rank_change: int
    dist_50dma_pct: float
    above_50dma: bool
    ret_1d: float = 0.0
    is_available: bool = True


@dataclass
class ThemeRelativeStrengthData:
    as_of_date: str
    spy_1w_return: float
    items: List[ThemeItem] = field(default_factory=list)
    top_theme_summary: str = ""
    commentary: str = ""
    primary_window: str = "1W"
    primary_benchmark_return: float = 0.0
    primary_benchmark_label: str = "SPY 1-Week Return"
    spy_1d_return: float = 0.0


def build_theme_relative_strength(
    bars: Dict[str, pd.DataFrame],
    as_of_date: str,
    cfg: Any,
    report_type: str = "daily",
) -> SectionResult:
    """Build relative strength ranking across industry and theme ETFs."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)
        spy_df = bars.get("SPY")

        # SPY benchmarks
        spy_1d = 0.0
        spy_1w = 0.0
        spy_1m = 0.0
        if spy_df is not None and not spy_df.empty:
            spy_sub = spy_df[spy_df.index <= as_of_dt]
            if len(spy_sub) >= 2:
                c_now = float(spy_sub.iloc[-1]["Close"])
                c_prev_1d = float(spy_sub.iloc[-2]["Close"])
                spy_1d = ((c_now - c_prev_1d) / c_prev_1d) * 100.0 if c_prev_1d > 0 else 0.0
            if len(spy_sub) >= 6:
                c_now = float(spy_sub.iloc[-1]["Close"])
                c_prev_1w = float(spy_sub.iloc[-6]["Close"])
                spy_1w = ((c_now - c_prev_1w) / c_prev_1w) * 100.0 if c_prev_1w > 0 else 0.0
            if len(spy_sub) >= 22:
                c_now = float(spy_sub.iloc[-1]["Close"])
                c_prev_1m = float(spy_sub.iloc[-22]["Close"])
                spy_1m = ((c_now - c_prev_1m) / c_prev_1m) * 100.0 if c_prev_1m > 0 else 0.0

        is_daily = (report_type.lower() == "daily")
        is_monthly = (report_type.lower() == "monthly")
        if is_daily:
            primary_win = "1D"
            primary_bench = spy_1d
            bench_label = f"SPY 1-Day ({spy_1d:+.2f}%)"
        elif is_monthly:
            primary_win = "1M"
            primary_bench = spy_1m
            bench_label = f"SPY 1-Month ({spy_1m:+.2f}%)"
        else:
            primary_win = "1W"
            primary_bench = spy_1w
            bench_label = f"SPY 1-Week ({spy_1w:+.2f}%)"

        theme_items_cfg = getattr(cfg.theme_etfs, "items", []) if hasattr(cfg, "theme_etfs") else []
        if not theme_items_cfg:
            return SectionResult(
                section_num=7,
                title="Theme & Industry Relative Strength",
                status="unavailable",
                error_message="Theme ETF configuration unavailable.",
            )

        raw_items: List[ThemeItem] = []

        for item_cfg in theme_items_cfg:
            sym = item_cfg.symbol
            df = bars.get(sym)

            if df is None or df.empty:
                # Mark as unavailable per Ground Rule 2
                raw_items.append(
                    ThemeItem(
                        symbol=sym,
                        name=item_cfg.name,
                        category=item_cfg.category,
                        close=0.0,
                        ret_1w=0.0,
                        ret_1m=0.0,
                        ret_3m=0.0,
                        rs_vs_spy=0.0,
                        rank=999,
                        rank_change=0,
                        dist_50dma_pct=0.0,
                        above_50dma=False,
                        is_available=False,
                    )
                )
                continue

            sub = df[df.index <= as_of_dt]
            if len(sub) < 10:
                raw_items.append(
                    ThemeItem(
                        symbol=sym,
                        name=item_cfg.name,
                        category=item_cfg.category,
                        close=0.0,
                        ret_1w=0.0,
                        ret_1m=0.0,
                        ret_3m=0.0,
                        rs_vs_spy=0.0,
                        rank=999,
                        rank_change=0,
                        dist_50dma_pct=0.0,
                        above_50dma=False,
                        is_available=False,
                    )
                )
                continue

            c_now = float(sub.iloc[-1]["Close"])
            # 1D (1 trading day ago)
            idx_1d = max(0, len(sub) - 2)
            c_1d = float(sub.iloc[idx_1d]["Close"])
            ret_1d = ((c_now - c_1d) / c_1d) * 100.0 if c_1d > 0 else 0.0

            # 1W (5 trading days ago)
            idx_1w = max(0, len(sub) - 6)
            c_1w = float(sub.iloc[idx_1w]["Close"])
            ret_1w = ((c_now - c_1w) / c_1w) * 100.0 if c_1w > 0 else 0.0

            # 1M (21 trading days ago)
            idx_1m = max(0, len(sub) - 22)
            c_1m = float(sub.iloc[idx_1m]["Close"])
            ret_1m = ((c_now - c_1m) / c_1m) * 100.0 if c_1m > 0 else 0.0

            # 3M (63 trading days ago)
            idx_3m = max(0, len(sub) - 64)
            c_3m = float(sub.iloc[idx_3m]["Close"])
            ret_3m = ((c_now - c_3m) / c_3m) * 100.0 if c_3m > 0 else 0.0

            # 50 DMA
            if len(sub) >= 50:
                dma_50 = float(sub["Close"].rolling(window=50).mean().iloc[-1])
                dist_50 = ((c_now - dma_50) / dma_50) * 100.0
                above_50 = c_now >= dma_50
            else:
                dist_50 = 0.0
                above_50 = False

            # RS vs SPY benchmark for primary window
            if is_daily:
                primary_ret = ret_1d
            elif is_monthly:
                primary_ret = ret_1m
            else:
                primary_ret = ret_1w
            rs_spy = primary_ret - primary_bench

            raw_items.append(
                ThemeItem(
                    symbol=sym,
                    name=item_cfg.name,
                    category=item_cfg.category,
                    close=c_now,
                    ret_1w=ret_1w,
                    ret_1m=ret_1m,
                    ret_3m=ret_3m,
                    rs_vs_spy=rs_spy,
                    rank=0,
                    rank_change=0,
                    dist_50dma_pct=dist_50,
                    above_50dma=above_50,
                    ret_1d=ret_1d,
                    is_available=True,
                )
            )

        # Sort available items by primary window return (1D for daily, 1M for monthly, 1W for weekly)
        available_items = [it for it in raw_items if it.is_available]
        unavailable_items = [it for it in raw_items if not it.is_available]

        if is_daily:
            available_items.sort(key=lambda x: x.ret_1d, reverse=True)
            for rank_idx, item in enumerate(available_items, 1):
                item.rank = rank_idx
            # Compare with 1W ranking for daily rank change
            items_by_1w = sorted(available_items, key=lambda x: x.ret_1w, reverse=True)
            prior_rank_map = {it.symbol: r for r, it in enumerate(items_by_1w, 1)}
            for it in available_items:
                prior_r = prior_rank_map.get(it.symbol, it.rank)
                it.rank_change = prior_r - it.rank
        elif is_monthly:
            available_items.sort(key=lambda x: x.ret_1m, reverse=True)
            for rank_idx, item in enumerate(available_items, 1):
                item.rank = rank_idx
            # Compare with 3M ranking for monthly rank change
            items_by_3m = sorted(available_items, key=lambda x: x.ret_3m, reverse=True)
            prior_rank_map = {it.symbol: r for r, it in enumerate(items_by_3m, 1)}
            for it in available_items:
                prior_r = prior_rank_map.get(it.symbol, it.rank)
                it.rank_change = prior_r - it.rank
        else:
            available_items.sort(key=lambda x: x.ret_1w, reverse=True)
            for rank_idx, item in enumerate(available_items, 1):
                item.rank = rank_idx
            # Compare with 1M ranking for weekly rank change
            items_by_1m = sorted(available_items, key=lambda x: x.ret_1m, reverse=True)
            prior_rank_map = {it.symbol: r for r, it in enumerate(items_by_1m, 1)}
            for it in available_items:
                prior_r = prior_rank_map.get(it.symbol, it.rank)
                it.rank_change = prior_r - it.rank

        final_items = available_items + unavailable_items

        if available_items:
            if is_daily:
                ret_fn = lambda it: it.ret_1d
                win_name = "1D"
            elif is_monthly:
                ret_fn = lambda it: it.ret_1m
                win_name = "1M"
            else:
                ret_fn = lambda it: it.ret_1w
                win_name = "1W"
            top_names = [f"{it.name} ({it.symbol}: {ret_fn(it):+.2f}%)" for it in available_items[:2]]
            lag_names = [f"{it.name} ({it.symbol}: {ret_fn(it):+.2f}%)" for it in available_items[-2:]]
            top_str = f"Leading Themes ({win_name}): {', '.join(top_names)} | Laggards: {', '.join(lag_names)}"
            commentary = (
                f"Thematic momentum ({win_name}) reflects outperformance in {available_items[0].name} ({available_items[0].symbol}: {available_items[0].rs_vs_spy:+.2f}% vs SPY), "
                f"while {available_items[-1].name} ({available_items[-1].symbol}: {available_items[-1].rs_vs_spy:+.2f}% vs SPY) underperformed benchmark equities."
            )
        else:
            top_str = ""
            commentary = "Theme ETF market data temporarily unavailable."

        data = ThemeRelativeStrengthData(
            as_of_date=as_of_date,
            spy_1w_return=spy_1w,
            items=final_items,
            top_theme_summary=top_str,
            commentary=commentary,
            primary_window=primary_win,
            primary_benchmark_return=primary_bench,
            primary_benchmark_label=bench_label,
            spy_1d_return=spy_1d,
        )

        return SectionResult(
            section_num=7,
            title="Theme & Industry Relative Strength",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building theme relative strength: %s", e)
        return SectionResult(
            section_num=7,
            title="Theme & Industry Relative Strength",
            status="unavailable",
            error_message=f"Theme relative strength error: {e}",
        )
