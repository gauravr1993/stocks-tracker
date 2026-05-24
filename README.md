# NIFTY Intel — Data Layer

## Setup

### 1. Supabase
1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** and run `data/storage/schema.sql`
3. Copy your project URL and service role key

### 2. Environment
```bash
cp config/.env.example config/.env
# Edit config/.env with your Supabase credentials
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. First-time backfill (run once)
```bash
python scripts/run_ingestion.py backfill
```
This fetches:
- NIFTY 100 constituent list (with historical membership)
- 10 years of daily OHLCV for all 100 stocks
- Dividends and splits from yfinance
- Fundamental ratios (PE/PB/PS) via yfinance
- Last 12 months of BSE corporate announcements

Takes ~30–40 minutes. Progress is logged to console.

### 5. Daily updates (via cron)
```bash
# Add to crontab — see scripts/crontab.txt for the schedule
python scripts/run_ingestion.py daily
```

---

## Project structure
```
nifty-intel/
├── config/
│   └── .env.example          # environment variables template
├── data/
│   ├── ingestion/
│   │   ├── prices.py         # OHLCV + corporate actions (yfinance)
│   │   └── fundamentals.py   # PE/PB/PS (yfinance + Screener.in)
│   ├── sources/
│   │   ├── universe.py       # NIFTY 100 constituent list (NSE)
│   │   └── bse_announcements.py  # Corporate events + RSS news
│   └── storage/
│       ├── db.py             # Supabase client + upsert helpers
│       └── schema.sql        # All table definitions + views
├── scripts/
│   ├── run_ingestion.py      # CLI runner
│   └── crontab.txt           # Cron schedule
└── requirements.txt
```

## Tables

| Table | Description | ~Rows |
|---|---|---|
| `nifty_constituents` | Index membership history | ~150 |
| `corporate_actions` | Dividends, splits, bonuses | ~5,000 |
| `daily_prices` | OHLCV, 10yr, 100 stocks | ~250,000 |
| `fundamentals` | PE/PB/PS, quarterly | ~2,000 |
| `news_events` | BSE announcements + RSS | ~50,000 |
| `ingestion_log` | Job run history | grows daily |

## Useful Supabase views
- `latest_prices` — current price for all active stocks
- `price_returns` — 3m/6m/1yr returns (used by screener)

## Common commands
```bash
# Sync constituent list only
python scripts/run_ingestion.py universe

# Update specific symbols
python scripts/run_ingestion.py prices --symbols RELIANCE,TCS,HDFCBANK

# Refresh fundamentals from Screener (slower, more accurate)
python scripts/run_ingestion.py fundamentals --source screener

# Fetch last 30 days of news
python scripts/run_ingestion.py news --days 30
```
