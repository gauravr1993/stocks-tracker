"""
data/sources/scrapers/economic_times.py
Economic Times Markets scraper.
Fetches paginated market news from ET's lazy-load endpoint.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

from .base import BaseNewsScraper, RawArticle

logger = logging.getLogger(__name__)

# ET uses this endpoint for paginated market news
ET_LAZY_URL   = "https://economictimes.indiatimes.com/lazyloadlistnew.cms"
ET_MARKETS_ID = "2146843"    # msid for ET Markets section
ET_BASE       = "https://economictimes.indiatimes.com"

# Date patterns ET uses
_DATE_PATTERNS = [
    # "15 Jan, 2025, 10:30 AM IST"
    (r"(\d{1,2}\s+\w{3},?\s+\d{4})", "%d %b %Y"),
    # "Jan 15, 2025"
    (r"(\w{3}\s+\d{1,2},?\s+\d{4})", "%b %d %Y"),
    # "15 Jan 2025"
    (r"(\d{1,2}\s+\w{3}\s+\d{4})", "%d %b %Y"),
    # Relative: "2 hours ago", "30 minutes ago" → today
]


class EconomicTimesScraper(BaseNewsScraper):

    source_name = "et_markets"
    base_url    = ET_LAZY_URL
    delay       = 1.5

    def fetch_page(self, page: int) -> list[RawArticle]:
        """Fetch one page from ET's lazy load endpoint."""
        params = {
            "msid":   ET_MARKETS_ID,
            "curpg":  page,
            "img":    0,
        }
        soup = self.get_soup(ET_LAZY_URL, params=params)
        if soup is None:
            return []

        articles = []
        for story in soup.select("div.eachStory"):
            try:
                title_tag = story.select_one("h3 a") or story.select_one("h4 a")
                time_tag  = story.select_one("time")
                desc_tag  = story.select_one("p")

                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                href     = title_tag.get("href", "")
                full_url = ET_BASE + href if href.startswith("/") else href
                raw_date = time_tag.get_text(strip=True) if time_tag else ""
                desc     = desc_tag.get_text(strip=True) if desc_tag else ""

                if not title or not full_url:
                    continue

                articles.append(RawArticle(
                    title       = title,
                    url         = full_url,
                    raw_date    = raw_date,
                    source      = self.source_name,
                    description = desc,
                    parsed_date = self.parse_date(raw_date),
                ))

            except Exception as exc:
                self.logger.debug("Skipping malformed story: %s", exc)
                continue

        return articles

    def parse_date(self, raw: str) -> Optional[date]:
        """
        Parse ET date strings like:
          "15 Jan, 2025, 10:30 AM IST"
          "2 hours ago"
          "30 minutes ago"
        """
        if not raw:
            return date.today()

        raw_clean = raw.strip()

        # Relative dates
        if "hour" in raw_clean.lower() or "minute" in raw_clean.lower() or "just now" in raw_clean.lower():
            return date.today()
        if "yesterday" in raw_clean.lower():
            return date.today() - timedelta(days=1)

        # Try each pattern
        for pattern, fmt in _DATE_PATTERNS:
            match = re.search(pattern, raw_clean, re.IGNORECASE)
            if match:
                try:
                    # Normalise: remove commas, collapse spaces
                    date_str = match.group(1).replace(",", "").strip()
                    date_str = re.sub(r"\s+", " ", date_str)
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue

        self.logger.debug("Could not parse ET date: %r", raw)
        return date.today()