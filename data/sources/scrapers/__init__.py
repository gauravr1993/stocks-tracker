"""
data/sources/scrapers/
News scraper framework — add new sources by creating a subclass of BaseNewsScraper.
"""
from .base             import BaseNewsScraper, RawArticle
from .economic_times   import EconomicTimesScraper
from .moneycontrol     import MoneyControlScraper
from .symbol_extractor import SymbolExtractor
from .ingest_news      import ingest_scraped_news, SCRAPERS

__all__ = [
    "BaseNewsScraper",
    "RawArticle",
    "EconomicTimesScraper",
    "MoneyControlScraper",
    "SymbolExtractor",
    "ingest_scraped_news",
    "SCRAPERS",
]