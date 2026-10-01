"""
analysis/seasonality/data_loader.py
Cached data fetchers specifically for the seasonality dashboard page.
Separate from dashboard/components/data_loader.py to keep concerns clean.
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd
import streamlit as st

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

logger = logging.getLogger(__name__)


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_prices() -> pd.DataFrame:
    """
    Full price history for all active NIFTY 100 symbols.
    Paginated to get past Supabase's 1000-row default limit.
    Returns DataFrame with symbol, date, adj_close columns.
    """
    from data.storage.db import get_client
    client = get_client()

    all_rows = []
    page_size = 1000
    offset    = 0

    while True:
        batch = (
            client.table("daily_prices")
            .select("symbol, date, open, high, low, close, adj_close, volume")
            .order("date", desc=False)
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

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"]      = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info("Loaded %d price rows for seasonality", len(df))
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_universe() -> pd.DataFrame:
    """Active NIFTY 100 stocks with sector info."""
    from data.storage.db import get_client
    client = get_client()
    rows = (
        client.table("nifty_constituents")
        .select("symbol, name, sector")
        .eq("is_active", True)
        .eq("index_name", "NIFTY100")
        .execute()
        .data
    )
    df = pd.DataFrame(rows)
    df["sector"] = df["sector"].fillna("Unknown")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def compute_universe_heatmap(matrix_type: str = "symbol") -> pd.DataFrame:
    """
    Pre-compute the full universe or sector heatmap matrix.
    matrix_type: 'symbol' or 'sector'
    Cached separately since it's expensive (~5s for 100 symbols).
    """
    from analysis.seasonality.patterns import (
        universe_monthly_heatmap,
        sector_monthly_heatmap,
    )

    prices   = load_all_prices()
    universe = load_universe()

    if prices.empty or universe.empty:
        return pd.DataFrame()

    if matrix_type == "sector":
        return sector_monthly_heatmap(prices, universe)
    else:
        symbols = universe["symbol"].tolist()
        return universe_monthly_heatmap(prices, symbols)