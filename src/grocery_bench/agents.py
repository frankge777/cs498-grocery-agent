"""Reference agents that need no LLM.

* ``OracleAgent`` replays a hidden reference cart. It reads evaluator-only
  fields, so it is a *validation tool* (feasibility, determinism), never a
  comparison system.
* ``KeywordBaseline`` is a non-LLM floor: it adds the cheapest in-stock
  product for every category word it sees in the instruction. It shows the
  benchmark is not trivially solvable; it is not one of the paper's planned
  reference systems (direct function calling, ReAct, plan-then-execute).

Agents implement ``run(env) -> None`` and interact only through tools.
"""

from __future__ import annotations

import re

from .environment import GroceryEnv

CATEGORY_WORDS = {
    "milk": ["milk"],
    "bread": ["bread", "loaf"],
    "eggs": ["egg"],
    "banana": ["banana"],
    "apples": ["apple"],
    "oranges": ["orange"],
    "berries": ["berries", "blueberr"],
    "oats": ["oats", "oatmeal"],
    "cereal": ["cereal"],
    "rice": ["rice"],
    "pasta": ["pasta", "spaghetti", "penne"],
    "flour": ["flour"],
    "sugar": ["sugar"],
    "pasta_sauce": ["sauce"],
    "beans": ["beans"],
    "lentils": ["lentil"],
    "tofu": ["tofu"],
    "chicken": ["chicken"],
    "carrots": ["carrot"],
    "broccoli": ["broccoli"],
    "spinach": ["spinach"],
    "frozen_vegetables": ["frozen vegetables"],
    "protein_bar": ["protein bar"],
    "yogurt": ["yogurt"],
    "crackers": ["cracker"],
    "popcorn": ["popcorn"],
    "protein_powder": ["protein powder"],
    "creatine": ["creatine"],
    "coffee": ["coffee"],
    "tortillas": ["tortilla"],
    "salsa": ["salsa"],
    "cheese": ["cheese"],
}


class OracleAgent:
    name = "oracle_validation"

    def __init__(self, reference_index: int = 0):
        self.reference_index = reference_index

    def run(self, env: GroceryEnv) -> None:
        scenario = env.scenario
        target = scenario.reference_carts[self.reference_index]
        for topic in scenario.clarification:
            if topic.get("status") == "required":
                env.ask_user(f"Is there anything I should know about the {topic['keywords'][0]}?")
        for product_id in list(env.cart):
            if product_id not in target:
                env.remove_from_cart(product_id)
        for product_id, quantity in target.items():
            env.update_quantity(product_id, quantity)
        env.finish("oracle replay complete")


class KeywordBaseline:
    name = "keyword_baseline"

    def run(self, env: GroceryEnv) -> None:
        text = env.observation()["instruction"].lower()
        for category, words in CATEGORY_WORDS.items():
            if not any(word in text for word in words):
                continue
            results = env.search_products(category.replace("_", " ")).data["products"]
            candidates = [p for p in results if p["category"] == category and p["in_stock"]]
            if not candidates:
                continue
            quantity = _stated_quantity(text, words)
            cheapest = min(candidates, key=lambda p: (p["price_cents"], p["id"]))
            env.add_to_cart(cheapest["id"], quantity)
        env.finish("keyword baseline done")


_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _stated_quantity(text: str, words) -> int:
    for word in words:
        match = re.search(r"(\d+|a|an|one|two|three|four|five|six|seven)\s+(?:[a-z0-9.\-]+\s+){0,3}" + re.escape(word), text)
        if match:
            token = match.group(1)
            return int(token) if token.isdigit() else _NUMBERS[token]
    return 1
