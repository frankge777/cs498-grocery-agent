#!/usr/bin/env python3
"""Freeze real, store-specific Kroger product data into a JSON catalog.

This script only reads locations and products. It never changes a Kroger cart.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_bench.kroger import (  # noqa: E402
    KrogerClient,
    KrogerConfigurationError,
    normalize_kroger_product,
    product_to_snapshot_row,
)

DEFAULT_QUERIES = [
    "whole milk", "oat milk", "soy milk", "bread", "eggs", "bananas", "apples", "oranges",
    "berries", "rolled oats", "cereal", "rice", "pasta", "flour", "sugar", "pasta sauce",
    "black beans", "lentils", "tofu", "chicken breast", "carrots", "broccoli", "spinach",
    "frozen vegetables", "protein bars", "yogurt", "crackers", "popcorn", "trail mix",
    "protein powder", "creatine", "coffee", "tortillas", "salsa", "shredded cheese",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, dest="zip_code", help="five-digit ZIP code")
    parser.add_argument("--location-id", help="use a specific Kroger location instead of the nearest result")
    parser.add_argument("--chain", default="Kroger", help="chain filter used for automatic location selection")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    parser.add_argument("--limit", type=int, default=20, help="results per query (1-50)")
    parser.add_argument("--out", type=Path, help="output path; defaults under benchmark/kroger_snapshots")
    args = parser.parse_args()

    try:
        client = KrogerClient()
    except KrogerConfigurationError as error:
        raise SystemExit(str(error)) from error
    location = client.get_location(args.location_id) if args.location_id else client.nearest_location(args.zip_code, args.chain)
    location_id = str(location.get("locationId") or args.location_id or "")
    if not location_id:
        raise SystemExit("Kroger did not return a locationId")

    products = {}
    failures = []
    for query in args.queries:
        try:
            rows = client.search_products(query, location_id, limit=args.limit)
        except Exception as error:  # keep a partial snapshot and make failures explicit
            failures.append({"query": query, "error": str(error)})
            continue
        for row in rows:
            try:
                product = normalize_kroger_product(row, query)
            except (TypeError, ValueError) as error:
                failures.append({"query": query, "error": str(error)})
                continue
            products[product.id] = product_to_snapshot_row(product)

    now = datetime.now(timezone.utc)
    output = args.out or ROOT / "benchmark" / "kroger_snapshots" / f"{location_id}-{now:%Y%m%d}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "version": "1.0.0",
        "source": {
            "provider": "Kroger Public API",
            "retrieved_at_utc": now.isoformat(),
            "zip_code": args.zip_code,
            "location": location,
            "queries": args.queries,
            "result_limit_per_query": args.limit,
            "limitations": [
                "availability is boolean; exact inventory count is not provided",
                "dietary tags and meal portions are not inferred from product names",
                "prices and availability are a time-specific snapshot",
            ],
        },
        "products": sorted(products.values(), key=lambda product: product["id"]),
        "failures": failures,
    }
    output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "location_id": location_id,
        "location_name": location.get("name"),
        "products": len(products),
        "failed_queries": len(failures),
    }, indent=2))


if __name__ == "__main__":
    main()
