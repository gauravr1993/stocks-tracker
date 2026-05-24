nifty-intel/
│
├── data/                          ← BUILT: data ingestion & storage
│   ├── sources/
│   │   ├── universe.py            ← NIFTY 100 constituent list (NSE)
│   │   └── bse_announcements.py   ← corporate events + RSS news
│   ├── ingestion/
│   │   ├── prices.py              ← OHLCV + corporate actions (yfinance)
│   │   └── fundamentals.py        ← PE/PB/PS (yfinance + Screener.in)
│   ├── storage/
│   │   ├── db.py                  ← Supabase client + upsert helpers
│   │   └── schema.sql             ← all table definitions + views
│   ├── cache/                     ← local .parquet cache (gitignored)
│   └── tests/
│       ├── test_prices.py
│       ├── test_universe.py
│       └── test_db.py
│
├── analysis/                      ← NEXT: analysis & screener
│   ├── historical/
│   │   ├── chart.py               ← price chart builder (plotly)
│   │   └── event_overlay.py       ← annotate charts with news events
│   ├── seasonality/
│   │   ├── patterns.py            ← STL decomposition, monthly returns
│   │   └── monthly_bias.py        ← day-of-week / month-of-year heatmaps
│   ├── screener/
│   │   ├── value.py               ← PE/PB/PS scoring
│   │   ├── momentum.py            ← 3m/6m/1y return scoring
│   │   ├── sector.py              ← sector-relative scoring
│   │   └── composite_score.py     ← combine value + momentum + sector
│   ├── signals/
│   │   └── indicators.py          ← RSI, MACD, Bollinger, ATR, VWAP
│   └── tests/
│
├── agents/                        ← PLANNED: AI agent layer
│   ├── researcher/
│   │   ├── agent.py               ← web search, filings, earnings scanner
│   │   └── tools.py               ← tool definitions for the agent
│   ├── sentiment/
│   │   ├── agent.py               ← news + social mood analysis
│   │   └── scorer.py              ← returns -1.0 to 1.0 per stock
│   ├── technical/
│   │   ├── agent.py               ← monitors indicators, fires alerts
│   │   └── signal_watcher.py      ← RSI overbought/oversold, MACD cross
│   ├── decision/
│   │   ├── agent.py               ← synthesises all agent outputs
│   │   └── risk.py                ← stop-loss, position sizing
│   └── orchestrator.py            ← runs all agents, produces morning brief
│
├── trading/                       ← PLANNED: algo trading engine
│   ├── live/
│   │   ├── feed.py                ← Kite Connect WebSocket price feed
│   │   └── tick_processor.py      ← normalise + store tick data
│   ├── strategies/
│   │   ├── base.py                ← abstract Strategy class
│   │   ├── momentum.py            ← trend-following strategy
│   │   └── mean_reversion.py      ← RSI mean-reversion strategy
│   ├── execution/
│   │   ├── broker.py              ← Kite Connect order API wrapper
│   │   ├── order_manager.py       ← tracks open orders, fills
│   │   └── paper_trade.py         ← simulated execution (no real money)
│   └── backtest/
│       ├── engine.py              ← vectorised backtester
│       └── metrics.py             ← Sharpe, max drawdown, win rate, CAGR
│
├── dashboard/                     ← PLANNED: Streamlit app
│   ├── Home.py                    ← entry point
│   ├── pages/
│   │   ├── 01_market_overview.py  ← top gainers/losers, index heatmap
│   │   ├── 02_stock_deep_dive.py  ← 10yr chart + events + fundamentals
│   │   ├── 03_screener.py         ← value + momentum top picks
│   │   ├── 04_seasonality.py      ← seasonal pattern explorer
│   │   ├── 05_morning_brief.py    ← daily AI agent summary
│   │   └── 06_algo_signals.py     ← live buy/sell signals
│   └── components/
│       ├── charts.py              ← shared Plotly chart helpers
│       ├── tables.py              ← styled dataframe components
│       └── sidebar.py             ← common filters (sector, date range)
│
├── scheduler/                     ← job orchestration
│   ├── run_ingestion.py           ← CLI for all data jobs (built)
│   ├── run_agents.py              ← CLI for agent morning run (planned)
│   ├── crontab.txt                ← local cron schedule (built)
│   └── github_actions.yml         ← cloud schedule alternative (planned)
│
├── config/
│   ├── .env.example               ← environment variables template
│   └── settings.py                ← typed config via pydantic-settings
│
├── shared/                        ← utilities used across all layers
│   ├── logging.py                 ← structured logging setup
│   ├── date_utils.py              ← IST timezone helpers, market calendar
│   └── constants.py               ← NIFTY100 symbol list, sector map
│
├── notebooks/                     ← exploration & research
│   ├── 01_data_exploration.ipynb
│   ├── 02_seasonality_research.ipynb
│   └── 03_strategy_research.ipynb
│
├── requirements.txt               ← built
├── README.md                      ← built
└── PROJECT_STRUCTURE.md           ← this file

Key Design Rules:
    1. Every layer imports from data/ and shared/ only — no circular imports.
    2. analysis/ never imports from agents/ or trading/.
    3. trading/ imports from analysis/signals but not from agents/.
    4. dashboard/ is a consumer of everything — it imports freely but never imported from.
    5. All DB access goes through data/storage/db.py — no raw Supabase calls elsewhere.