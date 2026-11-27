"""Opt-in, resumable product-choice loop for an intent-grounded shopping run.

The caller owns the environment and stores the checkpoint between requests.
The legacy benchmark agent remains unchanged so historical results stay valid.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional, Sequence

from .choices import ChoiceCoordinator, choice_brand_matches, coordinator_from_intent, packages_for
from .interactive_intent import (INTERACTIVE_INTENT_GUIDANCE, clarification_questions,
                                 normalize_interactive_intent)
from .llm_agents import amount_per_package, task_message
from . import prompts
from .discovery import ModelDiscovery


class InteractiveShoppingSession:
    def __init__(self, env, intent: Mapping, coordinator: Optional[ChoiceCoordinator] = None,
                 auto_allowed: Sequence[str] = (), max_rounds: int = 8, discovery=None):
        self.env = env
        self.intent = dict(intent)
        self.choices = coordinator
        if self.choices is None and not clarification_questions(self.intent):
            self.choices = coordinator_from_intent(intent)
        self.auto_allowed = list(auto_allowed)
        self.rounds = 0
        self.max_rounds = max_rounds
        self.pending_clarifications = []
        self.clarifications = []
        self.quantity_overrides = {}
        self.clarification_rounds = 0
        self.discovery = discovery
        self.semantic_discovery = discovery is not None
        self.pending_candidate_reviews = []

    @staticmethod
    def extract_intent(env, llm, clarifications=()) -> dict:
        user = task_message(env, env.view_cart().data)
        if clarifications:
            user += "\n\nAnswers from the shopper:\n" + json.dumps(list(clarifications))
        messages = [
            {"role": "system", "content": prompts.INTENT_SYSTEM},
            {"role": "user", "content": user + "\n\n" + prompts.INTENT_INSTRUCTIONS
             + "\n\n" + INTERACTIVE_INTENT_GUIDANCE},
        ]
        reply = llm.chat(messages, json_mode=True, env=env)
        return normalize_interactive_intent(json.loads(reply.content))

    @classmethod
    def from_model(cls, env, llm, auto_allowed: Sequence[str] = ()) -> "InteractiveShoppingSession":
        """Extract a fact-preserving intent; missing facts become questions."""
        intent = cls.extract_intent(env, llm)
        return cls(env, intent, auto_allowed=auto_allowed, discovery=ModelDiscovery(llm))

    def _candidate_review_questions(self):
        questions = []
        for requirement in self.choices.requirements.values():
            if requirement.candidates or not requirement.uncertain_candidates:
                continue
            reviews = {r["product_id"]: r for r in requirement.semantic_reviews}
            questions.append({"review_id": f"review_{requirement.requirement_id}_{self.rounds}",
                "requirement_id": requirement.requirement_id,
                "question": "Product information is inconclusive. Is one of these the item you mean?",
                "options": [{**p, "review": reviews[p["id"]]}
                            for p in requirement.uncertain_candidates]})
        return questions

    def answer_candidate_reviews(self, response):
        answers = response.get("answers")
        if not self.pending_candidate_reviews or not isinstance(answers, list):
            raise ValueError("No candidate review is pending, or answers are invalid")
        pending = {q["review_id"]: q for q in self.pending_candidate_reviews}
        if len(answers) != len(pending):
            raise ValueError("One answer is required for each candidate review")
        validated = []
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("review_id") not in pending:
                raise ValueError("Unknown or duplicate candidate review")
            question = pending.pop(answer["review_id"])
            product_id = answer.get("selected_product_id")
            product = next((p for p in question["options"] if p["id"] == product_id), None)
            if product_id is not None and product is None:
                raise ValueError("Product was not offered for review")
            validated.append((question, product))
        for question, product in validated:
            requirement = self.choices.requirements[question["requirement_id"]]
            if product is None:
                requirement.excluded_product_ids.update(p["id"] for p in requirement.uncertain_candidates)
                requirement.discovery_reason = "user_declined"
            else:
                # Confirmation resolves semantics only. Hard product facts are
                # read and checked by Python again before any cart action.
                matched = self.choices.filter_products(self.env, requirement, [product],
                                                       self.intent.get("budget_cents"))
                self.choices.set_candidates(requirement.requirement_id, matched)
                if matched:
                    requirement.selected_product_id = product["id"]
                    requirement.quantity = matched[0]["quantity"]
                    requirement.status = "needs_quantity" if requirement.quantity is None else "selected"
                    requirement.semantic_reviews.append({"product_id": product["id"],
                        "verdict": "user_confirmed", "reason": "Shopper confirmed product meaning", "evidence": []})
            requirement.uncertain_candidates = []
        self.pending_candidate_reviews = []

    def answer_clarifications(self, response: Mapping, llm=None) -> None:
        """Validate a whole clarification batch, then update intent atomically."""
        answers = response.get("answers")
        if not isinstance(answers, list) or len(answers) != len(self.pending_clarifications):
            raise ValueError("One answer is required for each clarification")
        pending = {item["question_id"]: item for item in self.pending_clarifications}
        validated = []
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("question_id") not in pending:
                raise ValueError("Unknown clarification question")
            question = pending.pop(answer["question_id"])
            if question["kind"] == "quantity":
                requirement = self.choices.requirements[question["requirement_id"]]
                if (requirement.status != "needs_quantity"
                        or requirement.selected_product_id != question["product_id"]):
                    raise ValueError("The selected package changed; refresh the quantity question")
                amount = answer.get("amount")
                measure = answer.get("measure") or question["suggested_measure"]
                if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                    raise ValueError("Quantity must be a positive integer")
                if measure not in question["allowed_measures"]:
                    raise ValueError("Unsupported quantity measure")
                validated.append((question, {"amount": amount, "measure": measure,
                                              "product_id": question["product_id"]}))
            else:
                value = answer.get("text")
                if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                    raise ValueError("Clarification text is required (maximum 1000 characters)")
                validated.append((question, value.strip()))
        if pending:
            raise ValueError("Duplicate clarification question")
        free_text = [(question, value) for question, value in validated
                     if question["kind"] == "free_text"]
        if free_text and llm is None:
            raise ValueError("A model is required to interpret free-text clarification")
        for question, value in validated:
            if question["kind"] == "quantity":
                self.quantity_overrides[question["requirement_id"]] = value
                requirement = self.choices.requirements[question["requirement_id"]]
                requirement.measure = "units"
                requirement.target_min = requirement.target_max = value["amount"]
                requirement.quantity = value["amount"]
                requirement.quantity_product_id = value["product_id"]
                requirement.status = "selected"
                for candidate in requirement.candidates:
                    if candidate["id"] == requirement.selected_product_id:
                        candidate["quantity"] = value["amount"]
            else:
                self.clarifications.append({"question": question["question"], "answer": value})
        if free_text:
            self.intent = self.extract_intent(self.env, llm, self.clarifications)
        else:
            self.intent["open_questions"] = []
        for item in self.intent["requirements"]:
            override = self.quantity_overrides.get(item["id"])
            if override:
                item.update({"measure": override["measure"], "min": override["amount"],
                             "max": override["amount"]})
        self.pending_clarifications = []
        if free_text:
            self.clarification_rounds += 1
        if free_text and not clarification_questions(self.intent):
            self.choices = coordinator_from_intent(self.intent)

    def _quantity_questions(self) -> list:
        """Bind missing-quantity questions to the package the shopper chose."""
        questions = []
        for requirement in self.choices.requirements.values():
            if requirement.status != "needs_quantity":
                continue
            product = next(item for item in requirement.candidates
                           if item["id"] == requirement.selected_product_id)
            questions.append({
                "question_id": f"q_{requirement.requirement_id}_quantity",
                "kind": "quantity", "requirement_id": requirement.requirement_id,
                "product_id": product["id"], "product_name": product["name"],
                "package_size": product.get("raw_size") or f"{product.get('size', '')} {product.get('unit', '')}".strip(),
                "price_cents": product["price_cents"],
                "question": f"How many packages of {product['name']} would you like?",
                "suggested_measure": "units", "allowed_measures": ["units"],
            })
        return questions

    def _forget_package_quantity(self, requirement) -> None:
        """A count confirmed for one UPC must not silently transfer to another."""
        if requirement.quantity_product_id is None:
            return
        requirement.quantity_product_id = None
        requirement.quantity = None
        requirement.target_min = requirement.target_max = None
        for candidate in requirement.candidates:
            candidate["quantity"] = None
        self.quantity_overrides.pop(requirement.requirement_id, None)
        for item in self.intent["requirements"]:
            if item["id"] == requirement.requirement_id:
                item["min"] = item["max"] = None

    def _mark_unavailable(self, requirement, product_id) -> None:
        self._forget_package_quantity(requirement)
        self.choices.mark_unavailable(requirement.requirement_id, product_id)

    def _remove_added(self, requirement) -> None:
        product_id = requirement.selected_product_id
        current = self.env.cart.get(product_id, 0)
        remaining = current - requirement.quantity
        if remaining < 0:
            raise ValueError(f"Cart quantity is inconsistent for {product_id}")
        if remaining == 0:
            result = self.env.remove_from_cart(product_id)
        else:
            result = self.env.update_quantity(product_id, remaining)
        if not result.ok:
            raise ValueError(result.message)

    def _refresh_selected(self) -> bool:
        """Refresh every chosen UPC, including items already in the local cart."""
        invalidated = False
        for requirement in self.choices.requirements.values():
            if requirement.status not in {"selected", "added"}:
                continue
            product_id = requirement.selected_product_id
            observed = self.env.get_product(product_id)
            detail = observed.data if observed.ok else None
            valid = bool(detail and detail.get("in_stock")
                         and set(requirement.required_tags).issubset(detail.get("dietary_tags", []))
                         and (not requirement.required_product_ids
                              or product_id in requirement.required_product_ids)
                         and choice_brand_matches(requirement.required_brand,
                                                  requirement.question, detail))
            quantity = packages_for(requirement, detail) if valid else None
            if quantity is None or (requirement.status == "added" and quantity != requirement.quantity):
                if requirement.status == "added":
                    self._remove_added(requirement)
                self._mark_unavailable(requirement, product_id)
                invalidated = True
                continue
            requirement.quantity = quantity
            for product in requirement.candidates:
                if product["id"] == product_id:
                    product["price_cents"] = detail["price_cents"]
                    product["quantity"] = quantity
                    break
        return invalidated

    def _planned_total_cents(self) -> int:
        total = self.env.total_cents
        for requirement in self.choices.requirements.values():
            if requirement.status == "added":
                continue
            product = next((item for item in requirement.candidates
                            if item["id"] == requirement.selected_product_id), None)
            if product is None:
                raise ValueError(f"No selected candidate for {requirement.requirement_id}")
            total += product["price_cents"] * requirement.quantity
        return total

    def verify_cart(self) -> dict:
        """Check the complete basket against each requirement and hard constraint."""
        violations = []
        expected = {}
        for requirement in self.choices.requirements.values():
            if requirement.status != "added":
                violations.append(f"{requirement.requirement_id} is not in the cart")
                continue
            product_id = requirement.selected_product_id
            expected[product_id] = expected.get(product_id, 0) + requirement.quantity
            product = self.env.catalog.get(product_id)
            if product is None:
                violations.append(f"{product_id} has no product details")
                continue
            details = product.public_details(self.env.stock.get(product_id, 0) > 0)
            if not details["in_stock"]:
                violations.append(f"{product_id} is unavailable")
            if not set(requirement.required_tags).issubset(details.get("dietary_tags", [])):
                violations.append(f"{product_id} lacks required dietary evidence")
            if requirement.required_product_ids and product_id not in requirement.required_product_ids:
                violations.append(f"{product_id} is not an allowed product")
            if not choice_brand_matches(requirement.required_brand,
                                        requirement.question, details):
                violations.append(f"{product_id} does not meet the required brand")
            amount = amount_per_package(details, requirement.measure) * requirement.quantity
            if amount < requirement.target_min or (requirement.target_max is not None
                                                   and amount > requirement.target_max):
                violations.append(f"{requirement.requirement_id} supplies {amount} {requirement.measure}, "
                                  f"needs {requirement.target_min}..{requirement.target_max}")
        if dict(self.env.cart) != expected:
            violations.append("Cart contents do not match selected requirements")
        budget = self.intent.get("budget_cents")
        if budget is not None and self.env.total_cents > budget:
            violations.append(f"Cart total {self.env.total_cents} exceeds budget {budget}")
        return {"ok": not violations, "violations": violations,
                "total_cents": self.env.total_cents, "expected_cart": expected}

    def advance(self, answers: Optional[Mapping] = None) -> dict:
        """Run to the next user-choice boundary, completion, or explicit error."""
        if self.env.done:
            return {"status": "complete", "cart": dict(self.env.cart),
                    "total_cents": self.env.total_cents}
        if self.pending_candidate_reviews:
            return {"status": "needs_candidate_review", "questions": self.pending_candidate_reviews}
        if self.pending_clarifications:
            return {"status": "needs_clarification", "questions": self.pending_clarifications}
        needed = clarification_questions(self.intent)
        if needed:
            if self.clarification_rounds >= 3:
                return {"status": "clarification_limit", "questions": needed}
            self.pending_clarifications = needed
            return {"status": "needs_clarification", "questions": needed}
        if answers is not None:
            self.choices.apply_answers(answers)
        elif self.choices._pending:
            return {"status": "waiting_for_user", "questions": list(self.choices._pending.values())}

        while self.rounds < self.max_rounds:
            self.rounds += 1
            if any(r.status == "unresolved" and not r.candidates
                   for r in self.choices.requirements.values()):
                if self.semantic_discovery and self.discovery is None:
                    raise ValueError("Semantic discovery needs a model to continue")
                self.choices.search_unresolved(self.env, self.intent.get("budget_cents"),
                                               self.discovery, self.intent)
            empty = [r.requirement_id for r in self.choices.requirements.values()
                     if r.status == "unresolved" and not r.candidates]
            if empty:
                issues = {rid: self.choices.requirements[rid].discovery_reason for rid in empty}
                error = next((reason for reason in issues.values()
                              if reason in {"search_error", "review_error"}), None)
                if error:
                    return {"status": error, "requirement_ids": empty, "reasons": issues}
                questions = self._candidate_review_questions()
                if questions:
                    self.pending_candidate_reviews = questions
                    return {"status": "needs_candidate_review", "questions": questions}
                return {"status": "no_candidates", "requirement_ids": empty, "reasons": issues}

            decision = self.choices.decide(self.auto_allowed)
            if decision["questions"]:
                return {"status": "waiting_for_user", "questions": decision["questions"]}

            quantities = self._quantity_questions()
            if quantities:
                self.pending_clarifications = quantities
                return {"status": "needs_clarification", "questions": quantities}

            if self._refresh_selected():
                continue

            total = self._planned_total_cents()
            budget = self.intent.get("budget_cents")
            if budget is not None and total > budget:
                return {"status": "budget_conflict", "total_cents": total,
                        "budget_cents": budget, "cart": dict(self.env.cart)}

            retry = False
            for requirement in self.choices.requirements.values():
                if requirement.status == "added":
                    continue
                product_id = requirement.selected_product_id
                if product_id not in self.env.catalog:
                    details = self.env.get_product(product_id)
                    if not details.ok:
                        self._mark_unavailable(requirement, product_id)
                        retry = True
                        continue
                result = self.env.add_to_cart(product_id, requirement.quantity)
                if result.ok:
                    self.choices.mark_added(requirement.requirement_id)
                else:
                    self._mark_unavailable(requirement, product_id)
                    retry = True
            if retry:
                continue
            if self._refresh_selected():
                continue
            if budget is not None and self.env.total_cents > budget:
                return {"status": "budget_conflict", "total_cents": self.env.total_cents,
                        "budget_cents": budget, "cart": dict(self.env.cart)}
            verification = self.verify_cart()
            if not verification["ok"]:
                return {"status": "verification_failed", "verification": verification,
                        "cart": dict(self.env.cart)}
            self.env.finish("interactive choices complete")
            return {"status": "complete", "cart": dict(self.env.cart),
                    "total_cents": self.env.total_cents, "verification": verification}
        return {"status": "round_limit", "rounds": self.rounds}

    def reconsider(self, requirement_ids: Sequence[str]) -> dict:
        """Reopen selected choices after a budget conflict or changed preference."""
        if self.pending_candidate_reviews or self.pending_clarifications or self.choices is None or self.choices._pending:
            raise ValueError("Answer the current choice request first")
        for requirement_id in requirement_ids:
            requirement = self.choices.requirements[requirement_id]
            if requirement.status == "added":
                self._remove_added(requirement)
            self._forget_package_quantity(requirement)
            requirement.selected_product_id = None
            requirement.status = "unresolved"
            requirement.force_user_choice = True
        return self.advance()

    def checkpoint(self) -> dict:
        return {"intent": self.intent, "choices": self.choices.checkpoint() if self.choices else None,
                "auto_allowed": self.auto_allowed, "rounds": self.rounds,
                "max_rounds": self.max_rounds, "cart": dict(self.env.cart),
                "pending_clarifications": self.pending_clarifications,
                "clarifications": self.clarifications,
                "quantity_overrides": self.quantity_overrides,
                "clarification_rounds": self.clarification_rounds,
                "semantic_discovery": self.semantic_discovery,
                "pending_candidate_reviews": self.pending_candidate_reviews}

    @classmethod
    def from_checkpoint(cls, env, snapshot: Mapping, discovery=None) -> "InteractiveShoppingSession":
        session = cls(env, snapshot["intent"], ChoiceCoordinator.from_checkpoint(snapshot["choices"])
                      if snapshot["choices"] else None,
                      snapshot.get("auto_allowed", ()), snapshot.get("max_rounds", 8), discovery)
        session.semantic_discovery = snapshot.get("semantic_discovery", False)
        session.pending_candidate_reviews = list(snapshot.get("pending_candidate_reviews") or [])
        session.rounds = snapshot["rounds"]
        session.pending_clarifications = list(snapshot.get("pending_clarifications") or [])
        session.clarifications = list(snapshot.get("clarifications") or [])
        session.quantity_overrides = dict(snapshot.get("quantity_overrides") or {})
        session.clarification_rounds = snapshot.get("clarification_rounds", 0)
        for product_id, quantity in snapshot["cart"].items():
            if product_id not in env.catalog:
                details = env.get_product(product_id)
                if not details.ok:
                    result = details
                else:
                    result = env.add_to_cart(product_id, quantity)
            else:
                result = env.add_to_cart(product_id, quantity)
            if not result.ok:
                affected = [requirement for requirement in session.choices.requirements.values()
                            if requirement.selected_product_id == product_id]
                if not affected:
                    raise ValueError(f"Could not restore cart item {product_id}: {result.message}")
                for requirement in affected:
                    session._mark_unavailable(requirement, product_id)
        return session
