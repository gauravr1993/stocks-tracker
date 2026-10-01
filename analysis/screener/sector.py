"""
analysis/screener/sector.py
Sector scoring: rewards stocks that are strong within their sector
AND whose sector itself is strong relative to the broader market.

Two-layer approach:
  1. Intra-sector rank   — how does this stock rank vs its sector peers?
  2. Inter-sector rank   — how strong is this sector vs all other sectors?
Final sector score blends both so you get stocks leading a leading sector.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# How many stocks minimum for a sector to get a meaningful intra-sector rank
MIN_SECTOR_SIZE = 3


def _percentile_score(series: pd.Series, lower_is_better: bool = False) -> pd.Series:
    ranks = series.rank(pct=True, na_option="keep")
    if lower_is_better:
        return (1 - ranks) * 100
    return ranks * 100


def score_sector(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute sector scores.

    Args:
        df: DataFrame with columns:
              symbol, sector, return_1m (optional), return_3m, return_6m, return_1y
              momentum_score (from momentum.py — used as proxy for stock strength)

    Returns:
        DataFrame with added columns:
            sector_return_3m        — median 3m return of the sector
            sector_return_1y        — median 1y return of the sector
            sector_strength_score   — how strong the sector is vs all sectors (0–100)
            intra_sector_score      — how strong this stock is vs its sector peers (0–100)
            sector_score            — blended final score (0–100)
            sector_rank             — rank within universe (1 = best)
            sector_label            — sector name (passed through)
    """
    df = df.copy()

    # ── 1. Sector-level aggregate returns ─────────────────────────────────────
    # Use median to be robust against outliers within a sector
    sector_agg = (
        df.groupby("sector")
        .agg(
            sector_return_3m=("return_3m", "median"),
            sector_return_6m=("return_6m", "median"),
            sector_return_1y=("return_1y", "median"),
            sector_size=("symbol",  "count"),
        )
        .reset_index()
    )

    # Sector strength: weighted median return (3m 30%, 6m 30%, 1y 40%)
    sector_agg["sector_raw_return"] = (
        sector_agg["sector_return_3m"].fillna(0) * 0.30
        + sector_agg["sector_return_6m"].fillna(0) * 0.30
        + sector_agg["sector_return_1y"].fillna(0) * 0.40
    )

    # Percentile rank each sector against all other sectors
    sector_agg["sector_strength_score"] = _percentile_score(
        sector_agg["sector_raw_return"], lower_is_better=False
    ).round(2)

    # ── 2. Merge sector-level scores back to stock level ──────────────────────
    df = df.merge(
        sector_agg[["sector", "sector_return_3m", "sector_return_1y",
                    "sector_strength_score", "sector_size"]],
        on="sector",
        how="left",
    )

    # ── 3. Intra-sector score — stock vs its own sector peers ─────────────────
    # Use momentum_score if available, else fall back to return_1y
    strength_col = "momentum_score" if "momentum_score" in df.columns else "return_1y"

    def _intra_rank(group: pd.DataFrame) -> pd.Series:
        if len(group) < MIN_SECTOR_SIZE:
            # Too few peers — give everyone 50 (neutral) so small sectors
            # aren't unfairly penalised or rewarded
            return pd.Series(50.0, index=group.index)
        return _percentile_score(group[strength_col], lower_is_better=False)

    df["intra_sector_score"] = (
        df.groupby("sector", group_keys=False)
        .apply(_intra_rank)
        .round(2)
    )

    # ── 4. Blended sector score ───────────────────────────────────────────────
    # 50% intra-sector (are you a leader in your sector?)
    # 50% inter-sector (is your sector itself a leader?)
    df["sector_score"] = (
        df["intra_sector_score"] * 0.50
        + df["sector_strength_score"] * 0.50
    ).round(2)

    df["sector_rank"] = (
        df["sector_score"].rank(ascending=False, na_option="bottom").astype(int)
    )

    # Convenience: keep sector label for display
    df["sector_label"] = df["sector"]

    logger.info(
        "Sector scoring done — %d sectors, %d stocks",
        df["sector"].nunique(), len(df),
    )
    return df