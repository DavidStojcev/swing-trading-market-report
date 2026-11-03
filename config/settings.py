"""Configuration loading and validation module."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import yaml


@dataclass(frozen=True)
class SymbolItem:
    symbol: str
    name: str


@dataclass(frozen=True)
class SymbolsConfig:
    indices: List[SymbolItem]
    technical_indices: List[SymbolItem]
    volatility: SymbolItem
    sectors: List[SymbolItem]
    benchmark: SymbolItem
    volatility_3m: Optional[SymbolItem] = None


@dataclass(frozen=True)
class IndicatorsConfig:
    dma_fast: int = 20
    dma_medium: int = 50
    dma_slow: int = 200
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14


@dataclass(frozen=True)
class ScoringConfig:
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    vix: Dict[str, float]
    min_inputs_per_category: int = 2
    mixed_verdict_spread_threshold: float = 0.8


@dataclass(frozen=True)
class MoversConfig:
    min_price: float = 5.0
    min_avg_volume: int = 1000000
    min_market_cap: float = 2000000000.0
    top_n: int = 5


@dataclass(frozen=True)
class DataConfig:
    cache_dir: str = ".cache"
    constituents_cache_days: int = 7
    request_delay_seconds: float = 0.05
    max_retries: int = 3
    backoff_factor: float = 1.5
    batch_size: int = 50
    snapshot_db_path: str = ".cache/snapshots.db"


@dataclass(frozen=True)
class FredConfig:
    api_key_env: str = "FRED_API_KEY"
    cache_days: int = 7
    series: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EconCalendarConfig:
    provider: str = "finnhub"
    finnhub_api_key_env: str = "FINNHUB_API_KEY"
    fmp_api_key_env: str = "FMP_API_KEY"
    cache_hours: int = 12


@dataclass(frozen=True)
class CrossAssetsConfig:
    dollar_index: str = "DX-Y.NYB"
    wti_oil: str = "CL=F"
    gold: str = "GC=F"


@dataclass(frozen=True)
class MacroScoringConfig:
    enabled: bool = True
    weights: Dict[str, float] = field(default_factory=dict)
    thresholds: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MacroConfig:
    enabled: bool = True
    fred: FredConfig = field(default_factory=FredConfig)
    calendar: EconCalendarConfig = field(default_factory=EconCalendarConfig)
    cross_assets: CrossAssetsConfig = field(default_factory=CrossAssetsConfig)
    tolerances: Dict[str, float] = field(default_factory=dict)
    scoring: MacroScoringConfig = field(default_factory=MacroScoringConfig)


@dataclass(frozen=True)
class BreadthScoringConfig:
    enabled: bool = True
    weights: Dict[str, float] = field(default_factory=dict)
    thresholds: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BreadthConfig:
    enabled: bool = True
    min_coverage_pct: float = 95.0
    min_history_bars: int = 252
    mcclellan_enabled: bool = True
    scoring: BreadthScoringConfig = field(default_factory=BreadthScoringConfig)


@dataclass(frozen=True)
class ChartsConfig:
    enabled: bool = True
    dpi: int = 120
    lookback_bars: int = 130
    monthly_lookback_bars: int = 252


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    smtp_host_env: str = "SMTP_HOST"
    smtp_port_env: str = "SMTP_PORT"
    smtp_user_env: str = "SMTP_USER"
    smtp_password_env: str = "SMTP_PASSWORD"
    email_from_env: str = "EMAIL_FROM"
    email_to_env: str = "EMAIL_TO"
    require_tls: bool = True


@dataclass(frozen=True)
class ScorecardCategoriesConfig:
    enabled: bool = True
    weights: Dict[str, float] = field(default_factory=lambda: {
        "trend_price": 0.30,
        "breadth": 0.20,
        "volatility_risk": 0.15,
        "rates_macro": 0.20,
        "sentiment_positioning": 0.15,
    })
    regimes: Dict[str, float] = field(default_factory=lambda: {
        "risk_on": 0.40,
        "constructive": 0.15,
        "neutral_lower": -0.15,
        "cautious_lower": -0.40,
    })


@dataclass(frozen=True)
class SectorsConfig:
    enabled: bool = True
    min_dollar_volume: float = 20_000_000.0
    max_dist_from_52w_high: float = 15.0
    defensive_exceptions: bool = False


@dataclass(frozen=True)
class SwingGateConfig:
    enabled: bool = True
    spy_symbol: str = "SPY"
    qqq_symbol: str = "QQQ"
    ema_fast: int = 20
    dma_medium: int = 50
    vix_low: float = 20.0
    vix_high: float = 25.0
    breadth_min_pct: float = 50.0
    breadth_defensive_pct: float = 40.0
    defensive_exceptions: bool = False


GateConfig = SwingGateConfig


@dataclass(frozen=True)
class ThemeEtfItem:
    symbol: str
    name: str
    category: str


@dataclass(frozen=True)
class ThemeEtfsConfig:
    enabled: bool = True
    items: List[ThemeEtfItem] = field(default_factory=list)


@dataclass(frozen=True)
class CrossAssetsExpandedConfig:
    enabled: bool = True
    items: List[SymbolItem] = field(default_factory=list)


@dataclass(frozen=True)
class ForwardCalendarConfig:
    enabled: bool = True
    lookahead_days: int = 14
    high_impact_rules: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EarningsConfig:
    enabled: bool = True
    top_constituents_count: int = 30
    lookahead_days: int = 7


@dataclass(frozen=True)
class SentimentConfig:
    enabled: bool = True
    realized_vol_window: int = 20


@dataclass(frozen=True)
class AppConfig:
    symbols: SymbolsConfig
    indicators: IndicatorsConfig
    scoring: ScoringConfig
    movers: MoversConfig
    data: DataConfig
    macro: MacroConfig = field(default_factory=MacroConfig)
    breadth: BreadthConfig = field(default_factory=BreadthConfig)
    charts: ChartsConfig = field(default_factory=ChartsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    scorecard_categories: ScorecardCategoriesConfig = field(default_factory=ScorecardCategoriesConfig)
    swing_gate: SwingGateConfig = field(default_factory=SwingGateConfig)
    theme_etfs: ThemeEtfsConfig = field(default_factory=ThemeEtfsConfig)
    cross_assets_expanded: CrossAssetsExpandedConfig = field(default_factory=CrossAssetsExpandedConfig)
    forward_calendar: ForwardCalendarConfig = field(default_factory=ForwardCalendarConfig)
    earnings: EarningsConfig = field(default_factory=EarningsConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    sectors: SectorsConfig = field(default_factory=SectorsConfig)
    defensive_exceptions: bool = False


ReportConfig = AppConfig


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load and parse application configuration from YAML.
    
    Args:
        config_path: Optional path to config YAML. If omitted, uses default config/config.yaml.
        
    Returns:
        Typed AppConfig instance.
    """
    if config_path is None:
        base_dir = Path(__file__).resolve().parent
        config_path = str(base_dir / "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f)

    sym = raw.get("symbols", {})
    indices = [SymbolItem(symbol=i["symbol"], name=i["name"]) for i in sym.get("indices", [])]
    tech_indices = [SymbolItem(symbol=i["symbol"], name=i["name"]) for i in sym.get("technical_indices", [])]
    vol = SymbolItem(symbol=sym["volatility"]["symbol"], name=sym["volatility"]["name"])
    vol_3m_raw = sym.get("volatility_3m")
    vol_3m = SymbolItem(symbol=vol_3m_raw["symbol"], name=vol_3m_raw["name"]) if vol_3m_raw else None
    sectors = [SymbolItem(symbol=s["symbol"], name=s["name"]) for s in sym.get("sectors", [])]
    benchmark = SymbolItem(symbol=sym["benchmark"]["symbol"], name=sym["benchmark"]["name"])
    symbols_cfg = SymbolsConfig(
        indices=indices,
        technical_indices=tech_indices,
        volatility=vol,
        sectors=sectors,
        benchmark=benchmark,
        volatility_3m=vol_3m,
    )

    ind = raw.get("indicators", {})
    indicators_cfg = IndicatorsConfig(
        dma_fast=ind.get("dma_fast", 20),
        dma_medium=ind.get("dma_medium", 50),
        dma_slow=ind.get("dma_slow", 200),
        rsi_period=ind.get("rsi_period", 14),
        rsi_overbought=ind.get("rsi_overbought", 70.0),
        rsi_oversold=ind.get("rsi_oversold", 30.0),
        macd_fast=ind.get("macd_fast", 12),
        macd_slow=ind.get("macd_slow", 26),
        macd_signal=ind.get("macd_signal", 9),
        adx_period=ind.get("adx_period", 14),
    )

    sc = raw.get("scoring", {})
    scoring_cfg = ScoringConfig(
        weights=sc.get("weights", {}),
        thresholds=sc.get("thresholds", {"bullish": 0.3, "bearish": -0.3}),
        vix=sc.get("vix", {"low_threshold": 20.0, "high_threshold": 25.0}),
        min_inputs_per_category=int(sc.get("min_inputs_per_category", 2)),
        mixed_verdict_spread_threshold=float(sc.get("mixed_verdict_spread_threshold", 0.8)),
    )

    mov = raw.get("movers", {})
    movers_cfg = MoversConfig(
        min_price=mov.get("min_price", 5.0),
        min_avg_volume=mov.get("min_avg_volume", 1000000),
        min_market_cap=mov.get("min_market_cap", 2000000000.0),
        top_n=mov.get("top_n", 5),
    )

    dat = raw.get("data", {})
    data_cfg = DataConfig(
        cache_dir=dat.get("cache_dir", ".cache"),
        constituents_cache_days=dat.get("constituents_cache_days", 7),
        request_delay_seconds=dat.get("request_delay_seconds", 0.05),
        max_retries=dat.get("max_retries", 3),
        backoff_factor=dat.get("backoff_factor", 1.5),
        batch_size=dat.get("batch_size", 50),
        snapshot_db_path=dat.get("snapshot_db_path", ".cache/snapshots.db"),
    )

    # Stage 2: Macro configuration
    mac = raw.get("macro", {})
    fred_raw = mac.get("fred", {})
    fred_cfg = FredConfig(
        api_key_env=fred_raw.get("api_key_env", "FRED_API_KEY"),
        cache_days=fred_raw.get("cache_days", 7),
        series=fred_raw.get("series", {}),
    )

    cal_raw = mac.get("calendar", {})
    cal_cfg = EconCalendarConfig(
        provider=cal_raw.get("provider", "finnhub"),
        finnhub_api_key_env=cal_raw.get("finnhub_api_key_env", "FINNHUB_API_KEY"),
        fmp_api_key_env=cal_raw.get("fmp_api_key_env", "FMP_API_KEY"),
        cache_hours=cal_raw.get("cache_hours", 12),
    )

    ca_raw = mac.get("cross_assets", {})
    cross_cfg = CrossAssetsConfig(
        dollar_index=ca_raw.get("dollar_index", "DX-Y.NYB"),
        wti_oil=ca_raw.get("wti_oil", "CL=F"),
        gold=ca_raw.get("gold", "GC=F"),
    )

    mac_sc_raw = mac.get("scoring", {})
    mac_sc_cfg = MacroScoringConfig(
        enabled=mac_sc_raw.get("enabled", True),
        weights=mac_sc_raw.get("weights", {}),
        thresholds=mac_sc_raw.get("thresholds", {}),
    )

    macro_cfg = MacroConfig(
        enabled=mac.get("enabled", True),
        fred=fred_cfg,
        calendar=cal_cfg,
        cross_assets=cross_cfg,
        tolerances=mac.get("tolerances", {}),
        scoring=mac_sc_cfg,
    )

    # Stage 3: Breadth configuration
    br = raw.get("breadth", {})
    br_sc_raw = br.get("scoring", {})
    br_sc_cfg = BreadthScoringConfig(
        enabled=br_sc_raw.get("enabled", True),
        weights=br_sc_raw.get("weights", {}),
        thresholds=br_sc_raw.get("thresholds", {}),
    )
    breadth_cfg = BreadthConfig(
        enabled=br.get("enabled", True),
        min_coverage_pct=float(br.get("min_coverage_pct", 95.0)),
        min_history_bars=int(br.get("min_history_bars", 252)),
        mcclellan_enabled=bool(br.get("mcclellan_enabled", True)),
        scoring=br_sc_cfg,
    )

    # Stage 4: Charts and Email configuration
    ch_raw = raw.get("charts", {})
    charts_cfg = ChartsConfig(
        enabled=bool(ch_raw.get("enabled", True)),
        dpi=int(ch_raw.get("dpi", 120)),
        lookback_bars=int(ch_raw.get("lookback_bars", 130)),
        monthly_lookback_bars=int(ch_raw.get("monthly_lookback_bars", 252)),
    )

    em_raw = raw.get("email", {})
    email_cfg = EmailConfig(
        enabled=bool(em_raw.get("enabled", False)),
        smtp_host_env=em_raw.get("smtp_host_env", "SMTP_HOST"),
        smtp_port_env=em_raw.get("smtp_port_env", "SMTP_PORT"),
        smtp_user_env=em_raw.get("smtp_user_env", "SMTP_USER"),
        smtp_password_env=em_raw.get("smtp_password_env", "SMTP_PASSWORD"),
        email_from_env=em_raw.get("email_from_env", "EMAIL_FROM"),
        email_to_env=em_raw.get("email_to_env", "EMAIL_TO"),
        require_tls=bool(em_raw.get("require_tls", True)),
    )

    sc_cat_raw = raw.get("scorecard_categories", {})
    scorecard_cat_cfg = ScorecardCategoriesConfig(
        enabled=bool(sc_cat_raw.get("enabled", True)),
        weights=sc_cat_raw.get("weights", {
            "trend_price": 0.30,
            "breadth": 0.20,
            "volatility_risk": 0.15,
            "rates_macro": 0.20,
            "sentiment_positioning": 0.15,
        }),
        regimes=sc_cat_raw.get("regimes", {
            "risk_on": 0.40,
            "constructive": 0.15,
            "neutral_lower": -0.15,
            "cautious_lower": -0.40,
        }),
    )

    def_exc_raw = raw.get("defensive_exceptions", None)
    sg_raw = raw.get("swing_gate", {})
    sg_def_exc = sg_raw.get("defensive_exceptions", False)
    sec_raw = raw.get("sectors", {})
    sec_def_exc = sec_raw.get("defensive_exceptions", False) if isinstance(sec_raw, dict) else False
    def_exc = bool(def_exc_raw if def_exc_raw is not None else (sg_def_exc or sec_def_exc))

    sectors_cfg = SectorsConfig(
        enabled=bool(sec_raw.get("enabled", True)) if isinstance(sec_raw, dict) else True,
        min_dollar_volume=float(sec_raw.get("min_dollar_volume", 20_000_000.0)) if isinstance(sec_raw, dict) else 20_000_000.0,
        max_dist_from_52w_high=float(sec_raw.get("max_dist_from_52w_high", 15.0)) if isinstance(sec_raw, dict) else 15.0,
        defensive_exceptions=def_exc,
    )

    swing_gate_cfg = SwingGateConfig(
        enabled=bool(sg_raw.get("enabled", True)),
        spy_symbol=sg_raw.get("spy_symbol", "SPY"),
        qqq_symbol=sg_raw.get("qqq_symbol", "QQQ"),
        ema_fast=int(sg_raw.get("ema_fast", 20)),
        dma_medium=int(sg_raw.get("dma_medium", 50)),
        vix_low=float(sg_raw.get("vix_low", 20.0)),
        vix_high=float(sg_raw.get("vix_high", 25.0)),
        breadth_min_pct=float(sg_raw.get("breadth_min_pct", 50.0)),
        breadth_defensive_pct=float(sg_raw.get("breadth_defensive_pct", 40.0)),
        defensive_exceptions=bool(sg_raw.get("defensive_exceptions", def_exc)),
    )

    tetf_raw = raw.get("theme_etfs", {})
    theme_items = [
        ThemeEtfItem(symbol=i["symbol"], name=i["name"], category=i.get("category", "Theme"))
        for i in tetf_raw.get("items", [])
    ]
    theme_etfs_cfg = ThemeEtfsConfig(
        enabled=bool(tetf_raw.get("enabled", True)),
        items=theme_items,
    )

    ca_exp_raw = raw.get("cross_assets_expanded", {})
    ca_items = [
        SymbolItem(symbol=i["symbol"], name=i["name"])
        for i in ca_exp_raw.get("items", [])
    ]
    cross_assets_expanded_cfg = CrossAssetsExpandedConfig(
        enabled=bool(ca_exp_raw.get("enabled", True)),
        items=ca_items,
    )

    fwd_cal_raw = raw.get("forward_calendar", {})
    forward_calendar_cfg = ForwardCalendarConfig(
        enabled=bool(fwd_cal_raw.get("enabled", True)),
        lookahead_days=int(fwd_cal_raw.get("lookahead_days", 14)),
        high_impact_rules=fwd_cal_raw.get("high_impact_rules", [
            "fomc decision", "fomc rate decision", "fomc press conference",
            "employment situation", "nonfarm payrolls", "consumer price index",
            "cpi yoy", "quarterly refunding", "chair keynote", "chair speech",
            "chair testimony", "general elections"
        ]),
    )

    earn_raw = raw.get("earnings", {})
    earnings_cfg = EarningsConfig(
        enabled=bool(earn_raw.get("enabled", True)),
        top_constituents_count=int(earn_raw.get("top_constituents_count", 30)),
        lookahead_days=int(earn_raw.get("lookahead_days", 7)),
    )

    sent_raw = raw.get("sentiment", {})
    sentiment_cfg = SentimentConfig(
        enabled=bool(sent_raw.get("enabled", True)),
        realized_vol_window=int(sent_raw.get("realized_vol_window", 20)),
    )

    return AppConfig(
        symbols=symbols_cfg,
        indicators=indicators_cfg,
        scoring=scoring_cfg,
        movers=movers_cfg,
        data=data_cfg,
        macro=macro_cfg,
        breadth=breadth_cfg,
        charts=charts_cfg,
        email=email_cfg,
        scorecard_categories=scorecard_cat_cfg,
        swing_gate=swing_gate_cfg,
        theme_etfs=theme_etfs_cfg,
        cross_assets_expanded=cross_assets_expanded_cfg,
        forward_calendar=forward_calendar_cfg,
        earnings=earnings_cfg,
        sentiment=sentiment_cfg,
        sectors=sectors_cfg,
        defensive_exceptions=def_exc,
    )
