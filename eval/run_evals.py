# evals/run_evals.py
from eval.test_cases import EVAL_CASES
from langchain_core.messages import SystemMessage, HumanMessage

def run_case(case, agent, system_prompt, n=3):
    results = []
    for i in range(n):
        out = agent.invoke(
            {"messages": [SystemMessage(system_prompt), HumanMessage(case["query"])]},
            config={"tags": [case["id"]], "metadata": {"run_idx": i}},
        )
        results.append(out["messages"][-1].content)
    return results

def run_all(agent, system_prompt, n=3):
    report = {}
    for case in EVAL_CASES:
        print(f"Running {case['id']} ({n}x)...")
        report[case["id"]] = run_case(case, agent, system_prompt, n=n)
    return report