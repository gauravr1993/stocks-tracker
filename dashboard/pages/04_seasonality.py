"""
dashboard/pages/04_seasonality.py
Seasonality explorer — monthly, day-of-week, and quarterly patterns
for individual stocks and the full NIFTY 100 universe.
"""
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(
    page_title = "Seasonality · NIFTY Intel",
    page_icon  = "📅",
    layout     = "wide",
)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "config", ".env"))

from components.sidebar import apply_dark_theme
from analysis.seasonality.data_loader import load_all_prices, load_universe, compute_universe_heatmap
from analysis.seasonality.patterns    import (
    monthly_patterns, dow_patterns, quarterly_patterns, best_worst_months,
)
from analysis.seasonality.charts import (
    monthly_bar, dow_bar, quarterly_bar,
    yearly_monthly_heatmap, universe_heatmap, consistency_chart,
)

apply_dark_theme()

st.title("📅 Seasonality Explorer")
st.caption("Historical return patterns across months, weekdays, and quarters — NIFTY 100, 10yr data")

# ── Load base data ────────────────────────────────────────────────────────────
with st.spinner("Loading price history..."):
    all_prices = load_all_prices()
    universe   = load_universe()

if all_prices.empty:
    st.error("No price data found. Run the backfill first.")
    st.stop()

symbols_list = sorted(universe["symbol"].dropna().tolist())
sym_clean    = {s.replace(".NS", ""): s for s in symbols_list}

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "📊 Stock Patterns",
    "🌡️ Universe Heatmap",
    "🏭 Sector Heatmap",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Single stock seasonality
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
    with col_ctrl1:
        selected_clean = st.selectbox(
            "Select stock",
            options=list(sym_clean.keys()),
            index=list(sym_clean.keys()).index("RELIANCE") if "RELIANCE" in sym_clean else 0,
        )
    with col_ctrl2:
        years_filter = st.select_slider(
            "History (years)",
            options=[3, 5, 7, 10],
            value=10,
        )
    with col_ctrl3:
        show_significance = st.checkbox("Highlight significant months", value=True)

    symbol     = sym_clean[selected_clean]
    sym_prices = all_prices[all_prices["symbol"] == symbol].copy()

    # Filter to selected years
    from datetime import date, timedelta
    cutoff = pd.Timestamp(date.today() - timedelta(days=365 * years_filter))
    sym_prices = sym_prices[sym_prices["date"] >= cutoff]

    if len(sym_prices) < 60:
        st.warning(f"Not enough data for {selected_clean} — need at least 3 months.")
        st.stop()

    # Compute patterns
    monthly_df    = monthly_patterns(sym_prices, selected_clean)
    dow_df        = dow_patterns(sym_prices, selected_clean)
    quarterly_df  = quarterly_patterns(sym_prices, selected_clean)
    bw            = best_worst_months(monthly_df)

    # ── KPI strip ─────────────────────────────────────────────────────────────
    data_years = round((sym_prices["date"].max() - sym_prices["date"].min()).days / 365, 1)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Data span",      f"{data_years} years")
    c2.metric("Best month",     bw.get("best_month",  "—"),
              delta=f"{bw.get('best_return', 0):.2f}%")
    c3.metric("Worst month",    bw.get("worst_month", "—"),
              delta=f"{bw.get('worst_return', 0):.2f}%",
              delta_color="inverse")
    c4.metric("Best win rate",  f"{bw.get('best_winrate',  0):.0f}%",
              help=f"In {bw.get('best_month','')}")
    c5.metric("Worst win rate", f"{bw.get('worst_winrate', 0):.0f}%",
              help=f"In {bw.get('worst_month','')}")

    st.markdown("---")

    # ── Monthly patterns ───────────────────────────────────────────────────────
    st.subheader("Monthly Return Patterns")
    st.caption("* = statistically significant (p < 0.10) · Yellow line = win rate %")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.plotly_chart(monthly_bar(monthly_df, selected_clean), use_container_width=True)
    with col2:
        st.plotly_chart(consistency_chart(monthly_df, selected_clean), use_container_width=True)

    # Monthly stats table
    with st.expander("Monthly stats table"):
        display = monthly_df[[
            "month_name", "mean_return", "median_return",
            "win_rate", "std", "p_value", "n_years", "is_significant"
        ]].rename(columns={
            "month_name":    "Month",
            "mean_return":   "Avg Return %",
            "median_return": "Median Return %",
            "win_rate":      "Win Rate %",
            "std":           "Std Dev",
            "p_value":       "p-value",
            "n_years":       "Years",
            "is_significant":"Significant",
        })
        st.dataframe(
            display.style
                .background_gradient(subset=["Avg Return %"], cmap="RdYlGn")
                .background_gradient(subset=["Win Rate %"],   cmap="RdYlGn", vmin=30, vmax=70)
                .format({"Avg Return %": "{:.2f}", "Median Return %": "{:.2f}",
                         "Win Rate %": "{:.1f}",   "Std Dev": "{:.2f}",
                         "p-value": "{:.4f}"},     na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")

    # ── Year-by-year heatmap ───────────────────────────────────────────────────
    st.subheader("Year × Month Heatmap")
    st.caption("Actual return for each month/year — shows consistency of seasonal patterns")
    st.plotly_chart(
        yearly_monthly_heatmap(sym_prices, selected_clean),
        use_container_width=True,
    )

    st.markdown("---")

    # ── Day-of-week + Quarterly side by side ──────────────────────────────────
    st.subheader("Day-of-Week & Quarterly Patterns")
    col_dow, col_q = st.columns(2)
    with col_dow:
        st.plotly_chart(dow_bar(dow_df, selected_clean), use_container_width=True)
        with st.expander("Day-of-week stats"):
            st.dataframe(
                dow_df[["dow_name","mean_return","win_rate","n","p_value"]]
                .rename(columns={"dow_name":"Day","mean_return":"Avg Return %",
                                  "win_rate":"Win Rate %","n":"N Days","p_value":"p-value"})
                .style.background_gradient(subset=["Avg Return %"], cmap="RdYlGn")
                .format({"Avg Return %":"{:.3f}","Win Rate %":"{:.1f}","p-value":"{:.4f}"}),
                hide_index=True,
            )
    with col_q:
        st.plotly_chart(quarterly_bar(quarterly_df, selected_clean), use_container_width=True)
        with st.expander("Quarterly stats"):
            st.dataframe(
                quarterly_df[["quarter_name","mean_return","win_rate","n","p_value"]]
                .rename(columns={"quarter_name":"Quarter","mean_return":"Avg Return %",
                                  "win_rate":"Win Rate %","n":"N Months","p_value":"p-value"})
                .style.background_gradient(subset=["Avg Return %"], cmap="RdYlGn")
                .format({"Avg Return %":"{:.2f}","Win Rate %":"{:.1f}","p-value":"{:.4f}"}),
                hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Universe heatmap (all 100 stocks × 12 months)
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("NIFTY 100 — Monthly Return Heatmap")
    st.caption("Average monthly return per stock across full history. Rows sorted by best overall avg return.")

    with st.spinner("Computing universe heatmap — this takes ~10s on first load..."):
        matrix = compute_universe_heatmap("symbol")

    if matrix.empty:
        st.warning("Not enough data to build universe heatmap.")
    else:
        # Sort rows by mean return across all months
        matrix["_avg"] = matrix.mean(axis=1)
        matrix = matrix.sort_values("_avg", ascending=False).drop(columns="_avg")

        # Filter controls
        col_f1, col_f2 = st.columns([2, 2])
        with col_f1:
            top_n = st.slider("Show top N stocks by avg return", 10, 100, 50, step=10)
        with col_f2:
            sector_filter = st.multiselect(
                "Filter by sector",
                options=universe["sector"].dropna().unique().tolist(),
                default=[],
                placeholder="All sectors",
            )

        display_matrix = matrix.head(top_n)

        # Apply sector filter
        if sector_filter:
            sector_symbols = set(
                universe[universe["sector"].isin(sector_filter)]["symbol"]
                .str.replace(".NS", "", regex=False)
            )
            display_matrix = display_matrix[
                display_matrix.index.isin(sector_symbols)
            ]

        st.plotly_chart(
            universe_heatmap(display_matrix, f"NIFTY 100 — Monthly Returns (Top {len(display_matrix)} stocks)"),
            use_container_width=True,
        )

        # Best month per stock summary
        with st.expander("Best & worst month per stock"):
            rows = []
            for sym in display_matrix.index:
                row_vals = display_matrix.loc[sym].dropna()
                if row_vals.empty:
                    continue
                rows.append({
                    "Symbol":        sym,
                    "Best Month":    row_vals.idxmax(),
                    "Best Return %": row_vals.max(),
                    "Worst Month":   row_vals.idxmin(),
                    "Worst Return %":row_vals.min(),
                    "Avg Return %":  row_vals.mean(),
                })
            summary_df = pd.DataFrame(rows).sort_values("Avg Return %", ascending=False)
            st.dataframe(
                summary_df.style
                    .background_gradient(subset=["Best Return %"],  cmap="Greens")
                    .background_gradient(subset=["Worst Return %"], cmap="Reds_r")
                    .format({c: "{:.2f}" for c in ["Best Return %","Worst Return %","Avg Return %"]}),
                use_container_width=True,
                hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Sector heatmap
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Sector × Month Heatmap")
    st.caption("Median monthly return per sector — useful for identifying macro-level seasonal patterns.")

    with st.spinner("Computing sector heatmap..."):
        sector_matrix = compute_universe_heatmap("sector")

    if sector_matrix.empty:
        st.warning("Not enough data to build sector heatmap.")
    else:
        sector_matrix["_avg"] = sector_matrix.mean(axis=1)
        sector_matrix = sector_matrix.sort_values("_avg", ascending=False).drop(columns="_avg")

        st.plotly_chart(
            universe_heatmap(sector_matrix, "Sector × Month — Median Monthly Returns", height=520),
            use_container_width=True,
        )

        st.markdown("---")
        st.subheader("Seasonal insight summary")

        # Auto-generate plain-English insights
        insights = []
        for sector in sector_matrix.index:
            row = sector_matrix.loc[sector].dropna()
            if len(row) < 6:
                continue
            best_m  = row.idxmax()
            worst_m = row.idxmin()
            avg     = row.mean()
            if row[best_m] > 2.0:
                insights.append(
                    f"**{sector}** historically performs best in **{best_m}** "
                    f"(avg {row[best_m]:.1f}%) and worst in **{worst_m}** "
                    f"(avg {row[worst_m]:.1f}%)."
                )

        if insights:
            for insight in insights:
                st.markdown(f"- {insight}")
        else:
            st.info("No strong seasonal patterns detected across sectors.")

        with st.expander("Full sector monthly stats table"):
            st.dataframe(
                sector_matrix.style
                    .background_gradient(cmap="RdYlGn", axis=None)
                    .format("{:.2f}", na_rep="—"),
                use_container_width=True,
            )