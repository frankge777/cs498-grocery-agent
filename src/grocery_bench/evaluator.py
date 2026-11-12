"""Final-state evaluator implementing Eq. (1) of the draft benchmark paper.

    S = prod_{n in N} 1[n(C)] * prod_{h in H} 1[h(C)] * prod_{a in A} 1[a(trajectory)]

Need predicates (N) check that a measured amount of matching products lies in
[min, max]. Hard predicates (H) are the budget, the implicit "only allowed
products" and "no unavailable SKU" rules, plus any scenario-specific ones.
Interaction predicates (A) are checked on the trajectory (e.g. a required
clarification happened before the relevant item was added).

The evaluator only reads the final cart, the trajectory, and environment
availability; it never inspects agent internals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Set

from .data import Product, Scenario


@dataclass
class PredicateResult:
    id: str
    kind: str
    passed: bool
    detail: str


@dataclass
class EvaluationResult:
    scenario_id: str
    variant: str
    success: int
    coverage: float
    hard_satisfaction: float
    budget_ok: Optional[bool]
    preference_score: Optional[float]
    required_clarification_missed: Optional[bool]
    unnecessary_clarifications: int
    total_cents: int
    predicates: List[PredicateResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- selectors
def matches(product: Product, select: Mapping) -> bool:
    if "product_ids" in select and product.id not in select["product_ids"]:
        return False
    if "categories" in select and product.category not in select["categories"]:
        return False
    if "brands" in select and product.brand not in select["brands"]:
        return False
    # Unknown dietary metadata never satisfies a required tag.
    if "tags_all" in select and not set(select["tags_all"]).issubset(product.tags):
        return False
    if "tags_none" in select and set(select["tags_none"]).intersection(product.tags):
        return False
    if "min_protein_g" in select and (product.protein_g is None or product.protein_g < select["min_protein_g"]):
        return False
    return True


def unit_amount(product: Product, measure: str) -> int:
    """How much one package contributes to a measure (0 = does not contribute)."""
    if measure == "units":
        return 1
    if measure == "count":
        return product.size if product.unit == "ct" else 0
    if measure == "volume_ml":
        return product.size if product.unit == "ml" else 0
    if measure == "weight_g":
        return product.size if product.unit == "g" else 0
    if measure.startswith("portions:"):
        return int(product.portions.get(measure.split(":", 1)[1], 0))
    raise ValueError(f"Unknown measure {measure}")


def need_matches(product: Product, need: Mapping) -> bool:
    return matches(product, need["select"]) and unit_amount(product, need["measure"]) > 0


def measure_need(cart: Mapping[str, int], catalog: Mapping[str, Product], need: Mapping) -> int:
    return sum(
        unit_amount(catalog[pid], need["measure"]) * qty
        for pid, qty in cart.items()
        if need_matches(catalog[pid], need)
    )


def cart_total(cart: Mapping[str, int], catalog: Mapping[str, Product]) -> int:
    return sum(catalog[pid].price_cents * qty for pid, qty in cart.items())


# ---------------------------------------------------------------- evaluation
def evaluate(
    scenario: Scenario,
    variant: str,
    cart: Mapping[str, int],
    catalog: Mapping[str, Product],
    trajectory: Iterable[dict] = (),
    unavailable: Optional[Set[str]] = None,
) -> EvaluationResult:
    cart = {pid: qty for pid, qty in cart.items() if qty > 0}
    trajectory = list(trajectory)
    unavailable = unavailable if unavailable is not None else _unavailable_from_scenario(scenario)

    need_results = [_check_need(cart, catalog, need) for need in scenario.needs]
    hard_results = _check_hard(scenario, cart, catalog, unavailable)
    interaction_results = [
        _check_interaction(i, trajectory, catalog, scenario.initial_cart) for i in scenario.interactions
    ]

    success = int(all(r.passed for r in need_results + hard_results + interaction_results))
    coverage = sum(r.passed for r in need_results) / len(need_results) if need_results else 1.0
    hard_sat = sum(r.passed for r in hard_results) / len(hard_results) if hard_results else 1.0
    budget = next((r for r in hard_results if r.id == "budget"), None)

    preference = None
    if scenario.preferences and all(r.passed for r in hard_results):
        preference = _preference_score(scenario.preferences, cart, catalog)

    required_topics = {t["id"] for t in scenario.clarification if t.get("status") == "required"}
    missed = None
    if required_topics:
        missed = not all(r.passed for r in interaction_results if r.kind == "interaction")
    known_topics = {t["id"] for t in scenario.clarification}
    unnecessary = sum(
        1 for step in trajectory if step.get("tool") == "ask_user" and step.get("topic") not in known_topics
    )

    return EvaluationResult(
        scenario_id=scenario.id,
        variant=variant,
        success=success,
        coverage=round(coverage, 4),
        hard_satisfaction=round(hard_sat, 4),
        budget_ok=None if budget is None else budget.passed,
        preference_score=None if preference is None else round(preference, 4),
        required_clarification_missed=missed,
        unnecessary_clarifications=unnecessary,
        total_cents=cart_total(cart, catalog),
        predicates=need_results + hard_results + interaction_results,
    )


def _check_need(cart, catalog, need) -> PredicateResult:
    amount = measure_need(cart, catalog, need)
    low, high = need["min"], need.get("max")
    passed = amount >= low and (high is None or amount <= high)
    bound = f"[{low}, {high}]" if high is not None else f">= {low}"
    return PredicateResult(f"need:{need['id']}", "need", passed, f"{need['measure']}={amount}, required {bound}")


def _check_hard(scenario: Scenario, cart, catalog, unavailable) -> List[PredicateResult]:
    results = []
    if scenario.budget_cents is not None:
        total = cart_total(cart, catalog)
        results.append(
            PredicateResult("budget", "hard", total <= scenario.budget_cents, f"total={total}, cap={scenario.budget_cents}")
        )
    if not scenario.extras_allowed:
        extras = sorted(
            pid for pid in cart if not any(need_matches(catalog[pid], need) for need in scenario.needs)
        )
        results.append(
            PredicateResult("only_allowed_products", "hard", not extras, f"disallowed={extras}" if extras else "ok")
        )
    bad = sorted(pid for pid in cart if pid in unavailable)
    results.append(PredicateResult("no_unavailable_sku", "hard", not bad, f"unavailable={bad}" if bad else "ok"))

    for index, rule in enumerate(scenario.hard):
        if rule["type"] == "all_items":
            violating = sorted(pid for pid in cart if not matches(catalog[pid], rule["select"]))
            results.append(
                PredicateResult(f"all_items:{index}", "hard", not violating, f"violating={violating}" if violating else "ok")
            )
        elif rule["type"] == "preserve_initial":
            missing = sorted(pid for pid, qty in scenario.initial_cart.items() if cart.get(pid, 0) < qty)
            results.append(
                PredicateResult("preserve_initial", "hard", not missing, f"reduced={missing}" if missing else "ok")
            )
        else:
            raise ValueError(f"Unknown hard predicate type {rule['type']}")
    return results


def _check_interaction(rule: Mapping, trajectory: List[dict], catalog, initial_cart: Mapping[str, int]) -> PredicateResult:
    if rule["type"] != "clarify_before_add":
        raise ValueError(f"Unknown interaction type {rule['type']}")
    asked_at = next(
        (s["step"] for s in trajectory if s.get("tool") == "ask_user" and s.get("topic") == rule["topic"]), None
    )
    first_add = None
    previous: Dict[str, int] = dict(initial_cart)
    for step in trajectory:
        if step.get("cart_changed"):
            after = step["cart_after"]
            increased = [
                pid for pid, qty in after.items()
                if qty > previous.get(pid, 0) and matches(catalog[pid], rule["select"])
            ]
            if increased and first_add is None:
                first_add = step["step"]
            previous = after
    passed = asked_at is not None and (first_add is None or asked_at < first_add)
    return PredicateResult(
        f"interaction:{rule['topic']}", "interaction", passed, f"asked_at={asked_at}, first_add={first_add}"
    )


def _preference_score(preferences, cart, catalog) -> float:
    total_weight = sum(p["weight"] for p in preferences)
    earned = 0.0
    for pref in preferences:
        in_scope = [pid for pid in cart if matches(catalog[pid], pref["scope"])]
        if in_scope and all(matches(catalog[pid], pref["prefer"]) for pid in in_scope):
            earned += pref["weight"]
    return earned / total_weight if total_weight else 1.0


def _unavailable_from_scenario(scenario: Scenario) -> Set[str]:
    """Availability at episode end when no environment is given (event SKUs fire on first attempt)."""
    gone = {pid for pid, qty in scenario.stock_overrides.items() if qty <= 0}
    gone.update(event["product_id"] for event in scenario.events)
    return gone


def evaluate_env(env) -> EvaluationResult:
    """Evaluate a finished GroceryEnv episode."""
    unavailable = env.unavailable_products()
    return evaluate(env.scenario, env.variant, env.cart, env.catalog, env.trajectory, unavailable)
