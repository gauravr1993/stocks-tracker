"""
dashboard/pages/01_screener.py
Enhanced screener — value, momentum, sector scores with filters.
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Screener · NIFTY Intel", page_icon="🔎", layout="wide")

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from components.sidebar import apply_dark_theme, sidebar_filters, apply_filters, score_badge, fmt_ratio, fmt_pct
from components.data_loader import load_screener
from components.charts import score_bars, THEME

apply_dark_theme()

st.title("🔎 Stock Screener")
st.caption("NIFTY 100 — Value · Momentum · Sector scoring")

with st.spinner("Running screener..."):
    df = load_screener()

filters = sidebar_filters(df)

# Mode selector in sidebar
st.sidebar.markdown("---")
st.sidebar.markdown("### Score mode")
mode = st.sidebar.radio(
    "Weight profile",
    options=["balanced", "value", "momentum"],
    format_func=lambda x: {"balanced": "⚖️ Balanced", "value": "💰 Value-tilted", "momentum": "🚀 Momentum-tilted"}[x],
)

top_n = st.sidebar.slider("Top N picks", 5, 50, 10, step=5)

st.sidebar.markdown("---")
min_conf = st.sidebar.select_slider(
    "Min score confidence",
    options=[0.33, 0.67, 1.0],
    value=0.67,
    format_func=lambda x: {0.33: "1 of 3 dims", 0.67: "2 of 3 dims", 1.0: "All 3 dims"}[x],
)

# ── Apply filters + get picks ─────────────────────────────────────────────────
filtered = apply_filters(df, filters)

from analysis.screener.composite import score_composite, get_top_picks, BALANCED, VALUE_TILTED, MOMENTUM_TILTED
weight_map = {"balanced": BALANCED, "value": VALUE_TILTED, "momentum": MOMENTUM_TILTED}
scored  = score_composite(filtered, weights=weight_map[mode])
picks   = get_top_picks(scored, n=top_n, mode=mode, min_confidence=min_conf, exclude_sectors=["Unknown"])

# ── KPI strip ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Universe",     f"{len(df)} stocks")
c2.metric("After filters",f"{len(filtered)} stocks")
c3.metric("Showing",      f"Top {len(picks)}")
c4.metric("Mode",         mode.capitalize())

st.markdown("---")

# ── Tabs: picks table / score charts ─────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Picks Table", "📊 Score Charts", "🔬 Full Universe"])

with tab1:
    if picks.empty:
        st.warning("No stocks match the current filters. Try relaxing the thresholds.")
    else:
        # Format display
        display = picks.copy()
        display["symbol"] = display["symbol"].str.replace(".NS", "", regex=False)

        # Colour-coded score columns
        st.dataframe(
            display.style
                .background_gradient(subset=["composite_score"], cmap="RdYlGn", vmin=0, vmax=100)
                .background_gradient(subset=["value_score"],     cmap="RdYlGn", vmin=0, vmax=100)
                .background_gradient(subset=["momentum_score"],  cmap="RdYlGn", vmin=0, vmax=100)
                .background_gradient(subset=["sector_score"],    cmap="RdYlGn", vmin=0, vmax=100)
                .format({
                    "composite_score": "{:.1f}", "value_score":    "{:.1f}",
                    "momentum_score":  "{:.1f}", "sector_score":   "{:.1f}",
                    "pe_ratio":        "{:.1f}", "pb_ratio":       "{:.1f}",
                    "return_3m":       "{:.1f}", "return_6m":      "{:.1f}",
                    "return_1y":       "{:.1f}", "score_confidence":"{:.0%}",
                }, na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )

        # Download button
        csv = picks.to_csv(index=False)
        st.download_button(
            "⬇️ Download picks as CSV",
            data=csv,
            file_name=f"nifty_picks_{mode}.csv",
            mime="text/csv",
        )

with tab2:
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            score_bars(scored, "composite_score", top_n, f"Top {top_n} — Composite ({mode})"),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(
            score_bars(scored, "momentum_score",  top_n, f"Top {top_n} — Momentum"),
            use_container_width=True,
        )
    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            score_bars(scored, "value_score",     top_n, f"Top {top_n} — Value"),
            use_container_width=True,
        )
    with col4:
        st.plotly_chart(
            score_bars(scored, "sector_score",    top_n, f"Top {top_n} — Sector"),
            use_container_width=True,
        )

with tab3:
    # Full sortable universe table
    cols = ["symbol", "name", "sector",
            "composite_score", "value_score", "momentum_score", "sector_score",
            "pe_ratio", "pb_ratio", "return_3m", "return_6m", "return_1y",
            "score_confidence"]
    available = [c for c in cols if c in filtered.columns]
    full = filtered[available].copy()
    full["symbol"] = full["symbol"].str.replace(".NS", "", regex=False)
    full = full.sort_values("composite_score", ascending=False).reset_index(drop=True)

    st.dataframe(
        full.style
            .background_gradient(subset=["composite_score"], cmap="RdYlGn", vmin=0, vmax=100)
            .format({c: "{:.1f}" for c in ["composite_score","value_score",
                    "momentum_score","sector_score","pe_ratio","pb_ratio",
                    "return_3m","return_6m","return_1y"] if c in full.columns},
                    na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )
