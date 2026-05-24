-- ============================================================
-- NIFTY INTEL — Supabase Schema
-- Run this in Supabase SQL editor (Dashboard > SQL Editor)
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ============================================================
-- UNIVERSE LAYER
-- ============================================================

create table if not exists nifty_constituents (
    symbol          text        not null,
    name            text        not null,
    sector          text,
    industry        text,
    index_name      text        not null default 'NIFTY100',
    added_date      date,
    removed_date    date,
    is_active       boolean     not null default true,
    isin            text,
    updated_at      timestamptz not null default now(),
    primary key (symbol, index_name)
);

comment on table nifty_constituents is 'Historical NIFTY index membership — tracks additions and removals to avoid survivorship bias';

create table if not exists corporate_actions (
    id              uuid        primary key default uuid_generate_v4(),
    symbol          text        not null,
    action_type     text        not null,  -- 'dividend', 'split', 'bonus', 'rights', 'merger'
    ex_date         date        not null,
    record_date     date,
    announcement_date date,
    ratio           numeric,               -- for splits/bonus: new:old ratio
    amount          numeric,               -- for dividends: amount per share
    notes           text,
    source          text,                  -- 'bse', 'nse', 'manual'
    bse_ann_id      text,                  -- BSE announcement reference
    created_at      timestamptz not null default now(),
    unique (symbol, action_type, ex_date)
);

create index if not exists idx_corp_actions_symbol_date on corporate_actions(symbol, ex_date desc);

-- ============================================================
-- MARKET DATA LAYER
-- ============================================================

create table if not exists daily_prices (
    symbol          text        not null,
    date            date        not null,
    open            numeric     not null,
    high            numeric     not null,
    low             numeric     not null,
    close           numeric     not null,
    adj_close       numeric,               -- adjusted for splits/dividends
    volume          bigint      not null,
    delivery_qty    bigint,                -- from NSE delivery data
    delivery_pct    numeric,               -- delivery % of total volume
    vwap            numeric,               -- volume weighted avg price
    source          text        not null default 'yfinance',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    primary key (symbol, date)
);

comment on table daily_prices is 'OHLCV daily data for all NIFTY 100 constituents, 10yr history';

create index if not exists idx_daily_prices_date on daily_prices(date desc);
create index if not exists idx_daily_prices_symbol on daily_prices(symbol);

create table if not exists fundamentals (
    id              uuid        primary key default uuid_generate_v4(),
    symbol          text        not null,
    report_date     date        not null,  -- quarter end date
    report_type     text        not null default 'quarterly',  -- 'quarterly', 'annual', 'ttm'
    -- Valuation ratios
    pe_ratio        numeric,
    pb_ratio        numeric,
    ps_ratio        numeric,
    ev_ebitda       numeric,
    -- Size
    market_cap      numeric,               -- in crores INR
    enterprise_value numeric,
    -- Profitability
    revenue         numeric,               -- in crores INR
    net_income      numeric,
    ebitda          numeric,
    eps             numeric,
    roe             numeric,               -- return on equity %
    roce            numeric,               -- return on capital employed %
    -- Leverage
    debt_to_equity  numeric,
    current_ratio   numeric,
    -- Growth (YoY)
    revenue_growth  numeric,               -- %
    earnings_growth numeric,               -- %
    source          text        not null default 'screener',
    created_at      timestamptz not null default now(),
    unique (symbol, report_date, report_type)
);

create index if not exists idx_fundamentals_symbol_date on fundamentals(symbol, report_date desc);

-- ============================================================
-- ENRICHMENT LAYER
-- ============================================================

create table if not exists news_events (
    id              uuid        primary key default uuid_generate_v4(),
    symbol          text,                  -- null = market-wide news
    event_date      date        not null,
    published_at    timestamptz,
    headline        text        not null,
    summary         text,
    source          text        not null,  -- 'bse', 'moneycontrol', 'et', 'rss'
    url             text,
    category        text,                  -- 'earnings', 'dividend', 'split', 'macro', 'sector', 'mgmt'
    sentiment_score numeric,               -- -1.0 to 1.0, populated by sentiment agent
    sentiment_label text,                  -- 'positive', 'negative', 'neutral'
    bse_ann_id      text,                  -- BSE announcement ID if from BSE
    is_processed    boolean     not null default false,
    created_at      timestamptz not null default now()
);

create index if not exists idx_news_symbol_date on news_events(symbol, event_date desc);
create index if not exists idx_news_date on news_events(event_date desc);
create index if not exists idx_news_unprocessed on news_events(is_processed) where is_processed = false;

create table if not exists ingestion_log (
    id              uuid        primary key default uuid_generate_v4(),
    job_name        text        not null,  -- 'daily_prices', 'fundamentals', 'bse_announcements', etc.
    run_at          timestamptz not null default now(),
    status          text        not null,  -- 'success', 'partial', 'failed'
    symbols_attempted int,
    rows_inserted   int         default 0,
    rows_updated    int         default 0,
    rows_skipped    int         default 0,
    error_msg       text,
    duration_secs   numeric,
    metadata        jsonb                  -- job-specific info (date range, source, etc.)
);

create index if not exists idx_ingestion_log_job on ingestion_log(job_name, run_at desc);

-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Latest price for each active stock
create or replace view latest_prices as
select
    nc.symbol,
    nc.name,
    nc.sector,
    dp.date,
    dp.close,
    dp.adj_close,
    dp.volume,
    dp.delivery_pct,
    dp.vwap
from nifty_constituents nc
join daily_prices dp on dp.symbol = nc.symbol
where nc.is_active = true
  and dp.date = (
      select max(d2.date) from daily_prices d2 where d2.symbol = nc.symbol
  );

-- Price returns for momentum calculations
create or replace view price_returns as
select
    symbol,
    date,
    close,
    adj_close,
    lag(adj_close, 63)  over w as close_3m_ago,   -- ~3 months
    lag(adj_close, 126) over w as close_6m_ago,   -- ~6 months
    lag(adj_close, 252) over w as close_1y_ago,   -- ~1 year
    round(((adj_close / nullif(lag(adj_close, 63)  over w, 0)) - 1) * 100, 2) as return_3m,
    round(((adj_close / nullif(lag(adj_close, 126) over w, 0)) - 1) * 100, 2) as return_6m,
    round(((adj_close / nullif(lag(adj_close, 252) over w, 0)) - 1) * 100, 2) as return_1y
from daily_prices
window w as (partition by symbol order by date);

-- ============================================================
-- ROW LEVEL SECURITY (enable when adding auth later)
-- ============================================================
-- alter table daily_prices enable row level security;
-- alter table news_events enable row level security;
-- create policy "Public read" on daily_prices for select using (true);
