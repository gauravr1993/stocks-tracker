"""
trading/backtest/metrics.py
Additional metrics and benchmark comparison utilities.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def buy_and_hold(prices: pd.DataFrame) -> pd.Series:
    """Returns the equity curve for a simple buy-and-hold strategy."""
    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    ret = prices[price_col].pct_change().fillna(0)
    return (1 + ret).cumprod()


def compare_to_benchmark(
    result_equity: pd.Series,
    benchmark_equity: pd.Series,
    label: str = "Strategy",
) -> pd.DataFrame:
    """
    Side-by-side comparison of strategy vs buy-and-hold.
    Returns a display-ready DataFrame.
    """
    def _stats(equity: pd.Series, name: str) -> dict:
        ret    = equity.pct_change().fillna(0)
        years  = len(equity) / 252
        total  = (equity.iloc[-1] - 1) * 100
        cagr   = (equity.iloc[-1] ** (1 / years) - 1) * 100 if years > 0 else 0
        sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
        dd     = ((equity - equity.cummax()) / equity.cummax()).min() * 100
        return {
            "Name":         name,
            "Total Return": f"{total:.2f}%",
            "CAGR":         f"{cagr:.2f}%",
            "Sharpe":       round(sharpe, 3),
            "Max Drawdown": f"{dd:.2f}%",
            "Volatility":   f"{ret.std() * np.sqrt(252) * 100:.2f}%",
        }

    rows = [
        _stats(result_equity,    label),
        _stats(benchmark_equity, "Buy & Hold"),
    ]

    # Alpha = strategy CAGR - benchmark CAGR
    s_cagr = float(rows[0]["CAGR"].replace("%", ""))
    b_cagr = float(rows[1]["CAGR"].replace("%", ""))
    rows[0]["Alpha vs B&H"] = f"{s_cagr - b_cagr:+.2f}%"
    rows[1]["Alpha vs B&H"] = "—"

    return pd.DataFrame(rows)


def rolling_sharpe(returns: pd.Series, window: int = 63) -> pd.Series:
    """Rolling Sharpe ratio over a given window (default 63 days = ~1 quarter)."""
    roll_mean = returns.rolling(window).mean()
    roll_std  = returns.rolling(window).std()
    return (roll_mean / roll_std.replace(0, np.nan) * np.sqrt(252)).round(3)


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Returns the drawdown series (0 to -N%) at each point in time."""
    roll_max = equity.cummax()
    return ((equity - roll_max) / roll_max * 100).round(3)


def monthly_returns_table(returns: pd.Series, dates: pd.Series) -> pd.DataFrame:
    """
    Pivot table of monthly returns — rows=year, columns=month.
    Useful for spotting seasonal patterns in strategy performance.
    """
    df = pd.DataFrame({"date": pd.to_datetime(dates), "return": returns})
    df["year"]  = df["date"].dt.year
    df["month"] = df["date"].dt.strftime("%b")

    monthly = (
        df.groupby(["year","month"])["return"]
        .apply(lambda x: (1 + x).prod() - 1)
        .reset_index()
    )
    monthly["return_pct"] = monthly["return"] * 100

    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"]
    pivot = monthly.pivot_table(
        index="year", columns="month", values="return_pct", aggfunc="sum"
    )
    available = [m for m in MONTHS if m in pivot.columns]
    pivot = pivot[available]

    pivot["Annual"] = (
        monthly.groupby("year")["return"]
        .apply(lambda x: ((1 + x).prod() - 1) * 100)
        .round(2)
    )
    return pivot.round(2)


def universe_backtest_summary(results: list) -> pd.DataFrame:
    """
    Aggregate backtest results across multiple symbols.
    Returns a summary DataFrame sorted by Sharpe.
    """
    rows = [r.summary() for r in results]
    df   = pd.DataFrame(rows)

    # Convert string metrics to numeric for aggregation
    for col in ["total_return","cagr","max_drawdown","win_rate","avg_win","avg_loss"]:
        if col in df.columns:
            df[f"{col}_num"] = df[col].str.replace("%","").astype(float)

    return df.sort_values("sharpe", ascending=False).reset_index(drop=True)