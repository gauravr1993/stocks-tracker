"""
data/ingestion/prices.py
Historical OHLCV ingestion from yfinance (primary) + nsepy (delivery data).
Handles batching, deduplication, and incremental updates.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from data.sources.universe import get_active_symbols
from data.storage.db import upsert_rows, fetch_rows, log_ingestion

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
NSE_SUFFIX = ".NS"


# ── helpers ──────────────────────────────────────────────────────────────────

def _nse_ticker(symbol: str) -> str:
    """Convert bare symbol to yfinance NSE format."""
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    return f"{symbol}{NSE_SUFFIX}"


def _df_to_rows(df: pd.DataFrame, symbol: str) -> list[dict]:
    """Convert yfinance OHLCV DataFrame to list of dicts for Supabase."""
    rows = []
    for idx, row in df.iterrows():
        dt = idx.date() if hasattr(idx, "date") else idx
        close = float(row.get("Close", 0))
        if close <= 0:
            continue
        rows.append({
            "symbol":    symbol,
            "date":      dt.isoformat(),
            "open":      round(float(row.get("Open",   close)), 4),
            "high":      round(float(row.get("High",   close)), 4),
            "low":       round(float(row.get("Low",    close)), 4),
            "close":     round(close,                           4),
            "adj_close": round(float(row.get("Adj Close", close)), 4),
            "volume":    int(row.get("Volume", 0)),
            "source":    "yfinance",
        })
    return rows


def _get_last_date(symbol: str) -> Optional[date]:
    """Return the latest date we have for this symbol, or None."""
    rows = fetch_rows(
        "daily_prices",
        filters={"symbol": symbol},
        columns="date",
        limit=1,
    )
    # fetch_rows doesn't order — use raw supabase query for this
    from data.storage.db import get_client
    result = (
        get_client()
        .table("daily_prices")
        .select("date")
        .eq("symbol", symbol)
        .order("date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if result:
        return date.fromisoformat(result[0]["date"])
    return None


# ── main fetch ────────────────────────────────────────────────────────────────

def fetch_symbol(symbol: str,
                 start: Optional[date] = None,
                 end: Optional[date] = None,
                 auto_incremental: bool = True) -> list[dict]:
    """
    Fetch OHLCV for one symbol from yfinance.

    Args:
        symbol:           NSE symbol (bare, e.g. 'RELIANCE')
        start:            Override start date
        end:              Override end date (default: today)
        auto_incremental: If True, fetch only from last stored date

    Returns:
        List of row dicts ready for upsert
    """
    ticker = _nse_ticker(symbol)
    end_dt = end or date.today()

    if start is None:
        if auto_incremental:
            last = _get_last_date(symbol)
            start = (last + timedelta(days=1)) if last else (end_dt - timedelta(days=365 * 10))
        else:
            start = end_dt - timedelta(days=365 * 10)

    if start >= end_dt:
        logger.debug("%s — already up to date", symbol)
        return []

    logger.debug("Fetching %s  %s → %s", ticker, start, end_dt)

    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end_dt.isoformat(),
            auto_adjust=False,
            progress=False,
            show_errors=False,
        )

        if df.empty:
            logger.warning("%s — empty response from yfinance", symbol)
            return []

        # yfinance sometimes returns MultiIndex columns when downloading single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        rows = _df_to_rows(df, symbol)
        logger.info("%s — %d rows fetched (%s → %s)", symbol, len(rows), start, end_dt)
        return rows

    except Exception as exc:
        logger.error("%s — yfinance error: %s", symbol, exc)
        return []


# ── batch ingestion ───────────────────────────────────────────────────────────

def ingest_prices(
    symbols: Optional[list[str]] = None,
    start: Optional[date] = None,
    backfill: bool = False,
    batch_size: int = BATCH_SIZE,
    delay: float = 1.0,
) -> dict:
    """
    Ingest daily prices for a list of symbols (default: all active NIFTY 100).

    Args:
        symbols:    List of symbols; if None, fetches all active from DB
        start:      Force start date (overrides incremental logic)
        backfill:   If True, fetch full 10yr history regardless of what's stored
        batch_size: Symbols per batch before a pause
        delay:      Seconds to sleep between batches

    Returns:
        Summary dict with total inserted/updated/failed counts
    """
    import time as _time
    t0 = _time.time()

    if symbols is None:
        symbols = get_active_symbols()

    logger.info("Starting price ingestion for %d symbols (backfill=%s)", len(symbols), backfill)

    total_inserted = 0
    total_updated = 0
    failed = []

    for i, symbol in enumerate(symbols, 1):
        try:
            rows = fetch_symbol(
                symbol,
                start=start,
                auto_incremental=not backfill,
            )

            if rows:
                upsert_rows("daily_prices", rows, on_conflict="symbol,date")
                total_inserted += len(rows)
                logger.info("[%d/%d] %s — upserted %d rows", i, len(symbols), symbol, len(rows))
            else:
                logger.debug("[%d/%d] %s — no new rows", i, len(symbols), symbol)

        except Exception as exc:
            logger.error("[%d/%d] %s — FAILED: %s", i, len(symbols), symbol, exc)
            failed.append(symbol)

        # Rate limit: pause between batches
        if i % batch_size == 0 and i < len(symbols):
            logger.debug("Batch pause %.1fs ...", delay)
            _time.sleep(delay)

    duration = _time.time() - t0
    status = "success" if not failed else ("partial" if total_inserted > 0 else "failed")

    log_ingestion(
        job_name="daily_prices",
        status=status,
        duration=duration,
        inserted=total_inserted,
        error=f"Failed: {failed}" if failed else None,
        metadata={
            "symbols_attempted": len(symbols),
            "symbols_failed":    len(failed),
            "backfill":          backfill,
        },
    )

    logger.info(
        "Price ingestion done — %d inserted, %d failed, %.1fs",
        total_inserted, len(failed), duration,
    )
    return {
        "inserted": total_inserted,
        "failed":   failed,
        "duration": round(duration, 1),
    }


# ── corporate actions ─────────────────────────────────────────────────────────

def fetch_corporate_actions_yf(symbol: str) -> list[dict]:
    """
    Fetch dividends and splits from yfinance for a symbol.
    These supplement the BSE announcements source.
    """
    ticker = yf.Ticker(_nse_ticker(symbol))
    rows = []

    try:
        # Dividends
        divs = ticker.dividends
        for dt, amount in divs.items():
            rows.append({
                "symbol":      symbol,
                "action_type": "dividend",
                "ex_date":     dt.date().isoformat(),
                "amount":      round(float(amount), 4),
                "source":      "yfinance",
            })

        # Splits
        splits = ticker.splits
        for dt, ratio in splits.items():
            rows.append({
                "symbol":      symbol,
                "action_type": "split",
                "ex_date":     dt.date().isoformat(),
                "ratio":       round(float(ratio), 4),
                "source":      "yfinance",
            })

        logger.debug("%s — %d corporate actions", symbol, len(rows))
    except Exception as exc:
        logger.warning("%s — corporate actions fetch failed: %s", symbol, exc)

    return rows


def ingest_corporate_actions(symbols: Optional[list[str]] = None) -> dict:
    """Ingest dividends and splits for all symbols."""
    import time as _time

    if symbols is None:
        symbols = get_active_symbols()

    total = 0
    for i, symbol in enumerate(symbols, 1):
        rows = fetch_corporate_actions_yf(symbol)
        if rows:
            upsert_rows("corporate_actions", rows, on_conflict="symbol,action_type,ex_date")
            total += len(rows)
        if i % 20 == 0:
            _time.sleep(1)

    logger.info("Corporate actions done — %d rows for %d symbols", total, len(symbols))
    return {"inserted": total, "symbols": len(symbols)}
