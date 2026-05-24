"""
data/ingestion/fundamentals.py
Fetch PE, PB, PS, and other fundamental ratios.
Primary: yfinance info (fast, free, less accurate)
Secondary: Screener.in scrape (slower, more accurate for Indian markets)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from data.sources.universe import get_active_symbols
from data.storage.db import upsert_rows, log_ingestion

logger = logging.getLogger(__name__)


# ── yfinance fundamentals (fast but approximate) ──────────────────────────────

def fetch_fundamentals_yf(symbol: str) -> Optional[dict]:
    """
    Fetch fundamental ratios from yfinance.
    Fast but PE/PB may be TTM and slightly stale.
    """
    ticker = yf.Ticker(f"{symbol}.NS")

    try:
        info = ticker.info
        if not info or info.get("regularMarketPrice") is None:
            return None

        market_cap_cr = None
        mc = info.get("marketCap")
        if mc:
            market_cap_cr = round(mc / 1e7, 2)    # convert to crores

        return {
            "symbol":       symbol,
            "report_date":  date.today().isoformat(),
            "report_type":  "ttm",
            "pe_ratio":     info.get("trailingPE"),
            "pb_ratio":     info.get("priceToBook"),
            "ps_ratio":     info.get("priceToSalesTrailing12Months"),
            "ev_ebitda":    info.get("enterpriseToEbitda"),
            "market_cap":   market_cap_cr,
            "revenue":      round(info.get("totalRevenue", 0) / 1e7, 2) if info.get("totalRevenue") else None,
            "net_income":   round(info.get("netIncomeToCommon", 0) / 1e7, 2) if info.get("netIncomeToCommon") else None,
            "eps":          info.get("trailingEps"),
            "roe":          round(info.get("returnOnEquity", 0) * 100, 2) if info.get("returnOnEquity") else None,
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio":  info.get("currentRatio"),
            "revenue_growth": round(info.get("revenueGrowth", 0) * 100, 2) if info.get("revenueGrowth") else None,
            "earnings_growth": round(info.get("earningsGrowth", 0) * 100, 2) if info.get("earningsGrowth") else None,
            "source":       "yfinance",
        }

    except Exception as exc:
        logger.warning("%s — yfinance fundamentals failed: %s", symbol, exc)
        return None


# ── Screener.in scraper (more accurate for Indian ratios) ────────────────────

SCREENER_BASE = "https://www.screener.in/company"
SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "text/html",
}


def _parse_number(text: str) -> Optional[float]:
    """Extract first float from a text string."""
    if not text:
        return None
    text = text.replace(",", "").strip()
    match = re.search(r"-?[\d.]+", text)
    return float(match.group()) if match else None


def fetch_fundamentals_screener(symbol: str) -> Optional[dict]:
    """
    Scrape fundamental data from Screener.in.
    More reliable PE/PB/PS for NSE-listed companies.
    Be respectful: add delay between requests.
    """
    url = f"{SCREENER_BASE}/{symbol}/consolidated/"
    try:
        response = requests.get(url, headers=SCREENER_HEADERS, timeout=15)
        if response.status_code == 404:
            # Try standalone (non-consolidated)
            response = requests.get(
                f"{SCREENER_BASE}/{symbol}/",
                headers=SCREENER_HEADERS,
                timeout=15,
            )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("%s — Screener fetch failed: %s", symbol, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    ratios: dict = {}

    # Screener's "company-ratios" section has key metrics
    ratio_section = soup.find("ul", id="top-ratios")
    if ratio_section:
        for li in ratio_section.find_all("li"):
            name_tag  = li.find("span", class_="name")
            value_tag = li.find("span", class_="value") or li.find("span", class_="number")
            if name_tag and value_tag:
                name  = name_tag.get_text(strip=True).lower()
                value = _parse_number(value_tag.get_text(strip=True))
                if "p/e" in name:
                    ratios["pe_ratio"] = value
                elif "p/b" in name:
                    ratios["pb_ratio"] = value
                elif "p/s" in name or "price/sales" in name:
                    ratios["ps_ratio"] = value
                elif "market cap" in name:
                    ratios["market_cap"] = value   # already in crores on screener
                elif "roe" in name:
                    ratios["roe"] = value
                elif "roce" in name:
                    ratios["roce"] = value
                elif "debt" in name and "equity" in name:
                    ratios["debt_to_equity"] = value
                elif "eps" in name:
                    ratios["eps"] = value

    if not ratios:
        logger.debug("%s — no ratios parsed from Screener", symbol)
        return None

    return {
        "symbol":         symbol,
        "report_date":    date.today().isoformat(),
        "report_type":    "ttm",
        **ratios,
        "source": "screener",
    }


# ── batch ingestion ───────────────────────────────────────────────────────────

def ingest_fundamentals(
    symbols: Optional[list[str]] = None,
    source: str = "yfinance",    # 'yfinance' or 'screener'
    delay: float = 2.0,
) -> dict:
    """
    Ingest fundamentals for all active NIFTY 100 symbols.

    Args:
        symbols: Override symbol list
        source:  Data source to use
        delay:   Seconds between requests (Screener needs ~2s to be polite)

    Returns:
        Summary dict
    """
    import time as _time
    t0 = _time.time()

    if symbols is None:
        symbols = get_active_symbols()

    fetch_fn = fetch_fundamentals_screener if source == "screener" else fetch_fundamentals_yf
    logger.info("Fundamentals ingestion: %d symbols via %s", len(symbols), source)

    rows = []
    failed = []

    for i, symbol in enumerate(symbols, 1):
        try:
            row = fetch_fn(symbol)
            if row:
                rows.append(row)
                logger.debug("[%d/%d] %s — ok", i, len(symbols), symbol)
            else:
                logger.debug("[%d/%d] %s — no data", i, len(symbols), symbol)
        except Exception as exc:
            logger.error("[%d/%d] %s — ERROR: %s", i, len(symbols), symbol, exc)
            failed.append(symbol)

        _time.sleep(delay)

    if rows:
        upsert_rows("fundamentals", rows, on_conflict="symbol,report_date,report_type")

    duration = _time.time() - t0
    status = "success" if not failed else "partial"
    log_ingestion(
        job_name="fundamentals",
        status=status,
        duration=duration,
        inserted=len(rows),
        error=str(failed) if failed else None,
        metadata={"source": source, "symbols_attempted": len(symbols)},
    )

    logger.info("Fundamentals done — %d rows, %d failed, %.1fs", len(rows), len(failed), duration)
    return {"inserted": len(rows), "failed": failed, "duration": round(duration, 1)}
