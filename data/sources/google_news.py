"""
data/sources/google_news.py

Per-company news from Google News RSS. The symbol comes from the query, so there is no
extraction step; aliases.py decides whether a headline is really about that company.

Pipeline per company:
  query (non-ambiguous aliases, OR-ed)  ->  drop junk  ->  keep only headlines that name
  the company  ->  drop already-stored URLs  ->  merge near-duplicates  ->  keep newest N
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import quote
from zoneinfo import ZoneInfo

from data.sources.scrapers.aliases import AMBIGUOUS, AliasMatcher

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

MAX_PER_COMPANY = 5          # newest unseen articles kept per company per run
SIMILARITY = 0.8             # headlines this alike are treated as the same story
PAUSE_SECS = 2.0             # between Google queries
WRAP_AT = 4                  # a headline naming this many universe companies is market news
# Judgment calls from reading real results; edit freely. ad-hoc-news.de publishes templated
# auto-generated stock blurbs; the other three are car-review sites, not company news.
BLOCKED_PUBLISHERS = {"Gallinews", "ad-hoc-news.de", "CarLelo", "Cartoq", "MotorOctane",
                      "CarTrade", "MarketsMojo", "AD HOC NEWS"}     # last two: used-car ads, templated "rated Sell by" blurbs
_BLOCKED = {p.lower() for p in BLOCKED_PUBLISHERS}
INDIC = re.compile(r"[\u0900-\u0DFF]")                  # Devanagari through Malayalam
QUOTE_PAGE = re.compile(
    r"stock price, news, quote|(share|stock) price today|(gold|silver) (rate|price)s? today"
    r"|^.{3,60} (share|stock) price$|for sale at (rs|\u20b9)"
    r"|stock forum|share price and techni|admit card|call letter", re.I)


# ── query building ────────────────────────────────────────────────────────────

CONTEXT_WORDS = ("shares", "stock", "share price", "results")


def query_terms(matcher: AliasMatcher, symbol: str) -> list[str]:
    """
    Search phrases for one company. Clear aliases go in as they are. Ambiguous ones
    ("eternal", "trent", "titan", "reliance"...) only go in paired with a finance word
    ("eternal shares"), so the query finds the company without pulling in every
    article that uses the plain word. Trailing 'limited'/'ltd' variants add nothing.
    """
    plain, risky = set(), set()
    for alias, owners in matcher.owners.items():
        if symbol not in owners:
            continue
        # "x limited" adds nothing when "x" is a clear name, but "bosch ltd" is how headlines
        # tell the company apart from the ambiguous word "bosch"
        if alias.split()[-1] in {"limited", "ltd"} and alias.rsplit(" ", 1)[0] not in AMBIGUOUS:
            continue
        (risky if alias in AMBIGUOUS else plain).add(alias)
    terms = plain | {f"{a} {c}" for a in risky for c in CONTEXT_WORDS}
    return sorted(terms, key=lambda a: (len(a), a))


def build_url(terms: list[str], days: int) -> str:
    q = "(" + " OR ".join(f'"{t}"' for t in terms) + f") when:{days}d"
    return "https://news.google.com/rss/search?q=" + quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en"


def fetch_entries(terms: list[str], days: int, retries: int = 3) -> list:
    import feedparser
    import requests

    url = build_url(terms, days)
    for attempt in range(1, retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code in (429, 503) and attempt < retries:
            time.sleep(5 * attempt)
            continue
        resp.raise_for_status()          # fail loudly instead of returning an empty list
        return feedparser.parse(resp.content).entries
    return []


# ── filtering (pure functions, no network or DB) ──────────────────────────────

def clean_title(entry) -> tuple[str, str]:
    """Strip the ' - Publisher' suffix Google adds. Returns (title, publisher)."""
    title = (entry.get("title") or "").strip()
    pub = ((entry.get("source") or {}).get("title") or "").strip()
    if pub and title.endswith(" - " + pub):
        title = title[: -(len(pub) + 3)].rstrip()
    else:
        title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
    return title, pub


def select_articles(symbol: str, entries: list, matcher: AliasMatcher,
                    known: set, stats: Counter) -> list[dict]:
    items = []
    for e in entries:
        about: list[str] = []
        title, pub = clean_title(e)
        link = e.get("link") or ""
        reason = None
        if not title or not link:
            reason = "empty"
        elif INDIC.search(title):
            reason = "non_english"
        elif pub.lower() in _BLOCKED or QUOTE_PAGE.search(title):
            reason = "blocked"
        else:
            tag = matcher.tag(title, wrap_at=WRAP_AT)
            about = tag["symbols"] or tag.get("candidates", [])
            if tag["status"] == "market_wrap":
                reason = "market_wrap"            # 3+ companies: market news, not company news
            elif tag["status"] == "none":
                reason = "no_company_in_headline"
            elif symbol not in about:
                reason = "other_company"          # picked up by this query but about another stock
        if not reason and (symbol, link) in known:
            reason = "already_stored"
        if reason:
            stats[reason] += 1
            continue
        pp = e.get("published_parsed")
        dt = (datetime(*pp[:6], tzinfo=timezone.utc).astimezone(IST) if pp else datetime.now(IST))
        items.append({"title": title, "pub": pub, "link": link, "dt": dt, "n": len(about)})

    # stories about one company first, multi-company roundups only if slots remain; newest first
    items.sort(key=lambda x: (x["n"] > 1, -x["dt"].timestamp()))
    kept: list[dict] = []
    for it in items:
        t = it["title"].lower()
        if any(SequenceMatcher(None, t, k["title"].lower()).ratio() >= SIMILARITY for k in kept):
            stats["near_duplicate"] += 1
            continue
        kept.append(it)
    if len(kept) > MAX_PER_COMPANY:
        stats["over_cap"] += len(kept) - MAX_PER_COMPANY
        kept = kept[:MAX_PER_COMPANY]
    return kept


# ── DB helpers and the ingest entry point ─────────────────────────────────────

def build_matcher() -> tuple[dict, AliasMatcher]:
    from data.storage.db import get_client
    rows = get_client().table("nifty_constituents").select("symbol, company_name").execute().data
    names = {r["symbol"]: r["company_name"] for r in rows if r.get("company_name")}
    return names, AliasMatcher(names)


def known_urls(days: int) -> set:
    from data.storage.db import get_client
    since = (datetime.now(IST) - timedelta(days=days)).date().isoformat()
    rows = (get_client().table("news_events").select("symbol, url")
            .eq("source", "google_news").gte("event_date", since).execute().data)
    return {(r["symbol"], r["url"]) for r in rows}


def ingest_google_news(days: int = 2, symbols: list[str] | None = None,
                       dry_run: bool = False) -> dict:
    """
    days:    look-back window. 2 overlaps runs so a late or missed run loses nothing;
             already-stored URLs are skipped, so overlap does not create duplicates.
    dry_run: fetch and filter, print the funnel, write nothing.
    """
    from data.storage.db import insert_rows, log_ingestion

    t0 = time.time()
    names, matcher = build_matcher()
    known = known_urls(days + 2)
    stats: Counter = Counter()
    rows, failed, per_company = [], [], {}

    for sym in (symbols or sorted(names)):
        try:
            entries = fetch_entries(query_terms(matcher, sym), days)
        except Exception as exc:
            logger.warning("Google News failed for %s: %s", sym, exc)
            failed.append(sym)
            time.sleep(PAUSE_SECS)
            continue
        kept = select_articles(sym, entries, matcher, known, stats)
        per_company[sym] = (len(entries), len(kept))
        for it in kept:
            rows.append({
                "symbol": sym,
                "event_date": it["dt"].date().isoformat(),
                "published_at": it["dt"].isoformat(),
                "headline": it["title"][:500],
                "summary": it["pub"],               # publisher name, handy for the digest
                "source": "google_news",
                "category": "company_news",
                "url": it["link"],
                "is_processed": False,
            })
        time.sleep(PAUSE_SECS)

    if rows and not dry_run:
        for i in range(0, len(rows), 200):
            insert_rows("news_events", rows[i:i + 200])

    status = "success" if not failed else ("partial" if rows else "failed")
    if not dry_run:
        # keep the funnel in the log row so an empty stock can be explained without re-running
        log_ingestion(job_name="google_news", status=status, duration=time.time() - t0,
                      inserted=len(rows), error=f"Failed: {failed}" if failed else None,
                      metadata={"dropped": dict(stats),
                                "per_company": {s: list(v) for s, v in per_company.items()}})
    step = max(1, len(rows) // 30)          # ~30 evenly spaced rows to eyeball
    return {
        "status": status, "inserted": 0 if dry_run else len(rows), "would_insert": len(rows),
        "failed": failed, "dropped": dict(stats), "per_company": per_company,
        "sample": [(r["symbol"], r["summary"], r["headline"][:90]) for r in rows[::step]],
        "duration": round(time.time() - t0, 1),
    }


def explain(symbol: str, days: int = 2) -> None:
    """Print every raw headline for one company with how the matcher sees it."""
    names, matcher = build_matcher()
    terms = query_terms(matcher, symbol)
    print("query terms:", terms)
    for e in fetch_entries(terms, days):
        title, pub = clean_title(e)
        tag = matcher.tag(title)
        who = tag["symbols"] or tag.get("candidates", [])
        print(f"{tag['status']:<12} {str(who):<26} {pub[:16]:<16} {title[:80]}")