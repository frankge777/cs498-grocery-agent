"""Run the prototype agents on the grocery benchmark without changing them.

The prototype agents were written against the old ``GroceryEnvironment``
(``search(category)``, ``add_to_cart``, ``view_cart``, dollar prices). This
adapter exposes that interface on top of ``grocery_bench.GroceryEnv`` so every
action still goes through the benchmark tools and is logged and scored there.

Simplification: the old agents read dietary tags straight from search
results. The benchmark's search summary omits tags, so the adapter attaches
them from the catalog instead of issuing one ``get_product`` call per result.
Tool-call counts are therefore slightly favourable to these agents.
"""

from __future__ import annotations

from typing import List, Tuple

from grocery_bench.environment import GroceryEnv

from .models import Product, ToolResult


class LegacyEnvAdapter:
    def __init__(self, env: GroceryEnv):
        self.env = env

    # Old interface ---------------------------------------------------------
    def search(self, category: str) -> ToolResult:
        obs = self.env.search_products(category.replace("_", " "), max_results=20)
        rows = []
        for item in obs.data["products"]:
            if item["category"] != category or not item["in_stock"]:
                continue
            product = self.env.catalog[item["id"]]
            rows.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "category": product.category,
                    "brand": product.brand,
                    "price": product.price_cents / 100,
                    "tags": sorted(product.tags),
                }
            )
        return ToolResult(True, f"Found {len(rows)} products in {category}", {"products": rows})

    def add_to_cart(self, product_id: str, quantity: int = 1) -> ToolResult:
        obs = self.env.add_to_cart(product_id, quantity)
        return ToolResult(obs.ok, obs.message, obs.data)

    def view_cart(self) -> ToolResult:
        obs = self.env.view_cart()
        return ToolResult(obs.ok, obs.message, obs.data)

    @property
    def cart(self):
        return self.env.cart

    @property
    def total_cost(self) -> float:
        return self.env.total_cents / 100

    @property
    def tool_calls(self) -> int:
        return self.env.tool_calls

    @property
    def log(self) -> list:
        return []

    def products_in_cart(self) -> List[Tuple[Product, int]]:
        out = []
        for pid, qty in self.env.cart.items():
            p = self.env.catalog[pid]
            out.append((Product(p.id, p.name, p.category, p.brand, p.price_cents / 100, set(p.tags)), qty))
        return out


class BenchmarkAgent:
    """Wrap a prototype agent so it implements ``run(env)`` for the benchmark runner."""

    def __init__(self, agent):
        self.agent = agent
        self.name = agent.name

    def run(self, env: GroceryEnv) -> None:
        obs = env.observation()
        self.agent.run(obs["scenario_id"], obs["instruction"], LegacyEnvAdapter(env))
        env.finish("prototype agent done")
