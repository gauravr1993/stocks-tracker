"""
trading/strategies/library.py
Ready-to-use strategy implementations built on the BaseStrategy interface.

Each strategy:
  - Has sensible defaults tuned for Indian markets
  - Is fully parameterisable for grid search
  - Includes a docstring explaining the logic

Available strategies:
  RSIMeanReversionStrategy  — buy oversold, sell overbought
  MACDMomentumStrategy      — buy on bullish MACD cross
  MACrossoverStrategy       — golden cross / death cross
  BollingerMeanReversionStrategy — buy at lower band, sell at upper
  CompositeSignalStrategy   — combines multiple indicators
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from trading.backtest.engine import BaseStrategy


# ── 1. RSI Mean Reversion ─────────────────────────────────────────────────────

class RSIMeanReversionStrategy(BaseStrategy):
    """
    Classic RSI mean reversion:
      - BUY  when RSI crosses above oversold threshold (default 30)
      - SELL when RSI crosses above overbought threshold (default 70)
      - FLAT otherwise

    Works best on range-bound stocks. Poor on strong trending stocks.
    """
    name = "rsi_mean_reversion"

    def __init__(self, rsi_period: int = 14, oversold: int = 30, overbought: int = 70):
        self.rsi_period = rsi_period
        self.oversold   = oversold
        self.overbought = overbought

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi_col = f"rsi_{self.rsi_period}"
        if rsi_col not in df.columns:
            return pd.Series(0, index=df.index)

        rsi  = df[rsi_col].values
        prev = df[rsi_col].shift(1).values
        signal = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(1, len(df)):
            if np.isnan(rsi[i]) or np.isnan(prev[i]):
                continue
            if not in_position:
                if rsi[i] > self.oversold and prev[i] <= self.oversold:
                    in_position = True
                    signal[i] = 1
            else:
                if rsi[i] >= self.overbought:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1

        return pd.Series(signal, index=df.index)


# ── 2. MACD Momentum ──────────────────────────────────────────────────────────

class MACDMomentumStrategy(BaseStrategy):
    """
    MACD histogram crossover momentum:
      - BUY  when MACD histogram crosses from negative to positive (bullish cross)
      - SELL when MACD histogram crosses from positive to negative (bearish cross)

    Works best on trending stocks. Gets chopped up in sideways markets.
    """
    name = "macd_momentum"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast   = fast
        self.slow   = slow
        self.signal = signal

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "macd_histogram" not in df.columns:
            return pd.Series(0, index=df.index)

        hist = df["macd_histogram"].values
        prev = df["macd_histogram"].shift(1).values
        signal = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(1, len(df)):
            if np.isnan(hist[i]) or np.isnan(prev[i]):
                continue
            if not in_position:
                if hist[i] > 0 and prev[i] <= 0:
                    in_position = True
                    signal[i] = 1
            else:
                if hist[i] < 0 and prev[i] >= 0:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1

        return pd.Series(signal, index=df.index)


# ── 3. Moving Average Crossover ───────────────────────────────────────────────

class MACrossoverStrategy(BaseStrategy):
    """
    Classic golden cross / death cross:
      - BUY  when fast SMA crosses above slow SMA (golden cross)
      - SELL when fast SMA crosses below slow SMA (death cross)

    Default: SMA 50 / SMA 200 — classic long-term trend following.
    For shorter term: fast=20, slow=50.
    """
    name = "ma_crossover"

    def __init__(self, fast: int = 50, slow: int = 200):
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_col = f"sma_{self.fast}"
        slow_col = f"sma_{self.slow}"

        if fast_col not in df.columns or slow_col not in df.columns:
            return pd.Series(0, index=df.index)

        fast      = df[fast_col].values
        slow      = df[slow_col].values
        prev_fast = df[fast_col].shift(1).values
        prev_slow = df[slow_col].shift(1).values
        signal    = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(1, len(df)):
            if any(np.isnan(v) for v in [fast[i], slow[i], prev_fast[i], prev_slow[i]]):
                continue
            if not in_position:
                if fast[i] > slow[i] and prev_fast[i] <= prev_slow[i]:
                    in_position = True
                    signal[i] = 1
            else:
                if fast[i] < slow[i] and prev_fast[i] >= prev_slow[i]:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1

        return pd.Series(signal, index=df.index)


# ── 4. Bollinger Band Mean Reversion ─────────────────────────────────────────

class BollingerMeanReversionStrategy(BaseStrategy):
    """
    Bollinger Band mean reversion:
      - BUY  when price closes below lower band (oversold)
      - SELL when price crosses above middle band (mean reversion complete)
      - EXIT when price closes above upper band (overbought)

    Best on stocks that oscillate around a stable mean (FMCG, utilities).
    """
    name = "bollinger_mean_reversion"

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period  = period
        self.std_dev = std_dev

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if not all(c in df.columns for c in ["bb_lower","bb_middle","bb_upper","bb_pct_b"]):
            return pd.Series(0, index=df.index)

        pct_b = df["bb_pct_b"].values
        prev  = df["bb_pct_b"].shift(1).values
        signal = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(1, len(df)):
            if np.isnan(pct_b[i]) or np.isnan(prev[i]):
                continue
            if not in_position:
                if pct_b[i] < 0:
                    in_position = True
                    signal[i] = 1
            else:
                # Exit: price crossed back above midpoint or went above upper band
                if pct_b[i] >= 0.5 or pct_b[i] > 1:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1

        return pd.Series(signal, index=df.index)


# ── 5. Composite Signal Strategy ─────────────────────────────────────────────

class CompositeSignalStrategy(BaseStrategy):
    """
    Multi-indicator composite strategy.
    Uses the signal_composite score already computed by add_all_indicators().
      - BUY  when composite score >= buy_threshold  (default +1)
      - SELL when composite score <= sell_threshold (default -1)
      - HOLD otherwise

    This is the most robust strategy since it requires agreement
    across multiple indicators before taking a position.
    """
    name = "composite_signal"

    def __init__(self, buy_threshold: float = 1.0, sell_threshold: float = -1.0):
        self.buy_threshold  = buy_threshold
        self.sell_threshold = sell_threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "signal_composite" not in df.columns:
            return pd.Series(0, index=df.index)

        score  = df["signal_composite"].values
        signal = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(len(df)):
            if np.isnan(score[i]):
                continue
            if not in_position:
                if score[i] >= self.buy_threshold:
                    in_position = True
                    signal[i] = 1
            else:
                if score[i] <= self.sell_threshold:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1

        return pd.Series(signal, index=df.index)


# ── 6. RSI + Trend Filter (best of both worlds) ───────────────────────────────

class RSITrendStrategy(BaseStrategy):
    """
    RSI mean reversion filtered by trend direction.
    Only takes RSI buy signals when the stock is in an uptrend (price > SMA 200).
    Avoids buying falling knives.

    This is generally the best single-stock strategy for Indian large caps.
    """
    name = "rsi_trend_filtered"

    def __init__(
        self,
        rsi_period:  int = 14,
        oversold:    int = 35,    # slightly higher than pure mean reversion
        overbought:  int = 65,
        trend_sma:   int = 200,
    ):
        self.rsi_period  = rsi_period
        self.oversold    = oversold
        self.overbought  = overbought
        self.trend_sma   = trend_sma

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi_col  = f"rsi_{self.rsi_period}"
        sma_col  = f"sma_{self.trend_sma}"

        if rsi_col not in df.columns:
            return pd.Series(0, index=df.index)

        rsi  = df[rsi_col].values
        prev = df[rsi_col].shift(1).values

        in_uptrend = (
            (df["close"] > df[sma_col]).values
            if sma_col in df.columns
            else np.ones(len(df), dtype=bool)
        )

        # Stateful signal: track position explicitly
        signal = np.zeros(len(df), dtype=int)
        in_position = False

        for i in range(1, len(df)):
            if np.isnan(rsi[i]) or np.isnan(prev[i]):
                signal[i] = 0
                continue
            if not in_position:
                # Entry: RSI crosses above oversold threshold while in uptrend
                if rsi[i] > self.oversold and prev[i] <= self.oversold and in_uptrend[i]:
                    in_position = True
                    signal[i] = 1
            else:
                # Exit: RSI overbought OR trend breaks
                if rsi[i] >= self.overbought or not in_uptrend[i]:
                    in_position = False
                    signal[i] = 0
                else:
                    signal[i] = 1   # hold

        return pd.Series(signal, index=df.index)


# ── Strategy registry ─────────────────────────────────────────────────────────

STRATEGIES = {
    "rsi_mean_reversion":       RSIMeanReversionStrategy,
    "macd_momentum":            MACDMomentumStrategy,
    "ma_crossover":             MACrossoverStrategy,
    "bollinger_mean_reversion": BollingerMeanReversionStrategy,
    "composite_signal":         CompositeSignalStrategy,
    "rsi_trend_filtered":       RSITrendStrategy,
}

# Default parameter grids for sweep
PARAM_GRIDS = {
    "rsi_mean_reversion": {
        "rsi_period": [10, 14, 21],
        "oversold":   [25, 30, 35],
        "overbought": [65, 70, 75],
    },
    "ma_crossover": {
        "fast": [20, 50],
        "slow": [100, 150, 200],
    },
    "rsi_trend_filtered": {
        "rsi_period": [10, 14],
        "oversold":   [30, 35, 40],
        "overbought": [60, 65, 70],
    },
    "composite_signal": {
        "buy_threshold":  [1.0, 2.0],
        "sell_threshold": [-1.0, -2.0],
    },
}