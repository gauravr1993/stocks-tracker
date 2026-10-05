# data/digest/mood.py
from datetime import date, timedelta
from collections import Counter, defaultdict
from data.storage.db import get_client

# same thresholds as agents/sentiment/scorer.py — import from there instead
# of redefining, to avoid the two drifting apart
# from agents.sentiment.scorer import POSITIVE_THRESHOLD, NEGATIVE_THRESHOLD  # 0.2 / -0.2

POSITIVE_THRESHOLD = 0.2
NEGATIVE_THRESHOLD = -0.2

def _label(score: float) -> str:
    if score >= POSITIVE_THRESHOLD:
        return "positive"
    if score <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"

def compute_market_mood(days_back: int = 1) -> dict:
    """
    Today's market mood, independent of when/whether the live sentiment
    run is still in memory — reads directly from news_events.
    """
    client = get_client()
    since = (date.today() - timedelta(days=days_back)).isoformat()

    rows = (
        client.table("news_events")
        .select("symbol, headline, sentiment_score, sentiment_label, event_date")
        .not_.is_("sentiment_score", "null")
        .gte("event_date", since)
        .execute()
        .data
    )
    if not rows:
        return {"mood": "no data", "total_articles": 0}

    pos = [r for r in rows if r["sentiment_label"] == "positive"]
    neg = [r for r in rows if r["sentiment_label"] == "negative"]
    total = len(rows)
    pos_pct, neg_pct = len(pos) / total * 100, len(neg) / total * 100

    if pos_pct >= 60: mood = "bullish"
    elif neg_pct >= 60: mood = "bearish"
    elif pos_pct >= neg_pct + 15: mood = "cautiously bullish"
    elif neg_pct >= pos_pct + 15: mood = "cautiously bearish"
    else: mood = "mixed"

    universe = {r["symbol"]: r["sector"] for r in
                client.table("nifty_constituents").select("symbol, sector").execute().data}
    by_sector = defaultdict(list)
    for r in rows:
        sector = universe.get(r["symbol"])
        if sector:
            by_sector[sector].append(r["sentiment_score"])
    sector_mood = {
        s: round(sum(scores) / len(scores), 2)
        for s, scores in by_sector.items() if len(scores) >= 2
    }

    return {
        "mood": mood, "total_articles": total,
        "positive_pct": round(pos_pct, 1), "negative_pct": round(neg_pct, 1),
        "sector_mood": sector_mood,
    }