"""
agents/sentiment/agent.py
Sentiment agent — fetches unscored news_events, scores them via Groq,
writes sentiment_score + sentiment_label + reasoning back to Supabase.

Designed to run every morning at 7AM via cron before market open.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import Optional

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_root, "config", ".env"))

from agents.sentiment.scorer import score_batch
from data.storage.db import get_client, log_ingestion

logger = logging.getLogger(__name__)


# ── Fetch unscored articles ───────────────────────────────────────────────────

def _fetch_unscored(
    days_back: int = 2,
    limit:     int = 200,
) -> list[dict]:
    """
    Fetch news_events rows that have no sentiment score yet.
    Prioritises:
      1. Articles with a known symbol (more actionable)
      2. Recent articles first
    """
    client = get_client()
    since  = (date.today() - timedelta(days=days_back)).isoformat()

    rows = (
        client.table("news_events")
        .select("id, symbol, headline, summary, source, category, event_date")
        .is_("sentiment_score", "null")
        .gte("event_date", since)
        .order("event_date", desc=True)
        .limit(limit)
        .execute()
        .data
    )

    logger.info("Fetched %d unscored articles (last %d days)", len(rows), days_back)
    return rows


# ── Write scores back ─────────────────────────────────────────────────────────

def _write_scores(scored: list[dict]) -> int:
    """
    Update news_events rows with sentiment results.
    Stores reasoning in a metadata JSONB column.
    Returns number of rows updated.
    """
    client  = get_client()
    updated = 0

    for item in scored:
        try:
            client.table("news_events").update({
                "sentiment_score": item["score"],
                "sentiment_label": item["label"],
                "is_processed":    True,
                "metadata":        {"reasoning": item.get("reasoning", "")},
            }).eq("id", item["id"]).execute()
            updated += 1
        except Exception as exc:
            logger.warning("Failed to update row %s: %s", item["id"], exc)

    return updated


def _ensure_metadata_column() -> None:
    """
    Ensure the metadata column exists on news_events.
    Safe to run multiple times — uses IF NOT EXISTS.
    """
    client = get_client()
    try:
        client.rpc("exec_sql", {
            "query": "ALTER TABLE news_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';"
        }).execute()
    except Exception:
        # RPC may not be available — that's fine, reasoning just won't be stored
        pass


# ── Morning brief summary ─────────────────────────────────────────────────────

def _build_morning_brief(scored_articles: list[dict], raw_articles: list[dict]) -> dict:
    """
    Build a structured morning brief summary from scored articles.
    Returns dict with market mood, top movers, key headlines.
    """
    # Map id → raw article for headline lookup
    raw_map = {str(a["id"]): a for a in raw_articles}

    positives = [s for s in scored_articles if s["label"] == "positive"]
    negatives = [s for s in scored_articles if s["label"] == "negative"]
    neutrals  = [s for s in scored_articles if s["label"] == "neutral"]

    total = len(scored_articles)
    if total == 0:
        return {"mood": "neutral", "summary": "No articles scored today."}

    pos_pct = len(positives) / total * 100
    neg_pct = len(negatives) / total * 100

    # Overall market mood
    if pos_pct >= 60:
        mood = "bullish"
    elif neg_pct >= 60:
        mood = "bearish"
    elif pos_pct >= neg_pct + 15:
        mood = "cautiously bullish"
    elif neg_pct >= pos_pct + 15:
        mood = "cautiously bearish"
    else:
        mood = "mixed"

    # Top positive headlines (highest score)
    top_positive = sorted(positives, key=lambda x: x["score"], reverse=True)[:3]
    top_negative = sorted(negatives, key=lambda x: x["score"])[:3]

    def _enrich(items):
        out = []
        for item in items:
            raw = raw_map.get(str(item["id"]), {})
            out.append({
                "symbol":     (raw.get("symbol") or "").replace(".NS", "") or "MARKET",
                "headline":   raw.get("headline", "")[:120],
                "event_date": str(raw.get("event_date", ""))[:10],
                "score":      item["score"],
                "label":      item["label"],
                "reasoning":  item["reasoning"],
            })
        return out

    # Stocks with multiple negative articles = higher risk
    from collections import Counter
    neg_symbol_counts = Counter(
        raw_map.get(str(s["id"]), {}).get("symbol", "")
        for s in negatives
        if raw_map.get(str(s["id"]), {}).get("symbol")
    )
    stocks_to_watch = [
        sym.replace(".NS", "")
        for sym, cnt in neg_symbol_counts.most_common(5)
        if cnt >= 2 and sym
    ]

    return {
        "date":           date.today().isoformat(),
        "mood":           mood,
        "total_articles": total,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "neutral_count":  len(neutrals),
        "positive_pct":   round(pos_pct, 1),
        "negative_pct":   round(neg_pct, 1),
        "top_positive":   _enrich(top_positive),
        "top_negative":   _enrich(top_negative),
        "stocks_to_watch":stocks_to_watch,
        "avg_score":      round(
            sum(s["score"] for s in scored_articles) / total, 3
        ),
    }


# ── Main agent entry point ────────────────────────────────────────────────────

def run_sentiment_agent(
    days_back:   int  = 2,
    limit:       int  = 200,
    dry_run:     bool = False,
) -> dict:
    """
    Main sentiment agent — fetch → score → write → summarise.

    Args:
        days_back: Score articles from last N days
        limit:     Max articles to score per run
        dry_run:   If True, compute scores but don't write to DB

    Returns:
        Morning brief summary dict
    """
    t0 = time.time()
    logger.info("── Sentiment agent starting (days_back=%d, limit=%d) ──",
                days_back, limit)

    # 1. Fetch unscored articles
    articles = _fetch_unscored(days_back=days_back, limit=limit)
    if not articles:
        logger.info("No unscored articles found — nothing to do")
        return {"mood": "neutral", "summary": "No new articles to score.", "total_articles": 0}

    # 2. Prepare batch input (id must be string for JSON round-trip)
    batch_input = [
        {
            "id":       str(a["id"]),
            "headline": a.get("headline", ""),
            "summary":  a.get("summary",  "") or "",
            "symbol":   a.get("symbol",   "") or "",
        }
        for a in articles
    ]

    # 3. Score
    logger.info("Scoring %d articles via Groq...", len(batch_input))
    scored = score_batch(batch_input)

    # 4. Write back to DB
    if not dry_run:
        updated = _write_scores(scored)
        logger.info("Updated %d rows in news_events", updated)
    else:
        logger.info("Dry run — skipping DB writes")
        updated = 0

    # 5. Build morning brief
    brief = _build_morning_brief(scored, articles)
    brief["updated_rows"] = updated
    brief["duration_secs"] = round(time.time() - t0, 1)

    # 6. Log the run
    log_ingestion(
        job_name = "sentiment_agent",
        status   = "success",
        duration = brief["duration_secs"],
        inserted = 0,
        updated  = updated,
        metadata = {
            "mood":           brief["mood"],
            "total_articles": brief["total_articles"],
            "positive_pct":   brief["positive_pct"],
            "negative_pct":   brief["negative_pct"],
        },
    )

    logger.info(
        "Sentiment agent done — mood: %s, %d articles, %.1fs",
        brief["mood"], brief["total_articles"], brief["duration_secs"],
    )
    return brief


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    logging.basicConfig(
        level   = logging.INFO,
        format  = "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
        datefmt = "%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Morning sentiment agent")
    parser.add_argument("--days",    type=int,  default=2,     help="Days of news to score")
    parser.add_argument("--limit",   type=int,  default=200,   help="Max articles")
    parser.add_argument("--dry-run", action="store_true",       help="Don't write to DB")
    args = parser.parse_args()

    brief = run_sentiment_agent(
        days_back = args.days,
        limit     = args.limit,
        dry_run   = args.dry_run,
    )

    print("\n" + "═" * 60)
    print(f"  MORNING BRIEF — {brief.get('date', '')}")
    print("═" * 60)
    print(f"  Market mood    : {brief.get('mood', '—').upper()}")
    print(f"  Articles scored: {brief.get('total_articles', 0)}")
    print(f"  Positive       : {brief.get('positive_count', 0)} ({brief.get('positive_pct', 0):.1f}%)")
    print(f"  Negative       : {brief.get('negative_count', 0)} ({brief.get('negative_pct', 0):.1f}%)")
    print(f"  Avg score      : {brief.get('avg_score', 0):+.3f}")

    if brief.get("stocks_to_watch"):
        print(f"\n  ⚠️  Stocks to watch: {', '.join(brief['stocks_to_watch'])}")

    if brief.get("top_positive"):
        print("\n  📈 Top positive:")
        for item in brief["top_positive"]:
            dt = item.get("event_date", "")
            print(f"     [{item['symbol']:12s}] {dt}  {item['headline'][:55]}")
            print(f"                    → {item['reasoning']}")

    if brief.get("top_negative"):
        print("\n  📉 Top negative:")
        for item in brief["top_negative"]:
            dt = item.get("event_date", "")
            print(f"     [{item['symbol']:12s}] {dt}  {item['headline'][:55]}")
            print(f"                    → {item['reasoning']}")

    print("═" * 60)


def backfill_reasoning(days_back: int = 7) -> int:
    """
    One-time utility — re-score articles that have sentiment_score
    but empty metadata (missing reasoning from before the fix).
    """
    import logging
    logger = logging.getLogger(__name__)
    from datetime import date, timedelta
    client = get_client()
    since  = (date.today() - timedelta(days=days_back)).isoformat()

    rows = (
        client.table("news_events")
        .select("id, symbol, headline, summary")
        .not_.is_("sentiment_score", "null")
        .eq("metadata", {})
        .gte("event_date", since)
        .limit(200)
        .execute()
        .data
    )

    if not rows:
        logger.info("No rows need reasoning backfill")
        return 0

    logger.info("Backfilling reasoning for %d rows...", len(rows))
    batch_input = [
        {"id": str(r["id"]), "headline": r.get("headline",""),
         "summary": r.get("summary","") or "", "symbol": r.get("symbol","") or ""}
        for r in rows
    ]
    scored  = score_batch(batch_input)
    updated = _write_scores(scored)
    logger.info("Backfilled reasoning for %d rows", updated)
    return updated

from datetime import date, timedelta
from data.storage.db import get_client

def get_sentiment_for_symbols(symbols: list[str], days_back: int = 700) -> dict:
    """
    Read pre-scored sentiment for the given symbols from news_events.
    Does NOT trigger new scoring — relies on the daily cron's output.
    Returns {} for symbols with no scored articles in the window.
    """
    client = get_client()
    since = (date.today() - timedelta(days=days_back)).isoformat()

    rows = (
        client.table("news_events")
        .select("symbol, headline, sentiment_score, sentiment_label, event_date, metadata")
        .in_("symbol", symbols)
        .not_.is_("sentiment_score", "null")
        .gte("event_date", since)
        .execute()
        .data
    )

    from collections import defaultdict
    by_symbol = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(r)

    out = {}
    for sym in symbols:
        items = by_symbol.get(sym, [])
        if not items:
            out[sym] = None  # explicit "no data" — don't let the model guess
            continue
        avg = sum(i["sentiment_score"] for i in items) / len(items)
        out[sym] = {
            "avg_score": round(avg, 2),
            "article_count": len(items),
            "label": "positive" if avg >= 0.2 else "negative" if avg <= -0.2 else "neutral",
            "recent_headlines": [i["headline"][:100] for i in items[:3]],
        }
    return out


def get_sentiment_rankings(
    direction: str = "positive",
    top_n: int = 10,
    days_back: int = 700,
    min_articles: int = 2,
) -> list[dict]:
    """
    Rank symbols by average sentiment across all scored news in the window.
    direction: "positive" or "negative" — sort order.
    min_articles: exclude symbols with too little coverage to be meaningful
                  (a single glowing headline shouldn't outrank a stock with
                  5 consistently positive articles).
    """
    client = get_client()
    since = (date.today() - timedelta(days=days_back)).isoformat()

    rows = (
        client.table("news_events")
        .select("symbol, sentiment_score")
        .not_.is_("sentiment_score", "null")
        .gte("event_date", since)
        .execute()
        .data
    )

    from collections import defaultdict
    by_symbol = defaultdict(list)
    for r in rows:
        if r["symbol"]:
            by_symbol[r["symbol"]].append(r["sentiment_score"])

    ranked = [
        {"symbol": sym, "avg_score": round(sum(scores) / len(scores), 2),
         "article_count": len(scores)}
        for sym, scores in by_symbol.items()
        if len(scores) >= min_articles
    ]
    reverse = direction == "positive"
    ranked.sort(key=lambda x: x["avg_score"], reverse=reverse)
    return ranked[:top_n]