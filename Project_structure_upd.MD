stocks-tracker/
│
├── data/                          ← BUILT: data ingestion & storage
│   ├── sources/
│   │   ├── universe.py            ← NIFTY 100 constituent list (NSE)
│   │   ├── bse_announcements.py   ← corporate events + RSS news
│   │   └── scrapers/
│   │       ├── __init__.py
│   │       ├── base.py            ← base scraper class
│   │       ├── economic_times.py  ← Economic Times web scraper
│   │       ├── moneycontrol.py    ← Moneycontrol web scraper
│   │       ├── symbol_extractor.py ← extract symbols from text
│   │       └── ingest_news.py     ← news ingestion pipeline
│   ├── ingestion/
│   │   ├── prices.py              ← OHLCV + corporate actions (yfinance)
│   │   └── fundamentals.py        ← PE/PB/PS (yfinance + Screener.in)
│   ├── storage/
│   │   ├── db.py                  ← Supabase client + upsert helpers
│   │   └── schema.sql             ← all table definitions + views
│   ├── cache/                     ← local cache directory (gitignored)
│   └── tests/                     ← data layer tests
│
├── analysis/                      ← BUILT: analysis & screener modules
│   ├── seasonality/
│   │   ├── __init__.py
│   │   ├── patterns.py            ← STL decomposition, monthly returns
│   │   ├── charts.py              ← seasonality visualizations
│   │   └── data_loader.py         ← seasonality data utilities
│   ├── screener/
│   │   ├── value.py               ← PE/PB/PS scoring
│   │   ├── momentum.py            ← 3m/6m/1y return scoring
│   │   ├── sector.py              ← sector-relative scoring
│   │   ├── composite.py           ← combine value + momentum + sector
│   │   ├── run_screener.py        ← main screener execution script
│   │   ├── test.py                ← screener tests
│   │   └── full_scored_universe.csv ← output data
│   └── signals/
│       ├── charts.py              ← signal visualization helpers
│       └── indicators.py          ← RSI, MACD, Bollinger, ATR, VWAP
│
├── agents/                        ← PARTIALLY BUILT: AI agent layer
│   └── sentiment/
│       ├── agent.py               ← news + social mood analysis
│       └── scorer.py              ← returns -1.0 to 1.0 per stock
│
├── trading/                       ← PARTIALLY BUILT: algo trading engine
│   ├── backtest/
│   │   ├── engine.py              ← vectorised backtester
│   │   ├── metrics.py             ← Sharpe, max drawdown, win rate, CAGR
│   │   └── universe_backtest.py   ← backtest across universe
│   └── strategies/
│       └── library.py             ← strategy definitions library
│
├── dashboard/                     ← BUILT: Streamlit app
│   ├── Home.py                    ← entry point
│   ├── .streamlit/                ← Streamlit configuration
│   ├── pages/
│   │   ├── 01_stock_deep_dive.py  ← 10yr chart + events + fundamentals
│   │   ├── 02_screener.py         ← value + momentum top picks
│   │   ├── 03_sector_analysis.py  ← sector analysis dashboard
│   │   ├── 04_seasonality.py      ← seasonal pattern explorer
│   │   ├── 05_morning_brief.py    ← daily AI agent summary
│   │   ├── 06_algo_signals.py     ← live buy/sell signals
│   │   └── 07_backtester.py       ← strategy backtesting UI
│   └── components/
│       ├── charts.py              ← shared Plotly chart helpers
│       ├── data_loader.py         ← dashboard data loading utilities
│       └── sidebar.py             ← common filters (sector, date range)
│
├── scheduler/                     ← BUILT: job orchestration
│   ├── run_ingestion.py           ← CLI for all data jobs
│   ├── crontab.txt                ← local cron schedule
│   └── github_actions.yml         ← cloud schedule alternative
│
├── notebooks/                     ← BUILT: exploration & research
│   ├── data.ipynb                 ← data exploration notebook
│   ├── screener.ipynb             ← screener research notebook
│   └── news_collector.ipynb       ← news collection pipeline
│
├── shared/                        ← BUILT: utilities used across all layers
│   └── (future utilities directory)
│
├── results/                       ← output directory
│   └── ma_crossover_5y.csv        ← backtest results
│
├── logs/                          ← application logs directory
│
├── config/                        ← configuration management
│   └── (future config files)
│
├── requirements.txt               ← Python package dependencies
├── pyproject.toml                 ← project configuration (Poetry/setuptools)
├── PROJECT_STRUCTURE.md           ← original project structure documentation
├── README.md                      ← project README
└── .gitignore                     ← git ignore rules
