"""
dashboard/pages/06_algo_signals.py
Technical signals dashboard — per-stock indicator charts and universe scan.
"""
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(
    page_title = "Signals · NIFTY Intel",
    page_icon  = "⚡",
    layout     = "wide",
)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "config", ".env"
))

from components.sidebar    import apply_dark_theme, fmt_pct
from components.data_loader import load_screener
from analysis.seasonality.data_loader import load_all_prices, load_universe
from analysis.signals.indicators import add_all_indicators, scan_universe
from analysis.signals.charts     import technical_chart, rsi_gauge, signal_scan_bars

apply_dark_theme()

st.title("⚡ Technical Signals")
st.caption("RSI · MACD · Bollinger Bands · Moving Averages · Signal Scanner")

# ── Load base data ────────────────────────────────────────────────────────────
with st.spinner("Loading data..."):
    universe   = load_universe()
    all_prices = load_all_prices()

symbols_list = sorted(universe["symbol"].dropna().tolist())
sym_clean    = {s.replace(".NS", ""): s for s in symbols_list}

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📈 Stock Chart", "🔍 Signal Scanner"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Single stock technical chart
# ══════════════════════════════════════════════════════════════════════════════
with tab1:

    # ── Controls ──────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_clean = st.selectbox(
            "Select stock",
            options=list(sym_clean.keys()),
            index=list(sym_clean.keys()).index("RELIANCE") if "RELIANCE" in sym_clean else 0,
            key="signal_stock",
        )
    with col2:
        period = st.select_slider(
            "Period",
            options=["3M", "6M", "1Y", "2Y", "5Y"],
            value="1Y",
        )
    with col3:
        show_sigs = st.checkbox("Show buy/sell signals", value=True)

    with st.expander("Indicator settings", expanded=False):
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            show_bb     = st.checkbox("Bollinger Bands", value=True)
            show_volume = st.checkbox("Volume panel",    value=True)
        with ec2:
            ma_20  = st.checkbox("SMA 20",  value=True)
            ma_50  = st.checkbox("SMA 50",  value=True)
            ma_200 = st.checkbox("SMA 200", value=True)
        with ec3:
            rsi_period = st.select_slider("RSI period", options=[9, 14, 21], value=14)

    show_mas  = [p for p, chk in [(20, ma_20), (50, ma_50), (200, ma_200)] if chk]
    symbol    = sym_clean[selected_clean]

    # ── Fetch and compute ─────────────────────────────────────────────────────
    period_days = {"3M": 90, "6M": 180, "1Y": 252, "2Y": 504, "5Y": 1260}
    days        = period_days[period]

    sym_prices = (
        all_prices[all_prices["symbol"] == symbol]
        .sort_values("date")
        .tail(days + 250)     # extra buffer for indicator warm-up
        .copy()
    )

    if len(sym_prices) < 50:
        st.warning(f"Not enough data for {selected_clean}.")
        st.stop()

    with st.spinner("Computing indicators..."):
        sym_ind = add_all_indicators(
            sym_prices,
            sma_periods  = show_mas or [20, 50, 200],
            rsi_period   = rsi_period,
            include_vwap = True,
            include_stoch= True,
            include_signals = show_sigs,
        )
        # Trim to selected period after warm-up
        sym_ind = sym_ind.tail(days)

    last = sym_ind.iloc[-1]

    # ── KPI strip ─────────────────────────────────────────────────────────────
    rsi_val   = last.get(f"rsi_{rsi_period}", np.nan)
    macd_hist = last.get("macd_histogram", np.nan)
    bb_pct    = last.get("bb_pct_b", np.nan)
    atr_pct   = last.get("atr_14_pct", np.nan)
    sig_label = last.get("signal_label", "—")
    sig_score = last.get("signal_composite", 0)

    sig_color = {
        "Strong Buy": "🟢", "Buy": "🟩",
        "Neutral": "⬜",
        "Sell": "🟥", "Strong Sell": "🔴",
    }.get(sig_label, "⬜")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Close",        f"₹{last['close']:.2f}")
    c2.metric("RSI (14)",     f"{rsi_val:.1f}"   if not np.isnan(rsi_val)   else "—",
              delta="Oversold" if rsi_val < 30 else ("Overbought" if rsi_val > 70 else None))
    c3.metric("MACD Hist",    f"{macd_hist:.3f}" if not np.isnan(macd_hist) else "—",
              delta="Bullish" if macd_hist > 0 else "Bearish" if macd_hist < 0 else None)
    c4.metric("BB %B",        f"{bb_pct:.2f}"    if not np.isnan(bb_pct)    else "—",
              help="<0 = below lower band, >1 = above upper band")
    c5.metric("ATR %",        f"{atr_pct:.2f}%"  if not np.isnan(atr_pct)   else "—",
              help="Daily volatility as % of price")
    c6.metric(f"Signal {sig_color}", sig_label,
              delta=f"Score: {sig_score:+.0f}")

    st.markdown("---")

    # ── Main chart ─────────────────────────────────────────────────────────────
    fig = technical_chart(
        sym_ind,
        symbol      = selected_clean,
        show_volume = show_volume,
        show_bb     = show_bb,
        show_mas    = show_mas,
        show_signals= show_sigs,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── RSI gauge + indicator table side by side ───────────────────────────────
    st.markdown("---")
    col_gauge, col_table = st.columns([1, 2])

    with col_gauge:
        st.plotly_chart(rsi_gauge(rsi_val, selected_clean), use_container_width=True)

        # Stochastic
        stoch_k = last.get("stoch_k", np.nan)
        stoch_d = last.get("stoch_d", np.nan)
        if not np.isnan(stoch_k):
            st.metric("Stoch %K", f"{stoch_k:.1f}",
                      delta="Oversold" if stoch_k < 20 else ("Overbought" if stoch_k > 80 else None))
            st.metric("Stoch %D", f"{stoch_d:.1f}" if not np.isnan(stoch_d) else "—")

    with col_table:
        st.subheader("Indicator snapshot")
        indicator_rows = []

        # Moving averages
        for p in [20, 50, 200]:
            val = last.get(f"sma_{p}", np.nan)
            if not np.isnan(val):
                vs_price = ((last["close"] / val) - 1) * 100
                indicator_rows.append({
                    "Indicator": f"SMA {p}",
                    "Value":     f"₹{val:.2f}",
                    "vs Price":  f"{vs_price:+.2f}%",
                    "Signal":    "Above ↑" if last["close"] > val else "Below ↓",
                })

        # MACD
        if not np.isnan(macd_hist):
            indicator_rows.append({
                "Indicator": "MACD Histogram",
                "Value":     f"{macd_hist:.4f}",
                "vs Price":  "—",
                "Signal":    "Bullish" if macd_hist > 0 else "Bearish",
            })

        # Bollinger
        for col_name, label in [("bb_upper","BB Upper"), ("bb_lower","BB Lower")]:
            val = last.get(col_name, np.nan)
            if not np.isnan(val):
                indicator_rows.append({
                    "Indicator": label,
                    "Value":     f"₹{val:.2f}",
                    "vs Price":  f"{((last['close']/val)-1)*100:+.2f}%",
                    "Signal":    "—",
                })

        if indicator_rows:
            st.dataframe(
                pd.DataFrame(indicator_rows),
                use_container_width=True,
                hide_index=True,
            )

    # ── Raw indicator data ─────────────────────────────────────────────────────
    with st.expander("Raw indicator data (last 30 rows)"):
        disp_cols = ["date","close","rsi_14","macd_histogram","bb_pct_b",
                     "sma_20","sma_50","sma_200","atr_14_pct","signal_label"]
        available = [c for c in disp_cols if c in sym_ind.columns]
        st.dataframe(
            sym_ind[available].tail(30)
            .sort_values("date", ascending=False)
            .style.format({
                "close":"{:.2f}", "rsi_14":"{:.1f}",
                "macd_histogram":"{:.4f}", "bb_pct_b":"{:.3f}",
                "sma_20":"{:.2f}", "sma_50":"{:.2f}", "sma_200":"{:.2f}",
                "atr_14_pct":"{:.3f}",
            }, na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Universe signal scanner
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Signal Scanner — All NIFTY 100 Stocks")
    st.caption("Latest indicator snapshot for each stock. Refreshes with page cache (1hr).")

    col_s1, col_s2 = st.columns([2, 2])
    with col_s1:
        scan_filter = st.multiselect(
            "Filter by signal",
            options=["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"],
            default=["Strong Buy", "Buy"],
        )
    with col_s2:
        rsi_range = st.slider("RSI range filter", 0, 100, (0, 100), step=5)

    with st.spinner("Scanning all 100 stocks... (~20s on first load)"):
        symbols = universe["symbol"].tolist()
        scan_df = scan_universe(all_prices, symbols, lookback=300)

    if scan_df.empty:
        st.warning("No scan data. Check that price data is populated.")
        st.stop()

    # Merge sector info
    scan_df = scan_df.merge(
        universe[["symbol", "sector"]],
        on="symbol", how="left"
    )
    scan_df["sym_clean"] = scan_df["symbol"].str.replace(".NS", "", regex=False)

    # Apply filters
    filtered_scan = scan_df.copy()
    if scan_filter:
        filtered_scan = filtered_scan[filtered_scan["signal_label"].isin(scan_filter)]
    filtered_scan = filtered_scan[
        filtered_scan["rsi_14"].fillna(50).between(rsi_range[0], rsi_range[1])
    ]

    # KPI strip
    total = len(scan_df)
    strong_buys  = (scan_df["signal_label"] == "Strong Buy").sum()
    buys         = (scan_df["signal_label"] == "Buy").sum()
    sells        = (scan_df["signal_label"] == "Sell").sum()
    strong_sells = (scan_df["signal_label"] == "Strong Sell").sum()
    oversold     = (scan_df["rsi_14"].fillna(50) < 30).sum()
    overbought   = (scan_df["rsi_14"].fillna(50) > 70).sum()

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Strong Buy",  strong_buys,  delta=f"{strong_buys/total*100:.0f}%")
    c2.metric("Buy",         buys,         delta=f"{buys/total*100:.0f}%")
    c3.metric("Sell",        sells,        delta=f"{sells/total*100:.0f}%",  delta_color="inverse")
    c4.metric("Strong Sell", strong_sells, delta=f"{strong_sells/total*100:.0f}%", delta_color="inverse")
    c5.metric("RSI Oversold",  oversold,   help="RSI < 30")
    c6.metric("RSI Overbought",overbought, help="RSI > 70")

    st.markdown("---")

    # Signal score bar chart
    st.plotly_chart(signal_scan_bars(scan_df), use_container_width=True)

    st.markdown("---")

    # Detailed table
    st.subheader(f"Filtered results ({len(filtered_scan)} stocks)")
    if filtered_scan.empty:
        st.info("No stocks match current filters.")
    else:
        disp = filtered_scan[[
            "sym_clean", "sector", "close", "signal_label", "signal_composite",
            "rsi_14", "macd_histogram", "bb_pct_b", "atr_14_pct", "signal_ma_trend",
        ]].rename(columns={
            "sym_clean":        "Symbol",
            "sector":           "Sector",
            "close":            "Close ₹",
            "signal_label":     "Signal",
            "signal_composite": "Score",
            "rsi_14":           "RSI",
            "macd_histogram":   "MACD Hist",
            "bb_pct_b":         "BB %B",
            "atr_14_pct":       "ATR %",
            "signal_ma_trend":  "MA Trend",
        }).sort_values("Score", ascending=False)

        st.dataframe(
            disp.style
                .background_gradient(subset=["Score"], cmap="RdYlGn", vmin=-4, vmax=4)
                .background_gradient(subset=["RSI"],   cmap="RdYlGn", vmin=20, vmax=80)
                .format({
                    "Close ₹":  "{:.2f}",
                    "Score":    "{:+.0f}",
                    "RSI":      "{:.1f}",
                    "MACD Hist":"{:.4f}",
                    "BB %B":    "{:.3f}",
                    "ATR %":    "{:.2f}",
                }, na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )

        # Download
        csv = disp.to_csv(index=False)
        st.download_button(
            "⬇️ Download scan results",
            data=csv,
            file_name="nifty_signals_scan.csv",
            mime="text/csv",
        )