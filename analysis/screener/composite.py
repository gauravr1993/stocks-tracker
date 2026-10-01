"""
analysis/screener/composite.py
Combines value, momentum, and sector scores into a single composite ranking.

Default weights are research-informed but easily tunable:
  - Momentum 45%: price momentum is the strongest factor in Indian markets
  - Value    35%: PE/PB/PS — undervalued stocks outperform long-term
  - Sector   20%: being in the right sector amplifies both

Also produces two flavoured outputs:
  - "value_picks"    — reweighted toward value (for quarterly long-term picks)
  - "momentum_picks" — reweighted toward momentum (for shorter-term trades)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ScoreWeights:
    value:    float = 0.35
    momentum: float = 0.45
    sector:   float = 0.20

    def __post_init__(self):
        total = self.value + self.momentum + self.sector
        assert abs(total - 1.0) < 1e-6, f"Weights must sum to 1.0, got {total}"


# Preset weight profiles
BALANCED       = ScoreWeights(value=0.35, momentum=0.45, sector=0.20)
VALUE_TILTED   = ScoreWeights(value=0.55, momentum=0.30, sector=0.15)
MOMENTUM_TILTED = ScoreWeights(value=0.20, momentum=0.65, sector=0.15)


def score_composite(
    df: pd.DataFrame,
    weights: ScoreWeights = BALANCED,
) -> pd.DataFrame:
    """
    Compute composite score from individual dimension scores.

    Args:
        df:      DataFrame already containing value_score, momentum_score, sector_score
        weights: ScoreWeights instance (default: BALANCED)

    Returns:
        DataFrame with added columns:
            composite_score   — weighted combination (0–100)
            composite_rank    — rank within universe (1 = best overall)
            score_confidence  — how many of the 3 dimensions had data (0.33 / 0.67 / 1.0)
    """
    df = df.copy()

    required = ["value_score", "momentum_score", "sector_score"]
    for col in required:
        if col not in df.columns:
            df[col] = np.nan

    weight_map = {
        "value_score":    weights.value,
        "momentum_score": weights.momentum,
        "sector_score":   weights.sector,
    }

    # Weighted average, ignoring NaN dimensions per stock
    numerator   = sum(df[col].fillna(0) * w for col, w in weight_map.items())
    denominator = sum(w * df[col].notna().astype(float) for col, w in weight_map.items())

    df["composite_score"] = (numerator / denominator.replace(0, np.nan)).round(2)
    df["composite_rank"]  = (
        df["composite_score"].rank(ascending=False, na_option="bottom").astype(int)
    )

    # Confidence: proportion of dimensions that had data
    dims_present = sum(df[col].notna().astype(int) for col in required)
    df["score_confidence"] = (dims_present / len(required)).round(2)

    logger.info(
        "Composite scoring done — weights: V=%.0f%% M=%.0f%% S=%.0f%%",
        weights.value * 100, weights.momentum * 100, weights.sector * 100,
    )
    return df


def get_top_picks(
    df: pd.DataFrame,
    n: int = 10,
    mode: str = "balanced",       # 'balanced' | 'value' | 'momentum'
    min_confidence: float = 0.67, # require at least 2 of 3 dimensions
    exclude_sectors: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Return top N stock picks with all scores and metadata.

    Args:
        df:               Fully scored DataFrame (output of run_screener)
        n:                Number of picks to return
        mode:             Weight profile to use
        min_confidence:   Minimum score_confidence threshold
        exclude_sectors:  Sectors to exclude (e.g. ['Unknown'])

    Returns:
        Top N DataFrame sorted by composite_score desc, with display columns
    """
    weight_map = {
        "balanced": BALANCED,
        "value":    VALUE_TILTED,
        "momentum": MOMENTUM_TILTED,
    }
    weights = weight_map.get(mode, BALANCED)

    scored = score_composite(df, weights=weights)

    # Apply filters
    mask = scored["score_confidence"] >= min_confidence
    if exclude_sectors:
        mask &= ~scored["sector"].isin(exclude_sectors)

    filtered = scored[mask].copy()

    # Sort and take top N
    top = (
        filtered.sort_values("composite_score", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )

    display_cols = [
        "symbol", "name", "sector",
        "composite_score", "composite_rank",
        "value_score",    "value_rank",
        "momentum_score", "momentum_rank",
        "sector_score",   "sector_rank",
        "pe_ratio", "pb_ratio", "ps_ratio",
        "return_3m", "return_6m", "return_1y",
        "score_confidence",
    ]
    available = [c for c in display_cols if c in top.columns]
    return top[available]