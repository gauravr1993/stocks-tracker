"""
dashboard/pages/05_morning_brief.py
Morning brief — sentiment-scored news, market mood, stocks to watch.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

st.set_page_config(
    page_title = "Morning Brief · NIFTY Intel",
    page_icon  = "🌅",
    layout     = "wide",
)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "config", ".env"
))

from components.sidebar     import apply_dark_theme
from components.data_loader import load_news_feed, load_screener
from analysis.signals.charts import THEME

apply_dark_theme()

st.title("🌅 Morning Brief")
st.caption(f"Pre-market sentiment & news — {date.today().strftime('%A, %d %B %Y')}")

col_ctrl1, col_ctrl2 = st.columns([1, 3])
with col_ctrl1:
    days_back = st.selectbox(
        "News from last",
        [1, 2, 3, 7], index=1,
        format_func=lambda x: f"{x} day{'s' if x > 1 else ''}",
    )

with st.spinner("Loading news & sentiment..."):
    news = load_news_feed(days=days_back)
    df   = load_screener()

if news.empty:
    st.warning("No news found. Run the morning pipeline first:")
    st.code("python scheduler/run_morning.py --days 2")
    st.stop()

scored   = news[news["sentiment_score"].notna()].copy()
unscored = news[news["sentiment_score"].isna()]
total    = len(news)
n_scored = len(scored)

pos = scored[scored["sentiment_label"] == "positive"]
neg = scored[scored["sentiment_label"] == "negative"]
neu = scored[scored["sentiment_label"] == "neutral"]

pos_pct   = len(pos) / n_scored * 100 if n_scored > 0 else 0
neg_pct   = len(neg) / n_scored * 100 if n_scored > 0 else 0
avg_score = scored["sentiment_score"].mean() if n_scored > 0 else 0

if n_scored == 0:
    mood, mood_emoji = "Pending", "⏳"
elif pos_pct >= 60:
    mood, mood_emoji = "Bullish",            "🟢"
elif neg_pct >= 60:
    mood, mood_emoji = "Bearish",            "🔴"
elif pos_pct >= neg_pct + 15:
    mood, mood_emoji = "Cautiously Bullish", "🟡"
elif neg_pct >= pos_pct + 15:
    mood, mood_emoji = "Cautiously Bearish", "🟠"
else:
    mood, mood_emoji = "Mixed",              "⬜"

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Market Mood",   f"{mood_emoji} {mood}")
c2.metric("Articles",      total, delta=f"{n_scored} scored")
c3.metric("Positive",      len(pos),  delta=f"{pos_pct:.0f}%", delta_color="normal")
c4.metric("Negative",      len(neg),  delta=f"{neg_pct:.0f}%", delta_color="inverse")
c5.metric("Avg Sentiment", f"{avg_score:+.3f}" if n_scored > 0 else "—")
c6.metric("Unscored",      len(unscored),
          help="Run scheduler/run_morning.py to score these")

st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Sentiment Overview",
    "📰 Headlines",
    "🏢 By Stock",
    "📢 BSE Announcements",
])

# ══ TAB 1 ════════════════════════════════════════════════════════════════════
with tab1:
    if n_scored == 0:
        st.info("No sentiment scores yet. Run the morning pipeline to populate this page.")
        st.code("python scheduler/run_morning.py --days 2")
        st.stop()

    col_pie, col_hist = st.columns(2)

    with col_pie:
        fig_pie = go.Figure(go.Pie(
            labels       = ["Positive", "Neutral", "Negative"],
            values       = [len(pos), len(neu), len(neg)],
            marker_colors= [THEME["green"], THEME["subtext"], THEME["red"]],
            hole         = 0.45,
            textinfo     = "label+percent",
            textfont     = dict(color=THEME["text"], size=13),
            hovertemplate= "<b>%{label}</b><br>%{value} articles (%{percent})<extra></extra>",
        ))
        fig_pie.update_layout(
            paper_bgcolor= THEME["bg"],
            font         = dict(color=THEME["text"]),
            height       = 300,
            margin       = dict(l=20, r=20, t=30, b=20),
            showlegend   = False,
            title        = dict(text="Sentiment Distribution", font=dict(color=THEME["text"])),
            annotations  = [dict(
                text=f"<b>{mood_emoji}<br>{mood}</b>",
                x=0.5, y=0.5, font_size=14,
                font_color=THEME["text"], showarrow=False,
            )],
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_hist:
        fig_hist = go.Figure(go.Histogram(
            x=scored["sentiment_score"], nbinsx=20,
            marker_color=THEME["blue"], opacity=0.8,
        ))
        fig_hist.add_vline(x=0, line_color=THEME["subtext"], line_dash="dash", line_width=1)
        fig_hist.add_vline(x=avg_score, line_color=THEME["yellow"], line_dash="dot",
                           annotation_text=f"Avg: {avg_score:+.3f}",
                           annotation_font_color=THEME["yellow"])
        fig_hist.update_layout(
            paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
            font=dict(color=THEME["text"]), height=300,
            margin=dict(l=40, r=20, t=30, b=40),
            title=dict(text="Score Distribution", font=dict(color=THEME["text"])),
            xaxis=dict(title="Sentiment Score", gridcolor=THEME["border"], range=[-1.1, 1.1]),
            yaxis=dict(title="Articles", gridcolor=THEME["border"]),
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    st.markdown("---")
    col_bull, col_bear = st.columns(2)

    with col_bull:
        st.markdown("### 📈 Top Bullish")
        for _, row in pos.sort_values("sentiment_score", ascending=False).head(5).iterrows():
            sym  = str(row.get("symbol","") or "MARKET").replace(".NS","")
            dt   = row["event_date"].strftime("%d %b") if hasattr(row["event_date"], "strftime") else str(row["event_date"])[:10]
            st.markdown(
                f"**[{sym}]** `{dt}` {str(row['headline'])[:80]}  \n"
                f"<span style='color:{THEME['green']}'>{row['sentiment_score']:+.2f}</span>",
                unsafe_allow_html=True,
            )
            st.divider()

    with col_bear:
        st.markdown("### 📉 Top Bearish")
        for _, row in neg.sort_values("sentiment_score").head(5).iterrows():
            sym  = str(row.get("symbol","") or "MARKET").replace(".NS","")
            dt   = row["event_date"].strftime("%d %b") if hasattr(row["event_date"], "strftime") else str(row["event_date"])[:10]
            st.markdown(
                f"**[{sym}]** `{dt}` {str(row['headline'])[:80]}  \n"
                f"<span style='color:{THEME['red']}'>{row['sentiment_score']:+.2f}</span>",
                unsafe_allow_html=True,
            )
            st.divider()

    st.markdown("---")
    st.subheader("⚠️ Stocks to Watch")
    stock_neg = (
        neg[neg["symbol"].notna()]
        .groupby("symbol")
        .agg(neg_articles=("sentiment_score","count"),
             avg_sentiment=("sentiment_score","mean"),
             worst_score  =("sentiment_score","min"))
        .reset_index()
        .sort_values("neg_articles", ascending=False)
    )
    stock_neg["symbol"] = stock_neg["symbol"].str.replace(".NS","",regex=False)

    if stock_neg.empty:
        st.success("No stocks with multiple negative articles — clear skies!")
    else:
        st.dataframe(
            stock_neg.rename(columns={
                "symbol":"Stock","neg_articles":"Neg Articles",
                "avg_sentiment":"Avg Sentiment","worst_score":"Worst Score",
            }).style
                .background_gradient(subset=["Neg Articles"],  cmap="Reds",   vmin=1, vmax=5)
                .background_gradient(subset=["Avg Sentiment"], cmap="RdYlGn", vmin=-1, vmax=0)
                .format({"Avg Sentiment":"{:.3f}","Worst Score":"{:.3f}"}),
            use_container_width=True, hide_index=True,
        )

    st.markdown("---")
    if st.button("🔄 Re-run sentiment scoring now"):
        with st.spinner("Running sentiment agent..."):
            try:
                from agents.sentiment.agent import run_sentiment_agent
                brief = run_sentiment_agent(days_back=days_back)
                st.success(
                    f"Done! Scored {brief['total_articles']} articles. "
                    f"Mood: **{brief['mood']}**. Reload the page to see results."
                )
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Agent failed: {exc}")

# ══ TAB 2 ════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("All Headlines")
    f1, f2, f3 = st.columns(3)
    with f1:
        label_filter = st.multiselect(
            "Sentiment", ["positive","neutral","negative"],
            default=["positive","negative"],
        )
    with f2:
        source_filter = st.multiselect(
            "Source", news["source"].dropna().unique().tolist(),
            default=news["source"].dropna().unique().tolist(),
        )
    with f3:
        sym_only = st.checkbox("Stock-specific only", value=False)

    filt = scored.copy() if label_filter else news.copy()
    if label_filter:
        filt = filt[filt["sentiment_label"].isin(label_filter)]
    if source_filter:
        filt = filt[filt["source"].isin(source_filter)]
    if sym_only:
        filt = filt[filt["symbol"].notna()]

    filt = filt.sort_values("sentiment_score", ascending=False)
    filt["symbol"]     = filt["symbol"].fillna("MARKET").str.replace(".NS","",regex=False)
    filt["event_date"] = filt["event_date"].dt.strftime("%Y-%m-%d")

    st.dataframe(
        filt[["event_date","symbol","sentiment_label","sentiment_score","headline","source"]]
        .rename(columns={"event_date":"Date","symbol":"Stock","sentiment_label":"Label",
                         "sentiment_score":"Score","headline":"Headline","source":"Source"})
        .style.background_gradient(subset=["Score"], cmap="RdYlGn", vmin=-1, vmax=1)
        .format({"Score":"{:+.2f}"}, na_rep="—"),
        use_container_width=True, hide_index=True,
    )

# ══ TAB 3 ════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Per-Stock Sentiment")
    stock_sent = (
        scored[scored["symbol"].notna()]
        .groupby("symbol")
        .agg(articles=("sentiment_score","count"),
             avg_score=("sentiment_score","mean"),
             pos_articles=("sentiment_label", lambda x: (x=="positive").sum()),
             neg_articles=("sentiment_label", lambda x: (x=="negative").sum()))
        .reset_index()
        .sort_values("avg_score", ascending=False)
    )
    stock_sent["symbol"] = stock_sent["symbol"].str.replace(".NS","",regex=False)

    if stock_sent.empty:
        st.info("No per-stock sentiment data yet.")
    else:
        fig_bar = go.Figure(go.Bar(
            x=stock_sent["symbol"], y=stock_sent["avg_score"],
            marker_color=[
                THEME["green"] if s >= 0.2 else THEME["red"] if s <= -0.2 else THEME["subtext"]
                for s in stock_sent["avg_score"]
            ],
            text=stock_sent["avg_score"].apply(lambda x: f"{x:+.2f}"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Avg: %{y:+.3f}<br>Articles: %{customdata}<extra></extra>",
            customdata=stock_sent["articles"],
        ))
        fig_bar.add_hline(y=0, line_color=THEME["border"], line_width=1)
        fig_bar.update_layout(
            paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
            font=dict(color=THEME["text"]), height=360,
            margin=dict(l=40, r=20, t=30, b=60),
            xaxis=dict(gridcolor=THEME["border"], tickangle=-45),
            yaxis=dict(gridcolor=THEME["border"], title="Avg Sentiment Score"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(
            stock_sent.rename(columns={
                "symbol":"Stock","articles":"Articles","avg_score":"Avg Score",
                "pos_articles":"Positive","neg_articles":"Negative",
            }).style
                .background_gradient(subset=["Avg Score"], cmap="RdYlGn", vmin=-1, vmax=1)
                .format({"Avg Score":"{:+.3f}"}),
            use_container_width=True, hide_index=True,
        )

# ══ TAB 4 ════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("BSE Corporate Announcements")
    bse = news[news["source"] == "bse"].copy()
    if bse.empty:
        st.info("No BSE announcements in the selected period.")
    else:
        cat_counts = bse["category"].value_counts().reset_index()
        cat_counts.columns = ["Category", "Count"]
        fig_cats = go.Figure(go.Bar(
            x=cat_counts["Category"], y=cat_counts["Count"],
            marker_color=THEME["blue"], text=cat_counts["Count"], textposition="outside",
        ))
        fig_cats.update_layout(
            paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"],
            font=dict(color=THEME["text"]), height=260,
            margin=dict(l=40, r=20, t=30, b=40),
            xaxis=dict(gridcolor=THEME["border"]),
            yaxis=dict(gridcolor=THEME["border"]),
            title=dict(text="Announcement Categories", font=dict(color=THEME["text"])),
        )
        st.plotly_chart(fig_cats, use_container_width=True)

        bse["event_date"] = bse["event_date"].dt.strftime("%Y-%m-%d")
        bse["symbol"]     = bse["symbol"].fillna("—").str.replace(".NS","",regex=False)
        st.dataframe(
            bse[["event_date","symbol","category","headline"]]
            .rename(columns={"event_date":"Date","symbol":"Stock",
                             "category":"Category","headline":"Headline"}),
            use_container_width=True, hide_index=True,
        )