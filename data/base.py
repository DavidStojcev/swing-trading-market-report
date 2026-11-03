"""Abstract DataProvider interface for financial market data."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd


class DataProvider(ABC):
    """Abstract base class for financial data providers."""

    @abstractmethod
    def get_history(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        interval: str = "1d",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch historical OHLCV bar data for a list of tickers.
        
        Args:
            tickers: List of ticker symbols (e.g. ['^GSPC', 'AAPL']).
            start_date: Start date string (YYYY-MM-DD).
            end_date: End date string (YYYY-MM-DD, inclusive).
            interval: Bar frequency, default '1d'.
            
        Returns:
            Dictionary mapping ticker symbol to pd.DataFrame with columns:
            ['Open', 'High', 'Low', 'Close', 'Volume'] indexed by datetime/date.
        """
        pass

    @abstractmethod
    def get_ticker_info(self, ticker: str) -> Dict[str, Any]:
        """Retrieve company and fundamental metadata for a ticker.
        
        Args:
            ticker: Ticker symbol (e.g. 'MSFT').
            
        Returns:
            Dictionary with metadata such as 'shortName', 'sector', 'marketCap'.
        """
        pass

    @abstractmethod
    def get_bulk_ticker_info(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Retrieve company and fundamental metadata for multiple tickers.
        
        Args:
            tickers: List of ticker symbols.
            
        Returns:
            Dictionary mapping ticker symbol to metadata dictionary.
        """
        pass
