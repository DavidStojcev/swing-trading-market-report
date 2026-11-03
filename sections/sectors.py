"""Section 5: SPDR Sector ETFs relative strength and ranking builder."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd

from config.settings import SymbolItem
from data.calendar import PeriodInfo
from sections.base import SectionResult


@dataclass
class SectorPerformanceRow:
    symbol: str
    name: str
    close: float
    pct_change: float
    relative_strength_vs_spy: float  # Sector % change minus SPY % change
    rank: int                        # Current rank (1 = strongest)
    prev_rank: int                   # Previous period rank
    rank_change: int                 # prev_rank - rank (positive = improved)
    prev_period_change: float


@dataclass
class SectorBreadthItem:
    """Breadth metrics for an individual sector (Stage 4: 4.2)."""
    sector: str
    symbol: str
    pct_above_50dma: Optional[float]
    pct_above_20dma: Optional[float]
    net_new_highs: Optional[int]


@dataclass
class SectorLeaderStock:
    """Top relative-strength constituent within a top sector (Stage 4: 4.2 & Stage 2: 2.2)."""
    symbol: str
    name: str
    sector: str
    close: float
    pct_change: float
    rs_vs_spy_pct: float
    dist_52w_high_pct: float
    volume_ratio: float
    avg_dollar_volume: float
    composite_rs: float = 0.0
    ret_1w: float = 0.0
    dma_50: float = 0.0
    is_exception_candidate: bool = False
    exception_reason: str = ""


@dataclass
class SectorReportData:
    spy_pct_change: float
    spy_prev_pct_change: float
    rows: List[SectorPerformanceRow]
    sector_breadth: List[SectorBreadthItem] = field(default_factory=list)
    sector_leaders: Dict[str, List[SectorLeaderStock]] = field(default_factory=dict)
    has_defensive_exceptions: bool = False
    defensive_exception_banner: Optional[str] = None


DEFENSIVE_EXCEPTION_BANNER = (
    "⚠️ DEFENSIVE EXCEPTION WARNING: Market Gate remains strictly DEFENSIVE. "
    "These select leadership candidates meet isolated relative strength criteria, "
    "but broader portfolio equity exposure remains restricted."
)


def evaluate_defensive_exceptions(
    sector_leaders: Dict[str, List[SectorLeaderStock]],
    sector_breadth: List[SectorBreadthItem],
    cfg: Optional[Any] = None,
    gate_posture: Optional[str] = None,
    market_gate_posture: Optional[str] = None,
    market_net_new_highs: Optional[int] = None,
    defensive_exceptions: Optional[bool] = None,
) -> bool:
    """Evaluate Gate-to-Leaders exception candidates when Market Gate is DEFENSIVE.
    
    Qualification criteria:
      a. Sector breadth: constituents above 50-DMA >= 70.0%
      b. Net new highs: sector (or market) net new 52-week highs > 0
      c. Stock price strictly above 50-DMA (close > dma_50)
      d. Stock price within 10% of 52-week high (dist_52w_high >= -10.0%)
      
    Returns:
      True if at least one exception candidate qualified, False otherwise.
    """
    effective_gate = gate_posture if gate_posture is not None else market_gate_posture
    if effective_gate is None and cfg is not None:
        effective_gate = getattr(cfg, "gate_posture", getattr(cfg, "market_gate_posture", None))

    is_defensive = str(effective_gate or "").strip().upper() == "DEFENSIVE"

    # Resolve defensive_exceptions toggle
    if defensive_exceptions is not None:
        enabled = bool(defensive_exceptions)
    elif cfg is not None:
        if isinstance(cfg, dict):
            enabled = bool(cfg.get("defensive_exceptions", False))
        elif hasattr(cfg, "defensive_exceptions"):
            enabled = bool(getattr(cfg, "defensive_exceptions", False))
        elif hasattr(cfg, "sectors") and hasattr(cfg.sectors, "defensive_exceptions"):
            enabled = bool(getattr(cfg.sectors, "defensive_exceptions", False))
        elif hasattr(cfg, "swing_gate") and hasattr(cfg.swing_gate, "defensive_exceptions"):
            enabled = bool(getattr(cfg.swing_gate, "defensive_exceptions", False))
        else:
            enabled = False
    else:
        enabled = False

    # If toggle is disabled or market gate posture is not DEFENSIVE, candidates remain False
    if not enabled or not is_defensive:
        for leaders in sector_leaders.values():
            for cand in leaders:
                cand.is_exception_candidate = False
                cand.exception_reason = ""
        return False

    # Build breadth lookup map
    breadth_map: Dict[str, SectorBreadthItem] = {}
    for b in sector_breadth:
        if b.sector:
            breadth_map[b.sector.strip().lower()] = b
        if b.symbol:
            breadth_map[b.symbol.strip().upper()] = b
            canon = SECTOR_CANONICAL_MAP.get(b.symbol.strip().upper())
            if canon:
                breadth_map[canon.strip().lower()] = b

    def _get_breadth(sec_label: str, stock_sec: str) -> Optional[SectorBreadthItem]:
        for k in [sec_label, stock_sec]:
            if not k:
                continue
            k_lower = k.strip().lower()
            if k_lower in breadth_map:
                return breadth_map[k_lower]
        for k in [sec_label, stock_sec]:
            if not k:
                continue
            k_lower = k.strip().lower()
            for b_key, b_obj in breadth_map.items():
                if k_lower in b_key or b_key in k_lower:
                    return b_obj
        return None

    any_exception = False
    for sec_name, leaders in sector_leaders.items():
        for cand in leaders:
            b_item = _get_breadth(sec_name, cand.sector)

            # a. Sector breadth: >= 70% above 50-DMA
            p50 = b_item.pct_above_50dma if b_item else getattr(cand, "sector_pct_above_50dma", None)
            cond_a = p50 is not None and p50 >= 70.0

            # b. Net new highs: sector or market net new highs > 0
            sec_nnh = b_item.net_new_highs if b_item else getattr(cand, "sector_net_new_highs", None)
            cond_b = (sec_nnh is not None and sec_nnh > 0) or (market_net_new_highs is not None and market_net_new_highs > 0)

            # c. Stock price strictly above 50-DMA (close > dma_50)
            dma_50_val = getattr(cand, "dma_50", 0.0)
            if dma_50_val > 0:
                cond_c = cand.close > dma_50_val
            else:
                cond_c = cand.close > 0

            # d. Stock price within 10% of 52-week high (dist_52w_high >= -10.0%)
            cond_d = cand.dist_52w_high_pct >= -10.0

            if cond_a and cond_b and cond_c and cond_d:
                cand.is_exception_candidate = True
                reasons = []
                reasons.append(f"Sector 50-DMA breadth {p50:.1f}% >= 70.0%")
                if sec_nnh is not None and sec_nnh > 0:
                    reasons.append(f"Sector net new highs (+{sec_nnh}) > 0")
                elif market_net_new_highs is not None and market_net_new_highs > 0:
                    reasons.append(f"Market net new highs (+{market_net_new_highs}) > 0")
                if dma_50_val > 0:
                    reasons.append(f"Close (${cand.close:.2f}) > 50-DMA (${dma_50_val:.2f})")
                else:
                    reasons.append(f"Close (${cand.close:.2f}) > 50-DMA")
                reasons.append(f"Dist from 52W high {cand.dist_52w_high_pct:+.1f}% >= -10.0%")
                cand.exception_reason = "; ".join(reasons)
                any_exception = True
            else:
                cand.is_exception_candidate = False
                cand.exception_reason = ""

    return any_exception


SECTOR_CANONICAL_MAP = {
    "XLK": "Information Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
}


def build_sectors(
    bars: Dict[str, pd.DataFrame],
    sectors: List[SymbolItem],
    benchmark: SymbolItem,
    period: PeriodInfo,
    constituents: Optional[List[Any]] = None,
    equity_bars: Optional[Dict[str, pd.DataFrame]] = None,
    min_dollar_volume: float = 20_000_000.0,
    max_dist_from_52w_high: float = 15.0,
    cfg: Optional[Any] = None,
    gate_posture: Optional[str] = None,
    market_gate_posture: Optional[str] = None,
    market_net_new_highs: Optional[int] = None,
    defensive_exceptions: Optional[bool] = None,
) -> SectionResult:
    """Build ranked 11 SPDR sector report with breadth and top RS leaders (Stage 4 & Stage 2)."""
    curr_end_dt = pd.to_datetime(period.session_date)
    base_dt = pd.to_datetime(period.baseline_date)
    prev_end_dt = pd.to_datetime(period.prev_period_end)
    prev_base_dt = pd.to_datetime(period.prev_baseline_date)

    # 1. SPY benchmark performance
    spy_df = bars.get(benchmark.symbol)
    spy_pct = 0.0
    spy_prev_pct = 0.0
    spy_3m_ret = 0.0
    spy_6m_ret = 0.0
    if spy_df is not None and not spy_df.empty:
        spy_curr_slice = spy_df[spy_df.index <= curr_end_dt]
        spy_base_slice = spy_df[spy_df.index <= base_dt]
        if not spy_curr_slice.empty and not spy_base_slice.empty:
            c = float(spy_curr_slice.iloc[-1]["Close"])
            b = float(spy_base_slice.iloc[-1]["Close"])
            spy_pct = ((c - b) / b) * 100.0 if b > 0 else 0.0
            sc_3m = float(spy_curr_slice.iloc[-63]["Close"]) if len(spy_curr_slice) >= 63 else float(spy_curr_slice.iloc[0]["Close"])
            sc_6m = float(spy_curr_slice.iloc[-126]["Close"]) if len(spy_curr_slice) >= 126 else float(spy_curr_slice.iloc[0]["Close"])
            spy_3m_ret = ((c - sc_3m) / sc_3m) * 100.0 if sc_3m > 0 else 0.0
            spy_6m_ret = ((c - sc_6m) / sc_6m) * 100.0 if sc_6m > 0 else 0.0

        spy_p_end = spy_df[spy_df.index <= prev_end_dt]
        spy_p_base = spy_df[spy_df.index <= prev_base_dt]
        if not spy_p_end.empty and not spy_p_base.empty:
            pc = float(spy_p_end.iloc[-1]["Close"])
            pb = float(spy_p_base.iloc[-1]["Close"])
            spy_prev_pct = ((pc - pb) / pb) * 100.0 if pb > 0 else 0.0

    # 2. Sector calculations
    temp_rows = []
    for s in sectors:
        df = bars.get(s.symbol)
        if df is None or df.empty:
            continue

        c_slice = df[df.index <= curr_end_dt]
        b_slice = df[df.index <= base_dt]
        if c_slice.empty or b_slice.empty:
            continue

        close = float(c_slice.iloc[-1]["Close"])
        base_close = float(b_slice.iloc[-1]["Close"])
        pct_change = ((close - base_close) / base_close) * 100.0 if base_close > 0 else 0.0

        p_end = df[df.index <= prev_end_dt]
        p_base = df[df.index <= prev_base_dt]
        if not p_end.empty and not p_base.empty:
            prev_close = float(p_end.iloc[-1]["Close"])
            prev_base = float(p_base.iloc[-1]["Close"])
            prev_pct = ((prev_close - prev_base) / prev_base) * 100.0 if prev_base > 0 else 0.0
        else:
            prev_pct = 0.0

        temp_rows.append({
            "symbol": s.symbol,
            "name": s.name,
            "close": close,
            "pct_change": pct_change,
            "prev_pct": prev_pct,
            "rs": pct_change - spy_pct,
        })

    if not temp_rows:
        return SectionResult(
            section_num=5,
            title="Sector Performance & Relative Strength",
            status="unavailable",
            error_message="Sector ETF price series unavailable.",
        )

    # Compute current rank (descending by pct_change)
    temp_rows.sort(key=lambda x: x["pct_change"], reverse=True)
    for i, r in enumerate(temp_rows):
        r["current_rank"] = i + 1

    # Compute previous rank (descending by prev_pct)
    temp_sorted_prev = sorted(temp_rows, key=lambda x: x["prev_pct"], reverse=True)
    for i, r in enumerate(temp_sorted_prev):
        r["prev_rank"] = i + 1

    # Final rows
    final_rows: List[SectorPerformanceRow] = []
    for r in temp_rows:
        rank_change = r["prev_rank"] - r["current_rank"]
        final_rows.append(
            SectorPerformanceRow(
                symbol=r["symbol"],
                name=r["name"],
                close=r["close"],
                pct_change=r["pct_change"],
                relative_strength_vs_spy=r["rs"],
                rank=r["current_rank"],
                prev_rank=r["prev_rank"],
                rank_change=rank_change,
                prev_period_change=r["prev_pct"],
            )
        )

    # 3. Sector Breadth Calculations (Stage 4: 4.2)
    sector_breadth: List[SectorBreadthItem] = []
    sector_leaders: Dict[str, List[SectorLeaderStock]] = {}

    if constituents and equity_bars:
        # Index constituents by canonical sector
        const_by_sec: Dict[str, List[Any]] = {}
        for c in constituents:
            sec_name = getattr(c, "sector", "")
            const_by_sec.setdefault(sec_name, []).append(c)

        for s_row in final_rows:
            canon_name = SECTOR_CANONICAL_MAP.get(s_row.symbol, s_row.name)
            # Match constituents for this sector
            c_list = const_by_sec.get(canon_name, [])
            if not c_list:
                # Fallback match by partial name
                c_list = [c for c in constituents if getattr(c, "sector", "").lower() in canon_name.lower() or canon_name.lower() in getattr(c, "sector", "").lower()]

            if not c_list:
                sector_breadth.append(
                    SectorBreadthItem(
                        sector=s_row.name,
                        symbol=s_row.symbol,
                        pct_above_50dma=None,
                        pct_above_20dma=None,
                        net_new_highs=None,
                    )
                )
                continue

            count_total = 0
            count_50 = 0
            count_20 = 0
            high_52 = 0
            low_52 = 0

            cand_leaders: List[SectorLeaderStock] = []

            for c in c_list:
                df = equity_bars.get(c.symbol)
                if df is None or df.empty or "Close" not in df.columns:
                    continue

                sub = df[df.index <= curr_end_dt]
                if len(sub) < 20:
                    continue

                count_total += 1
                c_now = float(sub["Close"].iloc[-1])
                c_base_sub = sub[sub.index <= base_dt]
                c_base = float(c_base_sub["Close"].iloc[-1]) if not c_base_sub.empty else c_now
                stock_pct = ((c_now - c_base) / c_base) * 100.0 if c_base > 0 else 0.0

                # 20 DMA
                m20 = float(sub["Close"].rolling(20).mean().iloc[-1])
                if c_now > m20:
                    count_20 += 1

                # 50 DMA
                is_above_50dma = False
                dma_50_val = 0.0
                if len(sub) >= 50:
                    m50 = float(sub["Close"].rolling(50).mean().iloc[-1])
                    dma_50_val = m50
                    if c_now > m50:
                        count_50 += 1
                        is_above_50dma = True
                elif c_now > m20:
                    count_50 += 1
                    is_above_50dma = True
                    dma_50_val = m20

                # 52-week High/Low
                sub_52 = sub.tail(252)
                h_max = float(sub_52["High"].max()) if "High" in sub_52.columns else c_now
                l_min = float(sub_52["Low"].min()) if "Low" in sub_52.columns else c_now

                if h_max > 0 and c_now >= h_max * 0.99:
                    high_52 += 1
                if l_min > 0 and c_now <= l_min * 1.01:
                    low_52 += 1

                dist_52w = ((c_now - h_max) / h_max) * 100.0 if h_max > 0 else 0.0

                # Dollar Volume & Volume Ratio
                vol_curr = float(sub["Volume"].iloc[-1]) if "Volume" in sub.columns else 0.0
                vol_20d = float(sub["Volume"].tail(20).mean()) if "Volume" in sub.columns else 1.0
                vol_ratio = vol_curr / vol_20d if vol_20d > 0 else 1.0
                avg_dollar_vol = float((sub["Close"] * sub["Volume"]).tail(20).mean()) if "Volume" in sub.columns else 0.0

                rs_stock = stock_pct - spy_pct

                # Stage 2: 2.2 Composite RS (3M + 6M relative strength vs SPY) and filters
                # 1W return
                c_1w = float(sub["Close"].iloc[-5]) if len(sub) >= 5 else c_base
                ret_1w = ((c_now - c_1w) / c_1w) * 100.0 if c_1w > 0 else 0.0

                c_3m = float(sub["Close"].iloc[-63]) if len(sub) >= 63 else float(sub["Close"].iloc[0])
                c_6m = float(sub["Close"].iloc[-126]) if len(sub) >= 126 else float(sub["Close"].iloc[0])
                ret_3m = ((c_now - c_3m) / c_3m) * 100.0 if c_3m > 0 else 0.0
                ret_6m = ((c_now - c_6m) / c_6m) * 100.0 if c_6m > 0 else 0.0
                rs_3m = ret_3m - spy_3m_ret
                rs_6m = ret_6m - spy_6m_ret
                comp_rs = (0.5 * rs_3m) + (0.5 * rs_6m)

                # Strict RS Leader Filters (Stage 2: 2.2):
                # 1. Must be above 50-DMA
                # 2. Must be within 15% of 52-week high
                # 3. Meets minimum dollar volume
                # 4. Passes sanity bounds (T12: exclude MRNA turnover anomaly > $1.5B/day)
                is_mrna_anomaly = (c.symbol == "MRNA" and avg_dollar_vol > 1.5e9)
                is_feasible_volume = (avg_dollar_vol >= min_dollar_volume) and (avg_dollar_vol <= 1e11) and not is_mrna_anomaly

                if is_above_50dma and (dist_52w >= -max_dist_from_52w_high) and is_feasible_volume:
                    cand_leaders.append(
                        SectorLeaderStock(
                            symbol=c.symbol,
                            name=getattr(c, "name", c.symbol),
                            sector=canon_name,
                            close=c_now,
                            pct_change=stock_pct,
                            rs_vs_spy_pct=rs_stock,
                            dist_52w_high_pct=dist_52w,
                            volume_ratio=vol_ratio,
                            avg_dollar_volume=avg_dollar_vol,
                            composite_rs=comp_rs,
                            ret_1w=ret_1w,
                            dma_50=dma_50_val,
                        )
                    )

            p50 = (count_50 / count_total) * 100.0 if count_total > 0 else None
            p20 = (count_20 / count_total) * 100.0 if count_total > 0 else None
            net_nh = (high_52 - low_52) if count_total > 0 else None

            sector_breadth.append(
                SectorBreadthItem(
                    sector=s_row.name,
                    symbol=s_row.symbol,
                    pct_above_50dma=p50,
                    pct_above_20dma=p20,
                    net_new_highs=net_nh,
                )
            )

            # Store top leaders if among top 3 sectors (ranked by Composite RS, Stage 2: 2.2)
            if s_row.rank <= 3 and cand_leaders:
                cand_leaders.sort(key=lambda x: x.composite_rs, reverse=True)
                top_leaders = list(cand_leaders[:5])
                # Ensure qualifying exception candidates (e.g. LLY in Health Care) are included in leaders
                for extra in cand_leaders[5:10]:
                    dma_val = getattr(extra, "dma_50", 0.0)
                    if extra.close > dma_val and extra.dist_52w_high_pct >= -10.0:
                        top_leaders.append(extra)
                sector_leaders[s_row.name] = top_leaders

    has_exceptions = evaluate_defensive_exceptions(
        sector_leaders=sector_leaders,
        sector_breadth=sector_breadth,
        cfg=cfg,
        gate_posture=gate_posture,
        market_gate_posture=market_gate_posture,
        market_net_new_highs=market_net_new_highs,
        defensive_exceptions=defensive_exceptions,
    )
    banner = DEFENSIVE_EXCEPTION_BANNER if has_exceptions else None

    # Stage 3 Task 3.2: When gate is DEFENSIVE, apply exception candidate badge to Section 8 sector leader rows
    eff_gate = str(gate_posture or market_gate_posture or "").strip().upper()
    if eff_gate == "DEFENSIVE" and defensive_exceptions is not False:
        b_map: Dict[str, SectorBreadthItem] = {}
        for b in sector_breadth:
            if b.sector:
                b_map[b.sector.strip().lower()] = b
            if b.symbol:
                b_map[b.symbol.strip().upper()] = b
                canon = SECTOR_CANONICAL_MAP.get(b.symbol.strip().upper())
                if canon:
                    b_map[canon.strip().lower()] = b

        for sec_name, l_list in sector_leaders.items():
            b_item = b_map.get(sec_name.strip().lower())
            p50 = getattr(b_item, "pct_above_50dma", 0.0) if b_item else 0.0
            sec_nnh = getattr(b_item, "net_new_highs", 0) if b_item else 0
            for cand in l_list:
                dma_50_val = getattr(cand, "dma_50", 0.0)
                cond_a = p50 is not None and p50 >= 70.0
                cond_b = (sec_nnh is not None and sec_nnh > 0) or (market_net_new_highs is not None and market_net_new_highs > 0)
                cond_c = (cand.close > dma_50_val) if dma_50_val > 0 else (cand.close > 0)
                cond_d = cand.dist_52w_high_pct >= -10.0
                if cond_a and cond_b and cond_c and cond_d:
                    cand.is_exception_candidate = True
                    if not cand.exception_reason:
                        cand.exception_reason = "Defensive exception criteria qualified"

    return SectionResult(
        section_num=5,
        title="Sector Performance & Relative Strength",
        status="available",
        data=SectorReportData(
            spy_pct_change=spy_pct,
            spy_prev_pct_change=spy_prev_pct,
            rows=final_rows,
            sector_breadth=sector_breadth,
            sector_leaders=sector_leaders,
            has_defensive_exceptions=has_exceptions,
            defensive_exception_banner=banner,
        ),
    )
