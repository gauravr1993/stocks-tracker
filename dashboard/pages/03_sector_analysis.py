"""
dashboard/pages/03_sector_analysis.py
Sector deep dive — strength ranking, top stocks per sector, return heatmap.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Sectors · NIFTY Intel", page_icon="🏭", layout="wide")

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from components.sidebar import apply_dark_theme
from components.data_loader import load_screener, load_sector_summary
from components.charts import sector_heatmap, score_bars, THEME

apply_dark_theme()

st.title("🏭 Sector Analysis")

with st.spinner("Loading..."):
    df      = load_screener()
    sectors = load_sector_summary(df)

# ── Sector strength ranking ───────────────────────────────────────────────────
st.subheader("Sector Leaderboard")
st.plotly_chart(sector_heatmap(sectors), use_container_width=True)

# ── Sector metrics table ──────────────────────────────────────────────────────
st.dataframe(
    sectors.rename(columns={
        "sector":           "Sector",
        "stocks":           "# Stocks",
        "avg_composite":    "Avg Composite",
        "avg_value":        "Avg Value",
        "avg_momentum":     "Avg Momentum",
        "sector_strength":  "Strength",
        "median_pe":        "Median PE",
        "median_return_1y": "Median 1Y Return %",
    }).style
        .background_gradient(subset=["Strength"],          cmap="RdYlGn", vmin=0,   vmax=100)
        .background_gradient(subset=["Avg Composite"],     cmap="RdYlGn", vmin=0,   vmax=100)
        .background_gradient(subset=["Median 1Y Return %"],cmap="RdYlGn", vmin=-30, vmax=50)
        .format({
            "Avg Composite": "{:.1f}", "Avg Value": "{:.1f}",
            "Avg Momentum":  "{:.1f}", "Strength":  "{:.1f}",
            "Median PE":     "{:.1f}", "Median 1Y Return %": "{:.1f}",
        }, na_rep="—"),
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")

# ── Sector deep dive ──────────────────────────────────────────────────────────
st.subheader("Sector Deep Dive")
selected_sector = st.selectbox(
    "Select sector",
    options=sectors["sector"].tolist(),
    index=0,
)

sector_stocks = df[df["sector"] == selected_sector].copy()
sector_stocks["symbol"] = sector_stocks["symbol"].str.replace(".NS", "", regex=False)
sector_stocks = sector_stocks.sort_values("composite_score", ascending=False)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Stocks in sector",  len(sector_stocks))
col2.metric("Avg Composite",     f"{sector_stocks['composite_score'].mean():.1f}")
col3.metric("Avg 1Y Return",     f"{sector_stocks['return_1y'].mean():.1f}%")
col4.metric("Sector Strength",
            f"{sectors[sectors['sector']==selected_sector]['sector_strength'].values[0]:.1f}"
            if selected_sector in sectors["sector"].values else "—")

st.markdown("---")

# Bubble chart: value vs momentum coloured by composite
fig_bubble = px.scatter(
    sector_stocks.dropna(subset=["value_score","momentum_score"]),
    x="value_score",
    y="momentum_score",
    size="composite_score",
    color="composite_score",
    color_continuous_scale="RdYlGn",
    hover_name="symbol",
    hover_data={"pe_ratio": True, "return_1y": True, "composite_score": True},
    labels={"value_score": "Value Score", "momentum_score": "Momentum Score",
            "composite_score": "Composite"},
    title=f"{selected_sector} — Value vs Momentum",
    range_x=[0, 100], range_y=[0, 100],
)
fig_bubble.update_layout(
    paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
    font=dict(color=THEME["text"]), height=420,
)
fig_bubble.add_hline(y=50, line_dash="dash", line_color=THEME["border"], opacity=0.5)
fig_bubble.add_vline(x=50, line_dash="dash", line_color=THEME["border"], opacity=0.5)
st.plotly_chart(fig_bubble, use_container_width=True)

# Stocks table for selected sector
display_cols = ["symbol", "composite_score", "value_score", "momentum_score",
                "sector_score", "pe_ratio", "return_3m", "return_6m", "return_1y"]
available = [c for c in display_cols if c in sector_stocks.columns]

st.dataframe(
    sector_stocks[available].style
        .background_gradient(subset=["composite_score"], cmap="RdYlGn", vmin=0, vmax=100)
        .format({c: "{:.1f}" for c in ["composite_score","value_score","momentum_score",
                 "sector_score","pe_ratio","return_3m","return_6m","return_1y"]
                 if c in sector_stocks.columns}, na_rep="—"),
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")

# ── Return heatmap across all sectors ────────────────────────────────────────
st.subheader("Return Heatmap — All Sectors")

pivot_data = []
for _, sec_row in sectors.iterrows():
    sec = sec_row["sector"]
    sec_df = df[df["sector"] == sec]
    pivot_data.append({
        "Sector": sec,
        "3M":  sec_df["return_3m"].median(),
        "6M":  sec_df["return_6m"].median(),
        "1Y":  sec_df["return_1y"].median(),
    })

heat_df = pd.DataFrame(pivot_data).set_index("Sector")
fig_heat = go.Figure(go.Heatmap(
    z=heat_df.values,
    x=heat_df.columns.tolist(),
    y=heat_df.index.tolist(),
    colorscale="RdYlGn",
    zmid=0,
    text=[[f"{v:.1f}%" for v in row] for row in heat_df.values],
    texttemplate="%{text}",
    textfont=dict(size=11),
    hovertemplate="<b>%{y}</b><br>%{x}: %{z:.1f}%<extra></extra>",
))
fig_heat.update_layout(
    paper_bgcolor=THEME["bg"], font=dict(color=THEME["text"]),
    height=max(400, len(heat_df) * 28),
    margin=dict(l=160, r=20, t=30, b=40),
    xaxis=dict(side="top"),
)
st.plotly_chart(fig_heat, use_container_width=True)
