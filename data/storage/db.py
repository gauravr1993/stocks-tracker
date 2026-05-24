"""
data/storage/db.py
Supabase client — singleton with retry logic and upsert helpers.
"""
from __future__ import annotations

import os
import time
import logging
from functools import wraps
from typing import Any

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    """Return a singleton Supabase client."""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
        logger.info("Supabase client initialised — %s", url)
    return _client


def retry(max_attempts: int = 3, delay: float = 2.0):
    """Decorator: retry on transient errors with exponential backoff."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        wait = delay * (2 ** (attempt - 1))
                        logger.warning("Attempt %d/%d failed: %s — retrying in %.1fs",
                                       attempt, max_attempts, exc, wait)
                        time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator


@retry()
def upsert_rows(table: str, rows: list[dict[str, Any]], on_conflict: str) -> dict:
    """
    Upsert a batch of rows into a Supabase table.

    Args:
        table:       Table name, e.g. 'daily_prices'
        rows:        List of dicts matching the table schema
        on_conflict: Comma-separated conflict columns, e.g. 'symbol,date'

    Returns:
        Supabase response data dict
    """
    if not rows:
        return {"count": 0}

    client = get_client()
    response = (
        client.table(table)
        .upsert(rows, on_conflict=on_conflict)
        .execute()
    )
    return response.data


@retry()
def fetch_rows(table: str, filters: dict[str, Any] | None = None,
               columns: str = "*", limit: int | None = None) -> list[dict]:
    """Simple select with optional equality filters."""
    client = get_client()
    query = client.table(table).select(columns)

    if filters:
        for col, val in filters.items():
            query = query.eq(col, val)

    if limit:
        query = query.limit(limit)

    return query.execute().data


def log_ingestion(job_name: str, status: str, duration: float,
                  inserted: int = 0, updated: int = 0, skipped: int = 0,
                  error: str | None = None, metadata: dict | None = None) -> None:
    """Write a row to ingestion_log."""
    row = {
        "job_name":          job_name,
        "status":            status,
        "duration_secs":     round(duration, 2),
        "rows_inserted":     inserted,
        "rows_updated":      updated,
        "rows_skipped":      skipped,
        "error_msg":         error,
        "metadata":          metadata or {},
    }
    try:
        get_client().table("ingestion_log").insert(row).execute()
    except Exception as exc:
        logger.error("Failed to write ingestion log: %s", exc)
