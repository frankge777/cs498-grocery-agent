"""Deterministic grocery shopping environment (paper Section 3.1).

Every trial gets a fresh environment: cart, inventory, clarification state and
event flags are reset. Failed cart operations never change the cart. All tool
calls are logged in ``trajectory`` so interaction predicates and efficiency
metrics can be recomputed from the log alone.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .data import Product, Scenario

TOOL_SCHEMA_VERSION = "1.0.0"
DEFAULT_LIMITS = {"max_tool_calls": 100, "max_model_calls": 100, "max_seconds": 300.0}
REPHRASE_ANSWER = (
    "I can't answer that. Please rephrase, or ask about a specific item, quantity, "
    "brand, budget, or dietary need."
)
_STOPWORDS = {"a", "an", "the", "of", "and", "or", "for", "with", "to", "in", "some", "any", "my"}


class EpisodeTerminated(Exception):
    """Raised when an agent calls a tool after the episode has ended."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Observation:
    ok: bool
    message: str
    data: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "message": self.message, "data": self.data}


class GroceryEnv:
    def __init__(
        self,
        catalog: Dict[str, Product],
        scenario: Scenario,
        variant: str,
        limits: Optional[dict] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.catalog = catalog
        self.scenario = scenario
        self.variant = variant
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self._clock = clock
        self._started = clock()

        self.stock: Dict[str, int] = {pid: product.stock for pid, product in catalog.items()}
        self.stock.update({pid: int(qty) for pid, qty in scenario.stock_overrides.items()})
        self.cart: Dict[str, int] = {pid: int(qty) for pid, qty in scenario.initial_cart.items()}
        self.initial_cart: Dict[str, int] = dict(self.cart)
        self._pending_events = {event["product_id"]: dict(event) for event in scenario.events}
        self.fired_events: List[str] = []

        self.trajectory: List[dict] = []
        self.tool_calls = 0
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.cart_modifications = 0
        self.termination_reason: Optional[str] = None

    # ------------------------------------------------------------------ public
    def observation(self) -> dict:
        return self.scenario.public_observation(self.variant)

    @property
    def done(self) -> bool:
        return self.termination_reason is not None

    @property
    def total_cents(self) -> int:
        return sum(self.catalog[pid].price_cents * qty for pid, qty in self.cart.items())

    @property
    def elapsed_seconds(self) -> float:
        return self._clock() - self._started

    def unavailable_products(self) -> set:
        return {pid for pid, qty in self.stock.items() if qty <= 0}

    def record_model_call(self, input_tokens: int = 0, output_tokens: int = 0, cached_input_tokens: int = 0) -> None:
        """Agents that call an LLM report each call here so caps and cost are enforced."""
        self._check_open()
        self.model_calls += 1
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        self.cached_input_tokens += int(cached_input_tokens)
        if self.model_calls > self.limits["max_model_calls"]:
            self._terminate("model_call_cap")

    def call(self, tool: str, args: Optional[dict] = None) -> dict:
        """Dispatch a tool call by name (used by function-calling agents)."""
        handlers = {
            "search_products": self.search_products,
            "get_product": self.get_product,
            "view_cart": self.view_cart,
            "add_to_cart": self.add_to_cart,
            "update_quantity": self.update_quantity,
            "remove_from_cart": self.remove_from_cart,
            "ask_user": self.ask_user,
            "finish": self.finish,
        }
        if tool not in handlers:
            self._begin_call(tool, args or {})
            return self._log(tool, args or {}, Observation(False, f"Unknown tool: {tool}")).to_dict()
        try:
            return handlers[tool](**(args or {})).to_dict()
        except TypeError as error:
            self._begin_call(tool, args or {})
            return self._log(tool, args or {}, Observation(False, f"Invalid arguments: {error}")).to_dict()

    # ------------------------------------------------------------------- tools
    def search_products(self, query: str, max_results: int = 10) -> Observation:
        args = {"query": query, "max_results": max_results}
        self._begin_call("search_products", args)
        tokens = [t for t in _tokenize(query) if t not in _STOPWORDS]
        scored = []
        for product in self.catalog.values():
            text = _search_text(product)
            score = sum(1 for token in tokens if token in text or _stem(token) in text)
            if score:
                scored.append((-score, product.price_cents, product.id, product))
        scored.sort(key=lambda row: row[:3])
        limit = max(1, min(int(max_results), 20))
        results = [p.public_summary(self._in_stock(p.id)) for *_, p in scored[:limit]]
        return self._log("search_products", args, Observation(True, f"{len(results)} results", {"products": results}))

    def get_product(self, product_id: str) -> Observation:
        args = {"product_id": product_id}
        self._begin_call("get_product", args)
        product = self.catalog.get(product_id)
        if product is None:
            obs = Observation(False, f"Unknown product: {product_id}")
        else:
            obs = Observation(True, "Product details", product.public_details(self._in_stock(product_id)))
        return self._log("get_product", args, obs)

    def view_cart(self) -> Observation:
        self._begin_call("view_cart", {})
        return self._log("view_cart", {}, Observation(True, "Current cart", self._cart_payload()))

    def add_to_cart(self, product_id: str, quantity: int = 1) -> Observation:
        args = {"product_id": product_id, "quantity": quantity}
        self._begin_call("add_to_cart", args)
        error = self._validate_increase(product_id, quantity, positive=True)
        if error:
            return self._log("add_to_cart", args, Observation(False, error))
        self.cart[product_id] = self.cart.get(product_id, 0) + int(quantity)
        return self._log_mutation("add_to_cart", args, f"Added {quantity} x {product_id}")

    def update_quantity(self, product_id: str, quantity: int) -> Observation:
        args = {"product_id": product_id, "quantity": quantity}
        self._begin_call("update_quantity", args)
        if not _is_int(quantity) or int(quantity) < 0:
            return self._log("update_quantity", args, Observation(False, "Quantity must be a non-negative integer"))
        if product_id not in self.catalog:
            return self._log("update_quantity", args, Observation(False, f"Unknown product: {product_id}"))
        current = self.cart.get(product_id, 0)
        quantity = int(quantity)
        if quantity > current:
            error = self._validate_increase(product_id, quantity - current, positive=True)
            if error:
                return self._log("update_quantity", args, Observation(False, error))
        if quantity == current:
            return self._log("update_quantity", args, Observation(True, "Quantity unchanged", self._cart_payload()))
        if quantity == 0:
            self.cart.pop(product_id, None)
        else:
            self.cart[product_id] = quantity
        return self._log_mutation("update_quantity", args, f"Set {product_id} to {quantity}")

    def remove_from_cart(self, product_id: str) -> Observation:
        args = {"product_id": product_id}
        self._begin_call("remove_from_cart", args)
        if product_id not in self.cart:
            return self._log("remove_from_cart", args, Observation(False, f"{product_id} is not in the cart"))
        del self.cart[product_id]
        return self._log_mutation("remove_from_cart", args, f"Removed {product_id}")

    def ask_user(self, question: str) -> Observation:
        args = {"question": question}
        self._begin_call("ask_user", args)
        topic = match_clarification_topic(self.scenario, question)
        if topic is None:
            obs = Observation(True, REPHRASE_ANSWER, {"answer": REPHRASE_ANSWER, "topic": None})
        else:
            obs = Observation(True, topic["answer"], {"answer": topic["answer"], "topic": topic["id"]})
        return self._log("ask_user", args, obs)

    def finish(self, message: str = "") -> Observation:
        args = {"message": message}
        self._begin_call("finish", args)
        obs = self._log("finish", args, Observation(True, "Episode finished", self._cart_payload()))
        self.termination_reason = "finished"
        return obs

    # ---------------------------------------------------------------- helpers
    def _validate_increase(self, product_id: str, quantity: Any, positive: bool) -> Optional[str]:
        if not _is_int(quantity) or (positive and int(quantity) <= 0):
            return "Quantity must be a positive integer"
        if product_id not in self.catalog:
            return f"Unknown product: {product_id}"
        event = self._pending_events.pop(product_id, None)
        if event is not None:
            self.stock[product_id] = 0
            self.fired_events.append(product_id)
            return f"Out of stock: {product_id} just became unavailable"
        if self.stock[product_id] <= 0:
            return f"Out of stock: {product_id}"
        if self.cart.get(product_id, 0) + int(quantity) > self.stock[product_id]:
            return f"Insufficient stock for {product_id}: only {self.stock[product_id]} available"
        return None

    def _in_stock(self, product_id: str) -> bool:
        return self.stock.get(product_id, 0) > 0

    def _cart_payload(self) -> dict:
        items = []
        for pid, qty in sorted(self.cart.items()):
            product = self.catalog[pid]
            items.append(
                {
                    **product.public_summary(self._in_stock(pid)),
                    "quantity": qty,
                    "line_total_cents": product.price_cents * qty,
                }
            )
        return {"items": items, "total_cents": self.total_cents}

    def _check_open(self) -> None:
        if self.done:
            raise EpisodeTerminated(self.termination_reason)
        if self.elapsed_seconds > self.limits["max_seconds"]:
            self._terminate("time_cap")

    def _begin_call(self, tool: str, args: dict) -> None:
        self._check_open()
        self.tool_calls += 1
        if self.tool_calls > self.limits["max_tool_calls"]:
            self.tool_calls -= 1
            self._terminate("tool_call_cap")

    def _terminate(self, reason: str) -> None:
        self.termination_reason = reason
        self.trajectory.append({"step": len(self.trajectory), "tool": None, "event": "terminated", "reason": reason})
        raise EpisodeTerminated(reason)

    def _log_mutation(self, tool: str, args: dict, message: str) -> Observation:
        self.cart_modifications += 1
        return self._log(tool, args, Observation(True, message, self._cart_payload()), cart_changed=True)

    def _log(self, tool: str, args: dict, obs: Observation, cart_changed: bool = False) -> Observation:
        self.trajectory.append(
            {
                "step": len(self.trajectory),
                "tool": tool,
                "args": dict(args),
                "ok": obs.ok,
                "message": obs.message,
                "topic": (obs.data or {}).get("topic") if tool == "ask_user" else None,
                "cart_changed": cart_changed,
                "cart_after": dict(self.cart) if cart_changed else None,
            }
        )
        return obs


def match_clarification_topic(scenario: Scenario, question: str) -> Optional[dict]:
    text = question.lower()
    for topic in scenario.clarification:
        if any(keyword in text for keyword in topic["keywords"]):
            return topic
    return None


def _tokenize(text: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 2]


def _stem(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _search_text(product: Product) -> str:
    parts = [product.name, product.category.replace("_", " "), product.brand]
    parts.extend(tag.replace("_", " ") for tag in product.tags)
    parts.extend(tag.replace("_", "-") for tag in product.tags)
    return " ".join(parts).lower()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
