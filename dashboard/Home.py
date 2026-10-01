"""
dashboard/Home.py
Market overview — entry point of the Streamlit app.
Run with: streamlit run dashboard/Home.py
"""
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title  = "NIFTY Intel",
    page_icon   = "📈",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

from components.sidebar import apply_dark_theme, fmt_pct, delta_color
from components.data_loader import load_latest_prices, load_screener, load_sector_summary
from components.charts import gainers_losers, sector_heatmap, return_histogram, score_bars

apply_dark_theme()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📈 NIFTY Intel")
st.caption("NIFTY 100 — Daily Market Overview")

# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Loading market data..."):
    prices  = load_latest_prices()
    df      = load_screener()
    sectors = load_sector_summary(df)

if prices.empty or df.empty:
    st.error("No data found. Run the backfill first: `python scripts/run_ingestion.py backfill`")
    st.stop()

# ── Top KPI strip ─────────────────────────────────────────────────────────────
prices["change_pct"] = ((prices["close"] - prices.get("open", prices["close"])) /
                         prices.get("open", prices["close"]).replace(0, float("nan")) * 100)

total_stocks  = len(prices)
advancers     = (prices["change_pct"] > 0).sum()
decliners     = (prices["change_pct"] < 0).sum()
avg_composite = df["composite_score"].mean()
top_sector    = sectors.iloc[0]["sector"] if not sectors.empty else "—"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Stocks Tracked",  f"{total_stocks}")
c2.metric("Advancers",       f"{advancers}",
          delta=f"{advancers/total_stocks*100:.0f}%", delta_color="normal")
c3.metric("Decliners",       f"{decliners}",
          delta=f"{decliners/total_stocks*100:.0f}%", delta_color="inverse")
c4.metric("Avg Composite",   f"{avg_composite:.1f}")
c5.metric("Leading Sector",  top_sector)

st.markdown("---")

# ── Gainers / Losers ──────────────────────────────────────────────────────────
st.subheader("Today's Movers")

# Use latest_prices view — daily change based on open vs close
prices_today = prices.copy()
prices_today["open"] = prices_today.get("open", prices_today["close"])

fig_g, fig_l = gainers_losers(prices_today, top_n=7)
col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(fig_g, use_container_width=True)
with col2:
    st.plotly_chart(fig_l, use_container_width=True)

st.markdown("---")

# ── Sector Overview ───────────────────────────────────────────────────────────
st.subheader("Sector Strength")
st.plotly_chart(sector_heatmap(sectors), use_container_width=True)

# Sector table below chart
sector_display = sectors[[
    "sector", "stocks", "sector_strength", "avg_momentum",
    "avg_value", "median_return_1y"
]].rename(columns={
    "sector":          "Sector",
    "stocks":          "# Stocks",
    "sector_strength": "Strength",
    "avg_momentum":    "Avg Momentum",
    "avg_value":       "Avg Value",
    "median_return_1y":"Median 1Y Return %",
})
st.dataframe(
    sector_display.style
        .background_gradient(subset=["Strength"], cmap="RdYlGn", vmin=0, vmax=100)
        .background_gradient(subset=["Median 1Y Return %"], cmap="RdYlGn"),
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")

# ── Return distribution ───────────────────────────────────────────────────────
st.subheader("Universe Return Distribution")
col1, col2, col3 = st.columns(3)
with col1:
    st.plotly_chart(return_histogram(df, "return_3m", "3M Returns"),  use_container_width=True)
with col2:
    st.plotly_chart(return_histogram(df, "return_6m", "6M Returns"),  use_container_width=True)
with col3:
    st.plotly_chart(return_histogram(df, "return_1y", "1Y Returns"),  use_container_width=True)

st.markdown("---")

# ── Top composite picks preview ───────────────────────────────────────────────
st.subheader("Top 10 Composite Picks")
top10 = df.nlargest(10, "composite_score")[[
    "symbol", "sector", "composite_score",
    "value_score", "momentum_score", "sector_score",
    "pe_ratio", "return_1y",
]].copy()
top10["symbol"] = top10["symbol"].str.replace(".NS", "", regex=False)
top10 = top10.rename(columns={
    "composite_score": "Composite",
    "value_score":     "Value",
    "momentum_score":  "Momentum",
    "sector_score":    "Sector",
    "pe_ratio":        "PE",
    "return_1y":       "1Y Return %",
})
st.dataframe(
    top10.style
        .background_gradient(subset=["Composite"], cmap="RdYlGn", vmin=0, vmax=100)
        .format({"Composite": "{:.1f}", "Value": "{:.1f}", "Momentum": "{:.1f}",
                 "Sector": "{:.1f}", "PE": "{:.1f}", "1Y Return %": "{:.1f}"}),
    use_container_width=True,
    hide_index=True,
)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Data refreshes every hour. Prices from yfinance · Fundamentals from Screener.in · Events from BSE")
