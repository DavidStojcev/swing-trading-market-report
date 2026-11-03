"""Local caching layer using Parquet for market data."""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class ParquetCache:
    """Manages disk caching of ticker bar data in Parquet format."""

    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = Path(cache_dir)
        self.bars_dir = self.cache_dir / "bars"
        self.bars_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, ticker: str, interval: str = "1d") -> Path:
        """Sanitize ticker symbol for safe file path."""
        safe_ticker = ticker.replace("^", "IDX_").replace("/", "_").replace(".", "_")
        return self.bars_dir / f"{safe_ticker}_{interval}.parquet"

    def read_bars(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """Read cached bars for a ticker, optionally filtering by date range."""
        path = self._get_path(ticker, interval)
        if not path.exists():
            return None

        try:
            df = pd.read_parquet(path)
            if df.empty:
                return None

            # Ensure DatetimeIndex normalized to midnight tz-naive
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None).normalize()
            else:
                df.index = df.index.normalize()

            if start_date:
                df = df[df.index >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df.index <= pd.to_datetime(end_date)]

            return df if not df.empty else None
        except Exception as e:
            logger.warning("Error reading cache for %s: %s", ticker, e)
            return None

    def write_bars(
        self,
        ticker: str,
        df: pd.DataFrame,
        interval: str = "1d",
    ) -> None:
        """Write or update cached bars for a ticker."""
        if df.empty:
            return

        path = self._get_path(ticker, interval)
        try:
            # Normalize index
            clean_df = df.copy()
            if not isinstance(clean_df.index, pd.DatetimeIndex):
                clean_df.index = pd.to_datetime(clean_df.index)
            if clean_df.index.tz is not None:
                clean_df.index = clean_df.index.tz_convert(None).normalize()
            else:
                clean_df.index = clean_df.index.normalize()

            # Merge with existing if present
            if path.exists():
                try:
                    existing = pd.read_parquet(path)
                    if not isinstance(existing.index, pd.DatetimeIndex):
                        existing.index = pd.to_datetime(existing.index)
                    if existing.index.tz is not None:
                        existing.index = existing.index.tz_convert(None).normalize()
                    else:
                        existing.index = existing.index.normalize()

                    clean_df = pd.concat([existing, clean_df])
                    clean_df = clean_df[~clean_df.index.duplicated(keep="last")]
                    clean_df.sort_index(inplace=True)
                except Exception as ex:
                    logger.debug("Could not merge existing parquet cache for %s: %s", ticker, ex)

            clean_df.to_parquet(path, engine="pyarrow", index=True)
        except Exception as e:
            logger.warning("Error writing cache for %s: %s", ticker, e)
