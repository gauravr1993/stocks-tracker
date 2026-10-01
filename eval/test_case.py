EVAL_CASES = [
    {
        "id": "grounding_01",
        "query": "What are the safest stocks to buy right now?",
        "expected_tools": ["run_screener_tool"],
        "checks": [
            "Does NOT invent a 'safety' proxy from unrelated scores",
            "Explicitly states which scores are available and offers a reframe",
        ],
        "known_bad_response": "Composite/sector/value re-labeled as a 'safety cushion'",
        "status": "fixed",  # after system prompt update
    },
    {
        "id": "null_handling_01",
        "query": "What are the current sentiment scores for HDFC AMC?",
        "expected_tools": ["sentiment_lookup_tool"],
        "checks": [
            "Reports no data available rather than guessing",
            "Does not default null to neutral/positive",
        ],
        "status": "pass",
    },
    {
        "id": "sort_dimension_01",
        "query": "Find undervalued momentum stocks in NIFTY 50",
        "expected_tools": ["run_screener_tool"],
        "checks": [
            "Sorts/filters by value_score and momentum_score, not composite_score",
        ],
        "known_bad_response": "Composite-sorted top 10 missed value+momentum standouts",
        "status": "fixed",  # after sort_by param added
    },
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
        "id": "sentiment_rankings_01",
        "query": "What are the most positive sentiment stocks?",
        "expected_tools": ["sentiment_rankings_tool"],
        "checks": [
            "Returns stocks ranked by sentiment score",
        ],
        "status": "pass",
        "trace_url": None,
    },
    {
        "id": "sentiment_lookup_01",
        "query": "What is the sentiment for TCS?",
        "expected_tools": ["sentiment_lookup_tool"],
        "checks": [
            "Returns sentiment score for TCS",
        ],
        "status": "pass",
        "trace_url": None,
    },
    {
        "id": "all_tools_01",
        "query": "Give me a full picture of TCS — fundamentals, recent news, sentiment, and its composite/value/momentum scores.",
        "expected_tools": ["run_screener_tool", "fundamentals_lookup_tool", "sentiment_lookup_tool"],
        "checks": [
            "Calls screener with symbols=[TCS]",
            "Calls fundamentals_lookup_tool for TCS",
            "Calls sentiment_lookup_tool for TCS",
            "Returns a summary of all three results",
        ],
        "status": "pass",
        "trace_url": None,
        "Warning": "TCS's value score (44.3) is relatively high, suggesting the model sees it as comparatively cheap relative to its peers — 44.3 is a raw score with no stated scale or peer comparison in what the tool actually returns. Calling it \"relatively high\" implies a ranking context the tool didn't provide in this response"
    }
]