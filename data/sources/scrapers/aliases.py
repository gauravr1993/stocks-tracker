"""
data/sources/scrapers/aliases.py

Company-name matching for the NIFTY universe.

  names  : {symbol: company_name}  read from nifty_constituents (symbol, company_name)
  EXTRAS : small hand-curated dict  brands, old names and abbreviations the legal name lacks

tag() returns a status so the caller never has to guess:
  tagged       one or two companies named unambiguously -> safe to tag
  market_wrap  three or more companies in one headline  -> no per-stock tag
  needs_check  alias is an ordinary word or is shared   -> ask the LLM, passing the candidates
  none         no company found
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

LEGAL_SUFFIXES = {"limited", "ltd", "corporation", "corp", "company", "co", "inc", "pvt", "private"}

# A hit on one of these is only a candidate: ordinary words, first names, or names that
# also belong to a bigger foreign group (parents of Indian subsidiaries).
AMBIGUOUS = {"eternal", "titan", "trent", "reliance", "hal", "bel", "ioc", "ltm", "rec",
             "indigo", "bosch", "siemens", "siemens energy", "hyundai", "hyundai motor",
             "abb", "cummins", "nestle", "westside", "gail", "union bank", "power grid", "pfc", "chola"}

# Names of companies NOT in the universe that share a word with one that is. Matching one
# uses up that text (so "sbi" inside "SBI Card" is not read as State Bank) and tags nothing.
DECOYS = ["sbi card", "sbi mutual fund", "sbi funds", "sbi general", "sbi shinsei",
          "mahindra finance", "mahindra lifespace", "mahindra logistics", "mahindra holidays",
          "reliance power", "reliance infrastructure", "reliance infra",
          "reliance communications", "reliance capital", "reliance nippon",
          # ITC is also GST input tax credit, the US International Trade Commission, and ITC Hotels (separately listed)
          "itc claim", "itc claims", "itc refund", "input tax credit", "itc hearing", "itc hotels",
          # separate Chola group companies (and "chola" is also a dynasty)
          "chola ms", "cholamandalam ms", "cholamandalam financial holdings", "chola securities",
          # Mahindra & Mahindra Financial Services is a separate listing; "m and m" is how "M&M" normalises
          "mahindra and mahindra financial services", "mahindra and mahindra finance",
          "m and m finance", "m and m financial services"]

# Aliases are normalised (lowercase, no accents or punctuation, "&" -> "and"), so write
# them that way. Tickers and legal-name variants are generated automatically.
EXTRAS: dict[str, list[str]] = {
    "RELIANCE.NS":   ["ril", "reliance", "jio", "jio platforms", "reliance jio", "reliance retail"],
    "JIOFIN.NS":     ["jio finance", "jio financial"],
    "ETERNAL.NS":    ["zomato", "blinkit"],
    "TITAN.NS":      ["titan co", "tanishq", "fastrack"],
    "TRENT.NS":      ["westside", "zudio"],
    "INDIGO.NS":     ["interglobe"],
    "DMART.NS":      ["dmart", "d mart"],
    "SBIN.NS":       ["sbi"],
    "SBILIFE.NS":    ["sbi life"],
    "HDFCLIFE.NS":   ["hdfc life"],
    "HDFCAMC.NS":    ["hdfc amc"],
    "HINDUNILVR.NS": ["hul"],
    "LT.NS":         ["l and t"],
    "M&M.NS":        ["mahindra"],
    "LTM.NS":        ["ltimindtree", "ltim"],
    "ADANIPORTS.NS": ["adani ports"],
    "ADANIENSOL.NS": ["adani energy"],
    "ADANIGREEN.NS": ["adani green"],
    "IOC.NS":        ["iocl", "indianoil"],
    "KOTAKBANK.NS":  ["kotak bank"],
    "BHARTIARTL.NS": ["airtel"],
    "MARUTI.NS":     ["maruti"],
    "SUNPHARMA.NS":  ["sun pharma"],
    "DRREDDY.NS":    ["dr reddys", "dr reddy"],
    "DIVISLAB.NS":   ["divis lab", "divis labs"],
    "NESTLEIND.NS":  ["nestle"],
    "HINDALCO.NS":   ["hindalco"],
    "CHOLAFIN.NS":   ["chola", "cholamandalam"],
    "TATACONSUM.NS": ["tata consumer"],
    "INDHOTEL.NS":   ["taj hotels", "ihcl"],
    "APOLLOHOSP.NS": ["apollo hospitals"],
    "MAXHEALTH.NS":  ["max healthcare"],
    "ZYDUSLIFE.NS":  ["zydus"],
    "TORNTPHARM.NS": ["torrent pharma"],
    "GODREJCP.NS":   ["godrej consumer", "gcpl", "godrej professional", "godrej aer", "goodknight", "cinthol"],
    "PIDILITIND.NS": ["pidilite"],
    "AMBUJACEM.NS":  ["ambuja cement"],
    "CGPOWER.NS":    ["cg power"],
    "CUMMINSIND.NS": ["cummins"],
    "MAZDOCK.NS":    ["mazagon dock", "mazdock"],
    "UNIONBANK.NS":  ["union bank"],
    "POWERGRID.NS":  ["power grid"],
    "ULTRACEMCO.NS": ["ultratech"],
    "HCLTECH.NS":    ["hcl tech"],
    "BAJAJHLDNG.NS": ["bajaj holdings"],
    "EICHERMOT.NS":  ["royal enfield"],
    "MOTHERSON.NS":  ["motherson"],
    "GAIL.NS":       ["gail india"],
    "RECLTD.NS":     ["rural electrification corporation"],
    "SHREECEM.NS":   ["shree cements"],
    "LODHA.NS":      ["lodha", "macrotech"],
    "HYUNDAI.NS":    ["hyundai india", "hmil"],
    # Tata Motors split in two: the bare name belongs to BOTH, so it is a collision on
    # purpose and gets resolved from context words below.
    "TMPV.NS":       ["tata motors", "jaguar land rover", "jlr"],
    "TMCV.NS":       ["tata motors"],
}

PV_WORDS = ("passenger", "jlr", "jaguar", "land rover", "nexon", "harrier", "safari", "punch", "tiago", "curvv")
CV_WORDS = ("commercial vehicle", "commercial vehicles", "truck", "trucks", "bus", "buses", "tipper")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"['’`]", "", s)           # divi's -> divis
    s = re.sub(r"[^a-z0-9 ]+", " ", s)    # punctuation -> space
    return re.sub(r"\s+", " ", s).strip()


def name_variants(company_name: str) -> set[str]:
    """Legal name with trailing suffixes peeled off one at a time ("titan company", then "titan")."""
    n = norm(re.sub(r"\(.*?\)", " ", company_name))
    words = n.split()
    if words and words[0] == "the":
        words = words[1:]
    out = {" ".join(words)}
    while words and words[-1] in LEGAL_SUFFIXES:
        words = words[:-1]
        out.add(" ".join(words))
    # "Maruti Suzuki India" -> "maruti suzuki", but not "Coal India" -> "coal" or "... of India"
    if len(words) > 2 and words[-1] == "india" and words[-2] != "of":
        out.add(" ".join(words[:-1]))
    for v in list(out):                  # headlines write "Bosch Ltd" far more often than "Bosch Limited"
        if v.endswith(" limited"):
            out.add(v[: -len(" limited")] + " ltd")
    return {v for v in out if len(v) >= 3}


class AliasMatcher:
    def __init__(self, names: dict[str, str], extras: dict[str, list[str]] = EXTRAS):
        owners: dict[str, set[str]] = defaultdict(set)
        for sym, name in names.items():
            for a in name_variants(name):
                owners[a].add(sym)
            ticker = norm(sym.split(".")[0])
            if len(ticker) >= 3:
                owners[ticker].add(sym)
        for sym, extra in extras.items():
            for a in extra:
                owners[norm(a)].add(sym)
        for d in DECOYS:
            owners.setdefault(norm(d), set())
        self.owners = dict(owners)
        self._order = sorted(self.owners, key=len, reverse=True)   # longest first
        self._pats = {a: re.compile(rf"\b{re.escape(a)}\b") for a in self._order}

    def match(self, headline: str) -> list[dict]:
        text = norm(headline)
        taken: list[tuple[int, int]] = []
        hits = []
        for alias in self._order:
            for m in self._pats[alias].finditer(text):
                s, e = m.span()
                if any(s < te and e > ts for ts, te in taken):   # already inside a longer match
                    continue
                taken.append((s, e))
                owners = sorted(self.owners[alias])
                if not owners:               # decoy
                    continue
                hits.append({"alias": alias, "symbols": owners,
                             "sure": len(owners) == 1 and alias not in AMBIGUOUS})
        return hits

    def tag(self, headline: str, wrap_at: int = 3) -> dict:
        text = norm(headline)
        resolved = []
        for h in self.match(headline):
            syms, sure = h["symbols"], h["sure"]
            if set(syms) == {"TMPV.NS", "TMCV.NS"}:
                pv = any(re.search(rf"\b{w}\b", text) for w in PV_WORDS)
                cv = any(re.search(rf"\b{w}\b", text) for w in CV_WORDS)
                if pv != cv:
                    syms, sure = (["TMPV.NS"] if pv else ["TMCV.NS"]), True
            resolved.append((syms, sure))
        distinct = sorted({s for syms, _ in resolved for s in syms})
        # an ambiguous word next to a clear alias of the same company is corroborated
        # ("Trent ... Zudio", "Eternal ... Blinkit"), so it no longer needs an LLM check
        sure_syms = {s for syms, sure in resolved if sure for s in syms}
        resolved = [(syms, sure or set(syms) <= sure_syms) for syms, sure in resolved]
        if len(distinct) >= wrap_at:
            return {"status": "market_wrap", "symbols": []}
        if any(not sure for _, sure in resolved):
            return {"status": "needs_check", "symbols": [], "candidates": distinct}
        if distinct:
            return {"status": "tagged", "symbols": distinct}
        return {"status": "none", "symbols": []}


def coverage_report(names: dict[str, str], matcher: AliasMatcher) -> dict:
    """Run whenever aliases change. Every list should be empty except intended collisions."""
    covered = {s for owners in matcher.owners.values() for s in owners}
    return {
        "missing":    sorted(set(names) - covered),
        "collisions": {a: sorted(o) for a, o in matcher.owners.items() if len(o) > 1},
        "orphans":    sorted(set(EXTRAS) - set(names)),
    }