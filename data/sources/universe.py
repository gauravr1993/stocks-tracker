"""
data/sources/universe.py
Fetch and maintain the NIFTY 100 constituent list.
Handles survivorship bias by tracking historical membership.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests

from data.storage.db import get_client, upsert_rows

logger = logging.getLogger(__name__)

# NSE unofficial endpoint for index constituents
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Fallback: hardcoded current NIFTY 100 symbols (update quarterly)
# These are used if the NSE endpoint is unavailable
NIFTY100_SYMBOLS_FALLBACK = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "HCLTECH",
    "NTPC", "POWERGRID", "ONGC", "COALINDIA", "NESTLEIND",
    "JSWSTEEL", "TATAMOTORS", "TATASTEEL", "ADANIENT", "ADANIPORTS",
    "BAJAJFINSV", "TECHM", "GRASIM", "CIPLA", "DRREDDY",
    "EICHERMOT", "APOLLOHOSP", "DIVISLAB", "SBILIFE", "HDFCLIFE",
    "BPCL", "INDUSINDBK", "TATACONSUM", "BRITANNIA", "HEROMOTOCO",
    "HINDZINC", "VEDL", "UPL", "SHREECEM", "PIDILITIND",
    "DMART", "BAJAJ-AUTO", "HAVELLS", "MUTHOOTFIN", "DABUR",
    "COLPAL", "MARICO", "BERGEPAINT", "GODREJCP", "SIEMENS",
    "TORNTPHARM", "AMBUJACEM", "ACC", "BANDHANBNK", "FEDERALBNK",
    "IDFCFIRSTB", "INDHOTEL", "JUBLFOOD", "LUPIN", "MCDOWELL-N",
    "MOTHERSON", "NAUKRI", "OBEROIRLTY", "PAGEIND", "PEL",
    "PIIND", "PNB", "POLYCAB", "SBICARD", "TATAPOWER",
    "TRENT", "VOLTAS", "ZOMATO", "PAYTM", "NYKAA",
    "DELHIVERY", "ADANIGREEN", "ADANITRANS", "ADANIPOWER", "ADANIWILMAR",
    "GMRINFRA", "IRCTC", "LICI", "NHPC", "RECLTD",
    "PFC", "HAL", "BEL", "BHEL", "SAIL",
]


def fetch_nse_constituents(index: str = "NIFTY 100") -> Optional[pd.DataFrame]:
    """
    Fetch current index constituents from NSE.
    Returns DataFrame with columns: symbol, name, sector, industry
    Returns None if fetch fails (use fallback).
    """
    session = requests.Session()

    try:
        # Prime cookies
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(1)

        url = "https://www.nseindia.com/api/equity-stockIndices"
        params = {"index": index}
        response = session.get(url, headers=NSE_HEADERS, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()
        records = []
        for item in data.get("data", []):
            sym = item.get("symbol", "")
            if not sym or sym == index:
                continue
            records.append({
                "symbol":   sym,
                "name":     item.get("meta", {}).get("companyName", sym),
                "sector":   item.get("meta", {}).get("industry", ""),
                "industry": item.get("meta", {}).get("industry", ""),
            })

        logger.info("Fetched %d constituents from NSE for %s", len(records), index)
        return pd.DataFrame(records)

    except Exception as exc:
        logger.warning("NSE fetch failed (%s), will use fallback list", exc)
        return None

    finally:
        session.close()


def get_constituents_df() -> pd.DataFrame:
    """
    Get current NIFTY 100 constituents.
    Tries NSE API first, falls back to hardcoded list.
    """
    df = fetch_nse_constituents()

    if df is None or df.empty:
        logger.info("Using fallback symbol list (%d symbols)", len(NIFTY100_SYMBOLS_FALLBACK))
        df = pd.DataFrame({
            "symbol":   NIFTY100_SYMBOLS_FALLBACK,
            "name":     NIFTY100_SYMBOLS_FALLBACK,
            "sector":   ["Unknown"] * len(NIFTY100_SYMBOLS_FALLBACK),
            "industry": ["Unknown"] * len(NIFTY100_SYMBOLS_FALLBACK),
        })

    return df


def sync_universe(mark_removed: bool = True) -> dict:
    """
    Sync current NIFTY 100 into nifty_constituents table.
    Marks previously active stocks as inactive if not in current list.

    Returns: summary dict with counts
    """
    logger.info("Starting universe sync...")
    today = date.today().isoformat()

    df = get_constituents_df()
    current_symbols = set(df["symbol"].tolist())

    # Fetch what we have in DB
    client = get_client()
    existing = client.table("nifty_constituents").select("symbol, is_active").execute().data
    existing_active = {r["symbol"] for r in existing if r["is_active"]}
    existing_all = {r["symbol"] for r in existing}

    # Upsert current constituents
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "symbol":     row["symbol"],
            "name":       row["name"],
            "sector":     row.get("sector", ""),
            "industry":   row.get("industry", ""),
            "index_name": "NIFTY100",
            "added_date": today if row["symbol"] not in existing_all else None,
            "is_active":  True,
            "updated_at": datetime.utcnow().isoformat(),
        })

    upsert_rows("nifty_constituents", rows, on_conflict="symbol,index_name")
    added = len(current_symbols - existing_all)
    logger.info("Upserted %d constituents (%d new)", len(rows), added)

    # Mark removals
    removed_count = 0
    if mark_removed:
        removed = existing_active - current_symbols
        for sym in removed:
            client.table("nifty_constituents").update({
                "is_active":    False,
                "removed_date": today,
                "updated_at":   datetime.utcnow().isoformat(),
            }).eq("symbol", sym).eq("index_name", "NIFTY100").execute()
            removed_count += 1
            logger.info("Marked %s as removed from NIFTY100", sym)

    return {
        "total":   len(rows),
        "added":   added,
        "removed": removed_count,
    }


def get_active_symbols() -> list[str]:
    """Return list of currently active NIFTY 100 symbols from DB."""
    client = get_client()
    rows = (
        client.table("nifty_constituents")
        .select("symbol")
        .eq("is_active", True)
        .eq("index_name", "NIFTY100")
        .execute()
        .data
    )
    symbols = [r["symbol"] for r in rows]
    if not symbols:
        logger.warning("No active symbols in DB — using fallback list")
        return NIFTY100_SYMBOLS_FALLBACK
    return symbols
