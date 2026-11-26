#!/usr/bin/env python3
"""Validate the new choice flow on real Kroger snapshot data, without model calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.choices import SimulatedChoiceProvider  # noqa: E402
from grocery_agent.interactive import InteractiveShoppingSession  # noqa: E402
from grocery_agent.llm_agents import normalize_intent  # noqa: E402
from grocery_bench import GroceryEnv, load_catalog  # noqa: E402
from grocery_bench.data import KROGER_CATALOG_PATH, Scenario  # noqa: E402


def run_case(case: dict, catalog: dict) -> dict:
    scenario = Scenario(
        id=case["id"], category="choice", difficulty="development", title=case["id"],
        variants={v: case["instruction"] for v in ("high", "medium", "low")},
        context={}, needs=[], events=case.get("stock_events", []), extras_allowed=True,
    )
    env = GroceryEnv(catalog, scenario, "high")
    intent = normalize_intent({**case["reference_intent"], "budget_cents": case["budget_cents"]})
    session = InteractiveShoppingSession(env, intent)
    provider = SimulatedChoiceProvider(case["simulated_user"])
    result = session.advance()
    question_rounds = []
    for _ in range(8):
        if result["status"] == "waiting_for_user":
            question_rounds.append([q["requirement_id"] for q in result["questions"]])
            choices = provider({"questions": result["questions"]})
            result = session.advance(choices)
        elif result["status"] == "budget_conflict" and case.get("budget_reconsider"):
            choice = case["budget_reconsider"]
            provider = SimulatedChoiceProvider(choice["simulated_user"])
            result = session.reconsider(choice["requirement_ids"])
        else:
            break
    passed = (result["status"] == "complete"
              and result["cart"] == case["expected_cart"]
              and question_rounds == case["expected_question_rounds"]
              and result["total_cents"] <= case["budget_cents"])
    return {"scenario_id": case["id"], "passed": passed, "status": result["status"],
            "cart": dict(env.cart), "total_cents": env.total_cents,
            "question_rounds": question_rounds, "tool_calls": env.tool_calls,
            "model_calls": env.model_calls}


def main() -> None:
    dataset = json.loads((ROOT / "benchmark" / "choice_scenarios_kroger.json").read_text(encoding="utf-8"))
    catalog = load_catalog(KROGER_CATALOG_PATH)
    results = [run_case(case, catalog) for case in dataset["scenarios"]]
    print(json.dumps({"version": dataset["version"], "passed": sum(r["passed"] for r in results),
                      "total": len(results), "results": results}, indent=2))
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
