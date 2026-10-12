# data/sources/bse_rss.py
import feedparser
from datetime import datetime, date
from data.storage.db import get_client, upsert_rows, log_ingestion
import logging
import requests
import time
import re   

BSE_ANN_RSS = "https://beta.bseindia.com/data/xml/announcements.xml"
logger = logging.getLogger(__name__)

def classify_bse(text: str) -> str:
    t = text.lower().strip()
    if "press release titled" in t:
        return "press_release"
    if "outcome of the board meeting" in t or "outcome of board meeting" in t:
        return "board_outcome"
    if t.rstrip(".") in ("disclosure attached", "intimation attached") or "captioned subject" in t:
        return "attachment_only"
    if "board of directors" in t and ("scheduled on" in t or "may consider" in t):
        return "board_meeting"
    if t.startswith("earnings call"):
        return "earnings_call"
    if "restricted stock" in t or "stock option" in t or "esop" in t:
        return "esop"
    if t.startswith("profile of"):
        return "governance"
    if ("certificate under reg" in t or "newspaper advertisement" in t
            or t.startswith("intimation under regulation 30")):
        return "compliance"
    return "other"

def fetch_bse_rss_announcements() -> list[dict]:
    scripcode_map = {
        r["bse_scripcode"]: r["symbol"]
        for r in get_client().table("nifty_constituents").select("symbol, bse_scripcode").execute().data
        if r.get("bse_scripcode")
    }
    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Referer": "https://www.bseindia.com/"}
    resp = requests.get(BSE_ANN_RSS, headers=HEADERS, timeout=15)
    resp.raise_for_status()  # raise an exception for non-200 responses
    feed = feedparser.parse(resp.content)
    rows = []
    for entry in feed.entries:
        scripcode = str(getattr(entry, "scripcode", "")).strip()
        symbol = scripcode_map.get(scripcode)
        if not symbol:
            continue  # not in our universe — this filters out the firehose noise
        
        try:
            pub_dt = datetime.strptime(entry.get("published", ""), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            logger.warning("Unparseable BSE pubDate: %r", entry.get("pubdate"))
            pub_dt = datetime.now()

        desc = (entry.get("description", "") or "").strip()
        category = classify_bse(desc) if desc else "attachment_only"  # no text, nothing to score
        headline = desc[:500] or entry.title
        if category == "press_release":
            parts = re.split(r"press release titled", desc, maxsplit=1, flags=re.I)
            if len(parts) == 2:
                headline = parts[1].strip(' "“”')[:500]
        
        rows.append({
            "symbol": symbol,
            "event_date": pub_dt.date().isoformat(),
            "published_at": pub_dt.isoformat(),
            "headline": headline,
            "source": "bse_rss",
            "category": category,
            "url": entry.get("link", ""),
            "is_processed": False,
            "bse_scripcode": scripcode,  # part of the dedup key, per the earlier duplicate-entry finding
        })
    return rows


def ingest_bse_rss() -> dict:
    t0 = time.time()
    rows = fetch_bse_rss_announcements()
    if rows:
        upsert_rows("news_events", rows, on_conflict="symbol,url,bse_scripcode")
    duration = time.time() - t0
    log_ingestion(job_name="bse_rss", status="success", inserted=len(rows), duration=duration)
    return {"inserted": len(rows)}