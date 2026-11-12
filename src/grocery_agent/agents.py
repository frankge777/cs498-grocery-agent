from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional, Set

from .environment import GroceryEnvironment
from .intent import IntentParser
from .models import AgentRun, ParsedIntent, Product, Requirement


class BaseShoppingAgent:
    name = "base"

    def __init__(self, parser: IntentParser):
        self.parser = parser

    @staticmethod
    def _valid_candidates(
        products: Iterable[Product], intent: ParsedIntent, failed: Optional[Set[str]] = None
    ) -> List[Product]:
        failed = failed or set()
        candidates = []
        for product in products:
            if product.id in failed:
                continue
            if not intent.required_tags.issubset(product.tags):
                continue
            if intent.forbidden_tags.intersection(product.tags):
                continue
            candidates.append(product)
        candidates.sort(
            key=lambda product: (
                0 if intent.preferred_brand and product.brand == intent.preferred_brand else 1,
                product.price,
                product.id,
            )
        )
        return candidates

    @staticmethod
    def _cart_counts(env: GroceryEnvironment) -> Counter:
        counts: Counter = Counter()
        for product, quantity in env.products_in_cart():
            counts[product.category] += quantity
        return counts


class DirectFunctionAgent(BaseShoppingAgent):
    """Single-pass baseline: literal extraction, one plan, and no recovery."""

    name = "direct_function"

    def __init__(self):
        super().__init__(IntentParser(infer_bundles=False))

    def run(self, task_id: str, instruction: str, env: GroceryEnvironment) -> AgentRun:
        intent = self.parser.parse(instruction)
        plan: List[tuple[str, int]] = []
        trace: List[dict] = [{"phase": "parse", "intent": _intent_dict(intent)}]

        for requirement in intent.requirements:
            result = env.search(requirement.category)
            products = _products_from_result(result.data or {})
            candidates = self._valid_candidates(products, intent)
            if not candidates:
                trace.append({"phase": "plan", "category": requirement.category, "status": "no_candidate"})
                continue
            plan.append((candidates[0].id, requirement.quantity))

        trace.append({"phase": "plan", "actions": plan})
        for product_id, quantity in plan:
            result = env.add_to_cart(product_id, quantity)
            trace.append({"phase": "execute", "product_id": product_id, "ok": result.ok, "message": result.message})

        env.view_cart()
        return AgentRun(
            agent=self.name,
            task_id=task_id,
            cart=dict(env.cart),
            total_cost=env.total_cost,
            tool_calls=env.tool_calls,
            replans=0,
            trace=trace + env.log,
            parsed_intent=intent,
        )


class IntentGroundedAgent(BaseShoppingAgent):
    """Intent -> plan -> execute -> verify loop with state-aware recovery."""

    name = "intent_grounded"

    def __init__(self, max_steps: int = 40):
        super().__init__(IntentParser(infer_bundles=True))
        self.max_steps = max_steps

    def run(self, task_id: str, instruction: str, env: GroceryEnvironment) -> AgentRun:
        intent = self.parser.parse(instruction)
        trace: List[dict] = [{"phase": "parse", "intent": _intent_dict(intent)}]
        failed_products: Set[str] = set()
        replans = 0
        steps = 0

        while steps < self.max_steps:
            counts = self._cart_counts(env)
            missing = [
                Requirement(requirement.category, requirement.quantity - counts[requirement.category])
                for requirement in intent.requirements
                if counts[requirement.category] < requirement.quantity
            ]
            if not missing:
                trace.append({"phase": "verify", "status": "complete"})
                break

            requirement = missing[0]
            search = env.search(requirement.category)
            products = _products_from_result(search.data or {})
            candidates = self._valid_candidates(products, intent, failed_products)
            affordable = [
                product
                for product in candidates
                if intent.budget is None
                or env.total_cost + product.price * requirement.quantity <= intent.budget + 1e-9
            ]
            if not affordable:
                trace.append(
                    {
                        "phase": "verify",
                        "category": requirement.category,
                        "status": "no_feasible_candidate",
                    }
                )
                break

            chosen = affordable[0]
            result = env.add_to_cart(chosen.id, requirement.quantity)
            steps += 1
            trace.append(
                {
                    "phase": "execute",
                    "category": requirement.category,
                    "product_id": chosen.id,
                    "quantity": requirement.quantity,
                    "ok": result.ok,
                    "message": result.message,
                }
            )
            if not result.ok:
                failed_products.add(chosen.id)
                replans += 1
                trace.append({"phase": "replan", "failed_product": chosen.id})

        env.view_cart()
        return AgentRun(
            agent=self.name,
            task_id=task_id,
            cart=dict(env.cart),
            total_cost=env.total_cost,
            tool_calls=env.tool_calls,
            replans=replans,
            trace=trace + env.log,
            parsed_intent=intent,
        )


def _products_from_result(data: Dict) -> List[Product]:
    products = []
    for row in data.get("products", []):
        products.append(
            Product(
                id=row["id"],
                name=row["name"],
                category=row["category"],
                brand=row["brand"],
                price=float(row["price"]),
                tags=set(row.get("tags", [])),
            )
        )
    return products


def _intent_dict(intent: ParsedIntent) -> dict:
    return {
        "requirements": [requirement.__dict__ for requirement in intent.requirements],
        "budget": intent.budget,
        "required_tags": sorted(intent.required_tags),
        "forbidden_tags": sorted(intent.forbidden_tags),
        "preferred_brand": intent.preferred_brand,
        "ambiguities": intent.ambiguities,
    }

