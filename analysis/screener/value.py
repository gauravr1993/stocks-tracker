"""
analysis/screener/value.py
Value scoring: PE, PB, PS ratios scored both absolutely and relative to sector peers.
Lower ratio = better value = higher score.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Weights for each ratio within the value score
RATIO_WEIGHTS = {
    "pe_ratio": 0.45,
    "pb_ratio": 0.30,
    "ps_ratio": 0.25,
}

# Hard caps — exclude stocks with ratios above these (likely distorted)
# Stocks exceeding these caps get NaN for that ratio only — they can still
# score on the other ratios and will show score_confidence < 1.0 in output.
# This is intentional: a high-PE stock isn't a value pick but can still
# rank well on momentum + sector.
RATIO_CAPS = {
    "pe_ratio": 150,   # PE > 100 = too speculative for value screen
    "pb_ratio": 25,
    "ps_ratio": 20,
}

# Minimum data required — stocks missing all three ratios are excluded
MIN_RATIOS_REQUIRED = 2


def _percentile_score(series: pd.Series, lower_is_better: bool = True) -> pd.Series:
    """
    Convert a raw ratio series to a 0–100 score using percentile rank.
    lower_is_better=True means low PE gets a high score.
    NaNs are preserved as NaN.
    """
    ranks = series.rank(pct=True, na_option="keep")
    if lower_is_better:
        return (1 - ranks) * 100
    return ranks * 100


def score_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute value scores for a DataFrame of stocks.

    Args:
        df: DataFrame with columns: symbol, sector, pe_ratio, pb_ratio, ps_ratio
            (typically from fundamentals table joined with nifty_constituents)

    Returns:
        DataFrame with added columns:
            pe_score, pb_score, ps_score        — individual ratio scores (0–100)
            pe_sector_score, pb_sector_score,
            ps_sector_score                     — sector-relative scores (0–100)
            value_score                         — final weighted composite (0–100)
            value_rank                          — rank within universe (1 = best value)
    """
    df = df.copy()

    # ── 1. Cap extreme ratios ─────────────────────────────────────────────────
    for ratio, cap in RATIO_CAPS.items():
        if ratio in df.columns:
            df[ratio] = df[ratio].where(df[ratio] <= cap, other=np.nan)
            # Also drop negative ratios (negative earnings = PE meaningless)
            df[ratio] = df[ratio].where(df[ratio] > 0, other=np.nan)

    # ── 2. Universe-wide percentile scores ───────────────────────────────────
    for ratio in RATIO_WEIGHTS:
        if ratio not in df.columns:
            df[f"{ratio[:2]}_score"] = np.nan
            continue
        col = ratio[:2]  # pe, pb, ps
        df[f"{col}_score"] = _percentile_score(df[ratio], lower_is_better=True)

    # ── 3. Sector-relative percentile scores ─────────────────────────────────
    for ratio in RATIO_WEIGHTS:
        if ratio not in df.columns:
            df[f"{ratio[:2]}_sector_score"] = np.nan
            continue
        col = ratio[:2]
        df[f"{col}_sector_score"] = (
            df.groupby("sector", group_keys=False)[ratio]
            .transform(lambda s: _percentile_score(s, lower_is_better=True))
        )

    # ── 4. Weighted composite: 60% universe + 40% sector-relative ────────────
    score_parts = []
    total_weight = 0.0

    for ratio, weight in RATIO_WEIGHTS.items():
        col = ratio[:2]
        uni_col    = f"{col}_score"
        sector_col = f"{col}_sector_score"

        if uni_col not in df.columns:
            continue

        # Blend universe and sector scores
        blended = df[uni_col] * 0.6 + df[sector_col].fillna(df[uni_col]) * 0.4

        # Only include if we have a value
        has_data = blended.notna()
        score_parts.append((blended, weight, has_data))
        total_weight += weight

    if not score_parts:
        df["value_score"] = np.nan
        df["value_rank"]  = np.nan
        return df

    # Weighted average ignoring NaN ratios per stock
    numerator   = sum(s.fillna(0) * w for s, w, _ in score_parts)
    denominator = sum(w * has.astype(float) for _, w, has in score_parts)
    df["value_score"] = (numerator / denominator.replace(0, np.nan)).round(2)

    # Exclude stocks with fewer than MIN_RATIOS_REQUIRED valid ratios
    valid_ratio_count = sum(has.astype(int) for _, _, has in score_parts)
    df.loc[valid_ratio_count < MIN_RATIOS_REQUIRED, "value_score"] = np.nan

    df["value_rank"] = df["value_score"].rank(ascending=False, na_option="bottom").astype(int)

    logger.info("Value scoring done — %d stocks scored, %d excluded (insufficient data)",
                df["value_score"].notna().sum(), df["value_score"].isna().sum())
    return df