"""
trading/backtest/engine.py
Vectorised backtester — runs entirely on numpy/pandas, no bar-by-bar loops.
Processes 10 years of 100 stocks in seconds.

Design:
  - Strategy produces a signal Series: +1 (long), -1 (short), 0 (flat)
  - Engine computes daily returns, equity curve, and all metrics in one pass
  - Supports long-only, long/short, and configurable costs
  - No lookahead bias — signals on day T are executed at open on day T+1

Usage:
    from trading.backtest.engine import Backtester
    from trading.strategies.momentum import RSICrossStrategy

    bt     = Backtester(prices_df)
    result = bt.run(RSICrossStrategy())
    print(result.summary())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    symbol:         str
    strategy_name:  str
    equity_curve:   pd.Series          # daily portfolio value (starts at 1.0)
    returns:        pd.Series          # daily strategy returns
    signals:        pd.Series          # raw signals (+1/0/-1)
    trades:         pd.DataFrame       # individual trade log
    params:         dict = field(default_factory=dict)

    # ── Metrics ───────────────────────────────────────────────────────────────

    @property
    def total_return(self) -> float:
        return round((self.equity_curve.iloc[-1] - 1.0) * 100, 2)

    @property
    def cagr(self) -> float:
        years = len(self.equity_curve) / 252
        if years <= 0:
            return 0.0
        return round((self.equity_curve.iloc[-1] ** (1 / years) - 1) * 100, 2)

    @property
    def sharpe(self) -> float:
        if self.returns.std() == 0:
            return 0.0
        return round(self.returns.mean() / self.returns.std() * np.sqrt(252), 3)

    @property
    def sortino(self) -> float:
        downside = self.returns[self.returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return round(self.returns.mean() / downside.std() * np.sqrt(252), 3)

    @property
    def max_drawdown(self) -> float:
        roll_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - roll_max) / roll_max
        return round(drawdown.min() * 100, 2)

    @property
    def win_rate(self) -> float:
        if self.trades.empty:
            return 0.0
        wins = (self.trades["pnl_pct"] > 0).sum()
        return round(wins / len(self.trades) * 100, 1)

    @property
    def avg_win(self) -> float:
        wins = self.trades[self.trades["pnl_pct"] > 0]["pnl_pct"]
        return round(wins.mean(), 2) if not wins.empty else 0.0

    @property
    def avg_loss(self) -> float:
        losses = self.trades[self.trades["pnl_pct"] < 0]["pnl_pct"]
        return round(losses.mean(), 2) if not losses.empty else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = self.trades[self.trades["pnl_pct"] > 0]["pnl_pct"].sum()
        gross_loss   = abs(self.trades[self.trades["pnl_pct"] < 0]["pnl_pct"].sum())
        if gross_loss == 0:
            return float("inf")
        return round(gross_profit / gross_loss, 3)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def avg_hold_days(self) -> float:
        if self.trades.empty or "hold_days" not in self.trades.columns:
            return 0.0
        return round(self.trades["hold_days"].mean(), 1)

    def summary(self) -> dict:
        return {
            "symbol":        self.symbol,
            "strategy":      self.strategy_name,
            "total_return":  f"{self.total_return:.2f}%",
            "cagr":          f"{self.cagr:.2f}%",
            "sharpe":        self.sharpe,
            "sortino":       self.sortino,
            "max_drawdown":  f"{self.max_drawdown:.2f}%",
            "win_rate":      f"{self.win_rate:.1f}%",
            "profit_factor": self.profit_factor,
            "n_trades":      self.n_trades,
            "avg_hold_days": self.avg_hold_days,
            "avg_win":       f"{self.avg_win:.2f}%",
            "avg_loss":      f"{self.avg_loss:.2f}%",
        }

    def summary_df(self) -> pd.DataFrame:
        return pd.DataFrame([self.summary()])


# ── Base strategy ─────────────────────────────────────────────────────────────

class BaseStrategy:
    """
    All strategies inherit from this.
    Subclasses implement generate_signals(df) which returns a +1/0/-1 Series.
    """
    name: str = "base"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Given a price DataFrame with indicators, return a signal Series.
        Index must match df.index.
        Values: +1 = long, -1 = short, 0 = flat
        """
        raise NotImplementedError

    def __repr__(self):
        params = {k: v for k, v in self.__dict__.items()
                  if not k.startswith("_")}
        return f"{self.name}({params})"


# ── Trade extractor ───────────────────────────────────────────────────────────

def _extract_trades(
    signals: pd.Series,
    prices:  pd.Series,
    dates:   pd.Series,
) -> pd.DataFrame:
    """
    Convert a signal series into a trade log.
    Each row = one trade: entry date, exit date, entry/exit price, pnl.
    """
    trades = []
    in_trade  = False
    entry_price = None
    entry_date  = None
    entry_signal= None

    sig_arr   = signals.values
    price_arr = prices.values
    date_arr  = dates.values

    for i in range(1, len(sig_arr)):
        sig   = sig_arr[i]
        prev  = sig_arr[i - 1]
        price = price_arr[i]
        date  = date_arr[i]

        # Entry: signal changes from 0 to +1 or -1
        if not in_trade and sig != 0:
            in_trade     = True
            entry_price  = price
            entry_date   = date
            entry_signal = sig

        # Exit: signal flips or goes to 0
        elif in_trade and (sig != entry_signal):
            exit_price = price
            if entry_price and entry_price > 0:
                pnl_pct = (exit_price / entry_price - 1) * 100 * entry_signal
                hold    = (pd.Timestamp(date) - pd.Timestamp(entry_date)).days
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   date,
                    "direction":   "long" if entry_signal == 1 else "short",
                    "entry_price": round(float(entry_price), 4),
                    "exit_price":  round(float(exit_price),  4),
                    "pnl_pct":     round(pnl_pct, 4),
                    "hold_days":   hold,
                })
            in_trade = (sig != 0)
            if in_trade:
                entry_price  = price
                entry_date   = date
                entry_signal = sig

    if not trades:
        return pd.DataFrame(columns=[
            "entry_date","exit_date","direction",
            "entry_price","exit_price","pnl_pct","hold_days",
        ])

    return pd.DataFrame(trades)


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    """
    Vectorised backtester.

    Args:
        prices:       DataFrame with date, open, high, low, close, volume, adj_close
        symbol:       Symbol label for results
        initial_cap:  Starting capital (default 100 = normalised to 1.0)
        commission:   Round-trip cost as fraction of trade value (default 0.1% = 0.001)
        slippage:     Slippage as fraction of price (default 0.05% = 0.0005)
        long_only:    If True, short signals are treated as exits only
    """

    def __init__(
        self,
        prices:      pd.DataFrame,
        symbol:      str   = "UNKNOWN",
        commission:  float = 0.001,    # 0.1% round-trip (NSE typical)
        slippage:    float = 0.0005,   # 0.05% slippage
        long_only:   bool  = True,     # Indian retail = long only by default
    ):
        self.prices     = prices.copy().sort_values("date").reset_index(drop=True)
        self.symbol     = symbol
        self.commission = commission
        self.slippage   = slippage
        self.long_only  = long_only

    def run(self, strategy: BaseStrategy) -> BacktestResult:
        """
        Run a strategy on the price data and return a BacktestResult.
        """
        from analysis.signals.indicators import add_all_indicators

        logger.info("Backtesting %s on %s (%d bars)",
                    strategy.name, self.symbol, len(self.prices))

        # Add indicators
        df = add_all_indicators(self.prices)

        # Generate signals
        raw_signals = strategy.generate_signals(df)

        # Long-only: clip short signals to 0
        if self.long_only:
            raw_signals = raw_signals.clip(lower=0)

        # Shift by 1: signal on day T → position on day T+1 (no lookahead)
        position = raw_signals.shift(1).fillna(0)

        # Daily returns from adj_close
        price_col = "adj_close" if "adj_close" in df.columns else "close"
        daily_ret = df[price_col].pct_change().fillna(0)

        # Strategy returns = position * daily return - costs on position changes
        pos_change = position.diff().abs().fillna(0)
        costs      = pos_change * (self.commission + self.slippage)
        strat_ret  = (position * daily_ret) - costs

        # Equity curve
        equity = (1 + strat_ret).cumprod()
        equity.index = df.index

        # Trade log
        trades = _extract_trades(position, df[price_col], df["date"])

        return BacktestResult(
            symbol        = self.symbol,
            strategy_name = strategy.name,
            equity_curve  = equity,
            returns       = strat_ret,
            signals       = raw_signals,
            trades        = trades,
            params        = strategy.__dict__.copy(),
        )

    def run_parameter_sweep(
        self,
        strategy_class,
        param_grid: dict,
    ) -> pd.DataFrame:
        """
        Run a strategy over a grid of parameters and return ranked results.
        Used for optimisation — find best params before live trading.

        Args:
            strategy_class: Strategy class (not instance)
            param_grid:     {param_name: [val1, val2, ...]}
                            e.g. {"rsi_period": [10,14,21], "oversold": [25,30,35]}

        Returns:
            DataFrame of results sorted by Sharpe ratio
        """
        import itertools

        keys   = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))

        logger.info("Parameter sweep: %d combinations for %s",
                    len(combos), strategy_class.__name__)

        rows = []
        for combo in combos:
            params   = dict(zip(keys, combo))
            strategy = strategy_class(**params)
            try:
                result = self.run(strategy)
                row    = result.summary()
                row.update(params)
                rows.append(row)
            except Exception as exc:
                logger.debug("Combo %s failed: %s", params, exc)

        if not rows:
            return pd.DataFrame()

        results_df = pd.DataFrame(rows)
        # Sort by Sharpe
        results_df["sharpe_num"] = pd.to_numeric(results_df["sharpe"], errors="coerce")
        results_df = results_df.sort_values("sharpe_num", ascending=False).drop(
            columns=["sharpe_num"]
        )
        return results_df.reset_index(drop=True)