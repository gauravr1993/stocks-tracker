"""
dashboard/components/sidebar.py
Shared sidebar filters and metric card helpers.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd


def apply_dark_theme():
    """Inject custom CSS for dark theme and card styling."""
    st.markdown("""
    <style>
    /* Dark background */
    .stApp { background-color: #0f1117; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background-color: #1a1d27;
        border: 1px solid #2a2d3e;
        border-radius: 10px;
        padding: 12px 16px;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #12141f;
        border-right: 1px solid #2a2d3e;
    }

    /* Dataframe */
    [data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { background-color: #1a1d27; border-radius: 8px; }
    .stTabs [data-baseweb="tab"] { color: #888; }
    .stTabs [aria-selected="true"] { color: #e0e0e0; }

    /* Headers */
    h1, h2, h3 { color: #e0e0e0 !important; }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 13px;
    }
    .score-high   { background: rgba(0,196,140,0.15); color: #00c48c; }
    .score-medium { background: rgba(76,155,232,0.15); color: #4c9be8; }
    .score-low    { background: rgba(255,77,109,0.15); color: #ff4d6d; }
    </style>
    """, unsafe_allow_html=True)


def score_badge(score: float) -> str:
    """Return HTML badge for a score value."""
    if score >= 60:
        cls, label = "score-high",   f"↑ {score:.0f}"
    elif score >= 35:
        cls, label = "score-medium", f"→ {score:.0f}"
    else:
        cls, label = "score-low",    f"↓ {score:.0f}"
    return f'<span class="score-badge {cls}">{label}</span>'


def sidebar_filters(df: pd.DataFrame) -> dict:
    """
    Render sidebar filters and return a dict of selected values.
    Applies to screener and overview pages.
    """
    st.sidebar.markdown("## 🔍 Filters")

    sectors = sorted(df["sector"].dropna().unique().tolist())
    selected_sectors = st.sidebar.multiselect(
        "Sectors",
        options=sectors,
        default=[],
        placeholder="All sectors",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Score thresholds")

    min_composite = st.sidebar.slider("Min composite score", 0, 100, 0, step=5)
    min_value      = st.sidebar.slider("Min value score",     0, 100, 0, step=5)
    min_momentum   = st.sidebar.slider("Min momentum score",  0, 100, 0, step=5)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Valuation")
    max_pe = st.sidebar.slider("Max PE ratio", 0, 150, 150, step=5)

    return dict(
        sectors        = selected_sectors,
        min_composite  = min_composite,
        min_value      = min_value,
        min_momentum   = min_momentum,
        max_pe         = max_pe,
    )


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Apply sidebar filters to a DataFrame."""
    out = df.copy()

    if filters["sectors"]:
        out = out[out["sector"].isin(filters["sectors"])]

    out = out[out["composite_score"].fillna(0) >= filters["min_composite"]]
    out = out[out["value_score"].fillna(0)      >= filters["min_value"]]
    out = out[out["momentum_score"].fillna(0)   >= filters["min_momentum"]]

    if filters["max_pe"] < 150:
        out = out[out["pe_ratio"].fillna(0) <= filters["max_pe"]]

    return out


def delta_color(val: float) -> str:
    """Return 'normal', 'inverse', or 'off' for st.metric delta_color."""
    return "normal" if val >= 0 else "inverse"


def fmt_cr(val: float | None) -> str:
    """Format a value in crores."""
    if val is None or pd.isna(val):
        return "—"
    if val >= 1_00_000:
        return f"₹{val/1_00_000:.1f}L Cr"
    if val >= 1_000:
        return f"₹{val/1_000:.1f}K Cr"
    return f"₹{val:.0f} Cr"


def fmt_pct(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:+.2f}%"


def fmt_ratio(val: float | None, decimals: int = 2) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:.{decimals}f}x"
