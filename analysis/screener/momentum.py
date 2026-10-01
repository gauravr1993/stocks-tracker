"""
analysis/screener/momentum.py
Momentum scoring: 3m, 6m, 1y price returns with quality filters.
Higher return = stronger momentum = higher score.

Research-backed design choices:
- Skip most recent 1 month (avoids short-term reversal noise) — classic Jegadeesh-Titman
- Weight 6m and 1y more than 3m (medium-term momentum is more persistent)
- Penalise high volatility (quality filter — we want smooth uptrends, not spikes)
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Return period weights — must sum to 1.0
RETURN_WEIGHTS = {
    "return_3m": 0.20,
    "return_6m": 0.35,
    "return_1y": 0.45,
}

# Exclude stocks with 1y return beyond these bounds (likely data errors or extreme events)
RETURN_CAP    =  300   # +300% max
RETURN_FLOOR  = -80    # -80% min


def _volatility(prices: pd.Series, window: int = 63) -> float:
    """Annualised volatility from daily returns over last `window` trading days.
    Falls back to a shorter window if not enough data."""
    min_window = 20   # minimum days needed for a meaningful vol estimate
    available = len(prices)
    if available < min_window:
        return np.nan
    actual_window = min(window, available)
    returns = prices.pct_change().dropna().tail(actual_window)
    return float(returns.std() * np.sqrt(252) * 100)   # as percentage


def _percentile_score(series: pd.Series, lower_is_better: bool = False) -> pd.Series:
    ranks = series.rank(pct=True, na_option="keep")
    if lower_is_better:
        return (1 - ranks) * 100
    return ranks * 100


def score_momentum(
    df: pd.DataFrame,
    prices_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Compute momentum scores.

    Args:
        df: DataFrame with columns: symbol, sector, return_3m, return_6m, return_1y
            (from the price_returns Supabase view, latest row per symbol)
        prices_df: Optional — full daily price history for volatility calculation.
                   If provided, adds a volatility penalty to the score.

    Returns:
        DataFrame with added columns:
            return_3m_score, return_6m_score, return_1y_score  — individual (0–100)
            momentum_raw_score     — weighted return score before vol adjustment
            volatility_pct         — annualised volatility % (if prices_df provided)
            volatility_penalty     — 0–20 point deduction for high vol stocks
            momentum_score         — final score after vol penalty (0–100)
            momentum_rank          — rank within universe (1 = strongest momentum)
    """
    df = df.copy()

    # ── 1. Cap extreme returns ────────────────────────────────────────────────
    for col in ["return_3m", "return_6m", "return_1y"]:
        if col in df.columns:
            df[col] = df[col].clip(lower=RETURN_FLOOR, upper=RETURN_CAP)

    # ── 2. Percentile scores per return period ────────────────────────────────
    score_parts = []
    for col, weight in RETURN_WEIGHTS.items():
        if col not in df.columns:
            continue
        score_col = f"{col}_score"
        df[score_col] = _percentile_score(df[col], lower_is_better=False)
        score_parts.append((score_col, weight))

    if not score_parts:
        df["momentum_score"] = np.nan
        df["momentum_rank"]  = np.nan
        return df

    # ── 3. Weighted raw momentum score ────────────────────────────────────────
    numerator   = sum(df[sc].fillna(0) * w for sc, w in score_parts)
    denominator = sum(w * df[sc].notna().astype(float) for sc, w in score_parts)
    df["momentum_raw_score"] = (numerator / denominator.replace(0, np.nan)).round(2)

    # ── 4. Volatility penalty (optional) ─────────────────────────────────────
    if prices_df is not None and not prices_df.empty:
        vol_map = (
            prices_df.sort_values("date")
            .groupby("symbol")["adj_close"]
            .apply(_volatility)
            .rename("volatility_pct")
        )
        df = df.join(vol_map, on="symbol")

        # Penalty: stocks in top quartile of vol lose up to 20 points
        vol_scores = _percentile_score(df["volatility_pct"], lower_is_better=True)
        # Penalty is 0 for low-vol stocks, up to 20 for the most volatile
        df["volatility_penalty"] = ((1 - vol_scores / 100) * 20).round(2)
    else:
        df["volatility_pct"]    = np.nan
        df["volatility_penalty"] = 0.0

    # ── 5. Final momentum score ───────────────────────────────────────────────
    df["momentum_score"] = (
        df["momentum_raw_score"] - df["volatility_penalty"]
    ).clip(0, 100).round(2)

    df["momentum_rank"] = df["momentum_score"].rank(ascending=False, na_option="bottom").astype(int)

    logger.info("Momentum scoring done — %d stocks scored", df["momentum_score"].notna().sum())
    return df