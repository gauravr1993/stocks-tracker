"""
data/sources/scrapers/base.py
Abstract base class for all news scrapers.
Each source implements fetch() and optionally parse_date().
Symbol extraction is handled centrally by the SymbolExtractor.
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Shared request session ────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    })
    return session


# ── Raw article schema ────────────────────────────────────────────────────────

class RawArticle:
    """Intermediate representation before mapping to news_events schema."""
    __slots__ = [
        "title", "description", "url", "raw_date",
        "parsed_date", "source", "scraped_at",
    ]

    def __init__(self, title: str, url: str, raw_date: str,
                 source: str, description: str = "",
                 parsed_date: Optional[date] = None):
        self.title       = title.strip()
        self.description = description.strip()
        self.url         = url.strip()
        self.raw_date    = raw_date.strip()
        self.source      = source
        self.parsed_date = parsed_date or date.today()
        self.scraped_at  = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ── Base scraper ──────────────────────────────────────────────────────────────

class BaseNewsScraper(ABC):
    """
    All scrapers inherit from this. Subclasses implement:
      - source_name   (class attribute)
      - fetch_page()  (fetch one page of articles)
      - parse_date()  (convert raw date string to date object)
    """
    source_name: str = "unknown"
    base_url:    str = ""
    delay:       float = 1.5    # seconds between page requests

    def __init__(self):
        self.session = _make_session()
        self.logger  = logging.getLogger(f"scraper.{self.source_name}")

    @abstractmethod
    def fetch_page(self, page: int) -> list[RawArticle]:
        """Fetch one page of articles. page is 0-indexed."""
        ...

    @abstractmethod
    def parse_date(self, raw: str) -> Optional[date]:
        """Parse source-specific date string to a date object."""
        ...

    def fetch(
        self,
        pages: int = 5,
        stop_before: Optional[date] = None,
    ) -> list[RawArticle]:
        """
        Fetch multiple pages, stopping early if articles are older than stop_before.

        Args:
            pages:       Max pages to fetch
            stop_before: Stop when article date < this date (incremental mode)

        Returns:
            List of RawArticle objects
        """
        all_articles: list[RawArticle] = []

        for page in range(pages):
            try:
                self.logger.debug("Fetching page %d/%d", page + 1, pages)
                articles = self.fetch_page(page)

                if not articles:
                    self.logger.info("Page %d empty — stopping", page + 1)
                    break

                # Parse dates and apply stop_before filter
                for art in articles:
                    if art.parsed_date is None:
                        art.parsed_date = self.parse_date(art.raw_date) or date.today()

                if stop_before:
                    articles = [a for a in articles if a.parsed_date >= stop_before]
                    if not articles:
                        self.logger.info("All articles on page %d older than %s — stopping",
                                         page + 1, stop_before)
                        break

                all_articles.extend(articles)
                self.logger.info("Page %d: %d articles (total %d)",
                                 page + 1, len(articles), len(all_articles))

            except Exception as exc:
                self.logger.error("Page %d failed: %s", page + 1, exc)

            if page < pages - 1:
                time.sleep(self.delay)

        return all_articles

    def get_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """Fetch URL and return BeautifulSoup, or None on error."""
        try:
            response = self.session.get(url, timeout=15, **kwargs)
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except Exception as exc:
            self.logger.warning("GET %s failed: %s", url, exc)
            return None

    def to_news_events(
        self,
        articles: list[RawArticle],
        symbol_map: dict[str, Optional[str]],
    ) -> list[dict]:
        """
        Convert RawArticles to news_events rows using a pre-built symbol map.

        Args:
            articles:   List of RawArticle objects
            symbol_map: {article.url: nse_symbol_or_None}

        Returns:
            List of dicts ready for Supabase insert
        """
        rows = []
        for art in articles:
            symbol = symbol_map.get(art.url)
            rows.append({
                "symbol":       f"{symbol}.NS" if symbol else None,
                "event_date":   art.parsed_date.isoformat() if art.parsed_date else date.today().isoformat(),
                "published_at": art.scraped_at,
                "headline":     art.title[:500],
                "summary":      art.description[:1000] if art.description else None,
                "source":       self.source_name,
                "url":          art.url,
                "category":     "other",    # overridden by SymbolExtractor if available
                "is_processed": False,
            })
        return rows