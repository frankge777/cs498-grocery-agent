#!/usr/bin/env python3
"""Run the intent-grounded agent against live Kroger product reads.

Search, product details, prices and availability come from Kroger. Cart changes
are local simulation only; this script cannot modify or submit a real cart.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.llm import DEFAULT_MODEL, DeepSeekClient  # noqa: E402
from grocery_agent.llm_agents import IntentGroundedLLMAgent  # noqa: E402
from grocery_bench.kroger import KrogerClient, KrogerConfigurationError, KrogerLiveEnv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, dest="zip_code", help="five-digit ZIP code")
    parser.add_argument("--instruction", required=True, help="shopping request for the agent")
    parser.add_argument("--location-id", help="use a specific Kroger location instead of the nearest result")
    parser.add_argument("--context-json", default="{}", help="household context as a JSON object")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--no-verifier", action="store_true")
    args = parser.parse_args()

    context = json.loads(args.context_json)
    if not isinstance(context, dict):
        raise SystemExit("--context-json must be a JSON object")
    try:
        client = KrogerClient()
    except KrogerConfigurationError as error:
        raise SystemExit(str(error)) from error
    location = client.get_location(args.location_id) if args.location_id else client.nearest_location(args.zip_code)
    env = KrogerLiveEnv(client, location, args.instruction, context)
    llm = DeepSeekClient(model=args.model, temperature=args.temperature)
    agent = IntentGroundedLLMAgent(llm, use_verifier=not args.no_verifier)
    agent.run(env)
    cart = env.view_cart().data if not env.done else {
        "items": [
            {**env.catalog[pid].public_summary(env.stock.get(pid, 0) > 0), "quantity": quantity,
             "line_total_cents": env.catalog[pid].price_cents * quantity}
            for pid, quantity in sorted(env.cart.items())
        ],
        "total_cents": env.total_cents,
    }
    print(json.dumps({
        "data_source": "Kroger Public API (live)",
        "location": env.observation()["location"],
        "cart_mode": "local simulation only",
        "cart": cart,
        "agent_notes": agent.notes,
        "tool_calls": env.tool_calls,
        "model_calls": env.model_calls,
    }, indent=2))


if __name__ == "__main__":
    main()
