# data/sources/bse_rss.py
import feedparser
from datetime import datetime, date
from data.storage.db import get_client, upsert_rows, log_ingestion
import logging
import requests
import time
import re   
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

BSE_ANN_RSS = "https://beta.bseindia.com/data/xml/announcements.xml"
logger = logging.getLogger(__name__)

NON_SCORABLE = ["board_meeting", "earnings_call", "compliance", "esop", "governance",
                "attachment_only", "board_outcome", "shareholding", "credit_rating", "irrelevant"]

def classify_bse(text: str) -> str:
    t = text.lower().strip()
    tt = t.rstrip(".")
    if not t:
        return "attachment_only"
    if t.startswith("press release -") or "press release titled" in t:
        return "press_release"
    if "outcome of the board meeting" in t or "outcome of board meeting" in t:
        return "board_outcome"
    if "earnings call" in t or "conference call" in t or "earnings conference" in t or tt == "investor call":
        return "earnings_call"
    if "board of directors" in t and ("scheduled on" in t or "may consider" in t):
        return "board_meeting"
    if "substantial acquisition" in t:   # SAST shareholding disclosure
        return "shareholding"
    if t.startswith("update on credit rating"):
        return "credit_rating"
    if "restricted stock" in t or "stock option" in t or "esop" in t:
        return "esop"
    if t.startswith("profile of"):
        return "governance"
    if ("newspaper" in t or "certificate under reg" in t or "listed debt securities" in t
            or ("regulation 30" in t and len(t) < 200)):
        return "compliance"
    if (tt in ("enclosed", "disclosure attached", "intimation attached")
            or re.fullmatch(r"please (find|refer)[^.]*(enclosed|file)\.?", t)
            or "captioned subject" in t or "media release" in t
            or t.startswith("press release by")):
        return "attachment_only"
    return "other"

def clean_headline(category: str, desc: str) -> str:
    if category == "press_release":
        m = (re.search(r"press release titled\s*(.+)", desc, re.I | re.S)
             or re.match(r"press release\s*-\s*(.+)", desc, re.I | re.S))
        if m:
            return m.group(1).strip(' "“”')[:500]
    return desc[:500]

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
    if not feed.entries:
        logger.warning("BSE feed returned 200 but no entries")
        # raise RuntimeError("BSE feed returned 200 but no entries")
    rows = []
    for entry in feed.entries:
        scripcode = str(getattr(entry, "scripcode", "")).strip()
        symbol = scripcode_map.get(scripcode)
        if not symbol:
            continue  # not in our universe — this filters out the firehose noise
        raw_pub = entry.get("published", "")
        try:
            pub_dt = datetime.strptime(raw_pub, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        except ValueError:
            logger.warning("Unparseable BSE pubDate: %r", raw_pub)
            pub_dt = datetime.now(IST)

        desc = (entry.get("description", "") or "").strip()
        category = classify_bse(desc) if desc else "attachment_only"  # no text, nothing to score
        headline = clean_headline(category, desc)
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
    try:
        rows = fetch_bse_rss_announcements()
        if rows:
            upsert_rows("news_events", rows, on_conflict="symbol,url,bse_scripcode")
    except Exception as exc:
        log_ingestion(job_name="bse_rss", status="failed",
                      duration=time.time() - t0, inserted=0, error=str(exc))
        raise
    log_ingestion(job_name="bse_rss", status="success",
                  duration=time.time() - t0, inserted=len(rows))
    return {"inserted": len(rows)}