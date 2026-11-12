from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from .models import Product, ToolResult


class GroceryEnvironment:
    """Deterministic shopping sandbox with explicit, logged state changes."""

    def __init__(self, catalog: Dict[str, Product], events: Optional[Iterable[dict]] = None):
        self.catalog = dict(catalog)
        self.inventory = {product_id: 20 for product_id in catalog}
        self.cart: Dict[str, int] = defaultdict(int)
        self.events = [dict(event, fired=False) for event in (events or [])]
        self.successful_adds = 0
        self.tool_calls = 0
        self.log: List[dict] = []

    @property
    def total_cost(self) -> float:
        return round(
            sum(self.catalog[product_id].price * quantity for product_id, quantity in self.cart.items()),
            2,
        )

    def search(self, category: str) -> ToolResult:
        self.tool_calls += 1
        matches = [
            product
            for product in self.catalog.values()
            if product.category == category and self.inventory.get(product.id, 0) > 0
        ]
        matches.sort(key=lambda product: (product.price, product.id))
        payload = [self._product_dict(product) for product in matches]
        result = ToolResult(True, f"Found {len(payload)} products in {category}", {"products": payload})
        self._record("search", {"category": category}, result)
        return result

    def add_to_cart(self, product_id: str, quantity: int = 1) -> ToolResult:
        self.tool_calls += 1
        self._apply_pre_add_events(product_id)
        if product_id not in self.catalog:
            result = ToolResult(False, f"Unknown product: {product_id}")
        elif quantity <= 0:
            result = ToolResult(False, "Quantity must be positive")
        elif self.inventory.get(product_id, 0) < quantity:
            result = ToolResult(False, f"Product unavailable: {product_id}")
        else:
            self.inventory[product_id] -= quantity
            self.cart[product_id] += quantity
            self.successful_adds += 1
            result = ToolResult(
                True,
                f"Added {quantity} x {product_id}",
                {"cart_total": self.total_cost},
            )
            self._apply_post_add_events()
        self._record("add_to_cart", {"product_id": product_id, "quantity": quantity}, result)
        return result

    def view_cart(self) -> ToolResult:
        self.tool_calls += 1
        items = [
            {**self._product_dict(self.catalog[product_id]), "quantity": quantity}
            for product_id, quantity in sorted(self.cart.items())
        ]
        result = ToolResult(True, "Current cart", {"items": items, "total": self.total_cost})
        self._record("view_cart", {}, result)
        return result

    def products_in_cart(self) -> List[tuple[Product, int]]:
        return [(self.catalog[product_id], quantity) for product_id, quantity in self.cart.items()]

    def _apply_pre_add_events(self, product_id: str) -> None:
        for event in self.events:
            if event["fired"] or not event.get("trigger_on_attempt"):
                continue
            if (
                product_id == event["product_id"]
                and self.successful_adds >= int(event["trigger_after_adds"])
            ):
                self._fire_event(event)

    def _apply_post_add_events(self) -> None:
        for event in self.events:
            if event["fired"] or event.get("trigger_on_attempt"):
                continue
            if self.successful_adds == int(event["trigger_after_adds"]):
                self._fire_event(event)

    def _fire_event(self, event: dict) -> None:
        target = event["product_id"]
        self.inventory[target] = 0
        event["fired"] = True
        self.log.append(
            {
                "action": "environment_event",
                "args": {"product_id": target},
                "ok": True,
                "message": f"Inventory changed: {target} is now unavailable",
            }
        )

    def _record(self, action: str, args: dict, result: ToolResult) -> None:
        self.log.append(
            {
                "action": action,
                "args": args,
                "ok": result.ok,
                "message": result.message,
                "data": result.data,
            }
        )

    @staticmethod
    def _product_dict(product: Product) -> dict:
        return {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "brand": product.brand,
            "price": product.price,
            "tags": sorted(product.tags),
        }

