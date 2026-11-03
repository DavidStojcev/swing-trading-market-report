"""Section 6: Top Movers across S&P 500 + Nasdaq-100 deduplicated universe."""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config.settings import MoversConfig
from data.calendar import MarketCalendar, PeriodInfo
from data.constituents import Constituent
from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class MoverItem:
    symbol: str
    name: str
    sector: str
    pct_change: float
    close: float
    volume: float
    avg_volume_20d: float
    volume_ratio: float
    market_cap: float
    has_earnings_in_window: bool = False
    move_cause_tag: str = "Unknown"
    market_cap_str: str = ""
    is_unconfirmed_outlier: bool = False


@dataclass
class PeriodMovers:
    period_name: str
    gainers: List[MoverItem]
    losers: List[MoverItem]
    theme_summary: str = ""


@dataclass
class TopMoversData:
    day: PeriodMovers
    week: PeriodMovers
    month: PeriodMovers


def _fmt_mcap(mcap: float) -> str:
    """Format market cap in billions or trillions."""
    if mcap >= 1e12:
        return f"\\${mcap / 1e12:.2f}T"
    elif mcap >= 1e9:
        return f"\\${mcap / 1e9:.1f}B"
    elif mcap > 0:
        return f"\\${mcap / 1e6:.0f}M"
    return "n/a"


DEFAULT_THEME_MAP: Dict[str, str] = {
    # Semiconductors & Semis Equipment
    "NVDA": "Semiconductors", "AMD": "Semiconductors", "INTC": "Semiconductors", "AVGO": "Semiconductors",
    "QCOM": "Semiconductors", "TXN": "Semiconductors", "MU": "Memory & Storage", "AMAT": "Semiconductor Equipment",
    "LRCX": "Semiconductor Equipment", "KLAC": "Semiconductor Equipment", "MRVL": "Semiconductors", "ARM": "Semiconductor IP",
    "ADI": "Semiconductors", "MCHP": "Semiconductors", "ON": "Semiconductors", "MPWR": "Semiconductors",
    # Data Storage & Enterprise Hardware
    "WDC": "Data Storage", "STX": "Data Storage", "PSTG": "Data Storage", "SMCI": "AI Server Hardware",
    "DELL": "Enterprise Hardware", "HPQ": "Hardware & PCs", "HPE": "Enterprise Hardware",
    # Enterprise Cloud & SaaS
    "NOW": "Enterprise Cloud Software", "CRM": "Enterprise SaaS", "ADBE": "Creative Software", "INTU": "Financial Software",
    "SNOW": "Cloud Data Platforms", "WDAY": "Human Capital SaaS", "PLTR": "Enterprise AI Software", "MDB": "Database Platforms",
    "ORCL": "Cloud Infrastructure & Database", "SAP": "Enterprise ERP", "DDOG": "Cloud Monitoring Software",
    # Cybersecurity
    "FTNT": "Cybersecurity", "CRWD": "Cybersecurity", "PANW": "Cybersecurity", "ZS": "Cybersecurity",
    "OKTA": "Identity Security", "NET": "Cloud & Web Security", "CYBR": "Identity Security",
    # Communications & Collaboration Software
    "TWLO": "Communications Platforms", "ZM": "Collaboration Software", "TEAM": "Productivity Software",
    # Internet Media & Platforms
    "RDDT": "Social & Internet Media", "META": "Social Media & Ad Tech", "GOOGL": "Search & Cloud Platforms",
    "GOOG": "Search & Cloud Platforms", "PINS": "Internet Media", "SNAP": "Social Media", "DASH": "Delivery Platforms",
    # Industrials, Power & Infrastructure
    "PNR": "Industrial Flow Equipment", "VRT": "Data Center Infrastructure & Cooling", "ETN": "Electrical Power Equipment",
    "HUBB": "Electrical Components", "GE": "Aerospace & Industrial", "CAT": "Heavy Machinery", "DE": "Agricultural Machinery",
    # Consumer & Fintech
    "CVNA": "Online Automotive Retail", "GEN": "Consumer Cyber Safety", "GPN": "Fintech & Payments",
    "PYPL": "Fintech & Payments", "SQ": "Fintech & Payments", "COIN": "Crypto Exchange & Custody",
}


def _generate_movers_theme_summary(
    gainers: List[MoverItem],
    losers: List[MoverItem],
    theme_map: Optional[Dict[str, str]] = None,
) -> str:
    """Synthesize thematic industry/sector concentration among top movers.
    
    Stage 3 (3.7): Group by granular sub-industry/theme rather than generic sector.
    """
    if not losers and not gainers:
        return ""
    from collections import Counter
    active_map = {**DEFAULT_THEME_MAP, **(theme_map or {})}

    def get_theme(m: MoverItem) -> str:
        return active_map.get(m.symbol, m.sector)

    loser_themes = Counter(get_theme(l) for l in losers)
    loser_sectors = Counter(l.sector for l in losers)
    gainer_themes = Counter(get_theme(g) for g in gainers)

    parts = []
    if losers:
        top_th, th_cnt = loser_themes.most_common(1)[0]
        if th_cnt >= 2:
            th_tickers = [l.symbol for l in losers if get_theme(l) == top_th]
            parts.append(f"{th_cnt} of {len(losers)} losers are {top_th} ({', '.join(th_tickers)})")
        elif loser_sectors and loser_sectors.most_common(1)[0][1] >= 3:
            top_sec = loser_sectors.most_common(1)[0][0]
            sec_movers = [f"{get_theme(l)} ({l.symbol})" for l in losers if l.sector == top_sec]
            has_earnings = any(l.has_earnings_in_window for l in losers if l.sector == top_sec)
            if has_earnings:
                parts.append(f"Losers reflect post-earnings selloff / guidance cuts across {top_sec}: {', '.join(sec_movers)}")
            else:
                parts.append(f"Losers reflect multiple compression across {top_sec} sub-industries: {', '.join(sec_movers)}")
        else:
            sub_list = [f"{get_theme(l)} ({l.symbol})" for l in losers[:3]]
            parts.append(f"Losers led by {', '.join(sub_list)}")

    if gainers:
        top_g_th, g_cnt = gainer_themes.most_common(1)[0]
        if g_cnt >= 2:
            g_tickers = [g.symbol for g in gainers if get_theme(g) == top_g_th]
            parts.append(f"Gainers led by {top_g_th} ({', '.join(g_tickers)})")
        else:
            g_list = [f"{get_theme(g)} ({g.symbol})" for g in gainers[:3]]
            parts.append(f"Gainers led by {', '.join(g_list)}")

    return "; ".join(parts) + "."


def _calculate_mover_stats(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    sector: str,
    market_cap: float,
    curr_dt: pd.Timestamp,
    base_dt: pd.Timestamp,
    movers_cfg: MoversConfig,
    earnings_in_window: bool = False,
) -> Optional[MoverItem]:
    """Calculate returns and volume metrics for an asset, applying liquidity filters."""
    sub = df[df.index <= curr_dt]
    if sub.empty or len(sub) < 5:
        return None

    curr_bar = sub.iloc[-1]
    close = float(curr_bar["Close"])
    volume = float(curr_bar["Volume"]) if "Volume" in curr_bar and not np.isnan(curr_bar["Volume"]) else 0.0

    # 1. Price filter
    if close < movers_cfg.min_price:
        return None

    # 2. Market cap filter (if market cap is available / non-zero)
    if market_cap > 0 and market_cap < movers_cfg.min_market_cap:
        return None

    # 3. 20-day Average Volume filter
    vols = sub["Volume"].replace(0, np.nan).dropna()
    if len(vols) >= 5:
        avg_vol_20 = float(vols.tail(20).mean())
        if avg_vol_20 < movers_cfg.min_avg_volume:
            return None
        vol_ratio = (volume / avg_vol_20) if avg_vol_20 > 0 else 1.0
    else:
        avg_vol_20 = volume
        vol_ratio = 1.0

    # % change calculation
    base_slice = sub[sub.index <= base_dt]
    if base_slice.empty:
        return None
    base_close = float(base_slice.iloc[-1]["Close"])
    if base_close <= 0:
        return None

    pct_change = ((close - base_close) / base_close) * 100.0

    # Move cause tag & sanity check for outliers (Bug 1.7 & Bug 1.8 & Stage 1: 1.9)
    # Cause tag reflects: post-earnings selloff / guidance cuts when Earnings = YES, or verified catalysts
    is_outlier = False
    if earnings_in_window:
        cause_tag = "Earnings"
    elif abs(pct_change) >= 30.0 and vol_ratio < 1.5:
        # Low-beta large cap monthly move without earnings or high volume
        cause_tag = "⚠ verify (possible data issue)"
        is_outlier = True
    else:
        cause_tag = "Unknown"

    return MoverItem(
        symbol=symbol,
        name=name,
        sector=sector,
        pct_change=pct_change,
        close=close,
        volume=volume,
        avg_volume_20d=avg_vol_20,
        volume_ratio=vol_ratio,
        market_cap=market_cap,
        has_earnings_in_window=earnings_in_window,
        move_cause_tag=cause_tag,
        market_cap_str=_fmt_mcap(market_cap),
        is_unconfirmed_outlier=is_outlier,
    )


def build_movers(
    bars: Dict[str, pd.DataFrame],
    constituents: List[Constituent],
    ticker_infos: Dict[str, dict],
    calendar: MarketCalendar,
    as_of_session: str,
    movers_cfg: MoversConfig,
    earnings_symbols: Optional[set] = None,
) -> SectionResult:
    """Build top gainers and losers for day, week, and month across universe."""
    try:
        session_dt = pd.to_datetime(as_of_session)

        # Baseline dates for Day, Week, Month
        day_period = calendar.resolve_period("daily", session_dt.date())
        week_period = calendar.resolve_period("weekly", session_dt.date())
        month_period = calendar.resolve_period("monthly", session_dt.date())

        day_base_dt = pd.to_datetime(day_period.baseline_date)
        week_base_dt = pd.to_datetime(week_period.baseline_date)
        month_base_dt = pd.to_datetime(month_period.baseline_date)

        const_map = {c.symbol: c for c in constituents}

        day_items: List[MoverItem] = []
        week_items: List[MoverItem] = []
        month_items: List[MoverItem] = []

        for symbol, df in bars.items():
            if df.empty or symbol.startswith("^"):
                continue

            # Require at least 252 trading sessions (1 year) up to as_of_session to exclude recent spin-offs/IPOs
            if len(df[df.index <= session_dt]) < 252:
                continue

            c = const_map.get(symbol)
            name = c.name if c else symbol
            sector = c.sector if c else "Unknown"
            info = ticker_infos.get(symbol, {})
            mcap = float(info.get("marketCap", 0) or 0)
            is_earnings = symbol in earnings_symbols if earnings_symbols else False

            # Day
            d_item = _calculate_mover_stats(df, symbol, name, sector, mcap, session_dt, day_base_dt, movers_cfg, earnings_in_window=is_earnings)
            if d_item:
                day_items.append(d_item)

            # Week
            w_item = _calculate_mover_stats(df, symbol, name, sector, mcap, session_dt, week_base_dt, movers_cfg, earnings_in_window=is_earnings)
            if w_item:
                week_items.append(w_item)

            # Month
            m_item = _calculate_mover_stats(df, symbol, name, sector, mcap, session_dt, month_base_dt, movers_cfg, earnings_in_window=is_earnings)
            if m_item:
                month_items.append(m_item)

        top_n = movers_cfg.top_n

        def extract_top(items: List[MoverItem]) -> Tuple[List[MoverItem], List[MoverItem]]:
            if not items:
                return [], []
            # Exclude unconfirmed outliers from headline top 5 (Bug 1.8)
            confirmed = [it for it in items if not getattr(it, "is_unconfirmed_outlier", False)]
            if not confirmed:
                confirmed = items
            sorted_items = sorted(confirmed, key=lambda x: x.pct_change, reverse=True)
            gainers = sorted_items[:top_n]
            losers = sorted_items[-top_n:][::-1]
            return gainers, losers

        d_gainers, d_losers = extract_top(day_items)
        w_gainers, w_losers = extract_top(week_items)
        m_gainers, m_losers = extract_top(month_items)

        if not d_gainers and not w_gainers and not m_gainers:
            return SectionResult(
                section_num=6,
                title="Top Movers (S&P 500 + Nasdaq-100)",
                status="unavailable",
                error_message="Insufficient filtered equity mover data.",
            )

        data = TopMoversData(
            day=PeriodMovers("Daily", d_gainers, d_losers, theme_summary=_generate_movers_theme_summary(d_gainers, d_losers)),
            week=PeriodMovers("Weekly", w_gainers, w_losers, theme_summary=_generate_movers_theme_summary(w_gainers, w_losers)),
            month=PeriodMovers("Monthly", m_gainers, m_losers, theme_summary=_generate_movers_theme_summary(m_gainers, m_losers)),
        )

        return SectionResult(
            section_num=6,
            title="Top Movers (S&P 500 + Nasdaq-100)",
            status="available",
            data=data,
        )
    except Exception as e:
        logger.warning("Error building top movers section: %s", e)
        return SectionResult(
            section_num=6,
            title="Top Movers (S&P 500 + Nasdaq-100)",
            status="unavailable",
            error_message=f"Error processing movers: {e}",
        )
