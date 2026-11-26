"""Opt-in, resumable product-choice loop for an intent-grounded shopping run.

The caller owns the environment and stores the checkpoint between requests.
The legacy benchmark agent remains unchanged so historical results stay valid.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional, Sequence

from .choices import ChoiceCoordinator, coordinator_from_intent
from .llm_agents import normalize_intent, task_message
from . import prompts


class InteractiveShoppingSession:
    def __init__(self, env, intent: Mapping, coordinator: Optional[ChoiceCoordinator] = None,
                 auto_allowed: Sequence[str] = (), max_rounds: int = 8):
        self.env = env
        self.intent = dict(intent)
        self.choices = coordinator or coordinator_from_intent(intent)
        self.auto_allowed = list(auto_allowed)
        self.rounds = 0
        self.max_rounds = max_rounds

    @classmethod
    def from_model(cls, env, llm, auto_allowed: Sequence[str] = ()) -> "InteractiveShoppingSession":
        """One model call extracts intent; tool/search/selection stay in Python."""
        messages = [
            {"role": "system", "content": prompts.INTENT_SYSTEM},
            {"role": "user", "content": task_message(env, env.view_cart().data) + "\n\n" + prompts.INTENT_INSTRUCTIONS},
        ]
        reply = llm.chat(messages, json_mode=True, env=env)
        intent = normalize_intent(json.loads(reply.content), strict_upc=True)
        if intent["open_questions"]:
            raise ValueError("Free-text clarification must be resolved before product choices")
        if not intent["requirements"]:
            raise ValueError("No shopping requirements were extracted")
        return cls(env, intent, auto_allowed=auto_allowed)

    def advance(self, answers: Optional[Mapping] = None) -> dict:
        """Run to the next user-choice boundary, completion, or explicit error."""
        if self.env.done:
            return {"status": "complete", "cart": dict(self.env.cart),
                    "total_cents": self.env.total_cents}
        if answers is not None:
            self.choices.apply_answers(answers)
        elif self.choices._pending:
            return {"status": "waiting_for_user", "questions": list(self.choices._pending.values())}

        while self.rounds < self.max_rounds:
            self.rounds += 1
            if any(r.status == "unresolved" and not r.candidates
                   for r in self.choices.requirements.values()):
                self.choices.search_unresolved(self.env, self.intent.get("budget_cents"))
            empty = [r.requirement_id for r in self.choices.requirements.values()
                     if r.status == "unresolved" and not r.candidates]
            if empty:
                return {"status": "no_candidates", "requirement_ids": empty}

            decision = self.choices.decide(self.auto_allowed)
            if decision["questions"]:
                return {"status": "waiting_for_user", "questions": decision["questions"]}

            # Live prices and fulfillment can change while the user is choosing.
            refreshed = False
            for requirement in self.choices.requirements.values():
                if requirement.status != "selected":
                    continue
                product_id = requirement.selected_product_id
                detail = self.env.get_product(product_id)
                if not detail.ok or not detail.data.get("in_stock", False):
                    self.choices.mark_unavailable(requirement.requirement_id, product_id)
                    refreshed = True
                    continue
                if not set(requirement.required_tags).issubset(detail.data.get("dietary_tags", [])):
                    self.choices.mark_unavailable(requirement.requirement_id, product_id)
                    refreshed = True
                    continue
                for product in requirement.candidates:
                    if product["id"] == product_id:
                        product["price_cents"] = detail.data["price_cents"]
                        break
            if refreshed:
                continue

            total = self.env.total_cents
            for requirement in self.choices.requirements.values():
                if requirement.status == "added":
                    continue
                product = next(p for p in requirement.candidates
                               if p["id"] == requirement.selected_product_id)
                total += product["price_cents"] * requirement.quantity
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
                        self.choices.mark_unavailable(requirement.requirement_id, product_id)
                        retry = True
                        continue
                result = self.env.add_to_cart(product_id, requirement.quantity)
                if result.ok:
                    self.choices.mark_added(requirement.requirement_id)
                else:
                    self.choices.mark_unavailable(requirement.requirement_id, product_id)
                    retry = True
            if retry:
                continue
            self.env.finish("interactive choices complete")
            return {"status": "complete", "cart": dict(self.env.cart),
                    "total_cents": self.env.total_cents}
        return {"status": "round_limit", "rounds": self.rounds}

    def reconsider(self, requirement_ids: Sequence[str]) -> dict:
        """Reopen selected choices after a budget conflict or changed preference."""
        if self.choices._pending:
            raise ValueError("Answer the current choice request first")
        for requirement_id in requirement_ids:
            requirement = self.choices.requirements[requirement_id]
            if requirement.status == "added":
                self.env.remove_from_cart(requirement.selected_product_id)
            requirement.selected_product_id = None
            requirement.status = "unresolved"
            requirement.force_user_choice = True
        return self.advance()

    def checkpoint(self) -> dict:
        return {"intent": self.intent, "choices": self.choices.checkpoint(),
                "auto_allowed": self.auto_allowed, "rounds": self.rounds,
                "max_rounds": self.max_rounds, "cart": dict(self.env.cart)}

    @classmethod
    def from_checkpoint(cls, env, snapshot: Mapping) -> "InteractiveShoppingSession":
        session = cls(env, snapshot["intent"], ChoiceCoordinator.from_checkpoint(snapshot["choices"]),
                      snapshot.get("auto_allowed", ()), snapshot.get("max_rounds", 8))
        session.rounds = snapshot["rounds"]
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
                    session.choices.mark_unavailable(requirement.requirement_id, product_id)
        return session
