"""
dashboard/components/data_loader.py
Cached data fetchers for the dashboard.
All heavy Supabase queries go here so pages share cached results.
"""
from __future__ import annotations

import os
import sys
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv

# ── ensure project root is on path ───────────────────────────────────────────
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

load_dotenv(os.path.join(_root, "config", ".env"))


# ── cached loaders ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)   # refresh every hour
def load_screener() -> pd.DataFrame:
    """Full scored universe from the screener."""
    from analysis.screener.run_screener import run_screener
    return run_screener()


@st.cache_data(ttl=3600, show_spinner=False)
def load_sector_summary(df: pd.DataFrame | None = None) -> pd.DataFrame:
    from analysis.screener.run_screener import sector_summary
    return sector_summary(df)


@st.cache_data(ttl=300, show_spinner=False)    # refresh every 5 min
def load_latest_prices() -> pd.DataFrame:
    """Latest closing price for all active stocks."""
    from data.storage.db import get_client
    client = get_client()
    rows = client.table("latest_prices").select("*").execute().data
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_price_history(symbol: str, years: int = 5) -> pd.DataFrame:
    """OHLCV history for a single symbol."""
    from data.storage.db import get_client
    client = get_client()
    since = (date.today() - timedelta(days=365 * years)).isoformat()
    rows = (
        client.table("daily_prices")
        .select("date, open, high, low, close, adj_close, volume")
        .eq("symbol", symbol)
        .gte("date", since)
        .order("date", desc=False)
        .execute()
        .data
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "adj_close"]:
            df[col] = df[col].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_events(symbol: str, years: int = 5) -> pd.DataFrame:
    """News events for a symbol."""
    from data.storage.db import get_client
    client = get_client()
    since = (date.today() - timedelta(days=365 * years)).isoformat()

    # Paginate to get all events
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        batch = (
            client.table("news_events")
            .select("event_date, headline, category, source")
            .eq("symbol", symbol)
            .gte("event_date", since)
            .order("event_date", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
        )
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"])
    return df


@st.cache_data(ttl=1800, show_spinner=False)   # 30 min
def load_news_feed(days: int = 3) -> pd.DataFrame:
    """Recent news across all stocks for morning brief."""
    from data.storage.db import get_client
    client = get_client()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = (
        client.table("news_events")
        .select("symbol, event_date, headline, category, source, sentiment_score, sentiment_label")
        .gte("event_date", since)
        .order("event_date", desc=True)
        .limit(500)
        .execute()
        .data
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"])
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_fundamentals(symbol: str) -> dict:
    """Latest fundamentals for a single stock."""
    from data.storage.db import get_client
    client = get_client()
    rows = (
        client.table("fundamentals")
        .select("*")
        .eq("symbol", symbol)
        .order("report_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else {}
