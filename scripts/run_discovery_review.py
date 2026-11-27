#!/usr/bin/env python3
"""Run the semantic-review development fixtures against the configured model (paid API)."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.discovery import ModelDiscovery  # noqa: E402
from grocery_agent.llm import DeepSeekClient  # noqa: E402
from grocery_bench.data import Scenario  # noqa: E402
from grocery_bench.environment import GroceryEnv  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    data = json.loads((ROOT / "benchmark/discovery_review_development.json").read_text())
    llm = DeepSeekClient(temperature=0, **({"model": args.model} if args.model else {}))
    discovery = ModelDiscovery(llm)
    results = []
    for case in data["cases"]:
        scenario = Scenario(id=case["id"], category="development", difficulty="M", title=case["id"],
            variants={v: case["request"] for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True)
        env = GroceryEnv({}, scenario, "high")
        reviews = discovery.review(env, case["requirement"], case["products"])
        actual = {row["product_id"]: row["verdict"] for row in reviews}
        results.append({"id": case["id"], "passed": actual == case["expected"],
                        "actual": actual, "reviews": reviews, "model_calls": env.model_calls})
    print(json.dumps({"version": data["version"], "model": llm.describe(),
        "data_source": "synthetic development fixtures, not live Kroger",
        "passed": sum(r["passed"] for r in results), "total": len(results), "results": results}, indent=2))
    if not all(row["passed"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
