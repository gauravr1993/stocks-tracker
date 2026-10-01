"""
analysis/signals/charts.py
Plotly chart builders for technical indicator visualisations.
Used by the stock deep dive page and the algo signals page.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

THEME = dict(
    bg      = "#0f1117",
    card_bg = "#1a1d27",
    border  = "#2a2d3e",
    text    = "#e0e0e0",
    subtext = "#888",
    green   = "#00c48c",
    red     = "#ff4d6d",
    blue    = "#4c9be8",
    purple  = "#9b72cf",
    orange  = "#f4a442",
    yellow  = "#f9e04b",
)


def _base(height: int = 500) -> dict:
    """Base layout — intentionally excludes xaxis/yaxis/margin so callers can pass freely."""
    return dict(
        height        = height,
        paper_bgcolor = THEME["bg"],
        plot_bgcolor  = THEME["card_bg"],
        font          = dict(color=THEME["text"]),
        legend        = dict(
            bgcolor=THEME["card_bg"], bordercolor=THEME["border"],
            font=dict(size=11), orientation="h", y=1.02,
        ),
        xaxis_rangeslider_visible = False,
    )


# ── Main technical chart: price + indicators ──────────────────────────────────

def technical_chart(
    df: pd.DataFrame,
    symbol: str = "",
    show_volume:  bool = True,
    show_bb:      bool = True,
    show_mas:     list[int] = [20, 50, 200],
    show_signals: bool = True,
) -> go.Figure:
    """
    Multi-panel chart:
      Row 1 (large): Candlestick + Bollinger Bands + Moving Averages + Buy/Sell signals
      Row 2 (small): Volume
      Row 3 (small): RSI
      Row 4 (small): MACD

    Args:
        df:           Price DataFrame with indicators already computed
        symbol:       Display label
        show_volume:  Include volume panel
        show_bb:      Overlay Bollinger Bands
        show_mas:     Which SMA periods to overlay
        show_signals: Mark buy/sell signal points on chart
    """
    # Build subplot layout
    rows        = 1 + show_volume + 1 + 1    # price + volume + RSI + MACD
    row_heights = [0.50]
    if show_volume:
        row_heights.append(0.12)
    row_heights += [0.19, 0.19]              # RSI, MACD

    fig = make_subplots(
        rows        = rows,
        cols        = 1,
        shared_xaxes= True,
        vertical_spacing = 0.02,
        row_heights = row_heights,
        subplot_titles = (
            [f"{symbol} — Technical Analysis", None, "RSI (14)", "MACD (12,26,9)"]
            if not show_volume else
            [f"{symbol} — Technical Analysis", None, None, "RSI (14)", "MACD (12,26,9)"]
        ),
    )

    price_row  = 1
    vol_row    = 2 if show_volume else None
    rsi_row    = 3 if show_volume else 2
    macd_row   = 4 if show_volume else 3

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x    = df["date"],
        open = df["open"],   high = df["high"],
        low  = df["low"],    close= df["close"],
        name = "Price",
        increasing_line_color = THEME["green"],
        decreasing_line_color = THEME["red"],
        increasing_fillcolor  = THEME["green"],
        decreasing_fillcolor  = THEME["red"],
    ), row=price_row, col=1)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if show_bb and "bb_upper" in df.columns:
        for band_col, name, dash in [
            ("bb_upper",  "BB Upper", "dot"),
            ("bb_middle", "BB Mid",   "solid"),
            ("bb_lower",  "BB Lower", "dot"),
        ]:
            if band_col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df[band_col],
                    name=name, mode="lines",
                    line=dict(color=THEME["purple"], width=1, dash=dash),
                    opacity=0.6,
                    showlegend=(band_col == "bb_upper"),
                    legendgroup="bb",
                    legendgrouptitle_text="Bollinger" if band_col == "bb_upper" else None,
                ), row=price_row, col=1)

        # Fill between bands
        fig.add_trace(go.Scatter(
            x=pd.concat([df["date"], df["date"][::-1]]),
            y=pd.concat([df["bb_upper"], df["bb_lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(155,114,207,0.05)",
            line=dict(color="rgba(0,0,0,0)"),
            showlegend=False, name="BB Fill",
        ), row=price_row, col=1)

    # ── Moving Averages ───────────────────────────────────────────────────────
    ma_colors = {20: THEME["blue"], 50: THEME["orange"], 200: THEME["yellow"]}
    for p in show_mas:
        col = f"sma_{p}"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col],
                name=f"SMA {p}", mode="lines",
                line=dict(color=ma_colors.get(p, THEME["subtext"]), width=1.5),
            ), row=price_row, col=1)

    # ── Buy / Sell signals ────────────────────────────────────────────────────
    if show_signals and "signal_label" in df.columns:
        buys  = df[df["signal_label"].isin(["Buy", "Strong Buy"])]
        sells = df[df["signal_label"].isin(["Sell", "Strong Sell"])]

        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys["date"], y=buys["low"] * 0.99,
                mode="markers", name="Buy Signal",
                marker=dict(symbol="triangle-up", size=12,
                            color=THEME["green"],
                            line=dict(width=1, color=THEME["bg"])),
                hovertemplate="<b>Buy Signal</b><br>%{x}<br>%{customdata}<extra></extra>",
                customdata=buys["signal_label"],
            ), row=price_row, col=1)

        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells["date"], y=sells["high"] * 1.01,
                mode="markers", name="Sell Signal",
                marker=dict(symbol="triangle-down", size=12,
                            color=THEME["red"],
                            line=dict(width=1, color=THEME["bg"])),
                hovertemplate="<b>Sell Signal</b><br>%{x}<br>%{customdata}<extra></extra>",
                customdata=sells["signal_label"],
            ), row=price_row, col=1)

    # ── Volume ────────────────────────────────────────────────────────────────
    if show_volume and "volume" in df.columns and vol_row:
        vol_colors = [
            THEME["green"] if c >= o else THEME["red"]
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(go.Bar(
            x=df["date"], y=df["volume"],
            marker_color=vol_colors, name="Volume", opacity=0.7,
        ), row=vol_row, col=1)

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_col = next((c for c in df.columns if c.startswith("rsi_")), None)
    if rsi_col:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df[rsi_col],
            name="RSI", mode="lines",
            line=dict(color=THEME["blue"], width=1.5),
        ), row=rsi_row, col=1)

        # Overbought / oversold zones
        for level, color, label in [(70, THEME["red"], "OB"), (30, THEME["green"], "OS")]:
            fig.add_hline(y=level, line_dash="dash", line_color=color,
                          line_width=1, opacity=0.6, row=rsi_row, col=1,
                          annotation_text=label,
                          annotation_font_color=color,
                          annotation_position="right")

        fig.update_yaxes(range=[0, 100], row=rsi_row, col=1,
                         gridcolor=THEME["border"])

    # ── MACD ──────────────────────────────────────────────────────────────────
    if "macd_line" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd_line"],
            name="MACD", mode="lines",
            line=dict(color=THEME["blue"], width=1.5),
        ), row=macd_row, col=1)

        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd_signal"],
            name="Signal", mode="lines",
            line=dict(color=THEME["orange"], width=1.5),
        ), row=macd_row, col=1)

        hist_colors = [
            THEME["green"] if v >= 0 else THEME["red"]
            for v in df["macd_histogram"].fillna(0)
        ]
        fig.add_trace(go.Bar(
            x=df["date"], y=df["macd_histogram"],
            marker_color=hist_colors, name="Histogram", opacity=0.7,
        ), row=macd_row, col=1)

        fig.add_hline(y=0, line_color=THEME["border"], line_width=1,
                      row=macd_row, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    base = _base(height=650)
    base["margin"] = dict(l=60, r=20, t=30, b=20)
    fig.update_layout(**base)
    fig.update_xaxes(gridcolor=THEME["border"], showgrid=True)
    fig.update_yaxes(gridcolor=THEME["border"], showgrid=True)
    # Hide x-axis labels on all but bottom panel
    for r in range(1, rows):
        fig.update_xaxes(showticklabels=False, row=r, col=1)

    return fig


# ── RSI gauge ────────────────────────────────────────────────────────────────

def rsi_gauge(rsi_value: float, symbol: str = "") -> go.Figure:
    """Gauge chart showing current RSI value."""
    if rsi_value is None or np.isnan(rsi_value):
        color = THEME["subtext"]
    elif rsi_value >= 70:
        color = THEME["red"]
    elif rsi_value <= 30:
        color = THEME["green"]
    else:
        color = THEME["blue"]

    fig = go.Figure(go.Indicator(
        mode  = "gauge+number",
        value = rsi_value if rsi_value and not np.isnan(rsi_value) else 0,
        title = dict(text=f"RSI (14){f' — {symbol}' if symbol else ''}",
                     font=dict(color=THEME["text"])),
        number= dict(font=dict(color=color, size=28)),
        gauge = dict(
            axis  = dict(range=[0, 100], tickwidth=1,
                         tickcolor=THEME["text"], tickfont=dict(color=THEME["text"])),
            bar   = dict(color=color),
            bgcolor     = THEME["card_bg"],
            bordercolor = THEME["border"],
            steps = [
                dict(range=[0,  30], color="rgba(0,196,140,0.15)"),
                dict(range=[30, 70], color="rgba(76,155,232,0.08)"),
                dict(range=[70,100], color="rgba(255,77,109,0.15)"),
            ],
            threshold = dict(
                line=dict(color=THEME["yellow"], width=2),
                thickness=0.75, value=50,
            ),
        ),
    ))
    fig.update_layout(
        paper_bgcolor=THEME["bg"], font=dict(color=THEME["text"]),
        height=220, margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


# ── Universe signal scan table ────────────────────────────────────────────────

def signal_scan_bars(scan_df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """
    Horizontal bar chart of composite signal scores for top N stocks.
    Green = bullish signals, red = bearish.
    """
    df = scan_df.dropna(subset=["signal_composite"]).copy()
    df["sym_clean"] = df["symbol"].str.replace(".NS", "", regex=False)

    # Show top bullish and top bearish
    top_bull = df.nlargest(top_n // 2, "signal_composite")
    top_bear = df.nsmallest(top_n // 2, "signal_composite")
    display  = pd.concat([top_bull, top_bear]).sort_values("signal_composite", ascending=True)

    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in display["signal_composite"]]

    fig = go.Figure(go.Bar(
        x            = display["signal_composite"],
        y            = display["sym_clean"],
        orientation  = "h",
        marker_color = colors,
        text         = display["signal_label"],
        textposition = "outside",
        hovertemplate= (
            "<b>%{y}</b><br>"
            "Score: %{x}<br>"
            "RSI: %{customdata[0]:.1f}<br>"
            "Label: %{customdata[1]}<extra></extra>"
        ),
        customdata   = display[["rsi_14", "signal_label"]].values,
    ))
    fig.add_vline(x=0, line_color=THEME["border"], line_width=1)
    fig.update_layout(
        **_base(height=max(300, len(display) * 22 + 60)),
        title  = dict(text="Signal Scan — Composite Score", font=dict(color=THEME["text"])),
        margin = dict(l=100, r=80, t=50, b=40),
        xaxis  = dict(range=[-4.5, 4.5], gridcolor=THEME["border"],
                      title="← Bearish  |  Bullish →"),
        yaxis  = dict(gridcolor=THEME["border"]),
    )
    return fig