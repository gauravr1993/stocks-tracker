"""
agents/sentiment/scorer.py
Sentiment scoring for financial news articles using Groq API.

Returns per-article:
  - sentiment_score : float  -1.0 (very negative) to +1.0 (very positive)
  - sentiment_label : str    'positive' | 'neutral' | 'negative'
  - reasoning       : str    one-sentence explanation

Design:
  - Batches articles to minimise API calls (up to 5 per request)
  - Retries on rate limit with exponential backoff
  - Falls back to neutral (0.0) on persistent failure
  - Stores reasoning in news_events.metadata JSONB column
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """You are a financial sentiment analyst specialising in Indian stock markets (NSE/BSE).

Your task: score the sentiment of news articles from the perspective of a retail equity investor.

SCORING RULES:
- Score from -1.0 (very negative for stock price) to +1.0 (very positive for stock price)
- 0.0 = neutral / no clear price impact
- Focus on SHORT-TERM price impact (next 1-3 trading days)
- Positive signals: earnings beat, new contracts, buybacks, upgrades, strong guidance, acquisitions at fair price
- Negative signals: earnings miss, downgrades, regulatory issues, promoter selling, fraud allegations, weak guidance
- Neutral: routine filings, index rebalancing announcements, general market commentary

LABEL THRESHOLDS:
- positive : score >= 0.2
- negative : score <= -0.2
- neutral  : -0.2 < score < 0.2

OUTPUT FORMAT — strict JSON array, one object per article, same order as input:
[
  {
    "id": <article_id>,
    "score": <float -1.0 to 1.0, one decimal place>,
    "label": "<positive|neutral|negative>",
    "reasoning": "<one sentence, max 20 words, explain the key factor>"
  }
]

No markdown, no explanation outside the JSON array."""


def _build_user_prompt(articles: list[dict]) -> str:
    """
    Build user prompt from a batch of articles.
    Each article: {id, headline, summary, symbol}
    """
    lines = ["Score these financial news articles:\n"]
    for art in articles:
        sym  = art.get("symbol", "").replace(".NS", "") or "MARKET"
        head = art.get("headline", "")[:200]
        summ = art.get("summary",  "")[:150]
        lines.append(
            f"[{art['id']}] Stock: {sym}\n"
            f"Headline: {head}\n"
            f"Summary: {summ}\n"
        )
    return "\n".join(lines)


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("groq package not installed — run: pip install groq")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in environment")

    return Groq(api_key=api_key)


def _parse_response(raw: str, article_ids: list[str]) -> list[dict]:
    """
    Parse Groq response into list of scored dicts.
    Handles markdown fences and malformed JSON gracefully.
    """
    # Strip markdown fences
    clean = re.sub(r"```json|```", "", raw).strip()

    # Extract JSON array — use first [ to last ] to handle multi-line arrays
    start = clean.find("[")
    end   = clean.rfind("]")
    if start == -1 or end == -1 or end <= start:
        logger.warning("No JSON array found in response: %s", raw[:300])
        return []

    try:
        parsed = json.loads(clean[start:end + 1])
    except json.JSONDecodeError as e:
        # Response may be truncated — try to salvage complete objects
        logger.warning("JSON parse error (likely truncated): %s", e)
        try:
            # Extract all complete {...} objects manually
            import re as _re
            objects = _re.findall(r'\{[^{}]+\}', clean, _re.DOTALL)
            parsed  = [json.loads(o) for o in objects if '"id"' in o]
            if parsed:
                logger.info("Salvaged %d complete objects from truncated response", len(parsed))
            else:
                return []
        except Exception:
            return []

    results = []
    for item in parsed:
        try:
            score = float(item.get("score", 0.0))
            score = max(-1.0, min(1.0, round(score, 2)))   # clamp to [-1, 1]

            label = item.get("label", "neutral").lower()
            if label not in ("positive", "negative", "neutral"):
                label = "positive" if score >= 0.2 else "negative" if score <= -0.2 else "neutral"

            results.append({
                "id":        str(item.get("id", "")),
                "score":     score,
                "label":     label,
                "reasoning": str(item.get("reasoning", ""))[:200],
            })
        except Exception as exc:
            logger.debug("Skipping malformed result item: %s", exc)

    return results


def _fallback_results(articles: list[dict]) -> list[dict]:
    """Return neutral scores for all articles when API fails."""
    return [
        {"id": str(a["id"]), "score": 0.0, "label": "neutral", "reasoning": "Scoring unavailable"}
        for a in articles
    ]


# ── Batch scorer ──────────────────────────────────────────────────────────────

def score_batch(
    articles:   list[dict],
    batch_size: int   = 3,     # reduced from 5 — prevents response truncation
    max_retries:int   = 3,
    retry_delay:float = 5.0,
) -> list[dict]:
    """
    Score a list of articles in batches.

    Args:
        articles:   List of dicts with keys: id, headline, summary, symbol
        batch_size: Articles per Groq API call (5 is sweet spot for quality + speed)
        max_retries:Retries per batch on rate limit / error
        retry_delay:Base delay between retries (doubles each attempt)

    Returns:
        List of dicts: {id, score, label, reasoning}
        Same length as input, preserving order.
        Failed articles get neutral fallback.
    """
    if not articles:
        return []

    client  = _get_groq_client()
    results = {}

    for i in range(0, len(articles), batch_size):
        batch = articles[i: i + batch_size]
        batch_ids = [str(a["id"]) for a in batch]

        logger.debug("Scoring batch %d-%d (%d articles)",
                     i + 1, min(i + batch_size, len(articles)), len(batch))

        scored = None
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model       = "openai/gpt-oss-120b",
                    messages    = [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user",   "content": _build_user_prompt(batch)},
                    ],
                    max_tokens  = 1500,  # ~300 tokens per article * 3 articles + buffer
                    temperature = 0.0,
                )
                raw    = response.choices[0].message.content.strip()
                scored = _parse_response(raw, batch_ids)

                if len(scored) == len(batch):
                    break   # clean parse — move on
                else:
                    logger.warning("Batch %d: expected %d results, got %d — retrying",
                                   i, len(batch), len(scored))
                    scored = None

            except Exception as exc:
                wait = retry_delay * (2 ** (attempt - 1))
                logger.warning("Batch %d attempt %d failed: %s — retrying in %.1fs",
                               i, attempt, exc, wait)
                time.sleep(wait)

        if not scored:
            logger.error("Batch %d failed after %d attempts — using fallback", i, max_retries)
            scored = _fallback_results(batch)

        for item in scored:
            results[item["id"]] = item

        # Groq free tier: ~30 req/min = 2s minimum between requests
        # Use 4s to stay safely under limit and avoid 429s
        if i + batch_size < len(articles):
            time.sleep(4.0)

    # Return in original order
    out = []
    for art in articles:
        aid = str(art["id"])
        out.append(results.get(aid, {
            "id": aid, "score": 0.0,
            "label": "neutral", "reasoning": "Not scored",
        }))

    logger.info("Scored %d articles — pos: %d, neu: %d, neg: %d",
                len(out),
                sum(1 for r in out if r["label"] == "positive"),
                sum(1 for r in out if r["label"] == "neutral"),
                sum(1 for r in out if r["label"] == "negative"))

    return out