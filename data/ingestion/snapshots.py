# data/ingestion/snapshots.py
from datetime import date
import time
from analysis.screener.run_screener import run_screener
from agents.sentiment.agent import get_sentiment_rankings
from data.storage.db import upsert_rows, log_ingestion


def ingest_score_snapshot() -> dict:
    """
    Run the screener + sentiment rankings once, persist today's scores
    so the digest can diff against yesterday. One row per symbol per day.
    """
    t0 = time.time()
    df = run_screener(include_vol_penalty=True)  # reuse, not reinvent

    sentiment_map = {
        r["symbol"]: r["avg_score"]
        for r in get_sentiment_rankings(direction="positive", top_n=1000)
        + get_sentiment_rankings(direction="negative", top_n=1000)
    }

    rows = [{
        "symbol": r["symbol"],
        "snapshot_date": date.today().isoformat(),
        "value_score": r["value_score"],
        "momentum_score": r["momentum_score"],
        "sector_score": r["sector_score"],
        "composite_score": r["composite_score"],
        "avg_sentiment_7d": sentiment_map.get(r["symbol"]),
    } for r in df.to_dict("records")]

    upsert_rows("score_snapshots", rows, on_conflict="symbol,snapshot_date")
    duration = time.time() - t0
    log_ingestion(job_name="score_snapshots", status="success",
                  duration=duration, inserted=len(rows))
    return {"inserted": len(rows), "duration": round(duration, 1)}