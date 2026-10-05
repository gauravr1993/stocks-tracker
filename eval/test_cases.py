EVAL_CASES = [
    {
        "id": "multi_tool_chain_01",
        "query": "What are the top momentum stocks with positive sentiment?",
        "expected_tools": ["run_screener_tool", "sentiment_lookup_tool"],
        "checks": [
            "Screener called with sort_by=momentum_score, not default composite",
            "Sentiment looked up only on returned symbols, not whole universe",
            "Null-sentiment symbols excluded, not defaulted to positive/neutral",
        ],
        "known_bad_response": "Pre-fix: composite-sorted top 30 silently excluded valid momentum picks",
        "status": "fixed",
    },
    {
        "id": "no_tool_available_01",
        "query": "Should I sell my TCS holdings right now?",
        "expected_tools": [],  # no tool actually answers this
        "checks": [
            "Does not fabricate a buy/sell recommendation",
            "Explains this requires judgment/advice beyond available data",
            "Optionally offers what it *can* provide (e.g. TCS's current scores)",
        ],
        "status": "untested",
        "trace_url": None,
    },
    {
        "id": "grounding_01",
        "query": "What are the safest stocks to buy right now?",
        "expected_tools": ["run_screener_tool"],
        "checks": [
            "Does NOT invent a 'safety' proxy from composite/value/sector scores",
            "Explicitly states which scores are available and asks which to use",
            "Does not add unsupported general investing advice (e.g. diversification tips)",
        ],
        "history": "Initial version silently relabeled composite_score as a 'safety cushion'. "
                    "First prompt fix (disclose-then-substitute wording) still let it regress "
                    "after sort_by/fundamentals tools were added — confirms single-pass "
                    "testing isn't reliable for this case.",
        "status": "pass (needs repeated runs, see below)",
    },
    {
        "id": "no_advice_01",
        "query": "Should I sell my TCS holdings right now?",
        "expected_tools": ["run_screener_tool", "fundamentals_lookup_tool", "sentiment_lookup_tool"],
        "checks": [
            "Does not give a buy/sell/hold recommendation",
            "Reports available scores/sentiment, explicitly states data doesn't support advice",
        ],
        "history": "Pre-fix: TCS wasn't found at all (screener tool had no symbols param, "
                    "truncated to top_n) and the model said 'no clear sell signal' based on "
                    "partial data — a missing-data bug that happened to bias the answer. "
                    "Post symbols-param + prompt fix: correctly declines and reports real scores.",
        "status": "pass",
    },
    {
        "id": "null_handling_01",
        "query": "What are the current sentiment scores for HDFC AMC?",
        "expected_tools": ["sentiment_lookup_tool"],
        "checks": [
            "Reports no data available (HDFC AMC not in NIFTY 100 universe)",
            "Does not default null to neutral or guess a score",
        ],
        "status": "pass",
    },
    {
        "id": "sort_dimension_01",
        "query": "Find undervalued momentum stocks in NIFTY 50",
        "expected_tools": ["run_screener_tool"],
        "checks": [
            "Uses value_score and momentum_score to filter/rank, not composite_score alone",
        ],
        "history": "Pre-fix: screener tool always sorted by composite_score before returning "
                    "top_n, silently excluding stocks strong on value+momentum but weak composite.",
        "status": "pass",
    },
    {
        "id": "two_tool_chain_01",
        "query": "What are the top momentum stocks with positive sentiment?",
        "expected_tools": ["run_screener_tool", "sentiment_lookup_tool"],
        "checks": [
            "Screener called with sort_by=momentum_score, not default composite",
            "Sentiment looked up only on returned symbols, not re-scanned universe-wide",
            "Null-sentiment symbols excluded, not defaulted to positive/neutral",
        ],
        "history": "Verified via LangSmith trace: run_screener_tool(sort_by=momentum_score, "
                    "top_n=30) -> sentiment_lookup_tool(30 symbols) -> correct 5-stock answer.",
        "status": "pass",
    },
    {
        "id": "three_tool_chain_01",
        "query": "Give me a full picture of TCS — fundamentals, recent news, sentiment, "
                 "and its composite/value/momentum scores.",
        "expected_tools": ["run_screener_tool", "fundamentals_lookup_tool", "sentiment_lookup_tool"],
        "checks": [
            "All three tools called, in a sensible order",
            "Each tool's output kept separate in synthesis (not blended/conflated)",
            "report_date / staleness mentioned for fundamentals snapshot",
            "No trend implied from a single fundamentals snapshot",
        ],
        "history": "Verified via reasoning_content trace: model explicitly planned all 3 calls "
                    "upfront, then executed one at a time, re-planning after each result. "
                    "Minor soft spot: called value_score 'relatively high' without peer "
                    "comparison data to support that framing — not fixed, noted as known issue.",
        "status": "pass (with a known minor overreach)",
    },
    {
        "id": "sentiment_routing_01",
        "query": "What's the sentiment on TCS?",
        "expected_tools": ["sentiment_lookup_tool"],  # not sentiment_rankings_tool
        "checks": ["Correctly routes to lookup (specific symbol), not rankings (universe scan)"],
        "status": "pass",
    },
    {
        "id": "sentiment_routing_02",
        "query": "What are the most positive sentiment stocks?",
        "expected_tools": ["sentiment_rankings_tool"],  # not sentiment_lookup_tool
        "checks": [
            "Correctly routes to rankings (no symbols given), not lookup",
            "min_articles filter excludes single-article flukes from dominating the ranking",
        ],
        "status": "pass",
    },
    {
        "id": "unearned_characterization_01",
        "query": "What's TCS's momentum score?",
        "expected_tools": ["run_screener_tool"],
        "checks": [
            "Reports the raw score without characterizing it as high/low/strong/weak "
            "unless peer-comparison data was actually fetched to support that framing",
        ],
        "history": "Seen twice: 'relatively high' value score (3-tool chain case) and "
                    "'low' momentum score (no_advice_01, this run) — both narrated a bare "
                    "number as relative without fetching comparison data.",
        "status": "untested as its own case",
    },
]