# data/sources/bse_rss.py
import feedparser
from datetime import datetime, date
from data.storage.db import get_client, upsert_rows, log_ingestion
import logging


BSE_ANN_RSS = "https://beta.bseindia.com/data/xml/announcements.xml"
logger = logging.getLogger(__name__)

def fetch_bse_rss_announcements() -> list[dict]:
    scripcode_map = {
        r["bse_scripcode"]: r["symbol"]
        for r in get_client().table("nifty_constituents").select("symbol, bse_scripcode").execute().data
        if r.get("bse_scripcode")
    }

    feed = feedparser.parse(BSE_ANN_RSS)
    rows = []
    for entry in feed.entries:
        scripcode = str(getattr(entry, "scripcode", "")).strip()
        symbol = scripcode_map.get(scripcode)
        if not symbol:
            continue  # not in our universe — this filters out the firehose noise

        try:
            pub_dt = datetime.strptime(entry.get("pubdate", ""), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            logger.warning("Unparseable BSE pubDate: %r", entry.get("published"))
            pub_dt = datetime.now()

        rows.append({
            "symbol": symbol,
            "event_date": pub_dt.date().isoformat(),
            "headline": entry.get("description", "")[:500] or entry.title,
            "source": "bse_rss",
            "category": "other",
            "url": entry.get("link", ""),
            "is_processed": False,
            "bse_scripcode": scripcode,  # part of the dedup key, per the earlier duplicate-entry finding
        })
    return rows


def ingest_bse_rss() -> dict:
    rows = fetch_bse_rss_announcements()
    if rows:
        upsert_rows("news_events", rows, on_conflict="symbol,url,bse_scripcode")
    log_ingestion(job_name="bse_rss", status="success", inserted=len(rows))
    return {"inserted": len(rows)}