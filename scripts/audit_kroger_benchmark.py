#!/usr/bin/env python3
"""Generate a human-readable audit of Kroger task wording and hidden selectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_bench import GroceryEnv, OracleAgent, evaluate_env, load_catalog, load_scenarios  # noqa: E402
from grocery_bench.data import KROGER_CATALOG_PATH, KROGER_SCENARIOS_PATH, VARIANTS  # noqa: E402
from grocery_bench.evaluator import cart_total  # noqa: E402


DECISIONS = {
    "K01": "Exact named Kroger half-gallon milk; one UPC is intentionally accepted.",
    "K02": "Public list names Kroger White Bread, Kroger large white eggs, and medium navel oranges; accepted package sizes produce the exact requested counts.",
    "K03": "The two public alternatives (one 24-count Simple Truth or two 12-count Kroger cartons) exactly match the hidden set.",
    "K04": "All five products are named with brand/type/size in the public list.",
    "K05": "The corrected list now names the 52 fl oz Planet Oat product, removing ambiguity with shelf-stable Original variants.",
    "K06": "Generic breakfast wording was replaced by visible approved oats/breads and named Kroger milk/eggs; hidden selectors match those visible lists.",
    "K07": "Three exact named products; organic and vegan declarations are independently enforced.",
    "K08": "Visible approved candidate lists match hidden selectors; organic oats remain a soft preference after hard budget constraints.",
    "K09": "Accepted UPCs are exhaustively derived from in-stock protein bars with 4-6 count, explicit gluten-free, and at least 10 g labeled protein; budget is evaluated separately.",
    "K10": "Both in-stock Kroger mild salsas and every in-stock 8 oz Kroger shredded cheese are accepted; budget is evaluated separately.",
    "K11": "All three products and quantities are explicitly named in the public three-day plan.",
    "K12": "All three products are explicitly named; every purchased item must also carry an explicit vegan declaration.",
    "K13": "Named powder/creatine/yogurt are exact; qualifying bar UPCs are exhaustively derived from 4-count, gluten-free products with at least 20 g labeled protein. Budget is separate.",
    "K14": "The public pantry sheet identifies each approved product family and exact target difference.",
    "K15": "After required clarification, accepted UPCs exhaustively cover in-stock oat/soy milks explicitly labeled dairy-free and nut-free.",
    "K16": "Preferred UPC has a scripted failure; substitute UPCs exhaustively cover in-stock oat/soy milks explicitly labeled dairy-free and nut-free.",
    "K17": "All three in-stock 340 g Kroger gluten-free pasta shapes are accepted; sauce is exact and explicitly gluten-free.",
    "K18": "Both Kroger mild salsas are accepted; the public context explicitly limits the cheese recovery to the named mozzarella substitute.",
    "K19": "Preferred and substitute 11 oz coffee UPCs and the 52 fl oz milk are explicitly visible.",
    "K20": "Initial items and both recovery substitutions are explicitly visible in the public context.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected(scenarios, scenario_id: str, need_id: str) -> set[str]:
    scenario = next(value for value in scenarios if value.id == scenario_id)
    need = next(value for value in scenario.needs if value["id"] == need_id)
    return set(need["select"].get("product_ids", []))


def attribute_audits(catalog, scenarios) -> list[tuple[str, bool, int]]:
    expected_k09 = {
        p.id for p in catalog.values()
        if p.stock > 0 and "protein bar" in p.name.lower() and "gluten_free" in p.tags
        and (p.protein_g or 0) >= 10 and p.unit == "ct" and 4 <= p.size <= 6
    }
    expected_k13 = {
        p.id for p in catalog.values()
        if p.stock > 0 and "protein bar" in p.name.lower() and "gluten_free" in p.tags
        and (p.protein_g or 0) >= 20 and p.unit == "ct" and p.size == 4
    }
    expected_salsa = {
        p.id for p in catalog.values()
        if p.stock > 0 and p.brand == "Kroger" and "salsa" in p.name.lower() and "mild" in p.name.lower()
    }
    expected_cheese = {
        p.id for p in catalog.values()
        if p.stock > 0 and p.brand == "Kroger" and "shredded cheese" in p.name.lower() and p.raw_size == "8 oz"
    }
    expected_milk = {
        p.id for p in catalog.values()
        if p.stock > 0 and any(label in p.name.lower() for label in ("oatmilk", "oat milk", "soymilk"))
        and {"dairy_free", "nut_free"}.issubset(p.tags)
    }
    checks = [
        ("K09 qualifying bars", selected(scenarios, "K09", "bars"), expected_k09),
        ("K13 qualifying bars", selected(scenarios, "K13", "bars"), expected_k13),
        ("K10 mild salsa", selected(scenarios, "K10", "salsa"), expected_salsa),
        ("K18 mild salsa", selected(scenarios, "K18", "salsa"), expected_salsa),
        ("K10 8 oz shredded cheese", selected(scenarios, "K10", "cheese"), expected_cheese),
        ("K15 dairy/nut-free oat or soy milk", selected(scenarios, "K15", "milk"), expected_milk),
        ("K16 dairy/nut-free oat or soy milk", selected(scenarios, "K16", "milk"), expected_milk),
    ]
    return [(name, actual == expected, len(expected)) for name, actual, expected in checks]


def reference_audit(catalog, scenarios) -> tuple[int, int]:
    checked = passed = 0
    for scenario in scenarios:
        for index in range(len(scenario.reference_carts)):
            for variant in VARIANTS:
                checked += 1
                env = GroceryEnv(catalog, scenario, variant)
                OracleAgent(index).run(env)
                passed += evaluate_env(env).success
    return checked, passed


def render(catalog, scenarios) -> str:
    raw = json.loads(KROGER_SCENARIOS_PATH.read_text(encoding="utf-8"))
    checked, passed = reference_audit(catalog, scenarios)
    attribute_checks = attribute_audits(catalog, scenarios)
    lines = [
        "# Kroger Benchmark Acceptance Audit — 2026-11-18",
        "",
        f"- Scenario version: `{raw['version']}`",
        f"- Catalog SHA-256: `{sha256(KROGER_CATALOG_PATH)}`",
        f"- Scenario SHA-256: `{sha256(KROGER_SCENARIOS_PATH)}`",
        f"- Catalog products: {len(catalog)}",
        f"- Scenarios: {len(scenarios)}",
        f"- Reference-cart replays passed: {passed}/{checked}",
        "",
        "## Audit policy",
        "",
        "Exact named products may use a narrow UPC set only when brand/type/size are visible to the agent. Attribute-defined requests must include every in-stock snapshot product satisfying the stated product type, package/count rule, explicit tags, and labeled protein threshold. Budget is scored independently and is never used to disguise an otherwise qualifying product as an invalid type. Unknown metadata never satisfies a required attribute.",
        "",
        "## Exhaustive attribute-set checks",
        "",
    ]
    for name, ok, count in attribute_checks:
        lines.append(f"- {'PASS' if ok else 'FAIL'} — {name}: {count} qualifying UPCs")
    lines += ["", "## Scenario-by-scenario audit", ""]
    for scenario in scenarios:
        lines += [
            f"### {scenario.id} — {scenario.title}",
            "",
            f"Public high-explicitness request: {scenario.variants['high']}",
            "",
            f"Decision: {DECISIONS[scenario.id]}",
            "",
        ]
        for need in scenario.needs:
            lines.append(
                f"- Need `{need['id']}`: {need['measure']} in [{need['min']}, {need.get('max')}], selector `{json.dumps(need['select'], sort_keys=True)}`"
            )
            for product_id in need["select"].get("product_ids", []):
                product = catalog[product_id]
                lines.append(
                    f"  - `{product_id}` — {product.name}; ${product.price_cents / 100:.2f}; {product.raw_size}; tags={','.join(sorted(product.tags)) or 'none'}"
                )
        if scenario.events:
            lines.append(f"- Scripted event UPCs: {', '.join(event['product_id'] for event in scenario.events)}")
        for index, cart in enumerate(scenario.reference_carts, 1):
            lines.append(f"- Reference cart {index}: ${cart_total(cart, catalog) / 100:.2f}; `{json.dumps(cart, sort_keys=True)}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "kroger_benchmark_audit_20261118.md")
    args = parser.parse_args()
    catalog = load_catalog(KROGER_CATALOG_PATH)
    scenarios = load_scenarios(KROGER_SCENARIOS_PATH)
    output = render(catalog, scenarios)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    failed = [name for name, ok, _ in attribute_audits(catalog, scenarios) if not ok]
    if failed:
        raise SystemExit(f"attribute-set audit failed: {failed}")
    print(json.dumps({"output": str(args.out), "scenarios": len(scenarios), "products": len(catalog)}, indent=2))


if __name__ == "__main__":
    main()
