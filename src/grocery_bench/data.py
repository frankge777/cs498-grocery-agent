"""Catalog and scenario loading for the intent-grounded grocery benchmark."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "benchmark"
CATALOG_PATH = BENCHMARK_DIR / "catalog.json"
SCENARIOS_PATH = BENCHMARK_DIR / "scenarios.json"

VARIANTS: Tuple[str, ...] = ("high", "medium", "low")
CATEGORIES: Tuple[str, ...] = ("explicit", "constrained", "goal", "recovery")
DEFAULT_STOCK = 20


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    brand: str
    size: int
    unit: str
    price_cents: int
    tags: FrozenSet[str]
    portions: Mapping[str, int]
    protein_g: Optional[int] = None
    stock: int = DEFAULT_STOCK

    def public_summary(self, in_stock: bool) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "category": self.category,
            "size": self.size,
            "unit": self.unit,
            "price_cents": self.price_cents,
            "in_stock": in_stock,
        }

    def public_details(self, in_stock: bool) -> dict:
        return {
            **self.public_summary(in_stock),
            "dietary_tags": sorted(self.tags),
            "portions": dict(self.portions),
            "protein_g": self.protein_g,
        }


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    difficulty: str
    title: str
    variants: Mapping[str, str]
    context: Mapping
    needs: List[dict]
    budget_cents: Optional[int] = None
    hard: List[dict] = field(default_factory=list)
    interactions: List[dict] = field(default_factory=list)
    preferences: List[dict] = field(default_factory=list)
    clarification: List[dict] = field(default_factory=list)
    events: List[dict] = field(default_factory=list)
    initial_cart: Mapping[str, int] = field(default_factory=dict)
    stock_overrides: Mapping[str, int] = field(default_factory=dict)
    extras_allowed: bool = False
    reference_carts: List[Dict[str, int]] = field(default_factory=list)

    def public_observation(self, variant: str) -> dict:
        """Everything an agent may see at the start of an episode."""
        return {
            "scenario_id": self.id,
            "variant": variant,
            "instruction": self.variants[variant],
            "household_context": self.context,
        }


@dataclass(frozen=True)
class Instance:
    scenario: Scenario
    variant: str

    @property
    def id(self) -> str:
        return f"{self.scenario.id}-{self.variant}"


def load_catalog(path: Path = CATALOG_PATH) -> Dict[str, Product]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog: Dict[str, Product] = {}
    for row in raw["products"]:
        product = Product(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            brand=row["brand"],
            size=int(row["size"]),
            unit=row["unit"],
            price_cents=int(row["price_cents"]),
            tags=frozenset(row.get("tags", [])),
            portions=dict(row.get("portions", {})),
            protein_g=row.get("protein_g"),
            stock=int(row.get("stock", DEFAULT_STOCK)),
        )
        if product.id in catalog:
            raise ValueError(f"Duplicate product id {product.id}")
        catalog[product.id] = product
    return catalog


def load_scenarios(path: Path = SCENARIOS_PATH) -> List[Scenario]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenarios = []
    for row in raw["scenarios"]:
        scenarios.append(
            Scenario(
                id=row["id"],
                category=row["category"],
                difficulty=row["difficulty"],
                title=row["title"],
                variants=row["variants"],
                context=row.get("context", {}),
                needs=row["needs"],
                budget_cents=row.get("budget_cents"),
                hard=row.get("hard", []),
                interactions=row.get("interactions", []),
                preferences=row.get("preferences", []),
                clarification=row.get("clarification", []),
                events=row.get("events", []),
                initial_cart=row.get("initial_cart", {}),
                stock_overrides=row.get("stock_overrides", {}),
                extras_allowed=row.get("extras_allowed", False),
                reference_carts=row.get("reference_carts", []),
            )
        )
    return scenarios


def iter_instances(scenarios: List[Scenario], variants: Tuple[str, ...] = VARIANTS) -> List[Instance]:
    return [Instance(scenario, variant) for scenario in scenarios for variant in variants]


def release_hashes(catalog_path: Path = CATALOG_PATH, scenarios_path: Path = SCENARIOS_PATH) -> dict:
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {"catalog_sha256": digest(catalog_path), "scenarios_sha256": digest(scenarios_path)}
