"""Section: Tactical Watchlist Panel (Stage 3, Task 3.2)."""

import csv
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd

from sections.base import SectionResult

logger = logging.getLogger(__name__)

# Default canonical sector map for major large-cap focus tickers
DEFAULT_TICKER_SECTOR_MAP: Dict[str, str] = {
    "AAPL": "Information Technology",
    "MSFT": "Information Technology",
    "NVDA": "Information Technology",
    "AMZN": "Consumer Discretionary",
    "GOOGL": "Communication Services",
    "META": "Communication Services",
    "TSLA": "Consumer Discretionary",
    "LLY": "Health Care",
    "AVGO": "Information Technology",
    "JPM": "Financials",
    "VRT": "Industrials",
    "NOW": "Information Technology",
    "AMD": "Information Technology",
    "NFLX": "Communication Services",
    "COST": "Consumer Staples",
}

DEFAULT_TICKER_NAME_MAP: Dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AMZN": "Amazon.com Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "LLY": "Eli Lilly and Company",
    "AVGO": "Broadcom Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "VRT": "Vertiv Holdings Co",
    "NOW": "ServiceNow Inc.",
    "AMD": "Advanced Micro Devices Inc.",
    "NFLX": "Netflix Inc.",
    "COST": "Costco Wholesale Corporation",
}

DEFAULT_WATCHLIST_TICKERS: List[str] = list(DEFAULT_TICKER_NAME_MAP.keys())


@dataclass
class WatchlistItem:
    """Individual stock setup and tactical indicators for a watchlist constituent."""
    ticker: str
    name: str = ""
    sector: str = ""
    close: float = 0.0
    dist_20dma_pct: Optional[float] = None
    dist_50dma_pct: Optional[float] = None
    dist_52w_high_pct: Optional[float] = None
    atr_pct: Optional[float] = None
    rs_vs_spy: Optional[float] = None
    next_earnings_date: str = "none within 30d"
    sector_breadth_status: str = "n/a"
    long_permitted: str = "BLOCKED (Gate Defensive)"
    readiness: str = "Not ready"
    is_available: bool = True
    notes: str = ""

    @property
    def symbol(self) -> str:
        return self.ticker


@dataclass
class WatchlistData:
    """Container for the Tactical Watchlist Panel section."""
    as_of_date: str
    gate_posture: str
    long_permitted_default: str
    items: List[WatchlistItem] = field(default_factory=list)
    total_count: int = 0
    blocked_count: int = 0
    selective_count: int = 0
    permitted_count: int = 0
    exception_count: int = 0
    csv_path: str = ""
    status_note: str = ""
    source_label: str = ""


def load_watchlist_tickers(csv_path: Union[str, Path] = "watchlist.csv") -> List[str]:
    """Read watchlist.csv dynamically supporting headers, plain lines, and CSV rows.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of uppercase ticker symbols without duplicates, preserving order.
    """
    path = Path(csv_path)
    if not path.is_file():
        logger.warning("Watchlist file '%s' not found.", path)
        return []

    tickers: List[str] = []
    seen = set()

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                for item in row:
                    item_clean = item.strip().strip("'\"")
                    if not item_clean or item_clean.startswith("#"):
                        continue
                    # Skip common CSV header keywords
                    if item_clean.lower() in ("ticker", "tickers", "symbol", "symbols"):
                        continue
                    sym = item_clean.upper()
                    if sym not in seen:
                        seen.add(sym)
                        tickers.append(sym)
    except Exception as e:
        logger.error("Error reading watchlist file '%s': %s", path, e)
        return []

    return tickers


def resolve_long_permitted(gate_posture: Union[str, Any]) -> str:
    """Map Swing-Trade Exposure Gate posture to execution directive string.

    Rules:
      - If Gate posture is DEFENSIVE -> "BLOCKED (Gate Defensive)"
      - If Gate posture is CAUTIOUS / SELECTIVE / REDUCED -> "SELECTIVE (Half Size)"
      - If Gate posture is OPEN / FULL -> "PERMITTED"
    """
    posture_str = ""
    if isinstance(gate_posture, str):
        posture_str = gate_posture
    elif hasattr(gate_posture, "posture"):
        posture_str = getattr(gate_posture, "posture", "")
    elif hasattr(gate_posture, "data") and hasattr(gate_posture.data, "posture"):
        posture_str = getattr(gate_posture.data, "posture", "")

    p_clean = posture_str.strip().upper()

    if any(k in p_clean for k in ("DEFENSIVE", "BLOCKED", "CLOSED", "SHUT")):
        return "BLOCKED (Gate Defensive)"
    elif any(k in p_clean for k in ("CAUTIOUS", "SELECTIVE", "REDUCED", "HALF")):
        return "SELECTIVE (Half Size)"
    elif any(k in p_clean for k in ("OPEN", "FULL", "PERMITTED")):
        return "PERMITTED"
    else:
        # Default safety fallback
        if "DEF" in p_clean:
            return "BLOCKED (Gate Defensive)"
        return "SELECTIVE (Half Size)"


def compute_atr_14(df: pd.DataFrame) -> Optional[float]:
    """Compute 14-period Average True Range (ATR) from OHLC price history."""
    if df is None or len(df) < 2:
        return None

    cols = {c.lower(): c for c in df.columns}
    h_col = cols.get("high")
    l_col = cols.get("low")
    c_col = cols.get("close")

    if not (h_col and l_col and c_col):
        if c_col:
            diff = df[c_col].diff().abs().dropna()
            return float(diff.tail(14).mean()) if not diff.empty else None
        return None

    high = df[h_col]
    low = df[l_col]
    prev_close = df[c_col].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).dropna()
    if tr.empty:
        return None

    window = min(14, len(tr))
    atr_val = float(tr.tail(window).mean())
    return atr_val


def build_watchlist_section(
    watchlist_path: Union[str, Path] = "watchlist.csv",
    bars: Optional[Dict[str, pd.DataFrame]] = None,
    equity_bars: Optional[Dict[str, pd.DataFrame]] = None,
    spy_df: Optional[pd.DataFrame] = None,
    calendar_provider: Optional[Any] = None,
    earnings_data: Optional[Any] = None,
    gate_posture: Union[str, Any] = "DEFENSIVE",
    sector_breadth_data: Optional[Any] = None,
    constituents: Optional[List[Any]] = None,
    ticker_infos: Optional[Dict[str, dict]] = None,
    as_of_date: Optional[str] = None,
    section_num: int = 14,
    cfg: Optional[Any] = None,
    market_net_new_highs: Optional[int] = None,
    custom_tickers: Optional[List[str]] = None,
    fallback_to_default: bool = True,
) -> SectionResult:
    """Build the Tactical Watchlist Panel section from watchlist.csv and market data.

    Args:
        watchlist_path: Path to watchlist CSV.
        bars: Core ETF and index price dataframes.
        equity_bars: Constituent equity price dataframes.
        spy_df: SPY benchmark dataframe for relative strength computation.
        calendar_provider: EconCalendarProvider for upcoming earnings dates.
        earnings_data: Precomputed EarningsLayerData or SectionResult.
        gate_posture: SwingGateData, string, or SectionResult determining long gate status.
        sector_breadth_data: SectorReportData, list of SectorBreadthItem, or dict of sector breadth.
        constituents: List of Constituent objects for sector and company name lookups.
        ticker_infos: Dictionary of yfinance info metadata per ticker.
        as_of_date: Evaluation date string (YYYY-MM-DD).
        section_num: Report section number.
        cfg: Optional application configuration.
        market_net_new_highs: Net new 52-week highs across the universe.
        custom_tickers: Optional list of ticker symbols passed directly (e.g. from CLI).

    Returns:
        SectionResult containing WatchlistData or unavailable status.
    """
    long_directive = resolve_long_permitted(gate_posture)
    posture_label = gate_posture if isinstance(gate_posture, str) else getattr(gate_posture, "posture", str(gate_posture))
    p_clean = posture_label.strip().upper()

    # 1. Read watchlist tickers dynamically
    if custom_tickers:
        tickers = [t.strip().upper() for t in custom_tickers if t.strip()]
        source_label = f"CLI specified ({len(tickers)} tickers)"
        status_note = f"Loaded {len(tickers)} watchlist focus candidates from CLI argument."
    else:
        raw_tickers = load_watchlist_tickers(watchlist_path)
        if not raw_tickers:
            if fallback_to_default:
                tickers = list(DEFAULT_TICKER_NAME_MAP.keys())
                source_label = "Default list (edit watchlist.csv to use your own)"
                status_note = "Loaded 15 default focus candidates (edit watchlist.csv to customize)."
            else:
                return SectionResult(
                    section_num=section_num,
                    title="Tactical Watchlist Panel",
                    status="unavailable",
                    error_message=f"Watchlist file '{watchlist_path}' not found or contains no valid tickers.",
                    data=WatchlistData(
                        as_of_date=as_of_date or "",
                        gate_posture=p_clean,
                        long_permitted_default=long_directive,
                        total_count=0,
                        csv_path=str(watchlist_path),
                        status_note=f"Watchlist file '{watchlist_path}' not found or contains no valid tickers.",
                        source_label="",
                    ),
                )
        else:
            tickers = raw_tickers
            source_label = f"Custom list ({len(tickers)} tickers from {Path(watchlist_path).name})"
            status_note = f"Loaded {len(tickers)} watchlist focus candidates from '{watchlist_path}'."

    # 2. Benchmark SPY dataframe resolution
    all_bars = {}
    if bars:
        all_bars.update(bars)
    if equity_bars:
        all_bars.update(equity_bars)

    if spy_df is None and "SPY" in all_bars:
        spy_df = all_bars["SPY"]

    # 3. Build sector breadth lookup table
    # Mapping: canonical sector name (lower) -> formatted status string, numeric % > 50dma, and net new highs
    sector_breadth_map: Dict[str, str] = {}
    sector_breadth_num_map: Dict[str, float] = {}
    sector_nnh_map: Dict[str, int] = {}
    if sector_breadth_data is not None:
        # Check if it's SectorReportData with .sector_breadth
        b_list = getattr(sector_breadth_data, "sector_breadth", None)
        if b_list is None and isinstance(sector_breadth_data, list):
            b_list = sector_breadth_data
        elif isinstance(sector_breadth_data, dict):
            for k, v in sector_breadth_data.items():
                if isinstance(v, (int, float)):
                    sector_breadth_map[k.lower()] = f"{float(v):.1f}% > 50-DMA"
                    sector_breadth_num_map[k.lower()] = float(v)
                else:
                    sector_breadth_map[k.lower()] = str(v)

        if b_list:
            for b_it in b_list:
                sec_name = getattr(b_it, "sector", "")
                p50 = getattr(b_it, "pct_above_50dma", None)
                nnh = getattr(b_it, "net_new_highs", None)
                if sec_name:
                    k_lower = sec_name.strip().lower()
                    if p50 is not None:
                        sector_breadth_map[k_lower] = f"{float(p50):.1f}% > 50-DMA"
                        sector_breadth_num_map[k_lower] = float(p50)
                    if nnh is not None:
                        sector_nnh_map[k_lower] = int(nnh)

    # 4. Build earnings schedule lookup table
    # Mapping: ticker -> next earnings date string
    earnings_map: Dict[str, str] = {}

    # Check calendar_provider scheduled earnings
    if calendar_provider is not None:
        if hasattr(calendar_provider, "_scheduled_earnings"):
            for ev in getattr(calendar_provider, "_scheduled_earnings", []):
                sym = ev.get("symbol")
                ev_date = ev.get("date")
                if sym and ev_date:
                    if as_of_date is None or ev_date >= as_of_date:
                        if sym not in earnings_map or ev_date < earnings_map[sym]:
                            earnings_map[sym] = ev_date

        if hasattr(calendar_provider, "get_upcoming_earnings"):
            try:
                start_query = as_of_date or "2026-01-01"
                # Query upcoming earnings for 90 days out
                end_dt = (pd.to_datetime(start_query) + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
                events = calendar_provider.get_upcoming_earnings(start_date=start_query, end_date=end_dt, symbols=tickers)
                for ev in events:
                    if ev.symbol and ev.date:
                        if ev.symbol not in earnings_map or ev.date < earnings_map[ev.symbol]:
                            earnings_map[ev.symbol] = ev.date
            except Exception as e:
                logger.debug("calendar_provider.get_upcoming_earnings lookup note: %s", e)

    # Check earnings_data if provided
    if earnings_data is not None:
        earn_obj = getattr(earnings_data, "data", earnings_data)
        upcoming_caps = getattr(earn_obj, "next_week_large_caps", [])
        for u_item in upcoming_caps:
            sym = getattr(u_item, "symbol", "")
            d_str = getattr(u_item, "date", "")
            if sym and d_str and sym not in earnings_map:
                earnings_map[sym] = d_str

    # 5. Build constituents metadata lookup table
    const_meta: Dict[str, Any] = {}
    if constituents:
        for c in constituents:
            sym = getattr(c, "symbol", "")
            if sym:
                const_meta[sym] = c

    # 6. Calculate SPY 3M benchmark return
    spy_3m_ret = 0.0
    as_of_dt = pd.to_datetime(as_of_date) if as_of_date else None
    if spy_df is not None and not spy_df.empty:
        spy_sub = spy_df[spy_df.index <= as_of_dt] if as_of_dt is not None else spy_df
        if not spy_sub.empty:
            cols = {c.lower(): c for c in spy_sub.columns}
            c_col = cols.get("close")
            if c_col:
                spy_now = float(spy_sub[c_col].iloc[-1])
                spy_idx_3m = max(0, len(spy_sub) - 64)
                spy_base = float(spy_sub[c_col].iloc[spy_idx_3m])
                if spy_base > 0:
                    spy_3m_ret = ((spy_now - spy_base) / spy_base) * 100.0

    # 7. Evaluate each watchlist ticker
    items: List[WatchlistItem] = []

    for sym in tickers:
        df = all_bars.get(sym)
        c_item = const_meta.get(sym)
        t_info = ticker_infos.get(sym, {}) if ticker_infos else {}

        # Company name
        name = (
            getattr(c_item, "name", None)
            or t_info.get("shortName")
            or t_info.get("longName")
            or DEFAULT_TICKER_NAME_MAP.get(sym, sym)
        )

        # Sector
        sector = (
            getattr(c_item, "sector", None)
            or t_info.get("sector")
            or DEFAULT_TICKER_SECTOR_MAP.get(sym, "General")
        )

        # Sector breadth status and metrics
        sec_breadth_str = "n/a"
        sec_breadth_num: Optional[float] = None
        sec_nnh_num: Optional[int] = None
        if sector:
            for k, v in sector_breadth_map.items():
                if k in sector.lower() or sector.lower() in k:
                    sec_breadth_str = v
                    sec_breadth_num = sector_breadth_num_map.get(k)
                    sec_nnh_num = sector_nnh_map.get(k)
                    break

        # Next earnings date formatting:
        # Show date if known (e.g. 2026-11-06);
        # "none within 30d" if calendar checked and no earnings within 30 days;
        # "n/a (source unavailable)" only when calendar source failed.
        next_earn = earnings_map.get(sym)
        if not next_earn and t_info:
            raw_ed = t_info.get("earningsDate") or t_info.get("nextEarningsDate")
            if isinstance(raw_ed, (list, tuple)) and raw_ed:
                raw_ed = raw_ed[0]
            if raw_ed:
                try:
                    next_earn = pd.to_datetime(raw_ed).strftime("%Y-%m-%d")
                except Exception:
                    pass

        if next_earn:
            earn_display = next_earn
        elif calendar_provider is not None:
            earn_display = "none within 30d"
        else:
            earn_display = "n/a (source unavailable)"

        # If price dataframe is missing or empty
        if df is None or df.empty:
            items.append(
                WatchlistItem(
                    ticker=sym,
                    name=name,
                    sector=sector,
                    close=0.0,
                    dist_20dma_pct=None,
                    dist_50dma_pct=None,
                    dist_52w_high_pct=None,
                    atr_pct=None,
                    rs_vs_spy=None,
                    next_earnings_date=earn_display,
                    sector_breadth_status=sec_breadth_str,
                    long_permitted=long_directive,
                    readiness="Not ready",
                    is_available=False,
                    notes="Price series data unavailable in bar cache.",
                )
            )
            continue

        # Slice up to as_of_date if specified
        sub = df[df.index <= as_of_dt] if as_of_dt is not None else df
        if sub.empty:
            items.append(
                WatchlistItem(
                    ticker=sym,
                    name=name,
                    sector=sector,
                    close=0.0,
                    dist_20dma_pct=None,
                    dist_50dma_pct=None,
                    dist_52w_high_pct=None,
                    atr_pct=None,
                    rs_vs_spy=None,
                    next_earnings_date=earn_display,
                    sector_breadth_status=sec_breadth_str,
                    long_permitted=long_directive,
                    readiness="Not ready",
                    is_available=False,
                    notes=f"No price history prior to as_of_date {as_of_date}.",
                )
            )
            continue

        cols = {c.lower(): c for c in sub.columns}
        c_col = cols.get("close")
        if not c_col:
            items.append(
                WatchlistItem(
                    ticker=sym,
                    name=name,
                    sector=sector,
                    close=0.0,
                    dist_20dma_pct=None,
                    dist_50dma_pct=None,
                    dist_52w_high_pct=None,
                    atr_pct=None,
                    rs_vs_spy=None,
                    next_earnings_date=earn_display,
                    sector_breadth_status=sec_breadth_str,
                    long_permitted=long_directive,
                    readiness="Not ready",
                    is_available=False,
                    notes="Missing Close column in price dataframe.",
                )
            )
            continue

        close_val = float(sub[c_col].iloc[-1])

        # Distance to 20-DMA
        dist_20: Optional[float] = None
        if len(sub) >= 20:
            dma20 = float(sub[c_col].rolling(20).mean().iloc[-1])
            if dma20 > 0:
                dist_20 = round(((close_val - dma20) / dma20) * 100.0, 2)

        # Distance to 50-DMA
        dist_50: Optional[float] = None
        if len(sub) >= 50:
            dma50 = float(sub[c_col].rolling(50).mean().iloc[-1])
            if dma50 > 0:
                dist_50 = round(((close_val - dma50) / dma50) * 100.0, 2)
        elif len(sub) >= 20:
            # Fallback if history is between 20 and 50 bars
            dma_est = float(sub[c_col].mean())
            if dma_est > 0:
                dist_50 = round(((close_val - dma_est) / dma_est) * 100.0, 2)

        # 52-week high distance
        sub_252 = sub.tail(252)
        h_col_name = next((c for c in sub_252.columns if c.lower() == "high"), None)
        h_max = float(sub_252[h_col_name].max()) if h_col_name else float(sub_252[c_col].max())
        dist_52w: Optional[float] = None
        if h_max > 0:
            dist_52w = round(((close_val - h_max) / h_max) * 100.0, 2)

        # 14-day ATR as percentage of close: (ATR_14 / close) * 100
        atr_pct: Optional[float] = None
        atr_val = compute_atr_14(sub)
        if atr_val is not None and close_val > 0:
            atr_pct = round((atr_val / close_val) * 100.0, 2)

        # Relative strength vs SPY over 3M
        rs_vs_spy: Optional[float] = None
        idx_3m = max(0, len(sub) - 64)
        c_3m = float(sub[c_col].iloc[idx_3m])
        if c_3m > 0:
            stock_3m_ret = ((close_val - c_3m) / c_3m) * 100.0
            rs_vs_spy = round(stock_3m_ret - spy_3m_ret, 2)

        # Readiness if gate opens (values: Ready / Watch / Not ready)
        # Evaluated from 4 technical criteria:
        # 1. Above 20-DMA and 50-DMA
        # 2. RS vs SPY (3M) > 0
        # 3. Sector breadth > 50%
        # 4. ATR% within limits (<= 5.0%)
        crit_ma = bool(dist_20 is not None and dist_20 > 0 and dist_50 is not None and dist_50 > 0)
        crit_rs = bool(rs_vs_spy is not None and rs_vs_spy > 0)
        crit_breadth = bool(sec_breadth_num is not None and sec_breadth_num > 50.0)
        crit_atr = bool(atr_pct is not None and atr_pct <= 5.0)

        readiness_score = sum([crit_ma, crit_rs, crit_breadth, crit_atr])
        if readiness_score == 4:
            readiness_val = "Ready"
        elif readiness_score >= 2:
            readiness_val = "Watch"
        else:
            readiness_val = "Not ready"

        # Defensive Exception candidate evaluation (Stage 3: 3.2)
        # When gate is DEFENSIVE, apply the same exception rules used in Section 8:
        # a. Sector 50-DMA breadth >= 70.0%
        # b. Sector net new highs > 0 (or market net new highs > 0)
        # c. Stock price above 50-DMA
        # d. Stock price within 10% of 52-week high
        is_defensive_gate = any(k in p_clean for k in ("DEFENSIVE", "BLOCKED", "CLOSED", "SHUT"))
        is_exception = False
        if is_defensive_gate:
            cond_a = (sec_breadth_num is not None and sec_breadth_num >= 70.0)
            cond_b = ((sec_nnh_num is not None and sec_nnh_num > 0) or (market_net_new_highs is not None and market_net_new_highs > 0))
            cond_c = (dist_50 is not None and dist_50 > 0.0)
            cond_d = (dist_52w is not None and dist_52w >= -10.0)
            if cond_a and cond_b and cond_c and cond_d:
                is_exception = True

        item_long_permitted = "Exception candidate (gate Defensive)" if is_exception else long_directive

        items.append(
            WatchlistItem(
                ticker=sym,
                name=name,
                sector=sector,
                close=close_val,
                dist_20dma_pct=dist_20,
                dist_50dma_pct=dist_50,
                dist_52w_high_pct=dist_52w,
                atr_pct=atr_pct,
                rs_vs_spy=rs_vs_spy,
                next_earnings_date=earn_display,
                sector_breadth_status=sec_breadth_str,
                long_permitted=item_long_permitted,
                readiness=readiness_val,
                is_available=True,
                notes="",
            )
        )

    # 8. Sort watchlist items by 3M Relative Strength vs SPY descending (strongest leaders first)
    items.sort(
        key=lambda x: (
            x.rs_vs_spy is None,
            -(x.rs_vs_spy if x.rs_vs_spy is not None else 0.0),
            x.ticker,
        )
    )

    # 9. Compute aggregate summary metrics
    total_c = len(items)
    blocked_c = sum(1 for it in items if "BLOCKED" in it.long_permitted)
    selective_c = sum(1 for it in items if "SELECTIVE" in it.long_permitted)
    permitted_c = sum(1 for it in items if "PERMITTED" in it.long_permitted)
    exception_c = sum(1 for it in items if "Exception candidate" in it.long_permitted)

    data = WatchlistData(
        as_of_date=as_of_date or "",
        gate_posture=posture_label,
        long_permitted_default=long_directive,
        items=items,
        total_count=total_c,
        blocked_count=blocked_c,
        selective_count=selective_c,
        permitted_count=permitted_c,
        exception_count=exception_c,
        csv_path=str(watchlist_path),
        status_note=status_note,
        source_label=source_label,
    )

    return SectionResult(
        section_num=section_num,
        title="Tactical Watchlist Panel",
        status="available",
        data=data,
        error_message=None,
    )
