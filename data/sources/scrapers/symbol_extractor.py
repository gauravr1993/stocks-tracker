"""
data/sources/scrapers/symbol_extractor.py
Two-stage symbol extraction:
  Stage 1: Fast keyword matching against company name + symbol aliases (free)
  Stage 2: Groq API LLM tagging for articles that didn't match (cheap + accurate)

Usage:
    extractor = SymbolExtractor()
    symbol_map = extractor.extract_batch(articles)
    # Returns {article.url: "RELIANCE" or None}
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from .base import RawArticle

logger = logging.getLogger(__name__)

# ── Company alias map ─────────────────────────────────────────────────────────
# symbol → list of names/aliases to match in headlines
# Covers common abbreviations, brand names, and alternate spellings
COMPANY_ALIASES: dict[str, list[str]] = {
    "RELIANCE":    ["reliance", "ril", "reliance industries", "jio"],
    "TCS":         ["tcs", "tata consultancy"],
    "HDFCBANK":    ["hdfc bank", "hdfcbank"],
    "ICICIBANK":   ["icici bank", "icicibank"],
    "INFY":        ["infosys", "infy"],
    "HINDUNILVR":  ["hindustan unilever", "hul"],
    "ITC":         ["itc ltd", "itc limited"],
    "SBIN":        ["sbi", "state bank", "state bank of india"],
    "BHARTIARTL":  ["airtel", "bharti airtel"],
    "KOTAKBANK":   ["kotak mahindra", "kotak bank"],
    "LT":          ["larsen", "l&t", "larsen and toubro", "larsen & toubro"],
    "AXISBANK":    ["axis bank"],
    "ASIANPAINT":  ["asian paints"],
    "MARUTI":      ["maruti", "maruti suzuki"],
    "SUNPHARMA":   ["sun pharma", "sun pharmaceutical"],
    "TITAN":       ["titan company", "titan watch"],
    "BAJFINANCE":  ["bajaj finance"],
    "WIPRO":       ["wipro"],
    "ULTRACEMCO":  ["ultratech cement", "ultratech"],
    "HCLTECH":     ["hcl tech", "hcl technologies"],
    "NTPC":        ["ntpc"],
    "POWERGRID":   ["power grid", "powergrid"],
    "ONGC":        ["ongc", "oil and natural gas"],
    "COALINDIA":   ["coal india"],
    "NESTLEIND":   ["nestle india", "nestle"],
    "JSWSTEEL":    ["jsw steel"],
    "TATAMOTORS":  ["tata motors"],
    "TATASTEEL":   ["tata steel"],
    "ADANIENT":    ["adani enterprises"],
    "ADANIPORTS":  ["adani ports"],
    "BAJAJFINSV":  ["bajaj finserv"],
    "TECHM":       ["tech mahindra"],
    "GRASIM":      ["grasim"],
    "CIPLA":       ["cipla"],
    "DRREDDY":     ["dr reddy", "dr. reddy"],
    "EICHERMOT":   ["eicher motors", "royal enfield"],
    "APOLLOHOSP":  ["apollo hospitals", "apollo hospital"],
    "DIVISLAB":    ["divi's lab", "divis lab", "divi laboratories"],
    "SBILIFE":     ["sbi life"],
    "HDFCLIFE":    ["hdfc life"],
    "BPCL":        ["bpcl", "bharat petroleum"],
    "INDUSINDBK":  ["indusind bank"],
    "TATACONSUM":  ["tata consumer"],
    "BRITANNIA":   ["britannia"],
    "HEROMOTOCO":  ["hero motocorp", "hero moto"],
    "HINDZINC":    ["hindustan zinc"],
    "VEDL":        ["vedanta"],
    "UPL":         ["upl"],
    "SHREECEM":    ["shree cement"],
    "PIDILITIND":  ["pidilite"],
    "DMART":       ["dmart", "avenue supermarts", "d-mart"],
    "BAJAJ-AUTO":  ["bajaj auto"],
    "HAVELLS":     ["havells"],
    "MUTHOOTFIN":  ["muthoot finance"],
    "DABUR":       ["dabur"],
    "COLPAL":      ["colgate", "colgate palmolive"],
    "MARICO":      ["marico"],
    "BERGEPAINT":  ["berger paints"],
    "GODREJCP":    ["godrej consumer"],
    "SIEMENS":     ["siemens india", "siemens"],
    "ZOMATO":      ["zomato"],
    "NAUKRI":      ["info edge", "naukri"],
    "IRCTC":       ["irctc"],
    "LICI":        ["lic", "life insurance corporation"],
    "ADANIGREEN":  ["adani green"],
    "ADANIPOWER":  ["adani power"],
    "HAL":         ["hal", "hindustan aeronautics"],
    "BEL":         ["bel", "bharat electronics"],
    "TATAPOWER":   ["tata power"],
    "TRENT":       ["trent", "westside"],
    "POLYCAB":     ["polycab"],
    "SBICARD":     ["sbi card"],
    "RECLTD":      ["rec ltd", "rural electrification"],
    "PFC":         ["pfc", "power finance"],
}

# Build reverse lookup: alias → symbol (lowercased for matching)
_ALIAS_TO_SYMBOL: dict[str, str] = {}
for sym, aliases in COMPANY_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_SYMBOL[alias.lower()] = sym
    _ALIAS_TO_SYMBOL[sym.lower()] = sym   # symbol itself is also an alias


# ── Stage 1: keyword matching ─────────────────────────────────────────────────

def _keyword_match(text: str) -> Optional[str]:
    """
    Try to find a NIFTY 100 company in text using alias matching.
    Returns NSE symbol or None.
    """
    text_lower = text.lower()

    # Sort by alias length descending to match longer phrases first
    # (avoids "sbi" matching inside "sbi life" before "sbi life" does)
    for alias in sorted(_ALIAS_TO_SYMBOL.keys(), key=len, reverse=True):
        # Word-boundary match to avoid "tcs" matching "electronics"
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, text_lower):
            return _ALIAS_TO_SYMBOL[alias]

    return None


# ── Stage 2: Groq API tagging ─────────────────────────────────────────────────

def _build_groq_system() -> str:
    known_str = ", ".join(sorted(COMPANY_ALIASES.keys()))
    return f"""You are a financial news tagger for Indian stock markets (NSE/BSE).

Your job: given a news headline and optional description, return the PRIMARY NSE stock symbol the article is about.

RULES:
1. Only return a symbol from this exact list: {known_str}
2. If the article covers multiple companies, return the PRIMARY one (most mentioned / most affected)
3. If the article is general market news (index moves, RBI policy, budget, FII flows, crude oil) return null
4. If you are not confident (>70% sure), return null
5. Common aliases to recognise: RIL=RELIANCE, Infy=INFY, HUL=HINDUNILVR, SBI=SBIN, Kotak=KOTAKBANK, L&T=LT

OUTPUT FORMAT — strict JSON only, no markdown, no explanation:
{{"symbol": "SYMBOL"}} or {{"symbol": null}}

EXAMPLES:
Headline: "Reliance Industries Q3 profit jumps 18% on Jio growth" → {{"symbol": "RELIANCE"}}
Headline: "Sensex falls 500 points on weak global cues" → {{"symbol": null}}
Headline: "Infosys raises FY25 revenue guidance after strong Q2" → {{"symbol": "INFY"}}
Headline: "RBI keeps repo rate unchanged at 6.5%" → {{"symbol": null}}
Headline: "TCS wins $500 million deal from US bank" → {{"symbol": "TCS"}}
Headline: "Adani Enterprises shares surge 8% after index inclusion" → {{"symbol": "ADANIENT"}}"""


_GROQ_SYSTEM = _build_groq_system()


def _groq_tag(articles: list[RawArticle], api_key: str) -> dict[str, Optional[str]]:
    """
    Use Groq API to tag a batch of articles that keyword matching couldn't resolve.
    Returns {url: symbol_or_None}
    """
    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq package not installed — run: pip install groq")
        return {a.url: None for a in articles}

    client = Groq(api_key=api_key)
    results: dict[str, Optional[str]] = {}

    # Process in small batches to stay within rate limits
    BATCH = 10
    for i in range(0, len(articles), BATCH):
        batch = articles[i: i + BATCH]
        for art in batch:
            prompt = f"Headline: {art.title}\nDescription: {art.description[:300]}"
            try:
                response = client.chat.completions.create(
                    model="openai/gpt-oss-120b",    # fast + free tier
                    messages=[
                        {"role": "system",  "content": _GROQ_SYSTEM},
                        {"role": "user",    "content": prompt},
                    ],
                    max_tokens=50,
                    temperature=0.0,
                )
                raw = response.choices[0].message.content.strip()

                # Strip any accidental markdown fences
                raw = re.sub(r"```json|```", "", raw).strip()

                parsed = json.loads(raw)
                sym = parsed.get("symbol")

                # Strict validation — must be in our known symbol list
                if sym and isinstance(sym, str) and sym.upper() in COMPANY_ALIASES:
                    results[art.url] = sym.upper()
                    logger.debug("Groq tagged '%s...' → %s", art.title[:40], sym.upper())
                else:
                    results[art.url] = None
            except Exception as exc:
                logger.debug("Groq tag failed for '%s': %s", art.title[:50], exc)
                results[art.url] = None

        # Respect Groq free tier rate limit (~30 req/min)
        if i + BATCH < len(articles):
            time.sleep(2.0)

    return results


# ── Main extractor ────────────────────────────────────────────────────────────

class SymbolExtractor:
    """
    Two-stage symbol extractor.
    Stage 1: fast keyword match (free)
    Stage 2: Groq LLM for unmatched articles (optional, needs GROQ_API_KEY)
    """

    def __init__(self, use_groq: bool = True):
        self.use_groq = use_groq
        self.api_key  = os.environ.get("GROQ_API_KEY")
        if use_groq and not self.api_key:
            logger.warning("GROQ_API_KEY not set — LLM fallback disabled, keyword-only mode")
            self.use_groq = False

    def extract_batch(self, articles: list[RawArticle]) -> dict[str, Optional[str]]:
        """
        Extract symbols for a list of articles.

        Returns:
            {article.url: "NSE_SYMBOL" or None}
        """
        results: dict[str, Optional[str]] = {}
        unmatched: list[RawArticle] = []

        # Stage 1: keyword match
        for art in articles:
            combined = f"{art.title} {art.description}"
            sym = _keyword_match(combined)
            if sym:
                results[art.url] = sym
            else:
                unmatched.append(art)

        matched_count = len(articles) - len(unmatched)
        logger.info("Keyword match: %d/%d articles matched", matched_count, len(articles))

        # Stage 2: Groq for unmatched
        if unmatched and self.use_groq:
            logger.info("Groq tagging %d unmatched articles...", len(unmatched))
            groq_results = _groq_tag(unmatched, self.api_key)
            results.update(groq_results)
            groq_matched = sum(1 for v in groq_results.values() if v)
            logger.info("Groq match: %d/%d additional articles tagged", groq_matched, len(unmatched))
        else:
            # Mark remaining as None
            for art in unmatched:
                results[art.url] = None

        total_matched = sum(1 for v in results.values() if v)
        logger.info("Final: %d/%d articles have a symbol", total_matched, len(articles))
        return results