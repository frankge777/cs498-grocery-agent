"""Backend contract for batched product choices.

The UI (or a benchmark simulator) receives one JSON-serializable request and
returns option IDs. Product names and prices come from catalog records, never
from model-generated option text. This module makes no model calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence


ChoiceProvider = Callable[[dict], dict]


@dataclass
class RequirementChoice:
    requirement_id: str
    question: str
    candidates: List[dict] = field(default_factory=list)
    selected_product_id: Optional[str] = None
    excluded_product_ids: set = field(default_factory=set)
    status: str = "unresolved"


class ChoiceCoordinator:
    """Keep independent choices for several requirements across retries."""

    def __init__(self, requirements: Sequence[RequirementChoice]):
        self.requirements: Dict[str, RequirementChoice] = {}
        for requirement in requirements:
            if requirement.requirement_id in self.requirements:
                raise ValueError(f"Duplicate requirement: {requirement.requirement_id}")
            self.requirements[requirement.requirement_id] = requirement
        self._next_decision = 1
        self._pending: Dict[str, dict] = {}
        self.history: List[dict] = []

    def set_candidates(self, requirement_id: str, products: Sequence[dict]) -> None:
        requirement = self.requirements[requirement_id]
        seen = set()
        candidates = []
        for product in products:
            product_id = str(product["id"])
            if product_id in seen or product_id in requirement.excluded_product_ids:
                continue
            if product.get("in_stock") is not True:
                continue
            if not isinstance(product.get("price_cents"), int) or product["price_cents"] < 0:
                continue
            seen.add(product_id)
            candidates.append(dict(product))
        requirement.candidates = candidates
        if requirement.status != "added":
            requirement.status = "unresolved"

    def prepare_batch(self, requirement_ids: Optional[Sequence[str]] = None) -> dict:
        """Make a serializable request for a future frontend or simulated user."""
        if self._pending:
            raise ValueError("Resolve the previous choice request first")
        ids = list(requirement_ids) if requirement_ids is not None else list(self.requirements)
        decisions = []
        for requirement_id in ids:
            requirement = self.requirements[requirement_id]
            if requirement.status in {"selected", "added"} or not requirement.candidates:
                continue
            decision_id = f"d{self._next_decision}"
            self._next_decision += 1
            options = []
            for number, product in enumerate(requirement.candidates, 1):
                options.append({
                    "option_id": f"{decision_id}_o{number}",
                    "product_id": str(product["id"]),
                    "name": product["name"],
                    "brand": product.get("brand"),
                    "size": product.get("raw_size") or f"{product.get('size', '')} {product.get('unit', '')}".strip(),
                    "price_cents": product["price_cents"],
                })
            decision = {"decision_id": decision_id, "requirement_id": requirement_id,
                        "question": requirement.question, "options": options}
            decisions.append(decision)
            self._pending[decision_id] = decision
            requirement.status = "needs_user"
        return {"questions": decisions}

    def apply_answers(self, response: Mapping) -> None:
        """Validate the whole response before applying any selected product."""
        answers = response.get("answers")
        if not isinstance(answers, list):
            raise ValueError("answers must be a list")
        if len(answers) != len(self._pending):
            raise ValueError("One answer is required for each pending decision")
        selections = []
        seen = set()
        for answer in answers:
            if not isinstance(answer, dict):
                raise ValueError("Each answer must be an object")
            decision_id = answer.get("decision_id")
            if decision_id not in self._pending or decision_id in seen:
                raise ValueError("Unknown or duplicate decision ID")
            seen.add(decision_id)
            decision = self._pending[decision_id]
            option = next((item for item in decision["options"]
                           if item["option_id"] == answer.get("selected_option_id")), None)
            if option is None:
                raise ValueError("Selected option was not offered")
            selections.append((decision, option))
        for decision, option in selections:
            requirement = self.requirements[decision["requirement_id"]]
            requirement.selected_product_id = option["product_id"]
            requirement.status = "selected"
            self.history.append({"decision_id": decision["decision_id"],
                                 "requirement_id": requirement.requirement_id,
                                 "selected_option_id": option["option_id"],
                                 "selected_product_id": option["product_id"]})
        self._pending.clear()

    def ask_pending(self, provider: ChoiceProvider, requirement_ids: Optional[Sequence[str]] = None) -> dict:
        request = self.prepare_batch(requirement_ids)
        if request["questions"]:
            self.apply_answers(provider(request))
        return request

    def mark_added(self, requirement_id: str) -> None:
        requirement = self.requirements[requirement_id]
        if requirement.status != "selected":
            raise ValueError("A product must be selected before it is added")
        requirement.status = "added"

    def mark_unavailable(self, requirement_id: str, product_id: str) -> None:
        requirement = self.requirements[requirement_id]
        if requirement.selected_product_id != product_id:
            raise ValueError("Only the selected product can be marked unavailable")
        requirement.excluded_product_ids.add(product_id)
        requirement.selected_product_id = None
        requirement.candidates = [p for p in requirement.candidates if p["id"] != product_id]
        requirement.status = "unresolved"

    def selected_total_cents(self, quantities: Mapping[str, int], initial_total_cents: int = 0) -> int:
        total = initial_total_cents
        for requirement_id, requirement in self.requirements.items():
            if requirement.selected_product_id is None:
                raise ValueError(f"No product selected for {requirement_id}")
            product = next((p for p in requirement.candidates
                            if p["id"] == requirement.selected_product_id), None)
            if product is None:
                raise ValueError(f"Selected product is unavailable for {requirement_id}")
            quantity = quantities[requirement_id]
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValueError("Quantity must be a positive integer")
            total += product["price_cents"] * quantity
        return total

    def checkpoint(self) -> dict:
        """Persist this state while a frontend is waiting for the user's reply."""
        return {
            "requirements": [
                {"requirement_id": item.requirement_id, "question": item.question,
                 "candidates": item.candidates, "selected_product_id": item.selected_product_id,
                 "excluded_product_ids": sorted(item.excluded_product_ids), "status": item.status}
                for item in self.requirements.values()
            ],
            "next_decision": self._next_decision,
            "pending": list(self._pending.values()),
            "history": list(self.history),
        }

    @classmethod
    def from_checkpoint(cls, snapshot: Mapping) -> "ChoiceCoordinator":
        coordinator = cls([
            RequirementChoice(
                requirement_id=item["requirement_id"], question=item["question"],
                candidates=list(item["candidates"]), selected_product_id=item["selected_product_id"],
                excluded_product_ids=set(item["excluded_product_ids"]), status=item["status"],
            )
            for item in snapshot["requirements"]
        ])
        coordinator._next_decision = snapshot["next_decision"]
        coordinator._pending = {item["decision_id"]: item for item in snapshot["pending"]}
        coordinator.history = list(snapshot["history"])
        return coordinator


class SimulatedChoiceProvider:
    """Deterministic benchmark adapter: ranked product IDs per requirement."""

    def __init__(self, preferred_product_ids: Mapping[str, Sequence[str]]):
        self.preferred_product_ids = {key: [value] if isinstance(value, str) else list(value)
                                      for key, value in preferred_product_ids.items()}

    def __call__(self, request: dict) -> dict:
        answers = []
        for question in request["questions"]:
            preferences = self.preferred_product_ids[question["requirement_id"]]
            option = next((item for desired_id in preferences for item in question["options"]
                           if item["product_id"] == desired_id), None)
            if option is None:
                raise ValueError(f"Preferred product was not offered for {question['requirement_id']}")
            answers.append({"decision_id": question["decision_id"],
                            "selected_option_id": option["option_id"]})
        return {"answers": answers}
