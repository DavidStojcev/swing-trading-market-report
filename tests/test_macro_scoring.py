"""Unit tests for macro scoring votes and engine integration."""

from dataclasses import dataclass, field
from typing import List, Optional
import pytest

from config.settings import MacroScoringConfig, ScoringConfig
from indicators.engine import TechnicalSnapshot
from scoring.engine import TrendScoringEngine
from scoring.rules import evaluate_macro_votes


@dataclass
class MockFedRates:
    yield_10y: float = 4.30
    yield_10y_delta: float = 0.20  # +20 bps
    spread_2s10s: float = 0.15
    is_inverted: bool = False


@dataclass
class MockCrossAsset:
    symbol: str = "DX-Y.NYB"
    name: str = "US Dollar Index"
    pct_change: float = 1.25


@dataclass
class MockRelease:
    title: str = "CPI Inflation"
    category: str = "inflation"
    surprise_flag: str = "hot"


@pytest.fixture
def macro_scoring_cfg():
    return MacroScoringConfig(
        enabled=True,
        weights={
            "yield_10y_surge": 0.5,
            "curve_inversion": 0.5,
            "dollar_surge": 0.5,
            "inflation_surprise": 0.5,
            "labor_surprise": 0.5,
        },
        thresholds={
            "yield_10y_surge_bps": 15.0,
            "dollar_surge_pct": 1.0,
        },
    )


@pytest.fixture
def mock_spx_snapshot():
    return TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-22",
        price=5800.0,
        dma_20=5750.0,
        dma_50=5700.0,
        dma_200=5300.0,
        price_vs_dma20_pct=0.87,
        price_vs_dma50_pct=1.75,
        price_vs_dma200_pct=9.43,
        cross_50_200="Bullish (50 > 200)",
        rsi=55.0,
        prev_rsi=54.0,
        delta_rsi=1.0,
        rsi_flag="Neutral",
        macd=20.0,
        macd_signal=15.0,
        macd_hist=5.0,
        macd_status="Bullish (MACD > Signal)",
        prev_macd=18.0,
        delta_macd=2.0,
        adx=25.0,
        plus_di=26.0,
        minus_di=16.0,
        prev_adx=24.0,
        delta_adx=1.0,
        trend_strength="Moderate Trend",
    )


def test_10y_yield_surge_vote(macro_scoring_cfg):
    # Case 1: 10Y surged +20 bps (> 15 bps threshold) -> -1
    rates_surge = MockFedRates(yield_10y_delta=0.20)
    votes = evaluate_macro_votes(
        fed_rates=rates_surge,
        cross_assets=[],
        recent_releases=[],
        macro_scoring_cfg=macro_scoring_cfg,
    )
    v10 = next(v for v in votes if "10Y Treasury" in v.rule_name)
    assert v10.vote == -1
    assert v10.weight == 0.5
    assert v10.weighted_vote == -0.5

    # Case 2: 10Y fell -20 bps (<-15 bps threshold) -> +1
    rates_drop = MockFedRates(yield_10y_delta=-0.20)
    votes_drop = evaluate_macro_votes(
        fed_rates=rates_drop,
        cross_assets=[],
        recent_releases=[],
        macro_scoring_cfg=macro_scoring_cfg,
    )
    v10_drop = next(v for v in votes_drop if "10Y Treasury" in v.rule_name)
    assert v10_drop.vote == 1


def test_curve_inversion_vote(macro_scoring_cfg):
    # Inverted curve -> -1
    inv_rates = MockFedRates(is_inverted=True, spread_2s10s=-0.25)
    votes = evaluate_macro_votes(
        fed_rates=inv_rates,
        cross_assets=[],
        recent_releases=[],
        macro_scoring_cfg=macro_scoring_cfg,
    )
    v_curve = next(v for v in votes if "Yield Curve" in v.rule_name)
    assert v_curve.vote == -1

    # Normal curve -> +1
    norm_rates = MockFedRates(is_inverted=False, spread_2s10s=0.30)
    votes_norm = evaluate_macro_votes(
        fed_rates=norm_rates,
        cross_assets=[],
        recent_releases=[],
        macro_scoring_cfg=macro_scoring_cfg,
    )
    v_norm = next(v for v in votes_norm if "Yield Curve" in v.rule_name)
    assert v_norm.vote == 1


def test_dollar_surge_vote(macro_scoring_cfg):
    # Dollar surged +1.25% (> 1.0% threshold) -> -1
    ca = [MockCrossAsset(symbol="DX-Y.NYB", name="US Dollar Index", pct_change=1.25)]
    votes = evaluate_macro_votes(
        fed_rates=MockFedRates(),
        cross_assets=ca,
        recent_releases=[],
        macro_scoring_cfg=macro_scoring_cfg,
    )
    v_dxy = next(v for v in votes if "Dollar" in v.rule_name)
    assert v_dxy.vote == -1


def test_macro_scoring_toggle_off(mock_spx_snapshot):
    """When macro scoring is disabled, macro votes must be omitted entirely."""
    cfg = ScoringConfig(
        weights={"price_above_50_dma": 1.0, "price_above_200_dma": 1.0, "dma_50_above_200": 1.0, "macd_bullish": 1.0, "vix_bullish": 1.0},
        thresholds={"bullish": 0.3, "bearish": -0.3},
        vix={"low_threshold": 20.0, "high_threshold": 25.0},
    )
    engine = TrendScoringEngine(cfg)

    # Disabled macro scoring config
    mac_cfg_off = MacroScoringConfig(enabled=False)

    class DummyMacroData:
        def __init__(self):
            self.fed_rates = MockFedRates(yield_10y_delta=0.30)
            self.cross_assets = []
            self.recent_releases = []

    scorecard = engine.compute_scorecard(
        spx_snapshot=mock_spx_snapshot,
        vix_current=17.0,
        vix_previous=18.0,
        macro_data=DummyMacroData(),
        macro_scoring_cfg=mac_cfg_off,
    )

    # Rates & Macro category must be unavailable and omitted from active votes
    cat_rates = next(c for c in scorecard.categories if c.category_key == "rates_macro")
    assert cat_rates.status == "unavailable"
    assert cat_rates.score == 0.0
    assert not any(v.category == "rates_macro" or "10Y Treasury" in v.rule_name for v in scorecard.votes)
