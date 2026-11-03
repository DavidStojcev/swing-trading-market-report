# Changelog

All notable changes to the US Market Report Generator across project milestones.

---

## [Stage 4] - Charts, Automated Scheduling & Email Delivery

### Added
- **Publication-Quality Chart Engine** (`render/charts.py`):
  - Headless `matplotlib` generation producing transparent, theme-neutral PNG charts for all report sections:
    1. S&P 500 price with 20/50/200 DMA over trailing 6–12 months.
    2. Nasdaq-100 price with 20/50/200 DMA over trailing 6–12 months.
    3. SPDR Sector performance horizontal bar chart (sorted, green/red bars).
    4. S&P 500 Market Breadth over time (% above 50 & 200 DMA with 40%/60% threshold lines).
    5. Cboe Volatility Index (VIX) regime with 20 (cautious) and 25 (fear) boundary lines.
    6. US Treasury 10Y yield and 2s10s yield curve spread (stacked subplots with inversion highlights).
    7. Top Movers horizontal bar chart for the report period.
  - Automatically embedded as inline base64 data URIs in HTML and linked as standalone PNG files in Markdown.
  - Fault-tolerant fallback: skips charts with missing data without failing the report run.
- **Session-Aware Scheduling & Calendar Logic** (`data/calendar.py`):
  - `is_last_trading_day_of_week(dt)`: accurately detects the week's final trading session, accounting for Friday market holidays (e.g. Good Friday).
  - `is_last_trading_day_of_month(dt)`: accurately detects the month's final trading session, accounting for weekends and holiday closures.
  - `is_scheduled_day_for_report(report_type, dt)`: checks if the report is due today.
  - CLI flag `--if-scheduled-day`: exits cleanly with code 0 and an informative log message when a report is not due today.
- **Automated GitHub Actions Workflow** (`.github/workflows/market_report.yml`):
  - Scheduled run triggered at 21:00 UTC Monday–Friday (ensuring market close in both EDT and EST).
  - Handles DST shifts and market holidays via `--if-scheduled-day`.
  - Persistent caching for `.cache/` (parquet bars, snapshots.db, FRED cache) across workflow runs.
  - Artifact upload of generated Markdown, HTML, and EML reports with 30-day retention.
  - `workflow_dispatch` manual trigger with dropdown selection for report type, target date, and email dispatch.
- **MIME Email Delivery & Dry-Run Export** (`delivery/email_sender.py`):
  - SMTP delivery with mandatory TLS and authentication.
  - Multipart MIME architecture:
    - Plain-text fallback summary.
    - Rich HTML body with inline CID attachments (`<img src="cid:chart_name">`).
    - Standalone full HTML report file attached.
  - Standard subject line format: `[Daily|Weekly|Monthly] Market Report - YYYY-MM-DD - {Bullish|Neutral|Bearish}`.
  - CLI flag `--dry-run-email`: exports compliant RFC 2822 `.eml` files to disk without sending.
  - CLI flag `--email` and `--no-email`: toggles SMTP dispatch; logs errors without crashing the run if delivery fails.
- **Structured Rotating File Logging**:
  - `RotatingFileHandler` writing up to 5MB logs with 3 backups to `logs/market_report.log`.
- **Test Suite Expansion**:
  - `tests/test_scheduler.py`: tests trading day, holiday cases (Good Friday, month on weekend), and `--if-scheduled-day`.
  - `tests/test_charts.py`: tests all 7 chart generators and missing data resilience.
  - `tests/test_email.py`: tests MIME construction, CID embedding, `.eml` dry-run, and SMTP failure paths.

---

## [Stage 3] - Market Breadth & Leadership Divergence

### Added
- **Vectorized Breadth Engine** (`indicators/breadth.py`):
  - Fast matrix operations across S&P 500 constituents (~35ms calculation time).
  - Reuses constituent bars from Top Movers without duplicate network downloads.
  - Enforces $\ge 252$ trading days filter, skipping and logging recent additions (`FDXF`, `HONA`, `Q`, `VYLR`) to achieve 99.2% clean universe coverage.
  - Moving average participation: % of stocks above 20, 50, and 200 DMA with period deltas.
  - Advance/Decline metrics: Advancers, Decliners, Unchanged, A/D Ratio, Cumulative A/D Line, and Confirmation vs. Index Divergence.
  - Trailing 252-day New 52-Week Highs vs. Lows and Net New Highs.
  - Equal-Weight vs. Cap-Weight Divergence: RSP vs. SPY comparison flagging "Narrow Leadership" when cap-weight outperforms equal-weight by $> 1.0\%$.
  - McClellan Oscillator: 19-EMA minus 39-EMA of daily net advances.
  - Plain-language Breadth Read sentence synthesized into executive summary.
- **Scoring Integration** (`scoring/rules.py`, `scoring/engine.py`):
  - 5 configurable breadth votes with weights and thresholds in `config/config.yaml`:
    - `stocks_above_50_dma` (>60% -> +1; <40% -> -1)
    - `stocks_above_200_dma` (>60% -> +1; <40% -> -1)
    - `net_new_highs` (positive and rising -> +1; strongly negative -> -1)
    - `narrow_leadership` (flagged -> -1; broad leadership -> +1)
    - `ad_line_confirmation` (confirming -> +1; divergence warning -> -1)
  - Breadth votes transparently displayed in conclusion voting scorecard.
- **Section 7: Market Breadth** (`sections/breadth.py`):
  - Standalone Market Breadth section rendered in Markdown and HTML.
  - KPI metric cards, moving average participation matrix, leadership split, and McClellan oscillator gauge.
  - Mandatory survivorship bias disclaimer in section and footer.
- **Snapshot Integration** (`storage/snapshots.py`):
  - SQLite persistence of breadth metrics enabling automatic period-over-period delta tracking.
- **Test Suite** (`tests/test_breadth.py`):
  - 7 comprehensive unit tests verifying MA breadth, A/D counts, 52W highs/lows, narrow leadership, McClellan oscillator, coverage filtering, and scoring votes.

---

## [Stage 2] - Macroeconomic & Economic Events
- FRED API integration for Inflation, Labor, Rates, and Activity.
- Finnhub & FMP economic and earnings calendar integration.
- Cross-asset snapshot (DXY, WTI Oil, Gold).
- Monthly report macroeconomic indicators history matrix & SVG charts.
- Macro scoring votes integrated into trend engine.

---

## [Stage 1] - Core Multi-Period Market Report Pipeline
- Daily, Weekly, and Monthly reports from a single modular codebase.
- DataProvider abstraction with yfinance provider, chunking, retry/backoff, and parquet caching.
- S&P 500 & Nasdaq-100 constituents programmatic scraper.
- Technical indicators: 20/50/200 DMA, Cross, RSI(14), MACD, ADX.
- 11 SPDR Sector ETFs relative strength ranking vs. SPY.
- Top Movers universe filtering ($5 price, 1M vol, $2B cap).
- Explainable voting scorecard (+1 / 0 / -1) and verdict mapping.
- Dual Markdown and self-contained HTML rendering with light/dark mode.
- SQLite snapshot state store.
