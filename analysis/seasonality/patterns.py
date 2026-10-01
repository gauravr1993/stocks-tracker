"""
analysis/seasonality/patterns.py
Core seasonality computations using 10yr daily price history.

Three pattern types:
  1. Monthly     — avg return per calendar month (Jan effect, year-end rally etc.)
  2. Day-of-week — avg return per weekday (Monday effect etc.)
  3. Quarterly   — avg return in Q1/Q2/Q3/Q4 + earnings season windows

All functions accept either a single symbol's price DataFrame or
the full universe DataFrame (grouped by symbol).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS   = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
QUARTERS = ["Q1 (Jan-Mar)", "Q2 (Apr-Jun)", "Q3 (Jul-Sep)", "Q4 (Oct-Dec)"]

# Minimum years of data required to compute reliable patterns
MIN_YEARS = 3


# ── helpers ───────────────────────────────────────────────────────────────────

def _daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Add daily return column, sorted by date."""
    df = prices.copy().sort_values("date")
    df["return_pct"] = df["adj_close"].pct_change() * 100
    df["date"]       = pd.to_datetime(df["date"])
    df["year"]       = df["date"].dt.year
    df["month"]      = df["date"].dt.month
    df["month_name"] = df["date"].dt.strftime("%b")
    df["dow"]        = df["date"].dt.dayofweek          # 0=Mon
    df["dow_name"]   = df["date"].dt.strftime("%A")
    df["quarter"]    = df["date"].dt.quarter
    return df.dropna(subset=["return_pct"])


def _monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute month-over-month returns (close of last day vs first day per month)."""
    df = prices.copy().sort_values("date")
    df["date"]       = pd.to_datetime(df["date"])
    df["year_month"] = df["date"].dt.to_period("M")

    monthly = (
        df.groupby("year_month")["adj_close"]
        .agg(first="first", last="last")
        .reset_index()
    )
    monthly["return_pct"] = (monthly["last"] / monthly["first"] - 1) * 100
    monthly["month"]      = monthly["year_month"].dt.month
    monthly["month_name"] = monthly["year_month"].dt.strftime("%b")
    monthly["year"]       = monthly["year_month"].dt.year
    monthly["quarter"]    = monthly["year_month"].dt.quarter
    return monthly


def _stat_summary(series: pd.Series) -> dict:
    """Mean, median, std, win_rate, t-stat, p-value for a return series."""
    clean = series.dropna()
    if len(clean) < 3:
        return dict(mean=np.nan, median=np.nan, std=np.nan,
                    win_rate=np.nan, t_stat=np.nan, p_value=np.nan, n=0)
    t_stat, p_value = stats.ttest_1samp(clean, 0)
    return dict(
        mean     = round(clean.mean(),   3),
        median   = round(clean.median(), 3),
        std      = round(clean.std(),    3),
        win_rate = round((clean > 0).mean() * 100, 1),
        t_stat   = round(t_stat,   3),
        p_value  = round(p_value,  4),
        n        = len(clean),
    )


# ── 1. Monthly patterns ───────────────────────────────────────────────────────

def monthly_patterns(
    prices: pd.DataFrame,
    symbol: Optional[str] = None,
) -> pd.DataFrame:
    """
    Avg return, win rate, and significance per calendar month.

    Args:
        prices: DataFrame with date, adj_close columns
        symbol: Optional symbol label for output

    Returns:
        DataFrame with one row per month (12 rows):
        month, month_name, mean_return, median_return, std,
        win_rate, t_stat, p_value, n_years, is_significant
    """
    years_span = (
        pd.to_datetime(prices["date"]).max() -
        pd.to_datetime(prices["date"]).min()
    ).days / 365
    if years_span < MIN_YEARS:
        logger.warning("%s: only %.1f years of data — patterns may be unreliable",
                       symbol or "symbol", years_span)

    monthly = _monthly_returns(prices)
    rows = []
    for m in range(1, 13):
        subset = monthly[monthly["month"] == m]["return_pct"]
        stats_ = _stat_summary(subset)
        rows.append({
            "month":          m,
            "month_name":     MONTHS[m - 1],
            "mean_return":    stats_["mean"],
            "median_return":  stats_["median"],
            "std":            stats_["std"],
            "win_rate":       stats_["win_rate"],
            "t_stat":         stats_["t_stat"],
            "p_value":        stats_["p_value"],
            "n_years":        stats_["n"],
            "is_significant": stats_["p_value"] < 0.10 if not np.isnan(stats_["p_value"]) else False,
        })

    df = pd.DataFrame(rows)
    if symbol:
        df.insert(0, "symbol", symbol)
    return df


# ── 2. Day-of-week patterns ───────────────────────────────────────────────────

def dow_patterns(
    prices: pd.DataFrame,
    symbol: Optional[str] = None,
) -> pd.DataFrame:
    """
    Avg daily return per weekday.

    Returns:
        DataFrame with one row per weekday (5 rows):
        dow, dow_name, mean_return, median_return, win_rate, n, is_significant
    """
    df = _daily_returns(prices)
    rows = []
    for d in range(5):    # 0=Mon to 4=Fri
        subset = df[df["dow"] == d]["return_pct"]
        stats_ = _stat_summary(subset)
        rows.append({
            "dow":            d,
            "dow_name":       DAYS[d],
            "mean_return":    stats_["mean"],
            "median_return":  stats_["median"],
            "win_rate":       stats_["win_rate"],
            "std":            stats_["std"],
            "t_stat":         stats_["t_stat"],
            "p_value":        stats_["p_value"],
            "n":              stats_["n"],
            "is_significant": stats_["p_value"] < 0.10 if not np.isnan(stats_["p_value"]) else False,
        })

    out = pd.DataFrame(rows)
    if symbol:
        out.insert(0, "symbol", symbol)
    return out


# ── 3. Quarterly patterns ─────────────────────────────────────────────────────

def quarterly_patterns(
    prices: pd.DataFrame,
    symbol: Optional[str] = None,
) -> pd.DataFrame:
    """
    Avg return per fiscal quarter + earnings season windows.

    Earnings season windows (approximate for Indian markets):
      Q1 results: mid-Jul to mid-Aug
      Q2 results: mid-Oct to mid-Nov
      Q3 results: mid-Jan to mid-Feb
      Q4 results: mid-Apr to mid-May

    Returns:
        DataFrame with quarter, mean_return, win_rate, n_years
    """
    monthly = _monthly_returns(prices)
    rows = []
    for q in range(1, 5):
        subset = monthly[monthly["quarter"] == q]["return_pct"]
        stats_ = _stat_summary(subset)
        rows.append({
            "quarter":        q,
            "quarter_name":   QUARTERS[q - 1],
            "mean_return":    stats_["mean"],
            "median_return":  stats_["median"],
            "win_rate":       stats_["win_rate"],
            "std":            stats_["std"],
            "t_stat":         stats_["t_stat"],
            "p_value":        stats_["p_value"],
            "n":              stats_["n"],
            "is_significant": stats_["p_value"] < 0.10 if not np.isnan(stats_["p_value"]) else False,
        })

    out = pd.DataFrame(rows)
    if symbol:
        out.insert(0, "symbol", symbol)
    return out


# ── 4. Universe-wide aggregations ─────────────────────────────────────────────

def universe_monthly_heatmap(
    all_prices: pd.DataFrame,
    symbols: list[str],
) -> pd.DataFrame:
    """
    Build a symbol × month matrix of mean monthly returns.
    Used for the heatmap in the dashboard.

    Args:
        all_prices: DataFrame with symbol, date, adj_close columns
        symbols:    List of symbols to include

    Returns:
        DataFrame with symbols as index, months as columns (Jan–Dec)
        Values are mean monthly return %
    """
    records = {}
    for symbol in symbols:
        sym_prices = all_prices[all_prices["symbol"] == symbol]
        if len(sym_prices) < 60:   # need at least ~3 months
            continue
        pat = monthly_patterns(sym_prices, symbol)
        records[symbol.replace(".NS", "")] = dict(
            zip(pat["month_name"], pat["mean_return"])
        )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).T
    # Reorder columns Jan→Dec
    available_months = [m for m in MONTHS if m in df.columns]
    return df[available_months].round(2)


def sector_monthly_heatmap(
    all_prices: pd.DataFrame,
    universe_df: pd.DataFrame,     # has symbol, sector columns
) -> pd.DataFrame:
    """
    Build a sector × month matrix of median monthly returns.
    More useful than individual stocks for identifying macro seasonal patterns.
    """
    merged = all_prices.merge(
        universe_df[["symbol", "sector"]],
        on="symbol", how="left"
    )

    records = {}
    for sector in merged["sector"].dropna().unique():
        sec_prices = merged[merged["sector"] == sector]
        if len(sec_prices) < 100:
            continue

        # Compute monthly returns per symbol then take sector median
        monthly_rows = []
        for sym, grp in sec_prices.groupby("symbol"):
            if len(grp) < 60:
                continue
            m = _monthly_returns(grp)
            monthly_rows.append(m)

        if not monthly_rows:
            continue

        all_monthly = pd.concat(monthly_rows)
        sector_monthly = (
            all_monthly.groupby("month_name")["return_pct"]
            .median()
        )
        records[sector] = sector_monthly.to_dict()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).T
    available_months = [m for m in MONTHS if m in df.columns]
    return df[available_months].round(2)


def best_worst_months(monthly_df: pd.DataFrame) -> dict:
    """
    Given output of monthly_patterns(), return best and worst months.
    Returns dict with best_month, worst_month, best_return, worst_return.
    """
    if monthly_df.empty or "mean_return" not in monthly_df.columns:
        return {}
    best  = monthly_df.loc[monthly_df["mean_return"].idxmax()]
    worst = monthly_df.loc[monthly_df["mean_return"].idxmin()]
    return {
        "best_month":   best["month_name"],
        "best_return":  best["mean_return"],
        "worst_month":  worst["month_name"],
        "worst_return": worst["mean_return"],
        "best_winrate": best["win_rate"],
        "worst_winrate":worst["win_rate"],
    }