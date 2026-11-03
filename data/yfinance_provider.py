"""YFinance implementation of DataProvider with rate-limiting, retries, and parquet caching."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import random
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import yfinance as yf

# Suppress benign yfinance pandas deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*inplace keyword.*")

from data.base import DataProvider
from data.cache import ParquetCache

logger = logging.getLogger(__name__)


class YFinanceDataProvider(DataProvider):
    """Resilient YFinance data provider supporting chunking, caching, and backoff."""

    def __init__(
        self,
        cache_dir: str = ".cache",
        batch_size: int = 50,
        request_delay: float = 0.05,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
    ):
        self.cache = ParquetCache(cache_dir=cache_dir)
        self.batch_size = batch_size
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self.info_cache_path = Path(cache_dir) / "ticker_info.json"
        self._info_cache: Dict[str, Dict[str, Any]] = self._load_info_cache()

    def _load_info_cache(self) -> Dict[str, Dict[str, Any]]:
        if self.info_cache_path.exists():
            try:
                with open(self.info_cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("Failed to read ticker_info cache: %s", e)
        return {}

    def _save_info_cache(self) -> None:
        try:
            with open(self.info_cache_path, "w", encoding="utf-8") as f:
                json.dump(self._info_cache, f, indent=2)
        except Exception as e:
            logger.debug("Failed to save ticker_info cache: %s", e)

    def _extract_ticker_df(self, raw_df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """Extract a single ticker's DataFrame with clean ['Open', 'High', 'Low', 'Close', 'Volume']."""
        if raw_df is None or raw_df.empty:
            return pd.DataFrame()

        df = pd.DataFrame()
        if isinstance(raw_df.columns, pd.MultiIndex):
            lvl0 = raw_df.columns.get_level_values(0)
            lvl1 = raw_df.columns.get_level_values(1)

            if ticker in lvl0:
                df = raw_df[ticker].copy()
            elif ticker in lvl1:
                sub = {}
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if (col, ticker) in raw_df.columns:
                        sub[col] = raw_df[(col, ticker)]
                df = pd.DataFrame(sub, index=raw_df.index)
        else:
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in raw_df.columns]
            df = raw_df[cols].copy()

        if df.empty:
            return pd.DataFrame()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = float("nan")

        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        if df.empty:
            return pd.DataFrame()

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None).normalize()
        else:
            df.index = df.index.normalize()

        df = df.sort_index()
        return df

    def _fetch_batch_with_retry(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch batch from yfinance with exponential backoff and jitter."""
        end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        end_str = end_ts.strftime("%Y-%m-%d")

        for attempt in range(1, self.max_retries + 1):
            try:
                if self.request_delay > 0:
                    time.sleep(self.request_delay + random.uniform(0.01, 0.05))

                data = yf.download(
                    tickers=tickers,
                    start=start_date,
                    end=end_str,
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                )
                if data is not None and not data.empty:
                    return data
            except Exception as e:
                sleep_secs = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    "Download attempt %d/%d failed for %d tickers: %s. Retrying in %.2fs",
                    attempt,
                    self.max_retries,
                    len(tickers),
                    e,
                    sleep_secs,
                )
                time.sleep(sleep_secs)

        logger.error("All %d retries failed for tickers batch of size %d", self.max_retries, len(tickers))
        return pd.DataFrame()

    def get_history(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        interval: str = "1d",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV bars with cache-first lookup and chunked network downloads."""
        results: Dict[str, pd.DataFrame] = {}
        missing_tickers: List[str] = []

        target_start = pd.to_datetime(start_date)
        target_end = pd.to_datetime(end_date)

        for t in tickers:
            cached_df = self.cache.read_bars(t, start_date=None, end_date=None, interval=interval)
            if cached_df is not None and not cached_df.empty:
                cached_min = cached_df.index.min()
                cached_max = cached_df.index.max()
                # Check if cached data covers the requested date window
                if cached_max >= target_end and cached_min <= target_start + pd.Timedelta(days=15):
                    sub = cached_df[(cached_df.index >= target_start) & (cached_df.index <= target_end)]
                    results[t] = sub if not sub.empty else cached_df
                    continue
            missing_tickers.append(t)

        if not missing_tickers:
            return results

        # Separate into stale tickers (cover start date, only need recent delta) vs fresh tickers (need full history)
        stale_tickers: List[str] = []
        fresh_tickers: List[str] = []
        for t in missing_tickers:
            c_df = self.cache.read_bars(t, start_date=None, end_date=None, interval=interval)
            if c_df is not None and not c_df.empty and c_df.index.min() <= target_start + pd.Timedelta(days=15):
                stale_tickers.append(t)
            else:
                fresh_tickers.append(t)

        # 1. Fetch fresh tickers needing full history
        if fresh_tickers:
            logger.info("Fetching full history for %d new/uninitialized tickers (%s to %s)", len(fresh_tickers), start_date, end_date)
            for i in range(0, len(fresh_tickers), self.batch_size):
                chunk = fresh_tickers[i : i + self.batch_size]
                raw_data = self._fetch_batch_with_retry(chunk, start_date, end_date, interval)
                for t in chunk:
                    ticker_df = self._extract_ticker_df(raw_data, t)
                    if not ticker_df.empty:
                        self.cache.write_bars(t, ticker_df, interval=interval)
                        full_df = self.cache.read_bars(t, start_date=start_date, end_date=end_date, interval=interval)
                        results[t] = full_df if full_df is not None and not full_df.empty else ticker_df
                    else:
                        results[t] = pd.DataFrame()

        # 2. Fetch incremental delta for stale tickers
        if stale_tickers:
            recent_start = (target_end - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
            logger.info("Fetching incremental update for %d cached tickers (%s to %s)", len(stale_tickers), recent_start, end_date)
            for i in range(0, len(stale_tickers), self.batch_size):
                chunk = stale_tickers[i : i + self.batch_size]
                raw_data = self._fetch_batch_with_retry(chunk, recent_start, end_date, interval)
                for t in chunk:
                    ticker_df = self._extract_ticker_df(raw_data, t)
                    if not ticker_df.empty:
                        self.cache.write_bars(t, ticker_df, interval=interval)
                        full_df = self.cache.read_bars(t, start_date=start_date, end_date=end_date, interval=interval)
                        results[t] = full_df if full_df is not None and not full_df.empty else ticker_df
                    else:
                        c_df = self.cache.read_bars(t, start_date=start_date, end_date=end_date, interval=interval)
                        results[t] = c_df if c_df is not None else pd.DataFrame()

        return results

    def get_ticker_info(self, ticker: str) -> Dict[str, Any]:
        """Fetch ticker metadata with local disk caching."""
        if ticker in self._info_cache:
            return self._info_cache[ticker]

        info_dict: Dict[str, Any] = {
            "symbol": ticker,
            "shortName": ticker,
            "sector": "Unknown",
            "marketCap": 10000000000,
            "regularMarketPrice": 0.0,
        }

        try:
            t = yf.Ticker(ticker)
            fast = getattr(t, "fast_info", None)
            if fast:
                mcap = getattr(fast, "market_cap", None)
                if mcap:
                    info_dict["marketCap"] = mcap
                last_p = getattr(fast, "last_price", None)
                if last_p:
                    info_dict["regularMarketPrice"] = last_p

            self._info_cache[ticker] = info_dict
        except Exception as e:
            logger.debug("Failed to fetch info for %s: %s", ticker, e)

        return info_dict

    def get_bulk_ticker_info(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch ticker metadata concurrently with thread pool."""
        res: Dict[str, Dict[str, Any]] = {}
        missing = [t for t in tickers if t not in self._info_cache]

        for t in tickers:
            if t in self._info_cache:
                res[t] = self._info_cache[t]

        if missing:
            logger.info("Fetching metadata for %d tickers in background threadpool", len(missing))
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(self.get_ticker_info, t): t for t in missing}
                for fut in as_completed(futures):
                    t = futures[fut]
                    try:
                        res[t] = fut.result()
                    except Exception:
                        res[t] = {"symbol": t, "shortName": t, "sector": "Unknown", "marketCap": 10000000000}
            self._save_info_cache()

        return res
