"""Programmatic retrieval, caching, and fallback for index constituents."""

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class Constituent:
    symbol: str
    name: str
    sector: str
    in_sp500: bool = False
    in_nasdaq100: bool = False


# Built-in baseline constituents fallback ensuring offline reliability and CI stability
FALLBACK_CONSTITUENTS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "GOOGL", "name": "Alphabet Inc. (Class A)", "sector": "Communication Services", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "GOOG", "name": "Alphabet Inc. (Class C)", "sector": "Communication Services", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "META", "name": "Meta Platforms Inc.", "sector": "Communication Services", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc.", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "V", "name": "Visa Inc.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "PG", "name": "Procter & Gamble Co.", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "MA", "name": "Mastercard Inc.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "HD", "name": "Home Depot Inc.", "sector": "Consumer Discretionary", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "CVX", "name": "Chevron Corporation", "sector": "Energy", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "MRK", "name": "Merck & Co. Inc.", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "ABBV", "name": "AbbVie Inc.", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "COST", "name": "Costco Wholesale Corp.", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "KO", "name": "Coca-Cola Co.", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "PEP", "name": "PepsiCo Inc.", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "ADBE", "name": "Adobe Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "WMT", "name": "Walmart Inc.", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "BAC", "name": "Bank of America Corp.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "CSCO", "name": "Cisco Systems Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "CRM", "name": "Salesforce Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "ACN", "name": "Accenture Plc", "sector": "Technology", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "MCD", "name": "McDonald's Corp.", "sector": "Consumer Discretionary", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "LIN", "name": "Linde Plc", "sector": "Materials", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "ABT", "name": "Abbott Laboratories", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "AMD", "name": "Advanced Micro Devices Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "QCOM", "name": "QUALCOMM Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "INTU", "name": "Intuit Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "TXN", "name": "Texas Instruments Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "AMGN", "name": "Amgen Inc.", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "HON", "name": "Honeywell International Inc.", "sector": "Industrials", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "IBM", "name": "International Business Machines", "sector": "Technology", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "NFLX", "name": "Netflix Inc.", "sector": "Communication Services", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "PM", "name": "Philip Morris International", "sector": "Consumer Staples", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "GE", "name": "General Electric Co.", "sector": "Industrials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "CAT", "name": "Caterpillar Inc.", "sector": "Industrials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "ISRG", "name": "Intuitive Surgical Inc.", "sector": "Health Care", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "DIS", "name": "Walt Disney Co.", "sector": "Communication Services", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "SPGI", "name": "S&P Global Inc.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "NOW", "name": "ServiceNow Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "BKNG", "name": "Booking Holdings Inc.", "sector": "Consumer Discretionary", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "GS", "name": "Goldman Sachs Group Inc.", "sector": "Financials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "RTX", "name": "RTX Corporation", "sector": "Industrials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "XOM", "name": "Exxon Mobil Corp.", "sector": "Energy", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "NEE", "name": "NextEra Energy Inc.", "sector": "Utilities", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "PLD", "name": "Prologis Inc.", "sector": "Real Estate", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "AMT", "name": "American Tower Corp.", "sector": "Real Estate", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "SHW", "name": "Sherwin-Williams Co.", "sector": "Materials", "in_sp500": True, "in_nasdaq100": False},
    {"symbol": "LRCX", "name": "Lam Research Corp.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "MU", "name": "Micron Technology Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "PANW", "name": "Palo Alto Networks Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "SNPS", "name": "Synopsys Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "CDNS", "name": "Cadence Design Systems", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "MELI", "name": "MercadoLibre Inc.", "sector": "Consumer Discretionary", "in_sp500": False, "in_nasdaq100": True},
    {"symbol": "PDD", "name": "PDD Holdings Inc.", "sector": "Consumer Discretionary", "in_sp500": False, "in_nasdaq100": True},
    {"symbol": "ASML", "name": "ASML Holding NV", "sector": "Technology", "in_sp500": False, "in_nasdaq100": True},
    {"symbol": "CRWD", "name": "CrowdStrike Holdings Inc.", "sector": "Technology", "in_sp500": True, "in_nasdaq100": True},
    {"symbol": "ARM", "name": "Arm Holdings Plc", "sector": "Technology", "in_sp500": False, "in_nasdaq100": True},
]


class ConstituentManager:
    """Manages scraping, disk caching, and fallbacks for S&P 500 and Nasdaq-100 constituents."""

    def __init__(self, cache_dir: str = ".cache", cache_days: int = 7):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "constituents.json"
        self.cache_ttl = cache_days * 86400

    def clean_symbol(self, symbol: str) -> str:
        """Format symbol for yfinance compatibility (e.g. BRK.B -> BRK-B)."""
        return symbol.strip().replace(".", "-").upper()

    def _fetch_sp500_web(self) -> Dict[str, Dict[str, str]]:
        """Scrape S&P 500 companies from Wikipedia."""
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table", {"id": "constituents"})
        if not table:
            table = soup.find("table", {"class": "wikitable"})

        constituents = {}
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) >= 4:
                raw_sym = cols[0].text.strip()
                symbol = self.clean_symbol(raw_sym)
                name = cols[1].text.strip()
                sector = cols[2].text.strip() if len(cols) > 2 else "Unknown"
                constituents[symbol] = {"name": name, "sector": sector}

        return constituents

    def _fetch_nasdaq100_web(self) -> Dict[str, Dict[str, str]]:
        """Scrape Nasdaq-100 companies from Wikipedia."""
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table", {"id": "constituents"})
        if not table:
            # Look for table with ticker column
            for t in soup.find_all("table", {"class": "wikitable"}):
                if "Ticker" in t.text or "Symbol" in t.text:
                    table = t
                    break

        constituents = {}
        if table:
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) >= 2:
                    # In Wikipedia Nasdaq-100, column 1 is company, column 2 is ticker or vice versa
                    col0 = cols[0].text.strip()
                    col1 = cols[1].text.strip()
                    if len(col1) <= 6 and col1.isupper():
                        symbol = self.clean_symbol(col1)
                        name = col0
                    else:
                        symbol = self.clean_symbol(col0)
                        name = col1
                    sector = cols[2].text.strip() if len(cols) > 2 else "Technology"
                    constituents[symbol] = {"name": name, "sector": sector}

        return constituents

    def get_universe(self, force_refresh: bool = False) -> List[Constituent]:
        """Get deduplicated S&P 500 + Nasdaq-100 universe."""
        if not force_refresh and self.cache_file.exists():
            try:
                mtime = self.cache_file.stat().st_mtime
                if (time.time() - mtime) < self.cache_ttl:
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return [Constituent(**item) for item in data]
            except Exception as e:
                logger.warning("Error reading constituents cache: %s", e)

        # Attempt web scraping
        universe_dict: Dict[str, Constituent] = {}
        scraped_ok = False

        try:
            sp500_data = self._fetch_sp500_web()
            for sym, info in sp500_data.items():
                universe_dict[sym] = Constituent(
                    symbol=sym,
                    name=info["name"],
                    sector=info["sector"],
                    in_sp500=True,
                    in_nasdaq100=False,
                )

            try:
                ndx_data = self._fetch_nasdaq100_web()
                for sym, info in ndx_data.items():
                    if sym in universe_dict:
                        universe_dict[sym].in_nasdaq100 = True
                    else:
                        universe_dict[sym] = Constituent(
                            symbol=sym,
                            name=info["name"],
                            sector=info["sector"],
                            in_sp500=False,
                            in_nasdaq100=True,
                        )
            except Exception as ex_ndx:
                logger.warning("Nasdaq-100 scraping failed: %s; continuing with S&P 500", ex_ndx)

            if len(universe_dict) > 400:
                scraped_ok = True
        except Exception as e:
            logger.warning("Web scraping constituents failed: %s; using fallback dataset", e)

        if not scraped_ok:
            for item in FALLBACK_CONSTITUENTS:
                sym = item["symbol"]
                universe_dict[sym] = Constituent(**item)

        result = list(universe_dict.values())

        # Save to cache
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump([asdict(c) for c in result], f, indent=2)
        except Exception as e:
            logger.warning("Failed to write constituents cache: %s", e)

        return result
