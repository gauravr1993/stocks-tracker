"""
dashboard/pages/02_stock_deep_dive.py
Single stock deep dive — price + technical indicators, fundamentals, scores, events.
"""
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Deep Dive · NIFTY Intel", page_icon="🔭", layout="wide")

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "config", ".env"
))

from components.sidebar      import apply_dark_theme, fmt_ratio, fmt_pct, fmt_cr
from components.data_loader  import load_screener, load_price_history, load_events, load_fundamentals
from components.charts       import score_radar, THEME
from analysis.signals.indicators import add_all_indicators
from analysis.signals.charts     import technical_chart, rsi_gauge

apply_dark_theme()

st.title("🔭 Stock Deep Dive")

# ── Stock selector ─────────────────────────────────────────────────────────────
with st.spinner("Loading universe..."):
    df = load_screener()

symbols   = sorted(df["symbol"].dropna().tolist())
sym_clean = {s.replace(".NS", ""): s for s in symbols}

col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
with col1:
    selected_clean = st.selectbox(
        "Select stock", options=list(sym_clean.keys()), index=0,
    )
with col2:
    years = st.select_slider("History", options=[1, 2, 3, 5, 10], value=2)
with col3:
    show_events = st.checkbox("Event overlays", value=True)
with col4:
    show_signals = st.checkbox("Buy/sell signals", value=True)

symbol = sym_clean[selected_clean]
row    = df[df["symbol"] == symbol].iloc[0] if not df[df["symbol"] == symbol].empty else pd.Series()

# ── Load data ──────────────────────────────────────────────────────────────────
with st.spinner(f"Loading {selected_clean}..."):
    prices = load_price_history(symbol, years=max(years, 2))   # extra buffer for indicators
    events = load_events(symbol, years=years) if show_events else pd.DataFrame()
    fundam = load_fundamentals(symbol)

if prices.empty:
    st.error(f"No price data found for {symbol}")
    st.stop()

# ── Compute indicators ─────────────────────────────────────────────────────────
with st.spinner("Computing indicators..."):
    prices_ind = add_all_indicators(
        prices,
        sma_periods    = [20, 50, 200],
        ema_periods    = [9, 21],
        include_signals= show_signals,
    )
    # Trim to selected history after warm-up
    from datetime import date, timedelta
    cutoff = pd.Timestamp(date.today() - timedelta(days=365 * years))
    prices_ind = prices_ind[prices_ind["date"] >= cutoff]

last = prices_ind.iloc[-1]

# ── Score + price KPI strip ───────────────────────────────────────────────────
composite  = row.get("composite_score") if isinstance(row, pd.Series) else None
value_s    = row.get("value_score")     if isinstance(row, pd.Series) else None
momentum_s = row.get("momentum_score")  if isinstance(row, pd.Series) else None
sector_s   = row.get("sector_score")    if isinstance(row, pd.Series) else None
sector     = row.get("sector", "—")     if isinstance(row, pd.Series) else "—"
rsi_val    = last.get("rsi_14",   np.nan)
sig_label  = last.get("signal_label", "—")
sig_score  = last.get("signal_composite", 0)

sig_emoji = {
    "Strong Buy": "🟢", "Buy": "🟩", "Neutral": "⬜",
    "Sell": "🟥", "Strong Sell": "🔴",
}.get(sig_label, "⬜")

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Sector",       str(sector))
c2.metric("Composite",    f"{composite:.1f}" if pd.notna(composite) else "—")
c3.metric("Value",        f"{value_s:.1f}"   if pd.notna(value_s)   else "—")
c4.metric("Momentum",     f"{momentum_s:.1f}"if pd.notna(momentum_s) else "—")
c5.metric("RSI (14)",     f"{rsi_val:.1f}"   if not np.isnan(rsi_val) else "—",
          delta="OS" if rsi_val < 30 else ("OB" if rsi_val > 70 else None))
c6.metric("Signal",       f"{sig_emoji} {sig_label}",
          delta=f"{sig_score:+.0f}")
c7.metric("Close",        f"₹{last['close']:.2f}")

st.markdown("---")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📈 Technical Chart", "📊 Fundamentals & Scores", "📰 Events"])

# ══ TAB 1 — Technical chart ═══════════════════════════════════════════════════
with tab1:
    # Indicator toggles
    with st.expander("Chart settings", expanded=False):
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            show_bb     = st.checkbox("Bollinger Bands", value=True)
            show_volume = st.checkbox("Volume",          value=True)
        with ec2:
            ma_20  = st.checkbox("SMA 20",  value=True)
            ma_50  = st.checkbox("SMA 50",  value=True)
            ma_200 = st.checkbox("SMA 200", value=True)
        with ec3:
            show_macd = st.checkbox("MACD panel",  value=True)
            show_rsi  = st.checkbox("RSI panel",   value=True)

    show_mas = [p for p, chk in [(20, ma_20), (50, ma_50), (200, ma_200)] if chk]

    fig = technical_chart(
        prices_ind,
        symbol      = selected_clean,
        show_volume = show_volume,
        show_bb     = show_bb,
        show_mas    = show_mas,
        show_signals= show_signals,
    )
    st.plotly_chart(fig, use_container_width=True)

    if show_events and not events.empty:
        st.caption(
            f"{len(events)} events overlaid — "
            + " · ".join(f"{cat}: {cnt}"
                         for cat, cnt in events["category"].value_counts().items())
        )

    # ── RSI gauge + latest indicator snapshot ─────────────────────────────────
    st.markdown("---")
    col_gauge, col_snap = st.columns([1, 2])

    with col_gauge:
        st.plotly_chart(rsi_gauge(rsi_val, selected_clean), use_container_width=True)

        stoch_k = last.get("stoch_k", np.nan)
        stoch_d = last.get("stoch_d", np.nan)
        if not np.isnan(stoch_k):
            sk1, sk2 = st.columns(2)
            sk1.metric("Stoch %K", f"{stoch_k:.1f}",
                       delta="OS" if stoch_k < 20 else ("OB" if stoch_k > 80 else None))
            sk2.metric("Stoch %D", f"{stoch_d:.1f}" if not np.isnan(stoch_d) else "—")

    with col_snap:
        st.subheader("Indicator snapshot")
        snap_rows = []

        for p in [20, 50, 200]:
            val = last.get(f"sma_{p}", np.nan)
            if not np.isnan(val):
                snap_rows.append({
                    "Indicator": f"SMA {p}",
                    "Value":     f"₹{val:.2f}",
                    "vs Price":  f"{((last['close']/val)-1)*100:+.2f}%",
                    "Signal":    "Above ↑" if last["close"] > val else "Below ↓",
                })

        macd_h = last.get("macd_histogram", np.nan)
        if not np.isnan(macd_h):
            snap_rows.append({
                "Indicator": "MACD Histogram",
                "Value":     f"{macd_h:.4f}",
                "vs Price":  "—",
                "Signal":    "Bullish" if macd_h > 0 else "Bearish",
            })

        bb_pct = last.get("bb_pct_b", np.nan)
        atr    = last.get("atr_14_pct", np.nan)
        if not np.isnan(bb_pct):
            snap_rows.append({
                "Indicator": "BB %B",
                "Value":     f"{bb_pct:.3f}",
                "vs Price":  "—",
                "Signal":    "Below lower" if bb_pct < 0 else ("Above upper" if bb_pct > 1 else "Within bands"),
            })
        if not np.isnan(atr):
            snap_rows.append({
                "Indicator": "ATR %",
                "Value":     f"{atr:.2f}%",
                "vs Price":  "—",
                "Signal":    "High vol" if atr > 2.5 else "Normal vol",
            })

        if snap_rows:
            st.dataframe(
                pd.DataFrame(snap_rows),
                use_container_width=True, hide_index=True,
            )

    # Raw data expander
    with st.expander("Raw indicator data (last 30 rows)"):
        disp_cols = ["date","close","rsi_14","macd_histogram","bb_pct_b",
                     "sma_20","sma_50","sma_200","atr_14_pct","signal_label"]
        available = [c for c in disp_cols if c in prices_ind.columns]
        st.dataframe(
            prices_ind[available].tail(30).sort_values("date", ascending=False)
            .style.format({
                "close":"{:.2f}","rsi_14":"{:.1f}",
                "macd_histogram":"{:.4f}","bb_pct_b":"{:.3f}",
                "sma_20":"{:.2f}","sma_50":"{:.2f}","sma_200":"{:.2f}",
                "atr_14_pct":"{:.3f}",
            }, na_rep="—"),
            use_container_width=True, hide_index=True,
        )

# ══ TAB 2 — Fundamentals & scores ═════════════════════════════════════════════
with tab2:
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.subheader("Fundamentals")
        f1, f2, f3 = st.columns(3)
        f1.metric("PE Ratio",   fmt_ratio(fundam.get("pe_ratio")))
        f2.metric("PB Ratio",   fmt_ratio(fundam.get("pb_ratio")))
        f3.metric("PS Ratio",   fmt_ratio(fundam.get("ps_ratio")))

        f4, f5, f6 = st.columns(3)
        f4.metric("Market Cap", fmt_cr(fundam.get("market_cap")))
        f5.metric("ROE",        fmt_pct(fundam.get("roe")))
        f6.metric("Debt/Eq",    fmt_ratio(fundam.get("debt_to_equity")))

        st.markdown("---")
        st.subheader("Price Returns")
        ret_3m = row.get("return_3m") if isinstance(row, pd.Series) else None
        ret_6m = row.get("return_6m") if isinstance(row, pd.Series) else None
        ret_1y = row.get("return_1y") if isinstance(row, pd.Series) else None

        r1, r2, r3 = st.columns(3)
        r1.metric("3M Return", fmt_pct(ret_3m), delta=fmt_pct(ret_3m) if ret_3m else None)
        r2.metric("6M Return", fmt_pct(ret_6m), delta=fmt_pct(ret_6m) if ret_6m else None)
        r3.metric("1Y Return", fmt_pct(ret_1y), delta=fmt_pct(ret_1y) if ret_1y else None)

        st.markdown("---")
        st.subheader("Screener Scores")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Composite", f"{composite:.1f}"  if pd.notna(composite)  else "—")
        s2.metric("Value",     f"{value_s:.1f}"    if pd.notna(value_s)    else "—")
        s3.metric("Momentum",  f"{momentum_s:.1f}" if pd.notna(momentum_s) else "—")
        s4.metric("Sector",    f"{sector_s:.1f}"   if pd.notna(sector_s)   else "—")

        conf = row.get("score_confidence", None) if isinstance(row, pd.Series) else None
        if conf:
            st.progress(float(conf), text=f"Score confidence: {conf*100:.0f}%")

    with col_right:
        if isinstance(row, pd.Series):
            st.plotly_chart(score_radar(row, selected_clean), use_container_width=True)

# ══ TAB 3 — Events ════════════════════════════════════════════════════════════
with tab3:
    st.subheader("News & Corporate Events")
    if events.empty:
        st.info("No events found for this stock in the selected period.")
    else:
        cat_filter = st.multiselect(
            "Filter by category",
            options=events["category"].dropna().unique().tolist(),
            default=events["category"].dropna().unique().tolist(),
        )
        filtered_events = (
            events[events["category"].isin(cat_filter)]
            .copy()
            .sort_values("event_date", ascending=False)
        )
        filtered_events["event_date"] = filtered_events["event_date"].dt.strftime("%Y-%m-%d")

        st.dataframe(
            filtered_events[["event_date","category","headline","source"]]
            .rename(columns={
                "event_date":"Date","category":"Category",
                "headline":"Headline","source":"Source",
            }),
            use_container_width=True, hide_index=True,
        )