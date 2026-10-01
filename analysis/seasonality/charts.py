"""
analysis/seasonality/charts.py
Plotly chart builders for seasonality visualisations.
All functions return go.Figure objects ready for st.plotly_chart().
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

THEME = dict(
    bg       = "#0f1117",
    card_bg  = "#1a1d27",
    border   = "#2a2d3e",
    text     = "#e0e0e0",
    subtext  = "#888",
    green    = "#00c48c",
    red      = "#ff4d6d",
    blue     = "#4c9be8",
    yellow   = "#f9e04b",
)

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _base(title: str = "", height: int = 380) -> dict:
    return dict(
        title         = dict(text=title, font=dict(color=THEME["text"], size=14)),
        height        = height,
        paper_bgcolor = THEME["bg"],
        plot_bgcolor  = THEME["card_bg"],
        font          = dict(color=THEME["text"]),
        margin        = dict(l=50, r=20, t=45, b=40),
        xaxis         = dict(gridcolor=THEME["border"]),
        yaxis         = dict(gridcolor=THEME["border"]),
    )


# ── Monthly return bar chart ──────────────────────────────────────────────────

def monthly_bar(monthly_df: pd.DataFrame, symbol: str = "") -> go.Figure:
    """
    Bar chart of mean monthly returns with win rate overlay.
    Green bars = positive avg return, red = negative.
    Asterisk on bar = statistically significant (p < 0.10).
    """
    df = monthly_df.copy()

    colors = [
        THEME["green"] if v >= 0 else THEME["red"]
        for v in df["mean_return"]
    ]

    # Add * marker for significant months
    labels = [
        f"{r:.2f}%{'*' if sig else ''}"
        for r, sig in zip(df["mean_return"], df["is_significant"])
    ]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Return bars
    fig.add_trace(go.Bar(
        x           = df["month_name"],
        y           = df["mean_return"],
        marker_color= colors,
        text        = labels,
        textposition= "outside",
        name        = "Avg Monthly Return %",
        hovertemplate = (
            "<b>%{x}</b><br>"
            "Avg return: %{y:.2f}%<br>"
            "Win rate: %{customdata:.0f}%<br>"
            "n: %{meta} years<extra></extra>"
        ),
        customdata  = df["win_rate"],
        meta        = df["n_years"],
    ), secondary_y=False)

    # Win rate line
    fig.add_trace(go.Scatter(
        x    = df["month_name"],
        y    = df["win_rate"],
        mode = "lines+markers",
        name = "Win Rate %",
        line = dict(color=THEME["yellow"], width=2, dash="dot"),
        marker=dict(size=7),
        hovertemplate="Win rate: %{y:.1f}%<extra></extra>",
    ), secondary_y=True)

    fig.add_hline(y=0, line_color=THEME["border"], line_width=1)

    title = f"{symbol} — Monthly Return Patterns" if symbol else "Monthly Return Patterns"
    fig.update_layout(**_base(title, height=400))
    fig.update_yaxes(title_text="Avg Return %",  secondary_y=False,
                     gridcolor=THEME["border"])
    fig.update_yaxes(title_text="Win Rate %",    secondary_y=True,
                     range=[0, 100], gridcolor="rgba(0,0,0,0)")
    fig.update_layout(legend=dict(
        bgcolor=THEME["card_bg"], bordercolor=THEME["border"],
        orientation="h", y=1.12,
    ))
    return fig


# ── Day-of-week bar chart ─────────────────────────────────────────────────────

def dow_bar(dow_df: pd.DataFrame, symbol: str = "") -> go.Figure:
    """Bar chart of mean daily return per weekday."""
    df = dow_df.copy()
    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in df["mean_return"]]

    fig = go.Figure(go.Bar(
        x            = df["dow_name"],
        y            = df["mean_return"],
        marker_color = colors,
        text         = [f"{v:.3f}%" for v in df["mean_return"]],
        textposition = "outside",
        hovertemplate= (
            "<b>%{x}</b><br>"
            "Avg return: %{y:.3f}%<br>"
            "Win rate: %{customdata:.0f}%<br>"
            "n: %{meta} days<extra></extra>"
        ),
        customdata   = df["win_rate"],
        meta         = df["n"],
    ))
    fig.add_hline(y=0, line_color=THEME["border"], line_width=1)

    title = f"{symbol} — Day-of-Week Effect" if symbol else "Day-of-Week Effect"
    fig.update_layout(**_base(title, height=340))
    return fig


# ── Quarterly bar chart ───────────────────────────────────────────────────────

def quarterly_bar(quarterly_df: pd.DataFrame, symbol: str = "") -> go.Figure:
    """Bar chart of mean monthly return per quarter."""
    df = quarterly_df.copy()
    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in df["mean_return"]]

    fig = go.Figure(go.Bar(
        x            = df["quarter_name"],
        y            = df["mean_return"],
        marker_color = colors,
        text         = [f"{v:.2f}%" for v in df["mean_return"]],
        textposition = "outside",
        hovertemplate= (
            "<b>%{x}</b><br>"
            "Avg return: %{y:.2f}%<br>"
            "Win rate: %{customdata:.0f}%<br>"
            "<extra></extra>"
        ),
        customdata   = df["win_rate"],
    ))
    fig.add_hline(y=0, line_color=THEME["border"], line_width=1)

    title = f"{symbol} — Quarterly Patterns" if symbol else "Quarterly Patterns"
    fig.update_layout(**_base(title, height=340))
    return fig


# ── Year-by-year monthly heatmap ──────────────────────────────────────────────

def yearly_monthly_heatmap(prices: pd.DataFrame, symbol: str = "") -> go.Figure:
    """
    Year × Month heatmap of actual monthly returns.
    Each cell = return for that specific month/year.
    More granular than the average bar — shows consistency over time.
    """
    from analysis.seasonality.patterns import _monthly_returns
    monthly = _monthly_returns(prices)
    pivot   = monthly.pivot_table(
        index="year", columns="month_name", values="return_pct", aggfunc="mean"
    )
    # Reorder columns Jan→Dec
    available = [m for m in MONTHS if m in pivot.columns]
    pivot     = pivot[available]

    # Custom text for hover
    text = [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row]
            for row in pivot.values]

    fig = go.Figure(go.Heatmap(
        z            = pivot.values,
        x            = pivot.columns.tolist(),
        y            = pivot.index.tolist(),
        colorscale   = "RdYlGn",
        zmid         = 0,
        text         = text,
        texttemplate = "%{text}",
        textfont     = dict(size=10),
        hovertemplate= "<b>%{y} %{x}</b><br>Return: %{z:.2f}%<extra></extra>",
        colorbar     = dict(
            title     = "Return %",
            # titlefont = dict(color=THEME["text"]),
            tickfont  = dict(color=THEME["text"]),
        ),
    ))

    title = f"{symbol} — Monthly Returns by Year" if symbol else "Monthly Returns by Year"
    layout = _base(title, height=max(300, len(pivot) * 28 + 80))
    layout["xaxis"].update(dict(side="top"))
    fig.update_layout(**layout)
    return fig


# ── Universe / sector heatmap ─────────────────────────────────────────────────

def universe_heatmap(
    matrix_df: pd.DataFrame,
    title:     str  = "Monthly Return Heatmap",
    height:    int  = 0,
) -> go.Figure:
    """
    Generic symbol×month or sector×month heatmap.
    matrix_df: rows=symbols/sectors, columns=month names, values=returns.
    """
    if matrix_df.empty:
        fig = go.Figure()
        fig.update_layout(**_base("No data available"))
        return fig

    text = [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row]
            for row in matrix_df.values]

    fig = go.Figure(go.Heatmap(
        z            = matrix_df.values,
        x            = matrix_df.columns.tolist(),
        y            = matrix_df.index.tolist(),
        colorscale   = "RdYlGn",
        zmid         = 0,
        text         = text,
        texttemplate = "%{text}",
        textfont     = dict(size=9),
        hovertemplate= "<b>%{y} — %{x}</b><br>Avg return: %{z:.2f}%<extra></extra>",
        colorbar     = dict(
            title     = "Avg Return %",
            # titlefont = dict(color=THEME["text"]),
            tickfont  = dict(color=THEME["text"]),
        ),
    ))

    auto_height = max(300, len(matrix_df) * 22 + 100)
    layout = _base(title, height=height or auto_height)
    layout["xaxis"].update(dict(side="top"))
    layout["margin"] = dict(l=140, r=20, t=60, b=20)
    fig.update_layout(**layout)
    return fig


# ── Consistency score chart ───────────────────────────────────────────────────

def consistency_chart(monthly_df: pd.DataFrame, symbol: str = "") -> go.Figure:
    """
    Scatter: avg return vs win rate per month.
    Top-right quadrant = high return + high win rate = most reliable months.
    """
    df = monthly_df.copy().dropna(subset=["mean_return", "win_rate"])

    colors = [
        THEME["green"]  if (r > 0 and w > 55) else
        THEME["red"]    if (r < 0 and w < 45) else
        THEME["yellow"]
        for r, w in zip(df["mean_return"], df["win_rate"])
    ]

    fig = go.Figure(go.Scatter(
        x         = df["win_rate"],
        y         = df["mean_return"],
        mode      = "markers+text",
        marker    = dict(size=14, color=colors,
                         line=dict(width=1, color=THEME["bg"])),
        text      = df["month_name"],
        textposition = "top center",
        textfont  = dict(size=10, color=THEME["text"]),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Avg return: %{y:.2f}%<br>"
            "Win rate: %{x:.0f}%<extra></extra>"
        ),
    ))

    # Quadrant lines
    fig.add_hline(y=0,  line_dash="dash", line_color=THEME["border"])
    fig.add_vline(x=50, line_dash="dash", line_color=THEME["border"])

    # Quadrant labels
    for txt, x, y in [
        ("Best",    85, df["mean_return"].max() * 0.9),
        ("Worst",   15, df["mean_return"].min() * 0.9),
    ]:
        fig.add_annotation(text=txt, x=x, y=y,
                           font=dict(color=THEME["subtext"], size=11),
                           showarrow=False)

    title = f"{symbol} — Return vs Consistency" if symbol else "Return vs Consistency"
    layout = _base(title, height=360)
    layout["xaxis"].update(dict(title="Win Rate %", range=[20, 85]))
    layout["yaxis"].update(dict(title="Avg Return %"))
    fig.update_layout(**layout)
    return fig