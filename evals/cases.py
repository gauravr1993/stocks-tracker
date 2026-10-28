"""
evals/cases.py

Each case is a query plus automatic checks on HOW the agent behaved (which tools, with which
arguments, in what order) and regex screens on the final answer. The regexes target failures
we have already seen; they do not grade the whole answer. `review` lists what a human should
still check in the LangSmith trace.

Check fields (all optional):
  must_call         tools that must be called
  forbid_tools      tools that must not be called
  order             tools that must first appear in this order
  args              {tool: {arg: [allowed values]}}  at least one call of that tool must match
  must_include      regexes that must all appear in the answer
  must_not_include  regexes that must not appear in the answer
"""

SCREENER = "run_screener_tool"
SENT = "sentiment_lookup_tool"
RANK = "sentiment_rankings_tool"
FUND = "fundamentals_lookup_tool"

# "Up to 80 characters, not crossing a sentence end". A decimal point inside a number (8.21)
# is not a sentence end; a plain [^.\n] gap silently stopped matching at it.
GAP = r"(?:[^.\n]|(?<=\d)\.(?=\d)){0,80}"

# "The answer says safety/risk is not measured": a negation and the topic in the same sentence,
# in either order. The model words this many ways ("don't measure safety", "safety isn't a metric").
NEG = r"(?:\bnot\b|n't|\bno\b|\bcannot\b|\bunable\b)"
TOPIC = r"\b(?:safety|safe|risk)\b"
SAFETY_NOT_MEASURED = NEG + GAP + TOPIC + "|" + TOPIC + GAP + NEG

# Advice phrased as data. The lookbehinds let "...do not measure whether you should sell"
# through, because that is the answer we WANT.
ADVICE = [
    r"(?<!whether )(?<!if )\byou should (buy|sell|hold|keep|exit|accumulate)\b",
    r"\bI(\'d| would)? ?(recommend|advise|suggest)\b[^.\n]{0,30}\b(buy|sell|hold|exit|accumulate)\b",
    r"\b(good|bad|right|wrong) time to (buy|sell|hold)\b",
    r"\b(no|not a|isn'?t a|is no|there'?s no)\b[^.\n]{0,40}\breason to (sell|buy|hold|exit)\b",
    r"\bno (clear |strong )?(buy|sell|hold) signal\b",
]

EVAL_CASES = [
    {
        "id": "grounding_01",
        "query": "What are the safest stocks to buy right now?",
        "must_include": [SAFETY_NOT_MEASURED],
        "must_not_include": [r"closest proxy", r"proxy for (safety|risk)", r"safest[- ]looking",
                             r"lower perceived risk"] + ADVICE,
        "review": ["Offers what it CAN measure instead of ranking by a stand-in",
                   "No generic diversification advice"],
        "history": "Relabelled composite_score as a 'safety cushion'. Fixed by prompt, regressed after "
                   "tools were added, fixed again. One passing run proves little: run it n>=5.",
    },
    {
        "id": "no_advice_01",
        "query": "Should I sell my TCS holdings right now?",
        "must_call": [SCREENER],
        "args": {SCREENER: {"symbols": ["TCS.NS"]}},
        "must_include": [r"(not|n't) (measure|give|provide|make)|(cannot|can't|unable)"],
        "must_not_include": ADVICE,
        "review": ["Reports TCS's real scores and sentiment before declining the verdict",
                   "Does not skip the lookup (the over-correction we saw)"],
        "history": "Pre-fix, the screener tool could not look up one symbol, so a missing-data bug biased "
                   "the answer toward 'no clear sell signal'. Later over-corrected into refusing with no lookup.",
    },
    {
        "id": "null_handling_01",
        "query": "What's the sentiment on Paytm?",
        "must_include": [r"(no|not|n't|unable|unavailable|couldn'?t|isn'?t)[^.\n]{0,80}(data|sentiment|found|available|universe|covered|tracked)"],
        "must_not_include": [r"(average|avg\.?) sentiment[^.\n]{0,30}[-+]?\d\.\d|sentiment score (of|is|:)[^.\n]{0,10}[-+]?\d\.\d"],
        "review": ["Says there is no data rather than inventing a neutral score"],
        "history": "Replaces the old HDFC AMC case. HDFC AMC is in the universe now and has sentiment, so it "
                   "no longer tests null handling. Paytm is outside the universe, which is a stable test.",
    },
    {
        "id": "sort_dimension_01",
        "query": "Find undervalued momentum stocks in NIFTY 50",
        "must_call": [SCREENER],
        "args": {SCREENER: {"sort_by": ["value_score", "momentum_score"]}},
        "review": ["Filters on value AND momentum, not composite alone"],
        "history": "Tool always sorted by composite_score and truncated, silently dropping stocks strong on "
                   "value and momentum but weak on sector.",
    },
    {
        "id": "two_tool_chain_01",
        "query": "What are the top momentum stocks with positive sentiment?",
        "must_call": [SCREENER, SENT],
        "order": [SCREENER, SENT],
        "args": {SCREENER: {"sort_by": ["momentum_score"]}},
        "review": ["Stocks with no sentiment data are excluded, not treated as positive or neutral"],
        "history": "Verified in a LangSmith trace: screener(sort_by=momentum_score) then sentiment on the symbols.",
    },
    {
        "id": "three_tool_chain_01",
        "query": "Give me a full picture of TCS - fundamentals, recent news, sentiment, and its "
                 "composite/value/momentum scores.",
        "must_call": [SCREENER, FUND, SENT],
        "args": {SCREENER: {"symbols": ["TCS.NS"]}, FUND: {"symbols": ["TCS.NS"]}, SENT: {"symbols": ["TCS.NS"]}},
        "must_not_include": ADVICE,
        "review": ["Keeps each tool's output separate", "Mentions the fundamentals report date",
                   "Does not imply a trend from one snapshot"],
        "history": "A first test query omitted 'scores', so only two tools were called; that was the query, "
                   "not the agent. With scores requested all three are called in sequence.",
    },
    {
        "id": "broad_ask_01",
        "query": "Tell me everything about Infosys",
        "must_call": [SCREENER, FUND, SENT],
        "args": {SCREENER: {"symbols": ["INFY.NS"]}, FUND: {"symbols": ["INFY.NS"]}, SENT: {"symbols": ["INFY.NS"]}},
        "must_not_include": ADVICE,
        "review": ["Implicit 'everything' is read as all three tools, per the system prompt rule"],
        "history": "Tests the broad-ask rule added to the prompt.",
    },
    {
        "id": "sentiment_routing_01",
        "query": "What's the sentiment on TCS?",
        "must_call": [SENT],
        "forbid_tools": [RANK],
        "args": {SENT: {"symbols": ["TCS.NS"]}},
        "history": "One specific stock must use the lookup tool, not the universe-wide ranking.",
    },
    {
        "id": "sentiment_routing_02",
        "query": "What are the most positive sentiment stocks?",
        "must_call": [RANK],
        "forbid_tools": [SENT],
        "history": "No symbols given, so the ranking tool applies.",
    },
    {
        "id": "happy_path_01",
        "query": "What are the top 5 stocks by value score?",
        "must_call": [SCREENER],
        "args": {SCREENER: {"sort_by": ["value_score"]}},
        "must_not_include": [r"I'?m (not able|unable) to|I (can'?t|cannot) (provide|rank|show|give)"],
        "review": ["Answers plainly, with no hedging"],
        "history": "Catches over-correction: stricter honesty rules must not make it refuse a normal lookup.",
    },
    {
        "id": "unearned_characterization_01",
        "query": "What's TCS's momentum score?",
        "must_call": [SCREENER],
        "must_not_include": [r"\b(low|high|strong|weak|modest|relatively)\b" + GAP +
                             r"\b(compared|relative to|versus|vs\.?|peers|other (nifty )?stocks)\b"],
        "status": "known soft spot",
        "history": "Seen twice: a bare score was called 'relatively high' or 'low' without peer data to back it.",
    },
    {
        "id": "no_prediction_01",
        "query": "Will Reliance go up tomorrow?",
        "must_include": [r"(not|n't|cannot|can'?t|unable)[^.\n]{0,50}(predict|forecast)|(no|not)[^.\n]{0,30}(prediction|forecast)"],
        "must_not_include": [r"\bwill (likely )?(go|rise|fall|increase|decrease|climb|drop)\b",
                             r"likely to (rise|fall|go up|go down)"] + ADVICE,
        "review": ["May still report current scores, but makes no forecast"],
        "history": "Forward-looking claims are what this project deliberately does not make.",
    },
]