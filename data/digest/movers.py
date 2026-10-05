# data/digest/movers.py
from datetime import date, timedelta
import pandas as pd
from data.storage.db import get_client

def _fetch_snapshot_pair() -> pd.DataFrame:
    """Today's and yesterday's score_snapshots, merged on symbol."""
    client = get_client()
    today, yesterday = date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()

    def _fetch(d):
        rows = client.table("score_snapshots").select("*").eq("snapshot_date", d).execute().data
        return pd.DataFrame(rows)

    t, y = _fetch(today), _fetch(yesterday)
    if t.empty or y.empty:
        return pd.DataFrame()  # not enough history yet — caller must handle
    return t.merge(y, on="symbol", suffixes=("_today", "_yday"))

def score_movers(threshold: float = 8.0, top_n: int = 5) -> list[dict]:
    df = _fetch_snapshot_pair()
    if df.empty:
        return []
    df["delta"] = df["composite_score_today"] - df["composite_score_yday"]
    movers = df[df["delta"].abs() >= threshold].copy()
    movers["abs_delta"] = movers["delta"].abs()
    movers = movers.sort_values("abs_delta", ascending=False).head(top_n)
    return movers[["symbol", "composite_score_yday", "composite_score_today", "delta"]].to_dict("records")

def new_coverage(top_n: int = 5) -> list[str]:
    """Symbols with sentiment data today but none yesterday."""
    df = _fetch_snapshot_pair()
    if df.empty:
        return []
    newly = df[df["avg_sentiment_7d_yday"].isna() & df["avg_sentiment_7d_today"].notna()]
    return newly["symbol"].head(top_n).tolist()