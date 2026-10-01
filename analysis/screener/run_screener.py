"""
analysis/screener/run_screener.py
Main entry point — pulls data from Supabase, runs all scorers,
returns fully scored DataFrame and top picks.

Usage (notebook or script):
    from analysis.screener.run_screener import run_screener, get_picks

    # Full scored universe
    df = run_screener()

    # Top 10 balanced picks
    picks = get_picks(df, n=10, mode="balanced")

    # Top 5 value picks
    value = get_picks(df, n=5, mode="value")

    # Top 5 momentum picks
    momentum = get_picks(df, n=5, mode="momentum")
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

from data.storage.db import get_client
from analysis.screener.value     import score_value
from analysis.screener.momentum  import score_momentum
from analysis.screener.sector    import score_sector
from analysis.screener.composite import score_composite, get_top_picks, BALANCED, ScoreWeights

logger = logging.getLogger(__name__)

# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_universe() -> pd.DataFrame:
    """Active NIFTY 100 stocks with sector info."""
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


def _fetch_latest_fundamentals() -> pd.DataFrame:
    """Most recent fundamental row per symbol (TTM preferred)."""
    client = get_client()

    # Get latest report_date per symbol
    rows = (
        client.table("fundamentals")
        .select("symbol, report_date, pe_ratio, pb_ratio, ps_ratio, market_cap, "
                "roe, debt_to_equity, ev_ebitda, current_ratio, "
                "revenue_growth, earnings_growth, source")
        .order("report_date", desc=True)
        .execute()
        .data
    )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Keep only the latest row per symbol
    df = df.sort_values("report_date", ascending=False).drop_duplicates("symbol")
    return df


def _fetch_price_returns() -> pd.DataFrame:
    """Latest return_3m / 6m / 1y per symbol — computed from daily_prices directly."""
    client = get_client()

    # Fetch from daily_prices instead of the view to avoid Supabase filter
    # reliability issues on views. Compute returns in pandas.
    # Supabase default page limit is 1000 — paginate to get all rows
    all_rows = []
    page_size = 10000 # requires db-max-rows >= 10000 in Supabase settings
    offset = 0
    start_time = time.time()
    while True:
        batch = (
            client.table("daily_prices")
            .select("symbol, date, adj_close")
            .order("date", desc=True)
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
        if offset >= 100 * 300:   # safety cap: 100 stocks x 300 days
            break
    rows = all_rows
    if not rows:
        return pd.DataFrame()
    print(f"Fetched {len(rows)} daily price rows in {time.time() - start_time:.1f}s", flush=True)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["adj_close"] = df["adj_close"].astype(float)
    df = df.sort_values(["symbol", "date"])

    results = []
    start_time = time.time()
    for symbol, grp in df.groupby("symbol"):
        grp = grp.reset_index(drop=True)
        prices = grp["adj_close"]
        n = len(prices)
        latest = prices.iloc[-1]

        def _ret(days, _p=prices, _n=n, _l=latest):
            idx = _n - days - 1
            if idx < 0:
                return None
            past = _p.iloc[idx]
            return round(((_l / past) - 1) * 100, 2) if past > 0 else None

        results.append({
            "symbol":    symbol,
            "return_3m": _ret(63),
            "return_6m": _ret(126),
            "return_1y": _ret(252),
        })
    print(f"Computed returns for {len(results)} symbols in {time.time() - start_time:.1f}s", flush=True)
    out = pd.DataFrame(results)
    out = out.dropna(subset=["return_3m", "return_6m", "return_1y"], how="all")
    print(f"Computed returns for {len(out)} symbols", flush=True)
    logger.info("Price returns computed for %d symbols, %d raw price rows", len(out), len(df))
    # Return both the returns summary AND the raw prices df so the caller
    # can pass it to score_momentum for volatility calculation without re-fetching
    return out, df


def _fetch_daily_prices() -> pd.DataFrame:
    """
    Stub — prices are already fetched by _fetch_price_returns via pagination.
    Keeping this function to avoid breaking the call signature but returning
    empty so the caller uses the shared prices_df instead.
    """
    return pd.DataFrame()


# ── Main screener ─────────────────────────────────────────────────────────────

def run_screener(include_vol_penalty: bool = True) -> pd.DataFrame:
    """
    Pull data from Supabase and run all three scorers.

    Args:
        include_vol_penalty: Pass daily prices to momentum scorer for vol adjustment

    Returns:
        Fully scored DataFrame with all dimension scores + composite
    """
    t0 = time.time()
    logger.info("Running screener...")
    print("Running screener...", flush=True)
    # ── Fetch all data ────────────────────────────────────────────────────────
    start_time = time.time()
    universe     = _fetch_universe()
    print(f"Fetched universe: {len(universe)} stocks in {time.time() - start_time:.1f}s", flush=True)
    start_time = time.time()
    fundamentals = _fetch_latest_fundamentals()
    print(f"Fetched fundamentals: {len(fundamentals)} rows in {time.time() - start_time:.1f}s", flush=True)
    start_time = time.time()
    # _fetch_price_returns paginates daily_prices and returns both returns + raw prices
    returns, prices_df = _fetch_price_returns()
    print(f"Fetched returns: {len(returns)} rows, prices: {len(prices_df)} rows in {time.time() - start_time:.1f}s", flush=True)

    logger.info(
        "Fetched: %d universe, %d fundamentals, %d symbols with returns, %d price rows",
        len(universe), len(fundamentals), len(returns), len(prices_df),
    )

    # ── Merge into one wide DataFrame ─────────────────────────────────────────
    df = universe.copy()
    df = df.merge(fundamentals, on="symbol", how="left")
    df = df.merge(returns,      on="symbol", how="left")

    # ── Score each dimension ──────────────────────────────────────────────────
    df = score_value(df)
    df = score_momentum(df, prices_df=prices_df if include_vol_penalty else None)
    df = score_sector(df)
    df = score_composite(df)

    elapsed = time.time() - t0
    logger.info(
        "Screener complete — %d stocks scored in %.1fs",
        df["composite_score"].notna().sum(), elapsed,
    )
    return df


def get_picks(
    df: Optional[pd.DataFrame] = None,
    n: int = 10,
    mode: str = "balanced",
    min_confidence: float = 0.67,
    exclude_sectors: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Convenience wrapper — runs screener if df not provided, returns top N picks.

    Args:
        df:               Pre-scored DataFrame (pass to avoid re-fetching)
        n:                Number of picks
        mode:             'balanced' | 'value' | 'momentum'
        min_confidence:   Require at least this fraction of dimensions to have data
        exclude_sectors:  Sectors to skip

    Returns:
        Top N picks as a clean display DataFrame
    """
    if df is None:
        df = run_screener()

    return get_top_picks(
        df,
        n=n,
        mode=mode,
        min_confidence=min_confidence,
        exclude_sectors=exclude_sectors or ["Unknown"],
    )


# ── Sector summary ─────────────────────────────────────────────────────────────

def sector_summary(df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Returns a sector-level summary sorted by sector strength.
    Useful for understanding which sectors are currently leading.
    """
    if df is None:
        df = run_screener()

    summary = (
        df.groupby("sector")
        .agg(
            stocks=("symbol", "count"),
            avg_composite=("composite_score", "mean"),
            avg_value=("value_score", "mean"),
            avg_momentum=("momentum_score", "mean"),
            sector_strength=("sector_strength_score", "first"),
            median_pe=("pe_ratio", "median"),
            median_return_1y=("return_1y", "median"),
        )
        .round(2)
        .sort_values("sector_strength", ascending=False)
        .reset_index()
    )
    return summary


## ── Main entry point for script usage to run screener ─────────────────────────────────────────

if __name__ == "__main__":
    df = run_screener()
    df.to_csv("screener_output.csv", index=False)