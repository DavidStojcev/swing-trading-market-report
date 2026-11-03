"""Section 2: Index Snapshot builder."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from config.settings import SymbolItem
from data.calendar import PeriodInfo
from sections.base import SectionResult


@dataclass
class IndexSnapshotRow:
    symbol: str
    name: str
    close: float
    pct_change: float
    volume: float
    avg_volume_20d: float
    volume_ratio: float           # Volume / 20d avg numeric
    volume_ratio_display: str     # Formatted display string (e.g. "1.15x", "1.13x (QQQ)", "n/a")
    prev_period_change: float     # Return in previous period
    delta_vs_prev_period: float   # Current % return minus previous % return
    is_proxy_volume: bool = False
    proxy_symbol: Optional[str] = None


@dataclass
class IndexSnapshotData:
    rows: List[IndexSnapshotRow]
    valuation: Optional[Any] = None


def build_index_snapshot(
    bars: Dict[str, pd.DataFrame],
    index_symbols: List[SymbolItem],
    period: PeriodInfo,
) -> SectionResult:
    """Build index snapshot table across major US benchmarks.
    
    Ensures volume metrics are verified:
    - If an index volume is zero, constant, or identical to another index, shows 'n/a'.
    - Uses the liquid ETF proxy (QQQ) for Nasdaq-100 (^NDX) volume and labels it explicitly.
    """
    rows: List[IndexSnapshotRow] = []

    curr_end_dt = pd.to_datetime(period.session_date)
    base_dt = pd.to_datetime(period.baseline_date)
    prev_end_dt = pd.to_datetime(period.prev_period_end)
    prev_base_dt = pd.to_datetime(period.prev_baseline_date)
    period_start_dt = pd.to_datetime(period.current_start)

    # Pre-scan raw volume series across all indices to detect duplicate series across indices
    native_volumes: Dict[str, List[float]] = {}
    duplicate_symbols = set()
    for item in index_symbols:
        df_sym = bars.get(item.symbol)
        if df_sym is not None and not df_sym.empty and "Volume" in df_sym.columns:
            s_v = df_sym[df_sym.index <= curr_end_dt]["Volume"].replace(0, np.nan).dropna()
            v_list = list(s_v.tail(10))
            if len(v_list) >= 3:
                for other_sym, other_v in native_volumes.items():
                    if other_v == v_list:
                        if item.symbol in ("^NDX", "NDX") and "QQQ" in bars:
                            duplicate_symbols.add(other_sym)
                        elif other_sym in ("^NDX", "NDX") and "QQQ" in bars:
                            duplicate_symbols.add(item.symbol)
                        else:
                            duplicate_symbols.add(item.symbol)
                native_volumes[item.symbol] = v_list

    for item in index_symbols:
        df = bars.get(item.symbol)
        if df is None or df.empty:
            continue

        # Strictly no lookahead: filter <= curr_end_dt
        df_sub = df[df.index <= curr_end_dt]
        if df_sub.empty:
            continue

        # Latest session close
        curr_slice = df_sub[df_sub.index <= curr_end_dt]
        if curr_slice.empty:
            continue
        curr_bar = curr_slice.iloc[-1]
        close = float(curr_bar["Close"])

        # Baseline close for current period return
        base_slice = df_sub[df_sub.index <= base_dt]
        if not base_slice.empty:
            base_close = float(base_slice.iloc[-1]["Close"])
            pct_change = ((close - base_close) / base_close) * 100.0 if base_close > 0 else 0.0
        else:
            pct_change = 0.0

        # Previous period performance
        prev_end_slice = df_sub[df_sub.index <= prev_end_dt]
        prev_base_slice = df_sub[df_sub.index <= prev_base_dt]
        if not prev_end_slice.empty and not prev_base_slice.empty:
            p_end_close = float(prev_end_slice.iloc[-1]["Close"])
            p_base_close = float(prev_base_slice.iloc[-1]["Close"])
            prev_pct_change = ((p_end_close - p_base_close) / p_base_close) * 100.0 if p_base_close > 0 else 0.0
        else:
            prev_pct_change = 0.0

        delta_vs_prev = pct_change - prev_pct_change

        # --- Volume Calculation & Verification ---
        volume = 0.0
        avg_vol_20 = 0.0
        vol_ratio = 0.0
        vol_ratio_display = "n/a"
        is_proxy = False
        proxy_sym = None

        # Check if ETF proxy should be used (e.g. QQQ for Nasdaq-100 ^NDX)
        if item.symbol in ("^NDX", "NDX") and "QQQ" in bars:
            proxy_df = bars.get("QQQ")
            if proxy_df is not None and not proxy_df.empty:
                p_sub = proxy_df[proxy_df.index <= curr_end_dt]
                p_slice = p_sub[(p_sub.index >= period_start_dt) & (p_sub.index <= curr_end_dt)]
                p_vols = p_slice["Volume"].replace(0, np.nan).dropna() if "Volume" in p_slice else pd.Series(dtype=float)
                if not p_vols.empty:
                    volume = float(p_vols.mean())
                else:
                    volume = float(p_sub["Volume"].iloc[-1]) if ("Volume" in p_sub.columns and not np.isnan(p_sub["Volume"].iloc[-1])) else 0.0

                p_all_vols = p_sub["Volume"].replace(0, np.nan).dropna() if "Volume" in p_sub else pd.Series(dtype=float)
                if volume > 0 and len(p_all_vols) >= 5:
                    avg_vol_20 = float(p_all_vols.tail(20).mean())
                    vol_ratio = (volume / avg_vol_20) if avg_vol_20 > 0 else 0.0
                    vol_ratio_display = f"{vol_ratio:.2f}x (QQQ)"
                    is_proxy = True
                    proxy_sym = "QQQ"
        else:
            # Native index volume verification
            period_slice = df_sub[(df_sub.index >= period_start_dt) & (df_sub.index <= curr_end_dt)]
            period_vols = period_slice["Volume"].replace(0, np.nan).dropna() if "Volume" in period_slice else pd.Series(dtype=float)
            if not period_vols.empty:
                volume = float(period_vols.mean())
            else:
                volume = float(curr_bar["Volume"]) if "Volume" in curr_bar and not np.isnan(curr_bar["Volume"]) else 0.0

            vols = df_sub["Volume"].replace(0, np.nan).dropna() if "Volume" in df_sub else pd.Series(dtype=float)
            recent_vols = list(vols.tail(10))

            # Check if volume is zero, constant (zero variance), or identical to another index (e.g. ^IXIC duplicating ^NDX)
            is_constant = len(recent_vols) >= 3 and (max(recent_vols) == min(recent_vols))
            is_zero = volume <= 0.0
            
            # Check duplicate volume series
            is_duplicate = item.symbol in duplicate_symbols

            if is_zero or is_constant or is_duplicate:
                vol_ratio = 0.0
                vol_ratio_display = "n/a"
                avg_vol_20 = 0.0
            else:
                if volume > 0 and len(vols) >= 5:
                    avg_vol_20 = float(vols.tail(20).mean())
                    vol_ratio = (volume / avg_vol_20) if avg_vol_20 > 0 else 0.0
                    vol_ratio_display = f"{vol_ratio:.2f}x"
                else:
                    avg_vol_20 = 0.0
                    vol_ratio = 0.0
                    vol_ratio_display = "n/a"

        rows.append(
            IndexSnapshotRow(
                symbol=item.symbol,
                name=item.name,
                close=close,
                pct_change=pct_change,
                volume=volume,
                avg_volume_20d=avg_vol_20,
                volume_ratio=vol_ratio,
                volume_ratio_display=vol_ratio_display,
                prev_period_change=prev_pct_change,
                delta_vs_prev_period=delta_vs_prev,
                is_proxy_volume=is_proxy,
                proxy_symbol=proxy_sym,
            )
        )

    if not rows:
        return SectionResult(
            section_num=2,
            title="Index Snapshot",
            status="unavailable",
            error_message="Historical bar data unavailable for index symbols.",
        )

    return SectionResult(
        section_num=2,
        title="Index Snapshot",
        status="available",
        data=IndexSnapshotData(rows=rows),
    )
