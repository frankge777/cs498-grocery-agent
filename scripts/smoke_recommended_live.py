#!/usr/bin/env python3
"""Read real Kroger products and exercise draft acceptance in a LOCAL cart."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_web import interactive_service  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-id", default="02100946")
    parser.add_argument("--instruction", default="Buy exactly 12 large chicken eggs in total under $5, nothing else.")
    parser.add_argument("--accept", action="store_true", help="accept the draft in the local simulated cart")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new path")
    result = interactive_service.start(args.instruction, source="live", location_id=args.location_id)
    steps = [{k: v for k, v in result.items() if k != "session_token"}]
    if args.accept and result["status"] == "awaiting_basket_confirmation":
        result = interactive_service.resume(result["session_token"], recommendation_answer={
            "recommendation_id": result["recommendation"]["recommendation_id"], "action": "accept"})
        steps.append({k: v for k, v in result.items() if k != "session_token"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"instruction": args.instruction, "source": "live",
        "cart_mode": "local simulation only", "auto_accept_local_draft": args.accept, "steps": steps}, indent=2))
    print(json.dumps({"statuses": [s["status"] for s in steps], "output": str(args.output)}))


if __name__ == "__main__":
    main()
