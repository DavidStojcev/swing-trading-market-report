"""Unit tests for indicator voting and trend scoring."""

import pytest
from config.settings import ScoringConfig
from indicators.engine import TechnicalSnapshot
from scoring.engine import TrendScoringEngine
from scoring.rules import evaluate_technical_votes, evaluate_vix_vote


@pytest.fixture
def scoring_cfg():
    return ScoringConfig(
        weights={
            "price_above_50_dma": 1.0,
            "price_above_200_dma": 1.0,
            "dma_50_above_200": 1.0,
            "macd_bullish": 1.0,
            "vix_bullish": 1.0,
        },
        thresholds={"bullish": 0.3, "bearish": -0.3},
        vix={"low_threshold": 20.0, "high_threshold": 25.0},
    )


def test_vix_voting_logic(scoring_cfg):
    # Case 1: VIX < 20 and falling -> +1
    vote_bull = evaluate_vix_vote(vix_current=17.5, vix_previous=18.5, scoring_cfg=scoring_cfg)
    assert vote_bull.vote == 1

    # Case 2: VIX > 25 and rising -> -1
    vote_bear = evaluate_vix_vote(vix_current=28.0, vix_previous=24.0, scoring_cfg=scoring_cfg)
    assert vote_bear.vote == -1

    # Case 3: VIX neutral
    vote_neutral = evaluate_vix_vote(vix_current=21.0, vix_previous=21.5, scoring_cfg=scoring_cfg)
    assert vote_neutral.vote == 0

    # Case 4: VIX in Cautious zone (19.42) with negligible -0.03 tick must remain Neutral (0), not +1 Complacent
    vote_cautious_flat = evaluate_vix_vote(vix_current=19.42, vix_previous=19.45, scoring_cfg=scoring_cfg)
    assert vote_cautious_flat.vote == 0


def test_bullish_verdict_mapping(scoring_cfg):
    snap = TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-22",
        price=5800.0,
        dma_20=5750.0,
        dma_50=5600.0,      # Price > 50 DMA (+1)
        dma_200=5300.0,     # Price > 200 DMA (+1) & 50 > 200 (+1)
        price_vs_dma20_pct=0.87,
        price_vs_dma50_pct=3.57,
        price_vs_dma200_pct=9.43,
        cross_50_200="Bullish (50 > 200)",
        rsi=62.0,
        prev_rsi=60.0,
        delta_rsi=2.0,
        rsi_flag="Neutral",
        macd=25.0,          # MACD > Signal (+1)
        macd_signal=20.0,
        macd_hist=5.0,
        macd_status="Bullish (MACD > Signal)",
        prev_macd=22.0,
        delta_macd=3.0,
        adx=30.0,
        plus_di=28.0,
        minus_di=14.0,
        prev_adx=29.0,
        delta_adx=1.0,
        trend_strength="Moderate Trend",
    )

    engine = TrendScoringEngine(scoring_cfg)
    # VIX falling from 18 to 16 -> positive volatility score
    scorecard = engine.compute_scorecard(spx_snapshot=snap, vix_current=16.0, vix_previous=18.0)

    # In Stage 2 regime framework, positive scores map to Constructive or Risk-on
    assert scorecard.verdict in ("Constructive", "Risk-on")
    assert scorecard.normalized_score > 0.0
    assert len(scorecard.votes) >= 5
    assert len(scorecard.top_bullish_factors) >= 1


def test_bearish_verdict_mapping(scoring_cfg):
    snap = TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-22",
        price=5000.0,
        dma_20=5100.0,
        dma_50=5200.0,      # Price < 50 DMA (-1)
        dma_200=5400.0,     # Price < 200 DMA (-1) & 50 < 200 (-1)
        price_vs_dma20_pct=-1.96,
        price_vs_dma50_pct=-3.85,
        price_vs_dma200_pct=-7.41,
        cross_50_200="Bearish (50 < 200)",
        rsi=28.0,           # Oversold caution flag!
        prev_rsi=31.0,
        delta_rsi=-3.0,
        rsi_flag="Oversold (<30)",
        macd=-30.0,         # MACD < Signal (-1)
        macd_signal=-20.0,
        macd_hist=-10.0,
        macd_status="Bearish (MACD < Signal)",
        prev_macd=-25.0,
        delta_macd=-5.0,
        adx=35.0,
        plus_di=12.0,
        minus_di=32.0,
        prev_adx=33.0,
        delta_adx=2.0,
        trend_strength="Moderate Trend",
    )

    engine = TrendScoringEngine(scoring_cfg)
    # VIX rising from 24 to 28 -> negative volatility score
    scorecard = engine.compute_scorecard(spx_snapshot=snap, vix_current=28.0, vix_previous=24.0)

    # In Stage 2 regime framework, negative scores map to Cautious or Risk-off
    assert scorecard.verdict in ("Cautious", "Risk-off")
    assert scorecard.normalized_score < 0.0
    # RSI < 30 must create caution flag
    assert any("Oversold" in cf for cf in scorecard.caution_flags)


# ==============================================================================
# STAGE 2 ACCEPTANCE TESTS
# ==============================================================================

def test_linear_gradient_replaces_hard_cliffs():
    """Verify linear gradient replaces binary cliffs with smooth interpolation."""
    from scoring.rules import linear_gradient
    # Ascending gradient: 40% = -1.0, 50% = 0.0, 60% = +1.0
    assert linear_gradient(40.0, 40.0, 50.0, 60.0) == -1.0
    assert linear_gradient(50.0, 40.0, 50.0, 60.0) == 0.0
    assert linear_gradient(60.0, 40.0, 50.0, 60.0) == 1.0
    assert linear_gradient(45.0, 40.0, 50.0, 60.0) == -0.5
    assert linear_gradient(55.0, 40.0, 50.0, 60.0) == 0.5
    # Clamping at extremes
    assert linear_gradient(20.0, 40.0, 50.0, 60.0) == -1.0
    assert linear_gradient(80.0, 40.0, 50.0, 60.0) == 1.0

    # Descending gradient: e.g. VIX level (20 = -1.0, 16.5 = 0.0, 13 = +1.0)
    assert linear_gradient(20.0, 20.0, 16.5, 13.0) == -1.0
    assert linear_gradient(16.5, 20.0, 16.5, 13.0) == 0.0
    assert linear_gradient(13.0, 20.0, 16.5, 13.0) == 1.0


def test_ndx_spx_divergence_picks_weaker(scoring_cfg):
    """Trend/Price category must evaluate both SPX and NDX and adopt the weaker score with divergence note."""
    spx_snap = TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-30",
        price=5800.0,
        dma_20=5750.0,
        dma_50=5700.0,
        dma_200=5400.0,
        price_vs_dma20_pct=0.87,
        price_vs_dma50_pct=1.75,
        price_vs_dma200_pct=7.41,
        cross_50_200="Bullish (50 > 200)",
        rsi=55.0,
        prev_rsi=54.0,
        delta_rsi=1.0,
        rsi_flag="Neutral",
        macd=15.0,
        macd_signal=10.0,
        macd_hist=5.0,
        macd_status="Bullish (MACD > Signal)",
        prev_macd=12.0,
        delta_macd=3.0,
        adx=25.0,
        plus_di=24.0,
        minus_di=16.0,
        prev_adx=24.0,
        delta_adx=1.0,
        trend_strength="Moderate Trend",
    )

    ndx_snap = TechnicalSnapshot(
        symbol="^NDX",
        name="Nasdaq-100",
        as_of_date="2026-10-30",
        price=18000.0,
        dma_20=18500.0,
        dma_50=18900.0,
        dma_200=17500.0,
        price_vs_dma20_pct=-2.70,
        price_vs_dma50_pct=-4.76,  # Weak tech breakdown
        price_vs_dma200_pct=2.86,
        cross_50_200="Bullish (50 > 200)",
        rsi=38.0,
        prev_rsi=42.0,
        delta_rsi=-4.0,
        rsi_flag="Neutral",
        macd=-20.0,
        macd_signal=-10.0,
        macd_hist=-10.0,
        macd_status="Bearish (MACD < Signal)",
        prev_macd=-15.0,
        delta_macd=-5.0,
        adx=28.0,
        plus_di=14.0,
        minus_di=30.0,
        prev_adx=26.0,
        delta_adx=2.0,
        trend_strength="Moderate Trend",
    )

    engine = TrendScoringEngine(scoring_cfg)
    scorecard = engine.compute_scorecard(
        spx_snapshot=spx_snap,
        vix_current=19.42,
        vix_previous=19.45,
        ndx_snapshot=ndx_snap,
    )

    cat_trend = next(c for c in scorecard.categories if c.category_key == "trend_price")
    # Score should adopt the weaker NDX score (negative) rather than the SPX score (positive)
    assert cat_trend.score < 0.0
    # Must flag the divergence
    assert "Divergence" in cat_trend.notes or "Divergence" in scorecard.divergence_note
    assert any("Divergence" in cf for cf in scorecard.caution_flags)


def test_unavailable_input_changes_denominator_not_sign(scoring_cfg):
    """Dropping an unavailable input must renormalize the denominator rather than pulling the score to zero."""
    from dataclasses import dataclass
    
    @dataclass
    class MockSentiment:
        put_call_ratio: float = 0.80   # Bullish
        aaii_bull_bear_spread: float = 10.0
        vix_vs_realized_vol: float = -2.0

    spx_snap = TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-30",
        price=5900.0,
        dma_20=5800.0,
        dma_50=5700.0,
        dma_200=5300.0,
        price_vs_dma20_pct=1.72,
        price_vs_dma50_pct=3.51,
        price_vs_dma200_pct=11.32,
        cross_50_200="Bullish (50 > 200)",
        rsi=65.0,
        prev_rsi=63.0,
        delta_rsi=2.0,
        rsi_flag="Neutral",
        macd=30.0,
        macd_signal=20.0,
        macd_hist=10.0,
        macd_status="Bullish (MACD > Signal)",
        prev_macd=25.0,
        delta_macd=5.0,
        adx=32.0,
        plus_di=30.0,
        minus_di=12.0,
        prev_adx=30.0,
        delta_adx=2.0,
        trend_strength="Strong Trend",
    )

    engine = TrendScoringEngine(scoring_cfg)
    
    # 1. Score with sentiment available (denominator = 1.0)
    score_with_sent = engine.compute_scorecard(
        spx_snapshot=spx_snap,
        vix_current=14.0,
        vix_previous=15.0,
        sentiment_data=MockSentiment(),
    )

    # 2. Score with sentiment unavailable (denominator = 0.85)
    score_without_sent = engine.compute_scorecard(
        spx_snapshot=spx_snap,
        vix_current=14.0,
        vix_previous=15.0,
        sentiment_data=None,
    )

    # Both must remain strongly positive in sign
    assert score_with_sent.normalized_score > 0.0
    assert score_without_sent.normalized_score > 0.0

    # Denominator adjusts from 1.0 to 0.85
    cat_sent = next(c for c in score_without_sent.categories if c.category_key == "sentiment_positioning")
    assert cat_sent.status == "unavailable"
    assert score_without_sent.max_score < score_with_sent.max_score


def test_scorecard_reproducible_from_json(scoring_cfg):
    """Verify that scorecard inputs and outputs can be fully serialized to and reproduced from JSON."""
    import json
    
    spx_snap = TechnicalSnapshot(
        symbol="^GSPC",
        name="S&P 500",
        as_of_date="2026-10-30",
        price=5750.0,
        dma_20=5780.0,
        dma_50=5720.0,
        dma_200=5350.0,
        price_vs_dma20_pct=-0.52,
        price_vs_dma50_pct=0.52,
        price_vs_dma200_pct=7.48,
        cross_50_200="Bullish (50 > 200)",
        rsi=51.0,
        prev_rsi=53.0,
        delta_rsi=-2.0,
        rsi_flag="Neutral",
        macd=12.0,
        macd_signal=14.0,
        macd_hist=-2.0,
        macd_status="Bearish (MACD < Signal)",
        prev_macd=15.0,
        delta_macd=-3.0,
        adx=22.0,
        plus_di=20.0,
        minus_di=18.0,
        prev_adx=23.0,
        delta_adx=-1.0,
        trend_strength="Weak Trend",
    )

    engine = TrendScoringEngine(scoring_cfg)
    scorecard = engine.compute_scorecard(spx_snapshot=spx_snap, vix_current=19.42, vix_previous=19.45)

    # Export to JSON
    json_str = scorecard.to_json()
    data = json.loads(json_str)

    # Verify JSON structure
    assert "normalized_score" in data
    assert "verdict" in data
    assert "regime_label" in data
    assert "categories" in data
    assert len(data["categories"]) == 5
    assert data["normalized_score"] == scorecard.normalized_score
    assert data["verdict"] == scorecard.verdict

