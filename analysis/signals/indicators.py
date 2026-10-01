"""
analysis/signals/indicators.py
Technical indicator computations on OHLCV price DataFrames.

Design principles:
  - All functions accept and return pandas DataFrames
  - Input: DataFrame with at minimum date, close, (high, low, volume as needed)
  - Output: same DataFrame with indicator columns added
  - No side effects — always returns a copy
  - NaN for periods where insufficient data exists (no forward-fill hacks)

Usage:
    from analysis.signals.indicators import add_all_indicators
    df = add_all_indicators(prices_df)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Moving Averages ───────────────────────────────────────────────────────────

def add_sma(df: pd.DataFrame, periods: list[int] = [20, 50, 200]) -> pd.DataFrame:
    """Simple Moving Averages."""
    df = df.copy()
    for p in periods:
        df[f"sma_{p}"] = df["close"].rolling(window=p, min_periods=p).mean().round(4)
    return df


def add_ema(df: pd.DataFrame, periods: list[int] = [9, 21, 50]) -> pd.DataFrame:
    """Exponential Moving Averages."""
    df = df.copy()
    for p in periods:
        df[f"ema_{p}"] = (
            df["close"]
            .ewm(span=p, adjust=False, min_periods=p)
            .mean()
            .round(4)
        )
    return df


# ── RSI ───────────────────────────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Relative Strength Index (Wilder's smoothing method).
    Columns added: rsi_{period}
    Signal zones: <30 oversold, >70 overbought
    """
    df    = df.copy()
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)

    # Wilder's smoothing (equivalent to EMA with alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).round(2)

    # First `period` values are NaN (insufficient data)
    rsi.iloc[:period] = np.nan
    df[f"rsi_{period}"] = rsi
    return df


# ── MACD ──────────────────────────────────────────────────────────────────────

def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    MACD (Moving Average Convergence Divergence).
    Columns added: macd_line, macd_signal, macd_histogram
    Signal: histogram cross above 0 = bullish, below 0 = bearish
    """
    df   = df.copy()
    ema_fast   = df["close"].ewm(span=fast,   adjust=False, min_periods=fast).mean()
    ema_slow   = df["close"].ewm(span=slow,   adjust=False, min_periods=slow).mean()
    macd_line  = (ema_fast - ema_slow).round(4)
    signal_line= macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean().round(4)
    histogram  = (macd_line - signal_line).round(4)

    # Mask until we have enough data
    min_periods = slow + signal - 1
    macd_line.iloc[:min_periods]   = np.nan
    signal_line.iloc[:min_periods] = np.nan
    histogram.iloc[:min_periods]   = np.nan

    df["macd_line"]      = macd_line
    df["macd_signal"]    = signal_line
    df["macd_histogram"] = histogram
    return df


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def add_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    """
    Bollinger Bands.
    Columns added: bb_middle, bb_upper, bb_lower, bb_width, bb_pct_b
    bb_pct_b: position within bands (0=lower, 1=upper, >1 overbought, <0 oversold)
    bb_width: band width as % of middle — proxy for volatility regime
    """
    df     = df.copy()
    middle = df["close"].rolling(window=period, min_periods=period).mean()
    std    = df["close"].rolling(window=period, min_periods=period).std()

    upper  = (middle + std_dev * std).round(4)
    lower  = (middle - std_dev * std).round(4)
    width  = ((upper - lower) / middle * 100).round(4)
    pct_b  = ((df["close"] - lower) / (upper - lower)).round(4)

    df["bb_middle"] = middle.round(4)
    df["bb_upper"]  = upper
    df["bb_lower"]  = lower
    df["bb_width"]  = width
    df["bb_pct_b"]  = pct_b
    return df


# ── ATR ───────────────────────────────────────────────────────────────────────

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average True Range — volatility measure.
    Requires: high, low, close columns.
    Columns added: atr_{period}, atr_pct (ATR as % of close)
    Used for: stop-loss sizing, position sizing, volatility regime detection.
    """
    df = df.copy()
    if not all(c in df.columns for c in ["high", "low", "close"]):
        return df

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().round(4)
    atr.iloc[:period] = np.nan

    df[f"atr_{period}"]     = atr
    df[f"atr_{period}_pct"] = (atr / df["close"] * 100).round(4)
    return df


# ── VWAP ──────────────────────────────────────────────────────────────────────

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Volume Weighted Average Price.
    Requires: high, low, close, volume columns.
    Computed as a rolling 20-day VWAP (true intraday VWAP needs tick data).
    Columns added: vwap_20
    """
    df = df.copy()
    if not all(c in df.columns for c in ["high", "low", "close", "volume"]):
        return df

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol        = typical_price * df["volume"]

    window = 20
    df["vwap_20"] = (
        tp_vol.rolling(window=window, min_periods=window).sum() /
        df["volume"].rolling(window=window, min_periods=window).sum()
    ).round(4)
    return df


# ── Stochastic Oscillator ─────────────────────────────────────────────────────

def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """
    Stochastic Oscillator (%K and %D).
    Requires: high, low, close.
    Columns added: stoch_k, stoch_d
    Signal zones: <20 oversold, >80 overbought
    """
    df = df.copy()
    if not all(c in df.columns for c in ["high", "low", "close"]):
        return df

    lowest_low   = df["low"].rolling(window=k_period,  min_periods=k_period).min()
    highest_high = df["high"].rolling(window=k_period, min_periods=k_period).max()

    k = ((df["close"] - lowest_low) / (highest_high - lowest_low) * 100).round(2)
    d = k.rolling(window=d_period, min_periods=d_period).mean().round(2)

    df["stoch_k"] = k
    df["stoch_d"] = d
    return df


# ── Signal generation ─────────────────────────────────────────────────────────

def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate composite buy/sell signals from indicators.
    Requires indicators already computed (run add_all_indicators first).

    Columns added:
        signal_rsi      — 'oversold' | 'overbought' | None
        signal_macd     — 'bullish_cross' | 'bearish_cross' | None
        signal_bb       — 'below_lower' | 'above_upper' | None
        signal_ma_trend — 'uptrend' | 'downtrend' | None
        signal_composite— numeric score -3 to +3 (sum of individual signals)
        signal_label    — 'Strong Buy' | 'Buy' | 'Neutral' | 'Sell' | 'Strong Sell'
    """
    df = df.copy()

    # ── RSI signal ────────────────────────────────────────────────────────────
    rsi_col = next((c for c in df.columns if c.startswith("rsi_")), None)
    if rsi_col:
        df["signal_rsi"] = np.where(
            df[rsi_col] < 30, "oversold",
            np.where(df[rsi_col] > 70, "overbought", None)
        )
    else:
        df["signal_rsi"] = None

    # ── MACD crossover signal ─────────────────────────────────────────────────
    if "macd_histogram" in df.columns:
        prev_hist = df["macd_histogram"].shift(1)
        df["signal_macd"] = np.where(
            (df["macd_histogram"] > 0) & (prev_hist <= 0), "bullish_cross",
            np.where(
                (df["macd_histogram"] < 0) & (prev_hist >= 0), "bearish_cross", None
            )
        )
    else:
        df["signal_macd"] = None

    # ── Bollinger Band signal ─────────────────────────────────────────────────
    if "bb_pct_b" in df.columns:
        df["signal_bb"] = np.where(
            df["bb_pct_b"] < 0,  "below_lower",
            np.where(df["bb_pct_b"] > 1, "above_upper", None)
        )
    else:
        df["signal_bb"] = None

    # ── MA trend signal (price vs 50 SMA vs 200 SMA) ─────────────────────────
    if "sma_50" in df.columns and "sma_200" in df.columns:
        df["signal_ma_trend"] = np.where(
            (df["close"] > df["sma_50"]) & (df["sma_50"] > df["sma_200"]), "uptrend",
            np.where(
                (df["close"] < df["sma_50"]) & (df["sma_50"] < df["sma_200"]), "downtrend", None
            )
        )
    else:
        df["signal_ma_trend"] = None

    # ── Composite score ───────────────────────────────────────────────────────
    score = pd.Series(0.0, index=df.index)

    if rsi_col:
        score += np.where(df["signal_rsi"] == "oversold",   1.0,
                 np.where(df["signal_rsi"] == "overbought", -1.0, 0.0))

    if "signal_macd" in df.columns:
        score += np.where(df["signal_macd"] == "bullish_cross",  1.0,
                 np.where(df["signal_macd"] == "bearish_cross", -1.0, 0.0))

    if "signal_bb" in df.columns:
        score += np.where(df["signal_bb"] == "below_lower",  1.0,
                 np.where(df["signal_bb"] == "above_upper", -1.0, 0.0))

    if "signal_ma_trend" in df.columns:
        score += np.where(df["signal_ma_trend"] == "uptrend",   1.0,
                 np.where(df["signal_ma_trend"] == "downtrend", -1.0, 0.0))

    df["signal_composite"] = score

    label_map = {
        lambda s: s >=  3: "Strong Buy",
        lambda s: s >=  1: "Buy",
        lambda s: s <= -3: "Strong Sell",
        lambda s: s <= -1: "Sell",
    }
    def _label(s):
        if s >= 3:   return "Strong Buy"
        if s >= 1:   return "Buy"
        if s <= -3:  return "Strong Sell"
        if s <= -1:  return "Sell"
        return "Neutral"

    df["signal_label"] = df["signal_composite"].apply(_label)
    return df


# ── Convenience: add everything ───────────────────────────────────────────────

def add_all_indicators(
    df: pd.DataFrame,
    sma_periods:  list[int] = [20, 50, 200],
    ema_periods:  list[int] = [9, 21, 50],
    rsi_period:   int = 14,
    atr_period:   int = 14,
    bb_period:    int = 20,
    include_stoch: bool = True,
    include_vwap:  bool = True,
    include_signals: bool = True,
) -> pd.DataFrame:
    """
    Add all technical indicators to a price DataFrame in one call.
    Input DataFrame must have: date, close (minimum)
    Optional but recommended: open, high, low, volume, adj_close

    Returns the same DataFrame with all indicator columns appended.
    """
    df = df.copy().sort_values("date").reset_index(drop=True)

    df = add_sma(df, sma_periods)
    df = add_ema(df, ema_periods)
    df = add_rsi(df, rsi_period)
    df = add_macd(df)
    df = add_bollinger(df, bb_period)
    df = add_atr(df, atr_period)

    if include_vwap:
        df = add_vwap(df)
    if include_stoch:
        df = add_stochastic(df)
    if include_signals:
        df = add_signals(df)

    return df


# ── Universe scan ─────────────────────────────────────────────────────────────

def scan_universe(
    all_prices: pd.DataFrame,
    symbols:    list[str],
    lookback:   int = 252,
) -> pd.DataFrame:
    """
    Compute latest indicator snapshot for all symbols.
    Returns one row per symbol with current indicator values — useful for
    screening stocks by technical condition (e.g. all RSI < 30 stocks).

    Args:
        all_prices: DataFrame with symbol, date, open, high, low, close, volume
        symbols:    List of symbols to scan
        lookback:   Days of history to use for indicator computation

    Returns:
        DataFrame with one row per symbol showing latest indicator values
    """
    rows = []
    for symbol in symbols:
        sym_df = (
            all_prices[all_prices["symbol"] == symbol]
            .sort_values("date")
            .tail(lookback)
            .copy()
        )
        if len(sym_df) < 50:
            continue

        try:
            ind = add_all_indicators(sym_df)
            last = ind.iloc[-1]
            rows.append({
                "symbol":           symbol,
                "date":             last["date"],
                "close":            last["close"],
                "rsi_14":           last.get("rsi_14"),
                "macd_histogram":   last.get("macd_histogram"),
                "bb_pct_b":         last.get("bb_pct_b"),
                "bb_width":         last.get("bb_width"),
                "atr_14_pct":       last.get("atr_14_pct"),
                "sma_50":           last.get("sma_50"),
                "sma_200":          last.get("sma_200"),
                "signal_composite": last.get("signal_composite"),
                "signal_label":     last.get("signal_label"),
                "signal_rsi":       last.get("signal_rsi"),
                "signal_macd":      last.get("signal_macd"),
                "signal_ma_trend":  last.get("signal_ma_trend"),
            })
        except Exception:
            continue

    return pd.DataFrame(rows)