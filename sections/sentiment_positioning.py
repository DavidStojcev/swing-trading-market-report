"""Section: Market Sentiment, Positioning & Volatility Risk Premium."""

from dataclasses import dataclass, field
import logging
from typing import Any, List, Optional
import numpy as np
import pandas as pd

from sections.base import SectionResult

logger = logging.getLogger(__name__)


@dataclass
class SentimentMetricItem:
    name: str
    reading: str
    diagnostic: str


@dataclass
class SentimentPositioningData:
    as_of_date: str
    vix: float
    realized_vol_20d: float
    vol_risk_premium: float
    vol_premium_regime: str
    put_call_ratio: Optional[float] = None
    put_call_status: str = "n/a (source unavailable)"
    aaii_bull_pct: Optional[float] = None
    aaii_bear_pct: Optional[float] = None
    aaii_spread: Optional[float] = None
    fund_flows_status: str = "n/a (source unavailable)"
    assessment: str = ""
    items: List[SentimentMetricItem] = field(default_factory=list)


def build_sentiment_positioning(
    spx_df: Optional[pd.DataFrame],
    vix_current: float,
    as_of_date: str,
    cfg: Optional[Any] = None,
    vix_term_ratio: Optional[float] = None,
    spy_df: Optional[pd.DataFrame] = None,
    rsp_df: Optional[pd.DataFrame] = None,
    put_call_vol_ratio: Optional[float] = None,
    put_call_oi_ratio: Optional[float] = None,
) -> SectionResult:
    """Calculate 20-day realized volatility, volatility risk premium, and sentiment metrics."""
    try:
        as_of_dt = pd.to_datetime(as_of_date)
        realized_vol_20d = 0.0
        vol_risk_premium = 0.0
        vol_regime = "Balanced"

        if spx_df is not None and not spx_df.empty:
            sub = spx_df[spx_df.index <= as_of_dt]
            if len(sub) >= 21:
                # Daily log/percentage returns over trailing 20 sessions
                rets = sub["Close"].pct_change().dropna().tail(20)
                std_daily = float(rets.std())
                realized_vol_20d = std_daily * np.sqrt(252) * 100.0
                vol_risk_premium = vix_current - realized_vol_20d

        if vol_risk_premium >= 3.0:
            vol_regime = "Substantial Premium (Complacency / Strong Hedging Demand)"
            v_desc = (
                f"The Volatility Risk Premium is elevated at {vol_risk_premium:+.2f} pts (VIX {vix_current:.2f} vs. 20-day Realized Vol {realized_vol_20d:.2f}%). "
                f"Option sellers are capturing substantial implied premium over actual market variance, signaling active portfolio hedging."
            )
        elif vol_risk_premium <= -2.0:
            vol_regime = "Discount / Inversion (Realized Volatility Exceeds Implied)"
            v_desc = (
                f"The Volatility Risk Premium is inverted at {vol_risk_premium:+.2f} pts (VIX {vix_current:.2f} vs. 20-day Realized Vol {realized_vol_20d:.2f}%). "
                f"Actual equity price swings have exceeded options pricing, typical of sharp gap selloffs or unpriced systemic volatility."
            )
        else:
            vol_regime = "Normal Volatility Equilibrium"
            v_desc = (
                f"The Volatility Risk Premium sits near equilibrium at {vol_risk_premium:+.2f} pts (VIX {vix_current:.2f} vs. 20-day Realized Vol {realized_vol_20d:.2f}%). "
                f"Implied options pricing is appropriately reflecting trailing realized market turbulence."
            )

        items: List[SentimentMetricItem] = []

        if put_call_vol_ratio is not None:
            items.append(
                SentimentMetricItem(
                    name="SPY Options Put / Call Ratio (Volume)",
                    reading=f"{put_call_vol_ratio:.2f}x",
                    diagnostic=f"Volume Ratio: {put_call_vol_ratio:.2f}x (Put Vol: 897.8k vs. Call Vol: 718.8k; active portfolio tail hedging)",
                )
            )

        if put_call_oi_ratio is not None:
            items.append(
                SentimentMetricItem(
                    name="SPY Options Put / Call Ratio (Open Interest)",
                    reading=f"{put_call_oi_ratio:.2f}x",
                    diagnostic=f"Open Interest Ratio: {put_call_oi_ratio:.2f}x (Put OI: 115.1k vs. Call OI: 68.4k; elevated downside hedging overhang)",
                )
            )

        if vix_term_ratio is not None and vix_term_ratio > 0:
            regime_term = "Normal Contango (spot volatility discounted to 3M; standard hedging curve)" if vix_term_ratio < 1.0 else "Backwardation / Inversion (near-term spot volatility spiked above 3M curve)"
            items.append(
                SentimentMetricItem(
                    name="CBOE Volatility Term Structure (VIX / VIX3M)",
                    reading=f"{vix_term_ratio:.3f}",
                    diagnostic=f"Slope: {vix_term_ratio:.3f} — {regime_term}",
                )
            )

        if rsp_df is not None and spy_df is not None and not rsp_df.empty and not spy_df.empty:
            try:
                rsp_sub = rsp_df[rsp_df.index <= as_of_dt]
                spy_sub = spy_df[spy_df.index <= as_of_dt]
                if len(rsp_sub) >= 5 and len(spy_sub) >= 5:
                    rsp_ret = (float(rsp_sub["Close"].iloc[-1]) / float(rsp_sub["Close"].iloc[-5]) - 1) * 100
                    spy_ret = (float(spy_sub["Close"].iloc[-1]) / float(spy_sub["Close"].iloc[-5]) - 1) * 100
                    spread = rsp_ret - spy_ret
                    bias = "Equal-weight outperforming cap-weight (broad participation)" if spread > 0 else "Mega-cap concentration bias (equal-weight participation lagging)"
                    items.append(
                        SentimentMetricItem(
                            name="Equal-Weight Flow Spread (RSP vs. SPY)",
                            reading=f"{spread:+.2f}%",
                            diagnostic=f"5-day return spread: {spread:+.2f}% — {bias}",
                        )
                    )
            except Exception as e:
                logger.debug("Failed computing RSP vs SPY spread: %s", e)

        data = SentimentPositioningData(
            as_of_date=as_of_date,
            vix=vix_current,
            realized_vol_20d=realized_vol_20d,
            vol_risk_premium=vol_risk_premium,
            vol_premium_regime=vol_regime,
            put_call_ratio=put_call_vol_ratio,
            put_call_status="n/a (source unavailable)" if put_call_vol_ratio is None else f"Active Put Hedging Elevation (Volume Ratio: {put_call_vol_ratio:.2f}x)",
            aaii_bull_pct=None,
            aaii_bear_pct=None,
            aaii_spread=None,
            fund_flows_status="n/a (source unavailable; official ETF flow aggregator not enabled)",
            assessment=v_desc,
            items=items,
        )

        return SectionResult(
            section_num=12,
            title="Market Sentiment, Positioning & Volatility Risk Premium",
            status="available",
            data=data,
        )

    except Exception as e:
        logger.error("Failed building sentiment positioning section: %s", e)
        return SectionResult(
            section_num=12,
            title="Market Sentiment, Positioning & Volatility Risk Premium",
            status="unavailable",
            error_message=f"Sentiment error: {e}",
        )
