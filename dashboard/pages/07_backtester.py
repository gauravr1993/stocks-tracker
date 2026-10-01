"""
dashboard/pages/07_backtester.py
Interactive backtester — run strategies on historical data, view results.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(
    page_title = "Backtester · NIFTY Intel",
    page_icon  = "🧪",
    layout     = "wide",
)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "config", ".env"
))

from components.sidebar import apply_dark_theme
from analysis.seasonality.data_loader import load_universe
from components.data_loader import load_price_history
from trading.backtest.engine  import Backtester
from trading.backtest.metrics import buy_and_hold, compare_to_benchmark, drawdown_series, monthly_returns_table
from trading.strategies.library import STRATEGIES, PARAM_GRIDS
from analysis.signals.charts import THEME

apply_dark_theme()

st.title("🧪 Strategy Backtester")
st.caption("Vectorised backtesting on 10yr NIFTY 100 price history · Results in seconds")

# ── Load universe ──────────────────────────────────────────────────────────────
with st.spinner("Loading universe..."):
    universe  = load_universe()

symbols   = sorted(universe["symbol"].dropna().tolist())
sym_clean = {s.replace(".NS", ""): s for s in symbols}

# ── Sidebar config ─────────────────────────────────────────────────────────────
st.sidebar.markdown("## ⚙️ Backtest Settings")

selected_clean = st.sidebar.selectbox(
    "Stock", list(sym_clean.keys()),
    index=list(sym_clean.keys()).index("RELIANCE") if "RELIANCE" in sym_clean else 0,
)
symbol = sym_clean[selected_clean]

strategy_key = st.sidebar.selectbox(
    "Strategy",
    options=list(STRATEGIES.keys()),
    format_func=lambda x: {
        "rsi_mean_reversion":       "RSI Mean Reversion",
        "macd_momentum":            "MACD Momentum",
        "ma_crossover":             "MA Crossover (Golden/Death Cross)",
        "bollinger_mean_reversion": "Bollinger Band Mean Reversion",
        "composite_signal":         "Composite Signal (Multi-indicator)",
        "rsi_trend_filtered":       "RSI + Trend Filter ⭐",
    }.get(x, x),
)

years = st.sidebar.select_slider("Backtest period", options=[2, 3, 5, 7, 10], value=5)
long_only = st.sidebar.checkbox("Long only", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### Strategy Parameters")

# Dynamic parameter inputs based on selected strategy
StratClass  = STRATEGIES[strategy_key]
strat_instance = StratClass()   # defaults
strat_params   = {}

param_defaults = {
    "rsi_period":    (14, 5,  30, 1),
    "oversold":      (30, 15, 45, 1),
    "overbought":    (70, 55, 85, 1),
    "trend_sma":     (200, 50, 200, 10),
    "fast":          (12, 5,  30, 1),
    "slow":          (26, 10, 60, 2),
    "signal":        (9,  3,  20, 1),
    "period":        (20, 10, 50, 2),
    "buy_threshold": (1,  1,  3,  1),
    "sell_threshold":(-1, -3, -1, 1),
}

for param, default_val in strat_instance.__dict__.items():
    if param.startswith("_"):
        continue
    if param in param_defaults:
        mn = param_defaults[param]
        if isinstance(default_val, float):
            strat_params[param] = st.sidebar.slider(
                param, float(mn[1]), float(mn[2]), float(default_val), step=0.5
            )
        else:
            strat_params[param] = st.sidebar.slider(
                param, mn[1], mn[2], int(default_val), step=mn[3]
            )
    else:
        strat_params[param] = default_val

strategy    = StratClass(**strat_params)
run_sweep   = st.sidebar.checkbox("Run parameter sweep", value=False)

st.sidebar.markdown("---")
commission  = st.sidebar.number_input("Commission % (round-trip)", value=0.1, step=0.05) / 100
slippage    = st.sidebar.number_input("Slippage %", value=0.05, step=0.01) / 100

run_btn = st.sidebar.button("▶ Run Backtest", type="primary", use_container_width=True)

# ── Run ────────────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner(f"Loading {selected_clean} price history..."):
        prices = load_price_history(symbol, years=years)

    if prices.empty:
        st.error("No price data found.")
        st.stop()

    with st.spinner(f"Running {strategy_key} on {selected_clean}..."):
        bt     = Backtester(prices, symbol=selected_clean,
                            commission=commission, slippage=slippage,
                            long_only=long_only)
        result = bt.run(strategy)
        bh_eq  = buy_and_hold(prices.tail(len(result.equity_curve)))
        comp   = compare_to_benchmark(result.equity_curve, bh_eq, label=strategy_key)
        dates  = prices["date"].tail(len(result.equity_curve))

    st.session_state["bt_result"]  = result
    st.session_state["bt_bh"]      = bh_eq
    st.session_state["bt_comp"]    = comp
    st.session_state["bt_dates"]   = dates
    st.session_state["bt_prices"]  = prices
    st.session_state["bt_symbol"]  = selected_clean
    st.session_state["bt_strat"]   = strategy_key

    if run_sweep and strategy_key in PARAM_GRIDS:
        with st.spinner("Running parameter sweep (this takes ~30s)..."):
            sweep_df = bt.run_parameter_sweep(StratClass, PARAM_GRIDS[strategy_key])
        st.session_state["bt_sweep"] = sweep_df

# ── Display results ────────────────────────────────────────────────────────────
if "bt_result" not in st.session_state:
    st.info("Configure settings in the sidebar and click **▶ Run Backtest** to start.")
    st.markdown("""
    **Available strategies:**
    - **RSI + Trend Filter ⭐** — Recommended starting point. RSI mean reversion filtered by SMA 200 uptrend. Avoids buying falling stocks.
    - **RSI Mean Reversion** — Pure RSI oversold/overbought signals. Best on range-bound stocks.
    - **MACD Momentum** — Trades MACD histogram crossovers. Best on trending stocks.
    - **MA Crossover** — Golden/death cross (SMA 50/200). Slow but reliable trend following.
    - **Bollinger Mean Reversion** — Buy at lower band, sell at upper. Works on stable stocks.
    - **Composite Signal** — Combines RSI + MACD + Bollinger + MA trend. Most conservative entry.
    """)
    st.stop()

result  = st.session_state["bt_result"]
bh_eq   = st.session_state["bt_bh"]
comp    = st.session_state["bt_comp"]
dates   = st.session_state["bt_dates"]
prices  = st.session_state["bt_prices"]
sym_lbl = st.session_state["bt_symbol"]

# ── KPI strip ──────────────────────────────────────────────────────────────────
summary = result.summary()

c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("Total Return",  summary["total_return"],
          delta=f"vs B&H: {float(summary['total_return'].replace('%','')) - float(comp[comp['Name']=='Buy & Hold']['Total Return'].values[0].replace('%','')):.2f}%")
c2.metric("CAGR",          summary["cagr"])
c3.metric("Sharpe Ratio",  summary["sharpe"],
          delta="Good" if float(summary["sharpe"]) > 1 else "Improve",
          delta_color="normal" if float(summary["sharpe"]) > 1 else "inverse")
c4.metric("Max Drawdown",  summary["max_drawdown"])
c5.metric("Win Rate",      summary["win_rate"])
c6.metric("Trades",        summary["n_trades"],
          delta=f"Avg {summary['avg_hold_days']}d hold")

st.markdown("---")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Equity Curve",
    "📊 Trade Analysis",
    "📅 Monthly Returns",
    "🔧 Parameter Sweep",
])

# ══ TAB 1 — Equity curve ══════════════════════════════════════════════════════
with tab1:
    # Comparison table
    st.dataframe(comp, use_container_width=True, hide_index=True)
    st.markdown("---")

    # Equity curve chart
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.04,
        subplot_titles=[f"{sym_lbl} — Equity Curve", "Drawdown %"],
    )

    date_vals = dates.values if hasattr(dates, "values") else dates

    # Strategy equity
    fig.add_trace(go.Scatter(
        x=date_vals, y=result.equity_curve.values,
        name=strategy_key, mode="lines",
        line=dict(color=THEME["blue"], width=2),
        hovertemplate="Strategy: %{y:.4f}<extra></extra>",
    ), row=1, col=1)

    # Buy & hold equity
    bh_vals = bh_eq.values[-len(result.equity_curve):]
    fig.add_trace(go.Scatter(
        x=date_vals, y=bh_vals,
        name="Buy & Hold", mode="lines",
        line=dict(color=THEME["subtext"], width=1.5, dash="dot"),
        hovertemplate="B&H: %{y:.4f}<extra></extra>",
    ), row=1, col=1)

    # Drawdown
    dd = drawdown_series(result.equity_curve)
    fig.add_trace(go.Scatter(
        x=date_vals, y=dd.values,
        name="Drawdown", mode="lines", fill="tozeroy",
        line=dict(color=THEME["red"], width=1),
        fillcolor="rgba(255,77,109,0.15)",
        hovertemplate="Drawdown: %{y:.2f}%<extra></extra>",
    ), row=2, col=1)

    fig.update_layout(
        paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
        font=dict(color=THEME["text"]), height=550,
        margin=dict(l=60, r=20, t=40, b=20),
        legend=dict(bgcolor=THEME["card_bg"], bordercolor=THEME["border"]),
        xaxis_rangeslider_visible=False,
    )
    fig.update_yaxes(gridcolor=THEME["border"])
    fig.update_xaxes(gridcolor=THEME["border"], showgrid=False)
    st.plotly_chart(fig, use_container_width=True)

    # Buy/sell markers on price chart
    st.subheader("Trade entries & exits on price")
    if not result.trades.empty:
        price_col = "adj_close" if "adj_close" in prices.columns else "close"
        fig_price = go.Figure()
        fig_price.add_trace(go.Scatter(
            x=prices["date"], y=prices[price_col],
            name="Price", mode="lines",
            line=dict(color=THEME["subtext"], width=1),
        ))
        # Entry markers
        entries = result.trades
        fig_price.add_trace(go.Scatter(
            x=entries["entry_date"], y=entries["entry_price"],
            mode="markers", name="Entry",
            marker=dict(symbol="triangle-up", size=10, color=THEME["green"],
                        line=dict(width=1, color=THEME["bg"])),
            hovertemplate="Entry: ₹%{y:.2f}<br>%{x}<extra></extra>",
        ))
        fig_price.add_trace(go.Scatter(
            x=entries["exit_date"], y=entries["exit_price"],
            mode="markers", name="Exit",
            marker=dict(symbol="triangle-down", size=10, color=THEME["red"],
                        line=dict(width=1, color=THEME["bg"])),
            hovertemplate="Exit: ₹%{y:.2f}<br>%{x}<extra></extra>",
        ))
        fig_price.update_layout(
            paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
            font=dict(color=THEME["text"]), height=350,
            margin=dict(l=60, r=20, t=30, b=20),
            xaxis=dict(gridcolor=THEME["border"]),
            yaxis=dict(gridcolor=THEME["border"]),
            legend=dict(bgcolor=THEME["card_bg"]),
        )
        st.plotly_chart(fig_price, use_container_width=True)

# ══ TAB 2 — Trade analysis ═════════════════════════════════════════════════════
with tab2:
    if result.trades.empty:
        st.info("No trades generated. Try adjusting strategy parameters.")
    else:
        # Trade stats
        s1,s2,s3,s4 = st.columns(4)
        s1.metric("Total Trades",  result.n_trades)
        s2.metric("Win Rate",      f"{result.win_rate:.1f}%")
        s3.metric("Avg Win",       f"{result.avg_win:.2f}%")
        s4.metric("Avg Loss",      f"{result.avg_loss:.2f}%")

        s5,s6,s7,s8 = st.columns(4)
        s5.metric("Profit Factor", result.profit_factor)
        s6.metric("Avg Hold",      f"{result.avg_hold_days:.0f} days")
        s7.metric("Sortino",       result.sortino)
        s8.metric("Best Trade",    f"{result.trades['pnl_pct'].max():.2f}%")

        st.markdown("---")

        # PnL distribution
        col_hist, col_scatter = st.columns(2)
        with col_hist:
            fig_pnl = go.Figure(go.Histogram(
                x=result.trades["pnl_pct"], nbinsx=25,
                marker_color=[
                    THEME["green"] if v >= 0 else THEME["red"]
                    for v in result.trades["pnl_pct"]
                ],
                opacity=0.8,
            ))
            fig_pnl.add_vline(x=0, line_color=THEME["border"], line_dash="dash")
            fig_pnl.update_layout(
                paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
                font=dict(color=THEME["text"]), height=300,
                margin=dict(l=40,r=20,t=30,b=40),
                title=dict(text="Trade P&L Distribution", font=dict(color=THEME["text"])),
                xaxis=dict(title="P&L %", gridcolor=THEME["border"]),
                yaxis=dict(title="Trades", gridcolor=THEME["border"]),
            )
            st.plotly_chart(fig_pnl, use_container_width=True)

        with col_scatter:
            fig_hd = go.Figure(go.Scatter(
                x=result.trades["hold_days"],
                y=result.trades["pnl_pct"],
                mode="markers",
                marker=dict(
                    color=[THEME["green"] if v >= 0 else THEME["red"]
                           for v in result.trades["pnl_pct"]],
                    size=8, opacity=0.7,
                ),
                hovertemplate="Hold: %{x}d<br>P&L: %{y:.2f}%<extra></extra>",
            ))
            fig_hd.add_hline(y=0, line_color=THEME["border"], line_dash="dash")
            fig_hd.update_layout(
                paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
                font=dict(color=THEME["text"]), height=300,
                margin=dict(l=40,r=20,t=30,b=40),
                title=dict(text="Hold Days vs P&L", font=dict(color=THEME["text"])),
                xaxis=dict(title="Hold Days", gridcolor=THEME["border"]),
                yaxis=dict(title="P&L %",     gridcolor=THEME["border"]),
            )
            st.plotly_chart(fig_hd, use_container_width=True)

        # Full trade log
        with st.expander("Full trade log"):
            st.dataframe(
                result.trades.style
                    .background_gradient(subset=["pnl_pct"], cmap="RdYlGn")
                    .format({"pnl_pct":"{:.2f}%","entry_price":"₹{:.2f}","exit_price":"₹{:.2f}"}),
                use_container_width=True, hide_index=True,
            )

# ══ TAB 3 — Monthly returns ════════════════════════════════════════════════════
with tab3:
    st.subheader("Monthly Returns Heatmap")
    st.caption("Each cell = strategy return for that month. Compare to seasonality page for alignment.")

    try:
        monthly_tbl = monthly_returns_table(result.returns, dates)
        fig_m = go.Figure(go.Heatmap(
            z    = monthly_tbl.values,
            x    = monthly_tbl.columns.tolist(),
            y    = monthly_tbl.index.tolist(),
            colorscale="RdYlGn", zmid=0,
            text = [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row]
                    for row in monthly_tbl.values],
            texttemplate="%{text}", textfont=dict(size=10),
            hovertemplate="<b>%{y} %{x}</b><br>%{z:.2f}%<extra></extra>",
            colorbar=dict(title="Return %", tickfont=dict(color=THEME["text"])),
        ))
        fig_m.update_layout(
            paper_bgcolor=THEME["bg"], font=dict(color=THEME["text"]),
            height=max(300, len(monthly_tbl) * 30 + 80),
            margin=dict(l=60, r=20, t=30, b=20),
            xaxis=dict(side="top"),
        )
        st.plotly_chart(fig_m, use_container_width=True)

        with st.expander("Monthly returns table"):
            st.dataframe(
                monthly_tbl.style
                    .background_gradient(cmap="RdYlGn", axis=None)
                    .format("{:.2f}%", na_rep="—"),
                use_container_width=True,
            )
    except Exception as e:
        st.warning(f"Could not compute monthly returns: {e}")

# ══ TAB 4 — Parameter sweep ════════════════════════════════════════════════════
with tab4:
    if "bt_sweep" not in st.session_state:
        if strategy_key in PARAM_GRIDS:
            st.info(
                "Enable **Run parameter sweep** in the sidebar and re-run "
                "to find optimal parameters for this strategy."
            )
            grid = PARAM_GRIDS[strategy_key]
            import itertools
            n_combos = len(list(itertools.product(*grid.values())))
            st.caption(f"Will test {n_combos} parameter combinations for {strategy_key}.")
        else:
            st.info("No parameter grid defined for this strategy.")
    else:
        sweep = st.session_state["bt_sweep"]
        st.subheader(f"Parameter Sweep — {strategy_key} on {sym_lbl}")
        st.caption(f"{len(sweep)} combinations tested · Sorted by Sharpe ratio")

        if not sweep.empty:
            c1, c2, c3 = st.columns(3)
            best = sweep.iloc[0]
            c1.metric("Best Sharpe",  best["sharpe"])
            c2.metric("Best CAGR",    best["cagr"])
            c3.metric("Best Params",  str({k: best[k] for k in PARAM_GRIDS[strategy_key]}))

            # Convert string metrics to numeric for display
            sweep_disp = sweep.copy()
            for col in ["sharpe", "sortino", "profit_factor"]:
                if col in sweep_disp.columns:
                    sweep_disp[col] = pd.to_numeric(sweep_disp[col], errors="coerce")
            for col in ["total_return","cagr","max_drawdown","win_rate","avg_win","avg_loss"]:
                if col in sweep_disp.columns:
                    sweep_disp[col] = pd.to_numeric(
                        sweep_disp[col].astype(str).str.replace("%",""), errors="coerce"
                    )
            st.dataframe(
                sweep_disp.style
                    .background_gradient(subset=["sharpe"],   cmap="RdYlGn", vmin=0, vmax=2)
                    .background_gradient(subset=["win_rate"], cmap="RdYlGn", vmin=30, vmax=70)
                    .format({
                        "sharpe":       "{:.3f}",
                        "total_return": "{:.2f}%",
                        "cagr":         "{:.2f}%",
                        "win_rate":     "{:.1f}%",
                        "max_drawdown": "{:.2f}%",
                    }, na_rep="—"),
                use_container_width=True, hide_index=True,
            )