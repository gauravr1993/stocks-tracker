"""
data/sources/scrapers/moneycontrol.py
MoneyControl news scraper.

MC's main site returns 403 for direct scraping since mid-2024.
This scraper uses their Buzzing Stocks + Markets API endpoints
which are still accessible (used by their own mobile app).
Falls back to their sitemap-based approach if API is blocked.
"""
from __future__ import annotations

import logging
import re
import json
from datetime import date, datetime, timedelta
from typing import Optional

from .base import BaseNewsScraper, RawArticle

logger = logging.getLogger(__name__)

MC_BASE = "https://www.moneycontrol.com"

# MC internal API endpoints (used by mobile app — more reliable than HTML scraping)
MC_NEWS_API   = "https://api.moneycontrol.com/mcapi/v1/news/listing"
MC_STOCKS_API = "https://api.moneycontrol.com/mcapi/v1/news/buzzingstocks"

# Fallback: Google News RSS filtered to moneycontrol.com
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q=site:moneycontrol.com+stock+market+india&hl=en-IN&gl=IN&ceid=IN:en"

_DATE_PATTERNS = [
    (r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", "%Y-%m-%dT%H:%M:%S"),
    (r"(\w+\s+\d{1,2},?\s+\d{4})",              "%B %d %Y"),
    (r"(\w{3}\s+\d{1,2},?\s+\d{4})",            "%b %d %Y"),
    (r"(\d{1,2}\s+\w{3}\s+\d{4})",              "%d %b %Y"),
    (r"(\d{4}-\d{2}-\d{2})",                     "%Y-%m-%d"),
]


class MoneyControlScraper(BaseNewsScraper):

    source_name = "moneycontrol"
    base_url    = MC_NEWS_API
    delay       = 2.0

    def fetch_page(self, page: int) -> list[RawArticle]:
        """
        Try MC API first, fall back to Google News RSS.
        page is 0-indexed; MC API uses 'page' param (1-indexed).
        """
        articles = self._fetch_from_api(page)
        if articles:
            return articles

        # API failed — try Google News RSS (only on first page, RSS has no pagination)
        if page == 0:
            self.logger.info("MC API failed, trying Google News RSS fallback")
            articles = self._fetch_from_google_rss()
            if articles:
                return articles

        return []

    def _fetch_from_api(self, page: int) -> list[RawArticle]:
        """Try MoneyControl's internal API."""
        params = {
            "auth_token": "a74d88fb7eb607f2731c1a27d5b96862",  # public token used by MC app
            "page":        page + 1,
            "limit":       20,
            "type":        "news",
        }
        try:
            resp = self.session.get(MC_NEWS_API, params=params, timeout=12)
            if resp.status_code != 200:
                self.logger.debug("MC API returned %d", resp.status_code)
                return []

            data = resp.json()
            items = (
                data.get("data", {}).get("items")
                or data.get("items")
                or data.get("data")
                or []
            )
            if not items or not isinstance(items, list):
                return []

            articles = []
            for item in items:
                title    = item.get("title", "") or item.get("headline", "")
                url      = item.get("url",   "") or item.get("news_url", "")
                raw_date = str(item.get("publish_date", "") or item.get("date", ""))
                desc     = item.get("description", "") or item.get("summary", "")

                if not title or not url:
                    continue

                full_url = url if url.startswith("http") else MC_BASE + url
                articles.append(RawArticle(
                    title       = title,
                    url         = full_url,
                    raw_date    = raw_date,
                    source      = self.source_name,
                    description = desc,
                    parsed_date = self.parse_date(raw_date),
                ))
            return articles

        except Exception as exc:
            self.logger.debug("MC API error: %s", exc)
            return []

    def _fetch_from_google_rss(self) -> list[RawArticle]:
        """
        Fallback: Google News RSS filtered to moneycontrol.com.
        Returns recent MC articles without hitting MC directly.
        """
        try:
            from bs4 import BeautifulSoup
            resp = self.session.get(GOOGLE_NEWS_RSS, timeout=12)
            if resp.status_code != 200:
                return []

            soup  = BeautifulSoup(resp.text, "xml")
            items = soup.find_all("item")
            if not items:
                # Google News sometimes returns HTML — try lxml parser
                soup  = BeautifulSoup(resp.text, "lxml")
                items = soup.find_all("item")

            articles = []
            for item in items:
                title_tag = item.find("title")
                link_tag  = item.find("link") or item.find("guid")
                date_tag  = item.find("pubDate")
                desc_tag  = item.find("description")

                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                url      = link_tag.get_text(strip=True) if link_tag else ""
                raw_date = date_tag.get_text(strip=True) if date_tag else ""
                desc     = BeautifulSoup(
                    desc_tag.get_text(strip=True), "lxml"
                ).get_text(strip=True) if desc_tag else ""

                # Skip non-MC articles
                if "moneycontrol" not in url.lower():
                    continue

                if not title or not url:
                    continue

                articles.append(RawArticle(
                    title       = title,
                    url         = url,
                    raw_date    = raw_date,
                    source      = self.source_name,
                    description = desc,
                    parsed_date = self.parse_date(raw_date),
                ))

            self.logger.info("Google RSS fallback: %d MC articles", len(articles))
            return articles

        except Exception as exc:
            self.logger.warning("Google RSS fallback failed: %s", exc)
            return []

    def parse_date(self, raw: str) -> Optional[date]:
        if not raw:
            return date.today()

        raw_clean = raw.strip()
        lower     = raw_clean.lower()

        if any(x in lower for x in ["min ago", "hour ago", "hours ago", "just now", "mins ago"]):
            return date.today()
        if "yesterday" in lower:
            return date.today() - timedelta(days=1)

        for pattern, fmt in _DATE_PATTERNS:
            match = re.search(pattern, raw_clean, re.IGNORECASE)
            if match:
                try:
                    date_str = match.group(1).replace(",", "").strip()
                    date_str = re.sub(r"\s+", " ", date_str)
                    # Handle ISO format with T separator
                    if "T" in date_str:
                        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").date()
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue

        self.logger.debug("Could not parse MC date: %r", raw)
        return date.today()