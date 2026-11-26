"""Backend contract for batched product choices.

The UI (or a benchmark simulator) receives one JSON-serializable request and
returns option IDs. Product names and prices come from catalog records, never
from model-generated option text. This module makes no model calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from .llm_agents import amount_per_package, brand_matches


ChoiceProvider = Callable[[dict], dict]
PACKAGING_WORDS = {"bag", "bags", "pack", "packs", "package", "packages"}


def _core_query_terms(query: str) -> List[str]:
    return [word.rstrip("s") for word in re.findall(r"[a-z]+", query.lower())
            if word not in PACKAGING_WORDS]


def _name_mentions_single_item(query: str, product: Mapping) -> bool:
    terms = _core_query_terms(query)
    if len(terms) != 1:
        return True
    name_words = {word.rstrip("s") for word in re.findall(r"[a-z]+", str(product.get("name") or "").lower())}
    return terms[0] in name_words


def _obvious_mixture(query: str, product: Mapping) -> bool:
    """Exclude clear vegetable mixes from a single-vegetable search.

    Keep uncertain products for the shopper to decide. This deliberately does
    not try to infer ingredients or dietary claims from a product title.
    """
    terms = _core_query_terms(query)
    if len(terms) != 1 or product.get("category") not in {"produce", "frozen"}:
        return False
    name = str(product.get("name") or "").lower()
    if not _name_mentions_single_item(query, product):
        return False
    return " & " in name or ", " in name


def choice_brand_matches(brand: Optional[str], description: str, product: Mapping) -> bool:
    """Accept a brand shown at the start of a title when Kroger omits its brand field."""
    if brand_matches({"brand": brand, "description": description}, product):
        return True
    actual = " ".join(str(product.get("brand") or "").lower().split())
    required = " ".join(str(brand or "").lower().split())
    name = " ".join(re.sub(r"[^a-z0-9 ]+", " ",
                           str(product.get("name") or "").lower()).split())
    return bool(required and actual in {"", "unknown"} and name.startswith(required + " "))


@dataclass
class RequirementChoice:
    requirement_id: str
    question: str
    search_query: str = ""
    quantity: int = 1
    measure: str = "units"
    target_min: int = 1
    target_max: Optional[int] = 1
    required_tags: List[str] = field(default_factory=list)
    required_brand: Optional[str] = None
    required_product_ids: List[str] = field(default_factory=list)
    candidates: List[dict] = field(default_factory=list)
    selected_product_id: Optional[str] = None
    excluded_product_ids: set = field(default_factory=set)
    status: str = "unresolved"
    force_user_choice: bool = False


def coordinator_from_intent(intent: Mapping) -> "ChoiceCoordinator":
    """Create one independently tracked choice per fully specified need."""
    requirements = []
    for item in intent["requirements"]:
        minimum = item.get("min", 1)
        maximum = item.get("max", minimum)
        if not isinstance(minimum, int) or minimum < 1 or (maximum is not None and maximum < minimum):
            raise ValueError("Interactive product choice requires a positive quantity range")
        requirements.append(RequirementChoice(
            requirement_id=item["id"], question=f"Which product for {item['description']}?",
            search_query=item["search_query"], quantity=minimum if item.get("measure", "units") == "units" else 0,
            measure=item.get("measure", "units"), target_min=minimum, target_max=maximum,
            required_tags=sorted(set(item.get("required_tags") or []) |
                                 set(intent.get("all_items_required_tags") or [])),
            required_brand=item.get("brand"),
            required_product_ids=list(item.get("product_ids") or []),
        ))
    return ChoiceCoordinator(requirements)


def packages_for(requirement: RequirementChoice, details: Mapping) -> Optional[int]:
    amount = amount_per_package(details, requirement.measure)
    if amount <= 0:
        return None
    packages = (requirement.target_min + amount - 1) // amount
    if requirement.target_max is not None and packages * amount > requirement.target_max:
        return None
    return packages if packages > 0 else None


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
            # Zero means the feed did not provide a usable price, not a free item.
            if not isinstance(product.get("price_cents"), int) or product["price_cents"] <= 0:
                continue
            seen.add(product_id)
            candidate = dict(product)
            candidate.setdefault("quantity", requirement.quantity)
            candidates.append(candidate)
        requirement.candidates = candidates
        if requirement.status != "added":
            requirement.status = "unresolved"

    def search_unresolved(self, env, budget_cents: Optional[int] = None) -> dict:
        """Search only unresolved needs using the public environment tools."""
        counts = {}
        for requirement in self.requirements.values():
            if requirement.status != "unresolved":
                continue
            observation = env.search_products(requirement.search_query, max_results=20)
            if not observation.ok:
                raise ValueError(observation.message)
            matched = []
            for summary in observation.data["products"]:
                product_id = str(summary["id"])
                if not _name_mentions_single_item(requirement.search_query, summary):
                    continue
                if _obvious_mixture(requirement.search_query, summary):
                    continue
                if requirement.required_product_ids and product_id not in requirement.required_product_ids:
                    continue
                if not choice_brand_matches(requirement.required_brand,
                                            requirement.question, summary):
                    continue
                details = summary
                if requirement.required_tags or requirement.measure.startswith("portions:"):
                    detail = env.get_product(product_id)
                    if not detail.ok:
                        continue
                    details = detail.data
                if not set(requirement.required_tags).issubset(details.get("dietary_tags", [])):
                    continue
                quantity = packages_for(requirement, details)
                if quantity is None:
                    continue
                if budget_cents is not None and summary["price_cents"] * quantity > budget_cents:
                    continue
                matched.append({**summary, "quantity": quantity})
            self.set_candidates(requirement.requirement_id, matched)
            counts[requirement.requirement_id] = len(self.requirements[requirement.requirement_id].candidates)
        return counts

    def decide(self, auto_allowed: Sequence[str] = ()) -> dict:
        """Select single options; batch the rest for the shopper.

        The caller may authorize automatic cheapest-choice per requirement only
        after interpreting the shopper's words. This method does not infer that
        authorization from a product count or price.
        """
        allowed = set(auto_allowed)
        if allowed - self.requirements.keys():
            raise ValueError("Unknown requirement in auto_allowed")
        auto_selected = {}
        for requirement in self.requirements.values():
            if requirement.status != "unresolved" or not requirement.candidates:
                continue
            if not requirement.force_user_choice and (
                len(requirement.candidates) == 1 or requirement.requirement_id in allowed
            ):
                chosen = min(requirement.candidates,
                             key=lambda product: (product["price_cents"], product["id"]))
                requirement.selected_product_id = chosen["id"]
                requirement.quantity = chosen["quantity"]
                requirement.status = "selected"
                auto_selected[requirement.requirement_id] = chosen["id"]
        request = self.prepare_batch()
        return {"auto_selected": auto_selected, **request}

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
                    "quantity": product["quantity"],
                    "line_total_cents": product["price_cents"] * product["quantity"],
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
            requirement.quantity = option["quantity"]
            requirement.status = "selected"
            requirement.force_user_choice = False
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
        requirement.force_user_choice = True

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
                 "search_query": item.search_query, "quantity": item.quantity,
                 "measure": item.measure, "target_min": item.target_min, "target_max": item.target_max,
                 "required_tags": item.required_tags, "required_brand": item.required_brand,
                 "required_product_ids": item.required_product_ids,
                 "candidates": item.candidates, "selected_product_id": item.selected_product_id,
                 "excluded_product_ids": sorted(item.excluded_product_ids), "status": item.status}
                 | {"force_user_choice": item.force_user_choice}
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
                search_query=item.get("search_query", ""), quantity=item.get("quantity", 1),
                measure=item.get("measure", "units"), target_min=item.get("target_min", 1),
                target_max=item.get("target_max", 1),
                required_tags=list(item.get("required_tags") or []),
                required_brand=item.get("required_brand"),
                required_product_ids=list(item.get("required_product_ids") or []),
                candidates=list(item["candidates"]), selected_product_id=item["selected_product_id"],
                excluded_product_ids=set(item["excluded_product_ids"]), status=item["status"],
                force_user_choice=item.get("force_user_choice", False),
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
