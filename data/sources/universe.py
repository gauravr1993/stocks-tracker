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
NIFTY100_SYMBOLS_FALLBACK = ['HDFCBANK.NS', 'RELIANCE.NS', 'ICICIBANK.NS', 'BHARTIARTL.NS', 
                             'LT.NS', 'INFY.NS', 'SBIN.NS', 'AXISBANK.NS', 'ITC.NS', 'KOTAKBANK.NS', 
                             'M&M.NS', 'BAJFINANCE.NS', 'TCS.NS', 'SUNPHARMA.NS', 'HINDUNILVR.NS', 
                             'NTPC.NS', 'ETERNAL.NS', 'TATASTEEL.NS', 'MARUTI.NS', 'TITAN.NS', 
                             'HINDALCO.NS', 'BEL.NS', 'ULTRACEMCO.NS', 'POWERGRID.NS', 'SHRIRAMFIN.NS', 
                             'ADANIPORTS.NS', 'HCLTECH.NS', 'JSWSTEEL.NS', 'GRASIM.NS', 'ASIANPAINT.NS', 
                             'BAJAJ-AUTO.NS', 'ONGC.NS', 'COALINDIA.NS', 'BAJAJFINSV.NS', 'NESTLEIND.NS', 
                             'INDIGO.NS', 'EICHERMOT.NS', 'TRENT.NS', 'ADANIPOWER.NS', 'TECHM.NS', 
                             'DIVISLAB.NS', 'APOLLOHOSP.NS', 'SBILIFE.NS', 'HAL.NS', 'DRREDDY.NS', 
                             'TMCV.NS', 'TVSMOTOR.NS', 'JIOFIN.NS', 'CIPLA.NS', 'ADANIENT.NS', 
                             'TATACONSUM.NS', 'TMPV.NS', 'MAXHEALTH.NS', 'VBL.NS', 'CUMMINSIND.NS', 
                             'TATAPOWER.NS', 'HDFCLIFE.NS', 'CHOLAFIN.NS', 'PFC.NS', 'BRITANNIA.NS', 
                             'DMART.NS', 'BPCL.NS', 'MOTHERSON.NS', 'CGPOWER.NS', 'INDHOTEL.NS', 
                             'WIPRO.NS', 'VEDL.NS', 'HDFCAMC.NS', 'IOC.NS', 'BANKBARODA.NS', 
                             'ADANIENSOL.NS', 'TORNTPHARM.NS', 'JINDALSTEL.NS', 'BAJAJHLDNG.NS', 
                             'PIDILITIND.NS', 'ADANIGREEN.NS', 'SOLARINDS.NS', 'GAIL.NS', 'RECLTD.NS', 
                             'CANBK.NS', 'GODREJCP.NS', 'DLF.NS', 'UNITDSPR.NS', 'LTM.NS', 'PNB.NS', 
                             'MUTHOOTFIN.NS', 'ABB.NS', 'SHREECEM.NS', 'SIEMENS.NS', 'ENRIN.NS', 
                             'BOSCHLTD.NS', 'UNIONBANK.NS', 'HINDZINC.NS', 'HYUNDAI.NS', 'AMBUJACEM.NS', 
                             'ZYDUSLIFE.NS', 'LODHA.NS', 'IRFC.NS', 'MAZDOCK.NS', 'TATACAP.NS']

SECTORS_FALLBACK = [
    'Financial Services', 'Energy', 'Financial Services', 'Telecommunication',
    'Industrials', 'Information Technology', 'Financial Services', 'Financial Services',
    'FMCG', 'Financial Services', 'Automobile', 'Financial Services',
    'Information Technology', 'Healthcare', 'FMCG', 'Utilities',
    'Consumer Services', 'Metals & Mining', 'Automobile', 'Consumer Discretionary',
    'Metals & Mining', 'Defence', 'Materials', 'Utilities',
    'Financial Services', 'Infrastructure', 'Information Technology', 'Metals & Mining',
    'Materials', 'Consumer Goods', 'Automobile', 'Energy',
    'Energy', 'Financial Services', 'FMCG', 'Aviation',
    'Automobile', 'Retail', 'Utilities', 'Information Technology',
    'Healthcare', 'Healthcare', 'Financial Services', 'Defence',
    'Healthcare', 'Automobile', 'Automobile', 'Financial Services',
    'Healthcare', 'Diversified', 'FMCG', 'Automobile',
    'Healthcare', 'FMCG', 'Industrials', 'Utilities',
    'Financial Services', 'Financial Services', 'Financial Services', 'FMCG',
    'Retail', 'Energy', 'Automobile', 'Industrials',
    'Hospitality', 'Information Technology', 'Metals & Mining', 'Financial Services',
    'Energy', 'Financial Services', 'Utilities', 'Healthcare',
    'Metals & Mining', 'Financial Services', 'Chemicals', 'Utilities',
    'Chemicals', 'Energy', 'Financial Services', 'Financial Services',
    'FMCG', 'Real Estate', 'FMCG', 'Information Technology',
    'Financial Services', 'Financial Services', 'Industrials', 'Materials',
    'Industrials', 'Infrastructure', 'Automobile', 'Financial Services',
    'Metals & Mining', 'Automobile', 'Materials', 'Healthcare',
    'Real Estate', 'Financial Services', 'Defence', 'Financial Services'
]

INDUSTRIES_FALLBACK = [
    'Private Bank', 'Oil & Gas / Conglomerate', 'Private Bank', 'Telecom Services',
    'Engineering & Construction', 'IT Services & Consulting', 'Public Sector Bank',
    'Private Bank', 'Diversified FMCG', 'Private Bank',
    'Auto Manufacturer', 'NBFC', 'IT Services & Consulting',
    'Pharmaceuticals', 'Consumer Goods', 'Power Generation',
    'Online Food Delivery / Internet', 'Steel', 'Passenger Vehicles',
    'Jewellery & Watches', 'Non-Ferrous Metals', 'Defence Electronics',
    'Cement', 'Power Transmission', 'NBFC',
    'Ports & Logistics', 'IT Services', 'Steel',
    'Diversified Materials', 'Paints', 'Two Wheelers',
    'Oil Exploration & Production', 'Coal Mining',
    'Financial Conglomerate', 'Packaged Foods', 'Airlines',
    'Commercial Vehicles & Bikes', 'Fashion & Retail',
    'Power Generation', 'IT Services', 'Pharmaceuticals',
    'Hospitals', 'Life Insurance', 'Aerospace & Defence',
    'Pharmaceuticals', 'Commercial Vehicles', 'Two Wheelers',
    'Financial Services', 'Pharmaceuticals',
    'Trading & Infrastructure', 'Food & Beverages',
    'Passenger Vehicles', 'Hospitals', 'Beverages',
    'Industrial Engines', 'Integrated Power Utilities',
    'Life Insurance', 'NBFC', 'Power Sector Financing',
    'Packaged Foods', 'Supermarkets & Hypermarkets',
    'Oil Marketing', 'Auto Components',
    'Electrical Equipment', 'Hotels', 'IT Services',
    'Diversified Mining', 'Asset Management',
    'Oil Marketing', 'Public Sector Bank',
    'Power Transmission', 'Pharmaceuticals',
    'Steel', 'Investment Company',
    'Specialty Chemicals', 'Renewable Energy',
    'Explosives & Defence', 'Gas Transmission',
    'Power Sector Financing', 'Public Sector Bank',
    'Personal Care', 'Real Estate Development',
    'Alcoholic Beverages', 'IT Services & Consulting',
    'Public Sector Bank', 'Gold Loan NBFC',
    'Industrial Automation', 'Cement',
    'Industrial Engineering', 'Energy Infrastructure',
    'Auto Components', 'Public Sector Bank',
    'Zinc Mining', 'Passenger Vehicles',
    'Cement', 'Pharmaceuticals',
    'Real Estate Development', 'Railway Financing',
    'Shipbuilding & Defence', 'NBFC'
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
            "sector":   SECTORS_FALLBACK,
            "industry": INDUSTRIES_FALLBACK,
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
