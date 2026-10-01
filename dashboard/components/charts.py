"""
dashboard/components/charts.py
Reusable Plotly chart builders used across all dashboard pages.
"""
from __future__ import annotations
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

THEME = dict(
    bg        = "#0f1117",
    card_bg   = "#1a1d27",
    border    = "#2a2d3e",
    text      = "#e0e0e0",
    subtext   = "#888",
    green     = "#00c48c",
    red       = "#ff4d6d",
    blue      = "#4c9be8",
    purple    = "#9b72cf",
    orange    = "#f4a442",
    yellow    = "#f9e04b",
)

SECTOR_COLORS = px.colors.qualitative.Set3


def _base_layout(title: str = "", height: int = 400) -> dict:
    return dict(
        title       = dict(text=title, font=dict(color=THEME["text"], size=14)),
        height      = height,
        paper_bgcolor = THEME["bg"],
        plot_bgcolor  = THEME["card_bg"],
        font        = dict(color=THEME["text"], family="Inter, sans-serif"),
        margin      = dict(l=50, r=20, t=40, b=40),
        xaxis       = dict(gridcolor=THEME["border"], showgrid=True),
        yaxis       = dict(gridcolor=THEME["border"], showgrid=True),
    )


# ── Price chart with event overlays ──────────────────────────────────────────

def price_chart(
    prices: pd.DataFrame,
    symbol: str,
    events: pd.DataFrame | None = None,
    show_volume: bool = True,
) -> go.Figure:
    """
    OHLCV candlestick chart with optional event annotation overlays.

    Args:
        prices:  DataFrame with date, open, high, low, close, volume, adj_close
        symbol:  Display symbol name
        events:  DataFrame with event_date, headline, category columns
        show_volume: Add volume bars as subplot
    """
    rows = 2 if show_volume else 1
    row_heights = [0.75, 0.25] if show_volume else [1.0]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=prices["date"],
        open=prices["open"],   high=prices["high"],
        low=prices["low"],     close=prices["close"],
        name="Price",
        increasing_line_color=THEME["green"],
        decreasing_line_color=THEME["red"],
    ), row=1, col=1)

    # Volume bars
    if show_volume and "volume" in prices.columns:
        colors = [
            THEME["green"] if c >= o else THEME["red"]
            for c, o in zip(prices["close"], prices["open"])
        ]
        fig.add_trace(go.Bar(
            x=prices["date"], y=prices["volume"],
            marker_color=colors, name="Volume", opacity=0.6,
        ), row=2, col=1)

    # Event overlays
    if events is not None and not events.empty:
        cat_colors = {
            "earnings":  THEME["blue"],
            "dividend":  THEME["green"],
            "split":     THEME["purple"],
            "mgmt":      THEME["orange"],
            "macro":     THEME["yellow"],
            "other":     THEME["subtext"],
        }
        cat_symbols = {
            "earnings": "triangle-up",
            "dividend": "circle",
            "split":    "diamond",
            "mgmt":     "square",
            "macro":    "cross",
            "other":    "x",
        }
        for cat, grp in events.groupby("category"):
            # Find price at event date for y-position
            merged = grp.merge(
                prices[["date", "high"]].rename(columns={"high": "price_at"}),
                left_on="event_date", right_on="date", how="left"
            )
            merged["price_at"] = merged["price_at"].fillna(
                prices["high"].max() * 0.95
            )
            fig.add_trace(go.Scatter(
                x=merged["event_date"],
                y=merged["price_at"] * 1.02,
                mode="markers",
                marker=dict(
                    symbol=cat_symbols.get(cat, "circle"),
                    size=10,
                    color=cat_colors.get(cat, THEME["subtext"]),
                    line=dict(width=1, color=THEME["bg"]),
                ),
                name=cat.capitalize(),
                text=merged["headline"].str[:80],
                hovertemplate="<b>%{text}</b><br>%{x}<extra></extra>",
            ), row=1, col=1)

    layout = _base_layout(f"{symbol} — Price History", height=500)
    layout.update(dict(
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(
            bgcolor=THEME["card_bg"],
            bordercolor=THEME["border"],
            font=dict(size=11),
        ),
    ))
    fig.update_layout(**layout)
    fig.update_xaxes(showgrid=False, row=2, col=1)
    return fig


# ── Screener score bar chart ──────────────────────────────────────────────────

def score_bars(df: pd.DataFrame, score_col: str = "composite_score",
               top_n: int = 20, title: str = "") -> go.Figure:
    """Horizontal bar chart of top N stocks by a score column."""
    top = df.nlargest(top_n, score_col).sort_values(score_col)

    colors = [
        THEME["green"] if s >= 60 else THEME["blue"] if s >= 40 else THEME["red"]
        for s in top[score_col]
    ]

    fig = go.Figure(go.Bar(
        x=top[score_col],
        y=top["symbol"].str.replace(".NS", "", regex=False),
        orientation="h",
        marker_color=colors,
        text=top[score_col].round(1),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(title or f"Top {top_n} by {score_col}", height=max(300, top_n * 22)))
    fig.update_xaxes(range=[0, 105])
    return fig


# ── Sector heatmap ────────────────────────────────────────────────────────────

def sector_heatmap(sector_df: pd.DataFrame) -> go.Figure:
    """Heatmap of sector strength vs median return."""
    fig = go.Figure(go.Bar(
        x=sector_df["sector"],
        y=sector_df["sector_strength"],
        marker=dict(
            color=sector_df["sector_strength"],
            colorscale="RdYlGn",
            cmin=0, cmax=100,
            showscale=True,
            colorbar=dict(title="Strength", tickfont=dict(color=THEME["text"])),
        ),
        text=sector_df["sector_strength"].round(0).astype(int),
        textposition="outside",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Strength: %{y:.0f}<br>"
            "Median 1y return: %{customdata:.1f}%<extra></extra>"
        ),
        customdata=sector_df["median_return_1y"],
    ))
    fig.update_layout(**_base_layout("Sector Strength", height=380))
    fig.update_xaxes(tickangle=-35)
    return fig


# ── Score radar for individual stock ─────────────────────────────────────────

def score_radar(row: pd.Series, symbol: str) -> go.Figure:
    """Radar chart showing value / momentum / sector scores for one stock."""
    categories = ["Value", "Momentum", "Sector"]
    values = [
        float(row.get("value_score",    0) or 0),
        float(row.get("momentum_score", 0) or 0),
        float(row.get("sector_score",   0) or 0),
    ]
    values_closed = values + [values[0]]
    cats_closed   = categories + [categories[0]]

    fig = go.Figure(go.Scatterpolar(
        r=values_closed,
        theta=cats_closed,
        fill="toself",
        fillcolor=f"rgba(76,155,232,0.2)",
        line=dict(color=THEME["blue"], width=2),
        marker=dict(size=6, color=THEME["blue"]),
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=THEME["card_bg"],
            radialaxis=dict(range=[0, 100], gridcolor=THEME["border"],
                            tickfont=dict(color=THEME["subtext"]), tickvals=[25,50,75,100]),
            angularaxis=dict(gridcolor=THEME["border"], tickfont=dict(color=THEME["text"])),
        ),
        paper_bgcolor=THEME["bg"],
        font=dict(color=THEME["text"]),
        title=dict(text=f"{symbol} Score Breakdown", font=dict(color=THEME["text"])),
        height=300,
        margin=dict(l=40, r=40, t=50, b=20),
        showlegend=False,
    )
    return fig


# ── Return distribution ───────────────────────────────────────────────────────

def return_histogram(df: pd.DataFrame, col: str = "return_1y",
                     title: str = "1Y Return Distribution") -> go.Figure:
    vals = df[col].dropna()
    fig = go.Figure(go.Histogram(
        x=vals, nbinsx=30,
        marker_color=THEME["blue"], opacity=0.8,
    ))
    # Median line
    med = vals.median()
    fig.add_vline(x=med, line_dash="dash", line_color=THEME["yellow"],
                  annotation_text=f"Median: {med:.1f}%",
                  annotation_font_color=THEME["yellow"])
    fig.add_vline(x=0, line_color=THEME["subtext"], line_width=1)
    fig.update_layout(**_base_layout(title, height=300))
    return fig


# ── Gainers / losers table ────────────────────────────────────────────────────

def gainers_losers(prices_today: pd.DataFrame, top_n: int = 5) -> tuple[go.Figure, go.Figure]:
    """Two bar charts: top gainers and top losers by daily change %."""
    df = prices_today.copy()
    df["change_pct"] = ((df["close"] - df["open"]) / df["open"] * 100).round(2)
    df["sym"] = df["symbol"].str.replace(".NS", "", regex=False)

    gainers = df.nlargest(top_n, "change_pct")
    losers  = df.nsmallest(top_n, "change_pct")

    def _bar(data, color, title):
        return go.Figure(go.Bar(
            x=data["sym"], y=data["change_pct"],
            marker_color=color,
            text=data["change_pct"].apply(lambda x: f"{x:+.2f}%"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>%{y:.2f}%<extra></extra>",
        )).update_layout(**_base_layout(title, height=280))

    return (
        _bar(gainers, THEME["green"], f"Top {top_n} Gainers"),
        _bar(losers,  THEME["red"],   f"Top {top_n} Losers"),
    )
