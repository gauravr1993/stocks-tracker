"""
data/sources/bse_announcements.py
Fetch corporate announcements from BSE's public API.
This is the best free source for structured Indian corporate events:
dividends, results, splits, board meetings, etc.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

import requests

from data.storage.db import upsert_rows

logger = logging.getLogger(__name__)

BSE_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer":         "https://www.bseindia.com/",
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# BSE category → our category mapping
CATEGORY_MAP = {
    "Results":                "earnings",
    "Dividend":               "dividend",
    "Board Meeting":          "earnings",
    "AGM/EGM":                "mgmt",
    "Bonus":                  "split",
    "Stock Split":            "split",
    "Rights":                 "split",
    "Buyback":                "mgmt",
    "Insider Trading":        "mgmt",
    "Merger/Amalgamation":    "mgmt",
    "Change in Management":   "mgmt",
    "Credit Rating":          "macro",
    "Others":                 "other",
}


def _prime_session() -> requests.Session:
    """Create a session with BSE cookies primed."""
    session = requests.Session()
    try:
        session.get("https://www.bseindia.com", headers=HEADERS, timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return session


def fetch_bse_announcements(
    symbol: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    category: str = "",
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Fetch announcements from BSE API.

    Args:
        symbol:    NSE symbol (converted to BSE format internally)
        from_date: Start date (default: 30 days ago)
        to_date:   End date (default: today)
        category:  BSE category filter (empty = all)

    Returns:
        List of parsed announcement dicts
    """
    to_dt   = to_date   or date.today()
    from_dt = from_date or (to_dt - timedelta(days=30))

    params = {
        "strCat":     category,
        "strPrevDate": from_dt.strftime("%Y%m%d"),
        "strScrip":   "",                       # BSE scrip code — we filter by symbol later
        "strSearch":  "P",
        "strToDate":  to_dt.strftime("%Y%m%d"),
        "strType":    "C",
        "subcategory": "-1",
    }

    url = f"{BSE_BASE}/AnnSubCategoryGetData/w"

    sess = session or _prime_session()
    try:
        response = sess.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error("BSE announcements fetch failed: %s", exc)
        return []

    raw_items = data.get("Table", []) + data.get("Table1", [])
    results = []

    for item in raw_items:
        # Parse each announcement
        try:
            ann_symbol = item.get("NSESYMBOL", "") or item.get("scrip_cd", "")
            headline   = item.get("HEADLINE",   "") or item.get("DissemDT", "")
            ann_date_str = item.get("DissemDT", "") or item.get("NEWS_DT", "")
            bse_ann_id   = str(item.get("NEWSID", "") or item.get("News_submission_dt", ""))
            cat_raw      = item.get("CATEGORYNAME", "") or item.get("Category", "Other")

            if not headline or not ann_date_str:
                continue

            # Skip if symbol filter given and this item doesn't match
            if symbol and ann_symbol and ann_symbol.upper() != symbol.upper():
                continue

            # Parse date
            try:
                ann_date = date.fromisoformat(ann_date_str[:10])
            except ValueError:
                continue

            category_mapped = CATEGORY_MAP.get(cat_raw, "other")

            results.append({
                "symbol":        ann_symbol or symbol,
                "event_date":    ann_date.isoformat(),
                "headline":      headline[:500],          # trim long headlines
                "source":        "bse",
                "category":      category_mapped,
                "bse_ann_id":    bse_ann_id,
                "url":           f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{bse_ann_id}.pdf",
                "is_processed":  False,
            })

        except Exception as exc:
            logger.debug("Skipping malformed announcement: %s", exc)
            continue

    logger.info("BSE announcements: %d items for %s (%s→%s)",
                len(results), symbol or "ALL", from_dt, to_dt)
    return results


def ingest_bse_announcements(
    symbols: Optional[list[str]] = None,
    days_back: int = 7,
) -> dict:
    """
    Ingest recent BSE announcements for all (or given) symbols.
    Designed to run daily — fetches last N days.
    """
    import time as _time
    from data.sources.universe import get_active_symbols

    t0 = _time.time()
    to_dt   = date.today()
    from_dt = to_dt - timedelta(days=days_back)

    # Fetch all announcements in date range at once (no symbol filter = all)
    session = _prime_session()
    rows = fetch_bse_announcements(
        from_date=from_dt,
        to_date=to_dt,
        session=session,
    )

    if not rows:
        logger.info("No BSE announcements found for period %s–%s", from_dt, to_dt)
        return {"inserted": 0}

    # Filter to only active NIFTY 100 symbols if symbols list provided
    if symbols:
        symbol_set = {s.upper() for s in symbols}
        rows = [r for r in rows if r.get("symbol", "").upper() in symbol_set]

    # Upsert — use bse_ann_id as dedup key
    if rows:
        upsert_rows("news_events", rows, on_conflict="bse_ann_id")

    duration = _time.time() - t0
    logger.info("BSE announcements ingestion done — %d rows in %.1fs", len(rows), duration)
    return {"inserted": len(rows), "duration": round(duration, 1)}


def fetch_rss_news(
    symbols: Optional[list[str]] = None,
    max_per_feed: int = 50,
) -> list[dict]:
    """
    Fetch news from free RSS feeds: MoneyControl, Economic Times.
    Maps headlines to symbols via keyword matching.

    Returns list of news_events rows.
    """
    import feedparser
    from data.sources.universe import get_active_symbols

    active = set(get_active_symbols() if symbols is None else symbols)

    feeds = [
        ("https://www.moneycontrol.com/rss/MCtopnews.xml",       "moneycontrol"),
        ("https://economictimes.indiatimes.com/markets/rss.cms", "et"),
        ("https://www.business-standard.com/rss/markets-106.rss","bs"),
    ]

    rows = []
    for feed_url, source_name in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_per_feed]:
                title   = getattr(entry, "title",   "") or ""
                summary = getattr(entry, "summary", "") or ""
                link    = getattr(entry, "link",    "") or ""

                # Try to match to a symbol
                text_upper = (title + " " + summary).upper()
                matched_symbol = None
                for sym in active:
                    if sym in text_upper:
                        matched_symbol = sym
                        break

                try:
                    pub_dt = entry.published_parsed
                    from datetime import datetime
                    event_date = datetime(*pub_dt[:3]).date().isoformat()
                except Exception:
                    event_date = date.today().isoformat()

                rows.append({
                    "symbol":       matched_symbol,   # None = market-wide
                    "event_date":   event_date,
                    "headline":     title[:500],
                    "summary":      summary[:1000],
                    "source":       source_name,
                    "url":          link,
                    "category":     "macro" if not matched_symbol else "other",
                    "is_processed": False,
                })

        except Exception as exc:
            logger.warning("RSS feed %s failed: %s", feed_url, exc)

    logger.info("RSS fetch: %d articles from %d feeds", len(rows), len(feeds))
    return rows
