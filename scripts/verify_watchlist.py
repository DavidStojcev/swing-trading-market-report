"""Standalone verification script for Watchlist Panel (Task 3.2)."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from sections import build_watchlist_section, WatchlistData, WatchlistItem
from sections.watchlist import load_watchlist_tickers, resolve_long_permitted, compute_atr_14


def main():
    print("=== TASK 3.2: WATCHLIST PANEL VERIFICATION ===")

    # 1. Test CSV Parsing
    csv_file = Path("watchlist.csv")
    assert csv_file.exists(), "watchlist.csv must exist in workspace root!"
    tickers = load_watchlist_tickers(csv_file)
    print(f"1. Parsed {len(tickers)} tickers from watchlist.csv:")
    print(f"   Tickers: {', '.join(tickers)}")
    assert len(tickers) >= 15, f"Expected at least 15 tickers, got {len(tickers)}"

    # 2. Test Long Gate Posture Mapping
    print("\n2. Verifying Model Filter Status Derivation:")
    posture_checks = [
        ("DEFENSIVE", "INACTIVE (Gate Defensive)"),
        ("CAUTIOUS", "SELECTIVE (Conservative)"),
        ("OPEN", "ACTIVE (Favorable Trend)"),
        ("REDUCED", "SELECTIVE (Conservative)"),
        ("SELECTIVE", "SELECTIVE (Conservative)"),
        ("FULL", "ACTIVE (Favorable Trend)"),
    ]
    for posture, expected in posture_checks:
        actual = resolve_long_permitted(posture)
        assert actual == expected, f"Failed for {posture}: expected {expected}, got {actual}"
        print(f"   Gate '{posture}' -> '{actual}' [PASS]")

    # 3. Test Missing File Graceful Degradation
    print("\n3. Testing Graceful Handling of Missing File:")
    res_missing = build_watchlist_section("non_existent_watchlist.csv", fallback_to_default=False)
    assert not res_missing.is_available, "Missing file should yield unavailable status"
    assert res_missing.status == "unavailable"
    print(f"   Status: '{res_missing.status}' | Error: '{res_missing.error_message}' [PASS]")

    # 4. Test Metric Calculations with Synthetic Bars
    print("\n4. Testing Indicator Calculations (20-DMA, 50-DMA, 14D-ATR%, 3M RS):")
    dates = pd.date_range("2026-06-01", "2026-10-30", freq="B")
    spy_df = pd.DataFrame({
        "Open": 500.0,
        "High": 505.0,
        "Low": 495.0,
        "Close": 500.0 + (np.arange(len(dates)) * 0.5),
        "Volume": 50_000_000.0,
    }, index=dates)

    # Stock with +10% above 50-DMA and 20-DMA
    stock_closes = 100.0 + (np.arange(len(dates)) * 0.4)
    stock_df = pd.DataFrame({
        "Open": stock_closes,
        "High": stock_closes + 2.0,
        "Low": stock_closes - 1.5,
        "Close": stock_closes,
        "Volume": 10_000_000.0,
    }, index=dates)

    equity_bars = {"AAPL": stock_df, "NVDA": stock_df}

    res = build_watchlist_section(
        watchlist_path=csv_file,
        bars={"SPY": spy_df},
        equity_bars=equity_bars,
        gate_posture="DEFENSIVE",
        as_of_date="2026-10-30",
    )
    assert res.is_available, "Expected available SectionResult"
    data: WatchlistData = res.data
    print(f"   Total items: {data.total_count}")
    print(f"   Gate posture: {data.gate_posture}")
    print(f"   Long directive default: {data.long_permitted_default}")
    print(f"   Blocked count: {data.blocked_count}")

    aapl = next(it for it in data.items if it.ticker == "AAPL")
    print(f"\n   AAPL metrics:")
    print(f"     Name: {aapl.name}")
    print(f"     Sector: {aapl.sector}")
    print(f"     Close: \\${aapl.close:,.2f}")
    print(f"     Dist 20-DMA: {aapl.dist_20dma_pct:+.2f}%")
    print(f"     Dist 50-DMA: {aapl.dist_50dma_pct:+.2f}%")
    print(f"     14D ATR%: {aapl.atr_pct:.2f}%")
    print(f"     RS vs SPY: {aapl.rs_vs_spy:+.2f}%")
    print(f"     Long Permitted: {aapl.long_permitted}")

    assert aapl.dist_20dma_pct is not None
    assert aapl.dist_50dma_pct is not None
    assert aapl.atr_pct is not None
    assert aapl.rs_vs_spy is not None
    assert aapl.long_permitted == "INACTIVE (Gate Defensive)"

    print("\nALL WATCHLIST TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
