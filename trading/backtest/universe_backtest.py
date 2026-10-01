"""
trading/backtest/universe_backtest.py
Run a strategy across all NIFTY 100 stocks and rank results.

Usage:
    # Run default strategy (RSITrendStrategy) on all stocks
    python trading/backtest/universe_backtest.py

    # Run specific strategy
    python trading/backtest/universe_backtest.py --strategy rsi_mean_reversion

    # Run with parameter sweep on top candidates
    python trading/backtest/universe_backtest.py --strategy rsi_trend_filtered --sweep

    # Save results to CSV
    python trading/backtest/universe_backtest.py --output results/universe_backtest.csv
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import Optional

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.abspath(os.path.join(_here, "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_root, "config", ".env"))

logging.basicConfig(
    level   = logging.WARNING,   # suppress per-stock noise
    format  = "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt = "%H:%M:%S",
)
logger = logging.getLogger("universe_backtest")
# Only show our own logger at INFO level
logger.setLevel(logging.INFO)

import pandas as pd
import numpy as np
from tqdm import tqdm

from trading.backtest.engine  import Backtester
from trading.backtest.metrics import buy_and_hold, compare_to_benchmark
from trading.strategies.library import STRATEGIES, PARAM_GRIDS


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _get_active_symbols() -> list[dict]:
    from data.storage.db import get_client
    client = get_client()
    rows = (
        client.table("nifty_constituents")
        .select("symbol, name, sector")
        .eq("is_active", True)
        .eq("index_name", "NIFTY100")
        .execute()
        .data
    )
    # Ensure name falls back to symbol if missing
    for r in rows:
        if not r.get("name") or r["name"] == r["symbol"]:
            r["name"] = r["symbol"].replace(".NS", "")
    return rows


def _fetch_prices(symbol: str, years: int) -> pd.DataFrame:
    from data.storage.db import get_client
    client = get_client()
    since  = (date.today() - timedelta(days=365 * years + 60)).isoformat()

    # Paginate — Supabase default cap is 1000 rows, 5yr = ~1260 rows
    all_rows  = []
    page_size = 1000
    offset    = 0
    while True:
        batch = (
            client.table("daily_prices")
            .select("date, open, high, low, close, adj_close, volume")
            .eq("symbol", symbol)
            .gte("date", since)
            .order("date", desc=False)
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

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open","high","low","close","adj_close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── Single-stock backtest ─────────────────────────────────────────────────────

def backtest_symbol(
    symbol:     str,
    name:       str,
    sector:     str,
    strategy,
    years:      int   = 5,
    commission: float = 0.001,
    slippage:   float = 0.0005,
) -> Optional[dict]:
    """Run backtest for one symbol. Returns summary dict or None on failure."""
    sym_clean = symbol.replace(".NS", "")
    try:
        prices = _fetch_prices(symbol, years)
        if len(prices) < 252:   # need at least 1 year
            return None

        bt     = Backtester(prices, symbol=sym_clean,
                            commission=commission, slippage=slippage)
        result = bt.run(strategy)

        if result.n_trades == 0:
            return None

        # Buy-and-hold benchmark for this symbol
        bh_equity = buy_and_hold(prices.tail(len(result.equity_curve)))

        row = {
            "symbol":       sym_clean,
            "name":         name,
            "sector":       sector,
            "total_return": result.total_return,
            "cagr":         result.cagr,
            "sharpe":       result.sharpe,
            "sortino":      result.sortino,
            "max_drawdown": result.max_drawdown,
            "win_rate":     result.win_rate,
            "profit_factor":result.profit_factor,
            "n_trades":     result.n_trades,
            "avg_hold_days":result.avg_hold_days,
            "avg_win":      result.avg_win,
            "avg_loss":     result.avg_loss,
            # Buy-and-hold comparison
            "bh_total_return": round((bh_equity.iloc[-1] - 1) * 100, 2),
            "bh_cagr":         round((bh_equity.iloc[-1] ** (1 / (len(bh_equity)/252)) - 1) * 100, 2),
            "alpha":           round(result.cagr - round((bh_equity.iloc[-1] ** (1/(len(bh_equity)/252))-1)*100,2), 2),
        }
        return row

    except Exception as exc:
        logger.warning("Failed %s: %s", symbol, exc)
        return None


# ── Universe runner ───────────────────────────────────────────────────────────

def run_universe_backtest(
    strategy_key: str  = "rsi_trend_filtered",
    years:        int  = 5,
    commission:   float= 0.001,
    slippage:     float= 0.0005,
    min_sharpe:   float= 0.0,    # filter threshold for output
    output_path:  Optional[str] = None,
) -> pd.DataFrame:
    """
    Run a strategy across all active NIFTY 100 stocks.

    Args:
        strategy_key: Key from STRATEGIES dict
        years:        Backtest period in years
        commission:   Round-trip commission fraction
        slippage:     Slippage fraction
        min_sharpe:   Only include results with Sharpe >= this value
        output_path:  Save CSV to this path if provided

    Returns:
        DataFrame of results sorted by Sharpe ratio
    """
    t0 = time.time()

    if strategy_key not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_key}. "
                         f"Choose from: {list(STRATEGIES.keys())}")

    StratClass = STRATEGIES[strategy_key]
    strategy   = StratClass()

    logger.info("═" * 60)
    logger.info("Universe backtest: %s | %dy | commission=%.2f%% | slippage=%.2f%%",
                strategy_key, years, commission*100, slippage*100)
    logger.info("Strategy params: %s", strategy.__dict__)
    logger.info("═" * 60)

    # Fetch universe
    universe = _get_active_symbols()
    logger.info("Running on %d stocks...", len(universe))

    rows = []
    failed = []

    for stock in tqdm(universe, desc=f"Backtesting {strategy_key}", unit="stock"):
        symbol = stock["symbol"]
        result = backtest_symbol(
            symbol     = symbol,
            name       = stock.get("name", symbol),
            sector     = stock.get("sector", "Unknown"),
            strategy   = strategy,
            years      = years,
            commission = commission,
            slippage   = slippage,
        )
        if result:
            rows.append(result)
        else:
            failed.append(symbol)

    if not rows:
        logger.error("No results — check data availability")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Apply min_sharpe filter
    if min_sharpe > 0:
        df = df[df["sharpe"] >= min_sharpe]

    # Sort by Sharpe ratio
    df = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
    df.index = df.index + 1   # 1-indexed rank

    duration = time.time() - t0
    logger.info("Done — %d stocks backtested, %d failed, %.1fs",
                len(rows), len(failed), duration)

    # Print summary to console
    _print_summary(df, strategy_key, years, failed)

    # Save if requested
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        df.to_csv(output_path)
        logger.info("Saved to %s", output_path)

    return df


# ── Parameter sweep on top candidates ─────────────────────────────────────────

def sweep_top_candidates(
    universe_results: pd.DataFrame,
    strategy_key:     str,
    top_n:            int   = 10,
    years:            int   = 5,
) -> dict[str, pd.DataFrame]:
    """
    Run parameter sweep on the top N stocks from universe_backtest.
    Finds optimal params per stock — useful before live trading.

    Returns:
        {symbol: sweep_results_df}
    """
    if strategy_key not in PARAM_GRIDS:
        logger.warning("No param grid for %s", strategy_key)
        return {}

    top_symbols = universe_results.head(top_n)["symbol"].tolist()
    StratClass  = STRATEGIES[strategy_key]
    param_grid  = PARAM_GRIDS[strategy_key]

    logger.info("Parameter sweep on top %d stocks: %s", top_n, top_symbols)
    sweep_results = {}

    for sym_clean in tqdm(top_symbols, desc="Sweeping top stocks"):
        symbol = f"{sym_clean}.NS"
        prices = _fetch_prices(symbol, years)
        if len(prices) < 252:
            continue
        bt = Backtester(prices, symbol=sym_clean)
        sweep_df = bt.run_parameter_sweep(StratClass, param_grid)
        sweep_results[sym_clean] = sweep_df
        logger.info("%s — best Sharpe: %s with params %s",
                    sym_clean,
                    sweep_df.iloc[0]["sharpe"] if not sweep_df.empty else "N/A",
                    {k: sweep_df.iloc[0][k] for k in param_grid} if not sweep_df.empty else {})

    return sweep_results


# ── Console output ────────────────────────────────────────────────────────────

def _print_summary(df: pd.DataFrame, strategy: str, years: int, failed: list):
    sep = "═" * 70

    print(f"\n{sep}")
    print(f"  UNIVERSE BACKTEST RESULTS — {strategy.upper()}")
    print(f"  Period: {years}y | Stocks: {len(df)} results | {len(failed)} failed")
    print(sep)

    # Overall stats
    print(f"\n  📊 UNIVERSE STATISTICS")
    print(f"  Avg Sharpe      : {df['sharpe'].mean():.3f}  (median: {df['sharpe'].median():.3f})")
    print(f"  Avg CAGR        : {df['cagr'].mean():.2f}%")
    print(f"  Avg Max DD      : {df['max_drawdown'].mean():.2f}%")
    print(f"  Avg Win Rate    : {df['win_rate'].mean():.1f}%")
    print(f"  Sharpe > 1.0    : {(df['sharpe'] >= 1.0).sum()} stocks")
    print(f"  Sharpe > 0.5    : {(df['sharpe'] >= 0.5).sum()} stocks")
    print(f"  Positive Alpha  : {(df['alpha'] > 0).sum()} stocks")

    # Top 10 by Sharpe
    print(f"\n  🏆 TOP 10 BY SHARPE RATIO")
    print(f"  {'#':>3}  {'Symbol':12} {'Sector':22} {'Sharpe':>7} {'CAGR':>7} {'MaxDD':>7} {'WinRate':>8} {'Alpha':>7}")
    print(f"  {'-'*3}  {'-'*12} {'-'*22} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")
    for rank, row in df.head(10).iterrows():
        print(
            f"  {rank:>3}  {row['symbol']:12} {str(row['sector'])[:22]:22} "
            f"{row['sharpe']:>7.3f} {row['cagr']:>6.1f}% {row['max_drawdown']:>6.1f}% "
            f"{row['win_rate']:>7.1f}% {row['alpha']:>+6.1f}%"
        )

    # Bottom 5
    print(f"\n  ⚠️  BOTTOM 5 (review or exclude from live trading)")
    print(f"  {'#':>3}  {'Symbol':12} {'Sharpe':>7} {'CAGR':>7} {'MaxDD':>7}")
    print(f"  {'-'*3}  {'-'*12} {'-'*7} {'-'*7} {'-'*7}")
    for rank, row in df.tail(5).iterrows():
        print(
            f"  {rank:>3}  {row['symbol']:12} "
            f"{row['sharpe']:>7.3f} {row['cagr']:>6.1f}% {row['max_drawdown']:>6.1f}%"
        )

    # Sector breakdown
    sector_stats = (
        df.groupby("sector")
        .agg(stocks=("symbol","count"), avg_sharpe=("sharpe","mean"),
             avg_cagr=("cagr","mean"), positive_alpha=("alpha", lambda x: (x>0).sum()))
        .sort_values("avg_sharpe", ascending=False)
        .reset_index()
    )
    print(f"\n  🏭 SECTOR BREAKDOWN (avg Sharpe)")
    for _, row in sector_stats.iterrows():
        bar = "█" * min(int(row["avg_sharpe"] * 10), 20)
        print(f"  {str(row['sector'])[:25]:25} {bar:<20} {row['avg_sharpe']:.3f}  "
              f"({row['stocks']} stocks, {row['positive_alpha']} +alpha)")

    if failed:
        print(f"\n  ❌ Failed ({len(failed)}): {', '.join(s.replace('.NS','') for s in failed[:10])}"
              + ("..." if len(failed) > 10 else ""))

    print(f"\n{sep}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universe-wide backtester")
    parser.add_argument("--strategy",   default="rsi_trend_filtered",
                        choices=list(STRATEGIES.keys()),
                        help="Strategy to backtest")
    parser.add_argument("--years",      type=int,   default=5,
                        help="Backtest period in years")
    parser.add_argument("--min-sharpe", type=float, default=0.0,
                        help="Minimum Sharpe to include in output")
    parser.add_argument("--commission", type=float, default=0.1,
                        help="Commission %% round-trip (default 0.1)")
    parser.add_argument("--slippage",   type=float, default=0.05,
                        help="Slippage %% (default 0.05)")
    parser.add_argument("--sweep",      action="store_true",
                        help="Run parameter sweep on top 10 stocks")
    parser.add_argument("--output",     default=None,
                        help="Save results CSV to this path")
    args = parser.parse_args()

    results = run_universe_backtest(
        strategy_key = args.strategy,
        years        = args.years,
        commission   = args.commission / 100,
        slippage     = args.slippage  / 100,
        min_sharpe   = args.min_sharpe,
        output_path  = args.output,
    )

    if args.sweep and not results.empty:
        print("\nRunning parameter sweep on top 10 stocks...")
        sweep_results = sweep_top_candidates(results, args.strategy, top_n=10, years=args.years)

        print("\n" + "═" * 60)
        print("  OPTIMAL PARAMETERS PER STOCK")
        print("═" * 60)
        for sym, sweep_df in sweep_results.items():
            if sweep_df.empty:
                continue
            best = sweep_df.iloc[0]
            param_keys = list(PARAM_GRIDS[args.strategy].keys())
            params_str = ", ".join(f"{k}={best[k]}" for k in param_keys if k in best)
            print(f"  {sym:12} → {params_str}  (Sharpe: {best['sharpe']})")
        print("═" * 60)