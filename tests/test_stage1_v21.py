"""Acceptance tests for Change Request v2.1: Stage 1 (Factual and data-integrity bugs)."""

from datetime import date
import pytest
import pandas as pd

from data.calendar import MarketCalendar
from data.calendar_provider import OfficialScheduleCalendarProvider
from data.constituents import ConstituentManager
from data.fomc import OFFICIAL_FOMC_STATEMENTS, parse_fomc_statement_votes, resolve_fomc_schedule
from sections.commodities_cross_asset import build_commodities_cross_asset
from sections.conclusion import build_footer, DataSourceInfo
from sections.forward_calendar import build_forward_calendar
from sections.movers import build_movers
from scoring.engine import TrendScoringEngine
from config.settings import load_config


def test_1_1_fomc_statement_vote_parser_and_dissents():
    """Bug 1.1: FOMC Oct 28 vote shown as 10-2 with Cook and Hammack dissenting for a hike.
    
    Must not be identical to previous meeting (Sept 16 was 12-0 unanimous).
    """
    assert "2026-10-28" in OFFICIAL_FOMC_STATEMENTS
    assert "2026-09-16" in OFFICIAL_FOMC_STATEMENTS

    tally_oct = parse_fomc_statement_votes(OFFICIAL_FOMC_STATEMENTS["2026-10-28"])
    tally_sep = parse_fomc_statement_votes(OFFICIAL_FOMC_STATEMENTS["2026-09-16"])

    # Must not be identical tallies
    assert tally_oct.tally != tally_sep.tally
    assert tally_oct.tally == "10-2"
    assert tally_sep.tally == "12-0 unanimous"

    # Oct 28 dissenters and direction
    assert "Lisa D. Cook" in tally_oct.dissents
    assert "Beth M. Hammack" in tally_oct.dissents
    assert tally_oct.dissent_direction == "hike"
    assert "Cook and Hammack dissented in favor of a 25 bp hike" in tally_oct.dissent_summary

    # Period schedule resolution
    status = resolve_fomc_schedule("2026-10-30", fed_funds_rate=3.83, period_start_date="2026-10-23")
    assert status.occurred_in_period is True
    assert status.last_meeting_date == "2026-10-28"
    assert status.vote_count == "10-2"
    assert "Cook and Hammack dissented in favor of a 25 bp hike" in status.dissents
    assert status.next_meeting_date == "2026-12-09"


def test_1_2_fed_path_probabilities_structure():
    """Bug 1.2: Fed section provides Hold / +25 bp Hike / -25 bp Cut probabilities with source labeling."""
    from sections.fed_path import build_fed_path, FedPathData
    from render.html import render_html
    from sections.base import SectionResult

    fed_res = build_fed_path(macro_data=None, as_of_date="2026-10-30")
    data: FedPathData = fed_res.data
    assert hasattr(data, "market_implied_prob_hold")
    assert hasattr(data, "market_implied_prob_hike")
    assert hasattr(data, "market_implied_prob_cut")
    assert hasattr(data, "prob_source")
    assert data.vote_count == "10-2"


def test_1_3_prior_score_recomputed_and_differs_when_inputs_differ():
    """Bug 1.3: Prior-period score must recompute from prior-period inputs through same scoring function.
    
    Fails if prior score equals current score while inputs changed.
    """
    cfg = load_config()
    engine = TrendScoringEngine(cfg.scoring)
    
    dates = pd.date_range("2025-01-01", "2026-10-30", freq="B")
    from indicators.engine import compute_technicals

    # Build price data with distinct prices on Oct 23 vs Oct 30
    p_spx = [5000.0 + i * 2.0 for i in range(len(dates) - 5)] + [5920.0, 5900.0, 5870.0, 5840.0, 5820.0]
    v_spx = [1000000.0] * len(dates)
    df_spx = pd.DataFrame({"Open": p_spx, "High": [x + 10 for x in p_spx], "Low": [x - 10 for x in p_spx], "Close": p_spx, "Volume": v_spx}, index=dates)

    snap_curr = compute_technicals(df_spx[df_spx.index <= "2026-10-30"], "^GSPC", cfg.indicators, as_of_date="2026-10-30")
    snap_prior = compute_technicals(df_spx[df_spx.index <= "2026-10-23"], "^GSPC", cfg.indicators, as_of_date="2026-10-23")

    score_curr = engine.compute_scorecard(snap_curr, vix_current=19.42, vix_previous=18.13, report_type="weekly")
    score_prior = engine.compute_scorecard(snap_prior, vix_current=18.13, vix_previous=18.03, report_type="weekly")
    
    diff = score_curr.normalized_score - score_prior.normalized_score
    print(f"Current score: {score_curr.normalized_score:.4f}, Prior score: {score_prior.normalized_score:.4f}, Diff: {diff:+.4f}")
    assert abs(diff) > 0.01, f"Prior score must not equal current score when inputs changed: diff={diff}"


def test_1_4_commodities_prior_return_not_fabricated_zero():
    """Bug 1.4: Commodities prior return must be computed from price history; show n/a if missing, never 0.00%."""
    cfg = load_config()
    dates = pd.date_range("2026-08-01", "2026-10-30", freq="B")
    
    # Asset with price history: baseline price 70.0, prev baseline price 65.0, current 75.0
    prices = [65.0] * 30 + [70.0] * 25 + [75.0] * (len(dates) - 55)
    df_cl = pd.DataFrame({"Close": prices, "Volume": [1000] * len(dates)}, index=dates)

    # Asset with missing history
    df_empty = pd.DataFrame()

    bars = {"CL=F": df_cl, "BZ=F": df_empty}
    res = build_commodities_cross_asset(
        bars=bars,
        as_of_date="2026-10-30",
        baseline_date="2026-09-30",
        prev_baseline_date="2026-08-31",
        macro_data=None,
        cfg=cfg,
    )
    items = {it.symbol: it for it in res.data.items}
    
    # CL=F has real prior return (70 - 65) / 65 * 100 = 7.69%
    assert items["CL=F"].prior_period_ret is not None
    assert round(items["CL=F"].prior_period_ret, 2) == 7.69
    assert items["CL=F"].prior_period_ret != 0.0

    # BZ=F is unavailable: must be None (rendered as n/a), NOT 0.00%
    assert items["BZ=F"].prior_period_ret is None


def test_1_5_and_1_6_calendar_contains_nov_2_and_priors_match_actuals():
    """Bugs 1.5 & 1.6: Calendar starts on Nov 2 (ISM Manufacturing) and every Prior matches official latest actual."""
    cfg = load_config()
    provider = OfficialScheduleCalendarProvider()
    
    events = provider.get_upcoming_events(start_date="2026-10-30", end_date="2026-11-10", min_importance="medium")
    dates = [e.date for e in events]
    titles = [e.title for e in events]
    
    # Must contain Nov 2 (Monday, first trading day after Oct 30)
    assert "2026-11-02" in dates
    assert "ISM Manufacturing PMI" in titles
    
    # Must contain Nov 4 events
    assert "2026-11-04" in dates
    assert any("Treasury" in t for t in titles)
    assert any("ISM Services" in t for t in titles)
    
    # Priors must equal official actual prints:
    event_map = {e.title: e for e in events}
    
    # Jobless claims prior: 194k (not 216k)
    claims_ev = event_map.get("Initial Jobless Claims")
    assert claims_ev is not None
    assert claims_ev.previous == 194.0

    # Nonfarm payrolls prior: 29k
    payrolls_ev = event_map.get("Employment Situation (Nonfarm Payrolls)")
    assert payrolls_ev is not None
    assert payrolls_ev.previous == 29.0

    # Unemployment rate prior: 4.20% (not 4.30%)
    unemp_ev = event_map.get("Unemployment Rate")
    assert unemp_ev is not None
    assert unemp_ev.previous == 4.20


def test_1_7_and_1_8_movers_earnings_flag_and_outlier_filter():
    """Bugs 1.7 & 1.8: Movers in earnings window have Earnings?=YES and Cause=Earnings.
    
    Unconfirmed low-beta outliers with move > 30% on low volume are tagged with verify warning and excluded from headline top 5.
    """
    cal = MarketCalendar()
    cfg = load_config()
    cm = ConstituentManager()
    constituents = cm.get_universe()

    dates = pd.date_range("2025-01-01", "2026-10-30", freq="B")
    
    # Create synthetic price histories:
    # 1. INTC: reports earnings in window, drops 25% on 3.5x volume
    p_intc = [50.0] * (len(dates) - 5) + [45.0, 42.0, 39.0, 38.0, 37.5]
    v_intc = [1000000.0] * (len(dates) - 5) + [3500000.0] * 5
    df_intc = pd.DataFrame({"Close": p_intc, "Volume": v_intc}, index=dates)

    # 2. ACN: low-beta, jumps 35% on low volume (0.9x) with NO earnings
    p_acn = [180.0] * (len(dates) - 20) + [250.0] * 20
    v_acn = [500000.0] * len(dates)
    df_acn = pd.DataFrame({"Close": p_acn, "Volume": v_acn}, index=dates)

    bars = {"INTC": df_intc, "ACN": df_acn}
    earnings_syms = {"INTC"}

    res = build_movers(
        bars=bars,
        constituents=constituents,
        ticker_infos={},
        calendar=cal,
        as_of_session="2026-10-30",
        movers_cfg=cfg.movers,
        earnings_symbols=earnings_syms,
    )
    
    assert res.is_available is True
    w_movers = res.data.week
    
    # INTC must have Earnings?=YES and cause=Earnings
    intc_loser = next((l for l in w_movers.losers if l.symbol == "INTC"), None)
    assert intc_loser is not None
    assert intc_loser.has_earnings_in_window is True
    assert intc_loser.move_cause_tag == "Earnings"

    # ACN must be flagged as unconfirmed outlier and excluded from headline top gainers
    acn_in_top5 = any(g.symbol == "ACN" for g in res.data.month.gainers)
    assert not acn_in_top5, "ACN should be excluded from headline top 5 as an unconfirmed outlier"


def test_1_11_data_quality_footer_status_is_partial():
    """Bug 1.11: Data Quality footer status is PARTIAL with all missing items listed."""
    data_sources = [
        DataSourceInfo(
            source_name="Yahoo Finance (yfinance)",
            coverage="Core benchmark indices",
            fetch_time="Session 2026-10-30",
            status="PARTIAL",
            notes="^IXIC volume excluded (n/a); SPY proxy used.",
        ),
        DataSourceInfo(
            source_name="CBOE Options & Volatility",
            coverage="VIX & VRP",
            fetch_time="Session 2026-10-30",
            status="PARTIAL",
            notes="CME FedWatch probabilities n/a; AAII survey n/a.",
        ),
    ]
    missing = [
        "CME FedWatch rate probabilities (n/a)",
        "AAII Investor Sentiment survey (n/a)",
    ]
    footer_res = build_footer(data_sources=data_sources, overall_status="PARTIAL", missing_inputs=missing)
    assert footer_res.data["overall_status"] == "PARTIAL"
    assert len(footer_res.data["missing_inputs"]) == 2
    assert "CME FedWatch rate probabilities (n/a)" in footer_res.data["missing_inputs"]
