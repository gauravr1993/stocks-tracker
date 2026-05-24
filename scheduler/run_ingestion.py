"""
scripts/run_ingestion.py
CLI for running data ingestion jobs.

Usage:
    # First time: full backfill (run once, takes ~30min for 100 stocks)
    python scripts/run_ingestion.py backfill

    # Daily update (run via cron every morning before market open)
    python scripts/run_ingestion.py daily

    # Specific jobs
    python scripts/run_ingestion.py universe
    python scripts/run_ingestion.py prices --symbols RELIANCE,TCS,INFY
    python scripts/run_ingestion.py fundamentals --source screener
    python scripts/run_ingestion.py news --days 7
"""
import argparse
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv("config/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("runner")


def run_universe():
    from data.sources.universe import sync_universe
    result = sync_universe()
    logger.info("Universe sync: %s", result)


def run_prices(symbols=None, backfill=False):
    from data.ingestion.prices import ingest_prices
    result = ingest_prices(symbols=symbols, backfill=backfill)
    logger.info("Prices: %s", result)


def run_corporate_actions(symbols=None):
    from data.ingestion.prices import ingest_corporate_actions
    result = ingest_corporate_actions(symbols=symbols)
    logger.info("Corporate actions: %s", result)


def run_fundamentals(symbols=None, source="yfinance"):
    from data.ingestion.fundamentals import ingest_fundamentals
    result = ingest_fundamentals(symbols=symbols, source=source)
    logger.info("Fundamentals: %s", result)


def run_news(days=7, symbols=None):
    from data.sources.bse_announcements import ingest_bse_announcements, fetch_rss_news
    from data.storage.db import upsert_rows

    # BSE announcements
    result = ingest_bse_announcements(symbols=symbols, days_back=days)
    logger.info("BSE announcements: %s", result)

    # RSS news
    rows = fetch_rss_news(symbols=symbols)
    if rows:
        upsert_rows("news_events", rows, on_conflict="bse_ann_id")
    logger.info("RSS news: %d articles", len(rows))


def cmd_backfill(args):
    """Full historical backfill — run once on project setup."""
    logger.info("=" * 60)
    logger.info("BACKFILL: Full historical data load")
    logger.info("This will take 20–40 minutes for 100 symbols")
    logger.info("=" * 60)

    run_universe()
    run_prices(backfill=True)
    run_corporate_actions()
    run_fundamentals(source=args.fundamentals_source)
    run_news(days=365)

    logger.info("Backfill complete!")


def cmd_daily(args):
    """Daily incremental update — run via morning cron."""
    logger.info("Daily update starting...")

    run_universe()           # check for constituent changes
    run_prices()             # yesterday's closing prices
    run_news(days=2)         # last 48hr news + BSE announcements

    # Fundamentals weekly (run on Monday only to avoid hammering Screener)
    from datetime import date
    if date.today().weekday() == 0:    # Monday
        run_fundamentals(source="yfinance")

    logger.info("Daily update complete.")


def cmd_universe(args):
    run_universe()


def cmd_prices(args):
    symbols = args.symbols.split(",") if args.symbols else None
    run_prices(symbols=symbols, backfill=args.backfill)


def cmd_fundamentals(args):
    symbols = args.symbols.split(",") if args.symbols else None
    run_fundamentals(symbols=symbols, source=args.source)


def cmd_news(args):
    symbols = args.symbols.split(",") if args.symbols else None
    run_news(days=args.days, symbols=symbols)


def main():
    parser = argparse.ArgumentParser(description="NIFTY Intel data ingestion")
    sub = parser.add_subparsers(dest="command", required=True)

    # backfill
    p_back = sub.add_parser("backfill", help="Full historical backfill (run once)")
    p_back.add_argument("--fundamentals-source", default="yfinance",
                        choices=["yfinance", "screener"])
    p_back.set_defaults(func=cmd_backfill)

    # daily
    p_daily = sub.add_parser("daily", help="Daily incremental update")
    p_daily.set_defaults(func=cmd_daily)

    # universe
    p_uni = sub.add_parser("universe", help="Sync NIFTY 100 constituent list")
    p_uni.set_defaults(func=cmd_universe)

    # prices
    p_prices = sub.add_parser("prices", help="Ingest OHLCV prices")
    p_prices.add_argument("--symbols", help="Comma-separated symbols")
    p_prices.add_argument("--backfill", action="store_true")
    p_prices.set_defaults(func=cmd_prices)

    # fundamentals
    p_fund = sub.add_parser("fundamentals", help="Ingest fundamental ratios")
    p_fund.add_argument("--symbols", help="Comma-separated symbols")
    p_fund.add_argument("--source", default="yfinance", choices=["yfinance", "screener"])
    p_fund.set_defaults(func=cmd_fundamentals)

    # news
    p_news = sub.add_parser("news", help="Ingest BSE announcements and RSS news")
    p_news.add_argument("--days", type=int, default=7)
    p_news.add_argument("--symbols", help="Comma-separated symbols")
    p_news.set_defaults(func=cmd_news)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
