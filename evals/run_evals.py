"""
evals/run_evals.py

    from evals.run_evals import run_all
    report = run_all(myAgent, SYSTEM_PROMPT, n=3)

Runs every case n times and checks the tool calls (names, arguments, order) and the final
answer. Set LANGCHAIN_PROJECT="nifty-agent-evals" first so eval traces stay out of your
dev project; each run is tagged with its case id.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from evals.cases import EVAL_CASES

RESULTS_DIR = Path(__file__).parent / "results"


_TYPO = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                       "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
                       "\u2014": "-", "\u2212": "-"})


def normalize(text: str) -> str:
    """The model writes curly quotes, non-breaking hyphens and narrow no-break spaces; every
    regex in cases.py assumes plain ASCII. Without this a check can fail a good answer
    ("don\u2019t" does not match "n't") or, worse, let a bad one through."""
    text = re.sub(r"[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]", " ", text)
    return text.translate(_TYPO)


def retry_wait(exc: Exception) -> float | None:
    """Seconds to wait if this is a rate-limit error, else None. Reads Groq's 'try again in 6.84s'."""
    msg = str(exc)
    if "429" not in msg and "rate limit" not in msg.lower():
        return None
    secs = 20.0
    tok = re.search(r"try again in ([0-9.ms]+)", msg)
    if tok:
        t = tok.group(1).rstrip(".")
        if t.endswith("ms"):
            secs = float(t[:-2]) / 1000
        else:
            mm = re.fullmatch(r"(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", t)
            if mm and (mm.group(1) or mm.group(2)):
                secs = int(mm.group(1) or 0) * 60 + float(mm.group(2) or 0)
    return min(secs + 2.0, 90.0)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                       # content blocks
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def extract_trace(messages) -> dict:
    """Tool calls in order, plus the last AI message that is not itself a tool request."""
    calls, answer = [], ""
    for m in messages:
        tcs = getattr(m, "tool_calls", None) or []
        for c in tcs:
            calls.append({"name": c["name"], "args": c.get("args") or {}})
        if getattr(m, "type", "") == "ai" and not tcs:
            answer = _text(m.content)
    return {"calls": calls, "answer": answer}


def _arg_matches(value, allowed) -> bool:
    values = value if isinstance(value, list) else [value]
    return any(v in allowed for v in values)


def check_case(case: dict, trace: dict) -> list[str]:
    fails = []
    names = [c["name"] for c in trace["calls"]]
    for t in case.get("must_call", []):
        if t not in names:
            fails.append(f"did not call {t}")
    for t in case.get("forbid_tools", []):
        if t in names:
            fails.append(f"called {t}, which it should not")
    order = case.get("order", [])
    if order and all(t in names for t in order):
        idx = [names.index(t) for t in order]
        if idx != sorted(idx):
            fails.append("wrong tool order: " + " -> ".join(names))
    for tool, wanted in case.get("args", {}).items():
        calls = [c for c in trace["calls"] if c["name"] == tool]
        if not calls:
            continue                                     # a missing call is already reported above
        for arg, allowed in wanted.items():
            if not any(_arg_matches(c["args"].get(arg), allowed) for c in calls):
                got = [c["args"].get(arg) for c in calls]
                fails.append(f"{tool}.{arg} was {got}, expected one of {allowed}")
    ans = normalize(trace["answer"])
    if not ans.strip():
        fails.append("empty answer")
    for pat in case.get("must_include", []):
        if not re.search(pat, ans, re.I | re.S):
            fails.append(f"answer is missing /{pat[:50]}.../")
    for pat in case.get("must_not_include", []):
        m = re.search(pat, ans, re.I | re.S)
        if m:
            fails.append(f"answer contains '{m.group(0)[:70]}'")
    return fails


def run_case(case: dict, agent, system_prompt: str, n: int = 3, pause: float = 10.0,
             max_attempts: int = 4) -> list[dict]:
    runs = []
    for i in range(n):
        for attempt in range(1, max_attempts + 1):
            try:
                out = agent.invoke(
                    {"messages": [("system", system_prompt), ("user", case["query"])]},
                    config={"tags": [case["id"], "eval"], "metadata": {"run_idx": i}},
                )
                trace = extract_trace(out["messages"])
                fails = check_case(case, trace)
                runs.append({"ok": not fails, "failures": fails, "retries": attempt - 1,
                             "tools": [c["name"] for c in trace["calls"]], "answer": trace["answer"]})
                break
            except Exception as exc:
                wait = retry_wait(exc)
                if wait is not None and attempt < max_attempts:
                    print(f"  rate limited, waiting {wait:.0f}s (attempt {attempt}/{max_attempts})", flush=True)
                    time.sleep(wait)
                    continue
                # a crash is recorded as a failure, never silently skipped
                runs.append({"ok": False, "failures": [f"error: {type(exc).__name__}: {exc}"[:200]],
                             "retries": attempt - 1, "tools": [], "answer": ""})
                break
        if i < n - 1:
            time.sleep(pause)
    return runs


def run_all(agent, system_prompt: str, n: int = 3, case_ids: list[str] | None = None,
            pause: float = 10.0, save: bool = True) -> dict:
    cases = [c for c in EVAL_CASES if not case_ids or c["id"] in case_ids]
    report = {"when": datetime.now().isoformat(timespec="seconds"), "n": n, "cases": {}}
    for case in cases:
        print(f"running {case['id']} x{n} ...", flush=True)
        runs = run_case(case, agent, system_prompt, n=n, pause=pause)
        report["cases"][case["id"]] = {"query": case["query"], "passed": sum(r["ok"] for r in runs),
                                       "runs": runs, "status": case.get("status", "")}
        if case is not cases[-1]:
            time.sleep(pause)
    print_summary(report)
    if save:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(report, indent=2))
        print(f"\nsaved {path}")
    return report


def print_summary(report: dict) -> None:
    n = report["n"]
    print("\n" + "=" * 72)
    total = sum(c["passed"] for c in report["cases"].values())
    print(f"{total}/{n * len(report['cases'])} runs passed")
    for cid, c in report["cases"].items():
        mark = "PASS" if c["passed"] == n else ("FAIL" if c["passed"] == 0 else "FLAKY")
        errs = sum(any(f.startswith("error:") for f in r["failures"]) for r in c["runs"])
        note = f"  [{errs} crashed: rerun, says nothing about the agent]" if errs else ""
        print(f"{mark:<6}{c['passed']}/{n}  {cid}  {('(' + c['status'] + ')') if c['status'] else ''}{note}")
        seen = []
        for r in c["runs"]:
            for f in r["failures"]:
                if f not in seen:
                    seen.append(f)
        for f in seen[:4]:
            print(f"        - {f}")


def to_markdown(report: dict) -> str:
    """Paste into EVALS.md."""
    n = report["n"]
    lines = [f"Run {report['when']}, {n} runs per case", "",
             "| Case | Query | Pass rate | Failures seen |", "|---|---|---|---|"]
    for cid, c in report["cases"].items():
        fails = sorted({f for r in c["runs"] for f in r["failures"]})
        lines.append(f"| {cid} | {c['query'][:50]} | {c['passed']}/{n} | {'; '.join(fails)[:120]} |")
    return "\n".join(lines)