"""
data/sources/scrapers/ingest_news.py
Orchestrates all scrapers → symbol extraction → Supabase insert.
Called by run_ingestion.py daily job.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

from .economic_times import EconomicTimesScraper
from .moneycontrol   import MoneyControlScraper
from .symbol_extractor import SymbolExtractor
from data.storage.db import insert_rows, log_ingestion

logger = logging.getLogger(__name__)

# All registered scrapers — add new ones here
SCRAPERS = {
    "et_markets":   EconomicTimesScraper,
    "moneycontrol": MoneyControlScraper,
}


def ingest_scraped_news(
    sources:    Optional[list[str]] = None,
    days_back:  int  = 2,
    pages:      int  = 5,
    use_groq:   bool = True,
) -> dict:
    """
    Run all (or selected) scrapers, extract symbols, insert into news_events.

    Args:
        sources:   List of source keys to run (default: all)
        days_back: Only keep articles from last N days
        pages:     Max pages to fetch per source
        use_groq:  Use Groq API for symbol extraction fallback

    Returns:
        Summary dict with counts per source
    """
    t0 = time.time()
    stop_before = date.today() - timedelta(days=days_back)
    sources     = sources or list(SCRAPERS.keys())
    extractor   = SymbolExtractor(use_groq=use_groq)

    summary = {}
    total_inserted = 0

    for source_key in sources:
        if source_key not in SCRAPERS:
            logger.warning("Unknown source: %s — skipping", source_key)
            continue

        logger.info("── Scraping %s ──", source_key)
        scraper = SCRAPERS[source_key]()

        # Fetch articles
        articles = scraper.fetch(pages=pages, stop_before=stop_before)
        if not articles:
            logger.info("%s: no articles fetched", source_key)
            summary[source_key] = {"fetched": 0, "inserted": 0}
            continue

        logger.info("%s: fetched %d articles", source_key, len(articles))

        # Extract symbols
        symbol_map = extractor.extract_batch(articles)

        # Convert to news_events rows
        rows = scraper.to_news_events(articles, symbol_map)

        # Insert into Supabase
        if rows:
            insert_rows("news_events", rows)
            total_inserted += len(rows)

        matched = sum(1 for v in symbol_map.values() if v)
        summary[source_key] = {
            "fetched":  len(articles),
            "inserted": len(rows),
            "matched":  matched,
        }
        logger.info("%s: inserted %d rows (%d with symbol)", source_key, len(rows), matched)

    duration = time.time() - t0
    log_ingestion(
        job_name  = "scraped_news",
        status    = "success",
        duration  = duration,
        inserted  = total_inserted,
        metadata  = {"sources": sources, "days_back": days_back, **summary},
    )

    logger.info("News scraping done — %d total rows in %.1fs", total_inserted, duration)
    return summary