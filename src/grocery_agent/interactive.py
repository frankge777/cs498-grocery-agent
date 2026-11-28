"""Opt-in, resumable product-choice loop for an intent-grounded shopping run.

The caller owns the environment and stores the checkpoint between requests.
The legacy benchmark agent remains unchanged so historical results stay valid.
"""

from __future__ import annotations

import json
import hashlib
import copy
import time
from typing import Mapping, Optional, Sequence

from .choices import ChoiceCoordinator, choice_brand_matches, coordinator_from_intent, packages_for
from .interactive_intent import (INTERACTIVE_INTENT_GUIDANCE, clarification_questions,
                                 normalize_interactive_intent)
from .llm_agents import amount_per_package, task_message
from . import prompts
from .discovery import ModelDiscovery
from .recommendation import ModelBasketRecommender, RecommendationError
from .intent_schema import INTENT_V2, normalize_v2, source_text, active_spec, fact_violations, IntentContractError
from .quantity_interpretation import ModelQuantityInterpreter, QuantityInterpretationError, quantity_fingerprint


class InteractiveShoppingSession:
    def __init__(self, env, intent: Mapping, coordinator: Optional[ChoiceCoordinator] = None,
                 auto_allowed: Sequence[str] = (), max_rounds: int = 8, discovery=None,
                 selection_mode="user_choice", recommender=None):
        if selection_mode not in {"user_choice", "recommend"}:
            raise ValueError("Unknown selection_mode")
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
        self.selection_mode = selection_mode
        # Opt-in (web app): when the shopper's own words authorize a fallback
        # ("organic if available, otherwise regular") and no primary product
        # passes the checks, use the fallback instead of stopping.
        self.fallback_when_primary_empty = False
        self.recommender = recommender
        self.initial_cart = dict(env.cart)
        self.pending_recommendation = None
        self.recommendation_revision = 0
        self.recommendation_history = []
        self.approved_fingerprint = None
        self.original_request = copy.deepcopy(env.observation())
        self.intent_revisions = []
        self.pending_substitution_questions = []
        self.pending_quantity_reviews = []
        self.pending_issue = None
        self.quantity_interpreter = (ModelQuantityInterpreter(recommender.llm)
            if intent.get("schema_version") == 2 and recommender is not None else None)

    def _active_intent(self):
        if not self.choices or self.intent.get("schema_version") != 2:
            return self.intent
        return {**self.intent, "intent_revisions": self.intent_revisions,
                "requirements": [r.active_requirement() for r in self.choices.requirements.values()]}

    def _invalidate_approval(self):
        self.approved_fingerprint = None
        self.pending_recommendation = None

    @staticmethod
    def extract_intent(env, llm, clarifications=(), selection_mode="user_choice") -> dict:
        cart = env.view_cart().data
        if selection_mode == "recommend":
            obs = env.observation()
            sources = {"instruction": obs["instruction"], "context": source_text(obs.get("household_context", {})),
                       "cart": source_text(cart), "revision": source_text(list(clarifications))}
            messages = [{"role": "system", "content": INTENT_V2},
                        {"role": "user", "content": json.dumps({"sources": sources, "cart": cart})}]
            diagnostics = []
            for attempt in range(2):
                reply = llm.chat(messages, json_mode=True, env=env)
                try:
                    raw = json.loads(reply.content)
                    # Explicit compatibility for existing v1 clients/checkpoints.
                    if isinstance(raw, dict) and raw.get("schema_version", 1) == 1:
                        return normalize_interactive_intent(raw)
                    return normalize_v2(raw, sources)
                except (ValueError, KeyError, TypeError) as error:
                    diagnostics.append({"message": str(error), "raw_response": reply.content[:20000]})
                    if attempt:
                        raise IntentContractError(str(error), diagnostics) from error
                    messages += [{"role": "assistant", "content": reply.content},
                                 {"role": "user", "content": f"Repair once: {error}. Keep actual user constraints; do not fabricate evidence or silently remove explicit needs."}]
        user = task_message(env, cart)
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
    def from_model(cls, env, llm, auto_allowed: Sequence[str] = (),
                   selection_mode="user_choice") -> "InteractiveShoppingSession":
        """Extract a fact-preserving intent; missing facts become questions."""
        intent = cls.extract_intent(env, llm, selection_mode=selection_mode)
        return cls(env, intent, auto_allowed=auto_allowed, discovery=ModelDiscovery(llm),
                   selection_mode=selection_mode,
                   max_rounds=32 if selection_mode == "recommend" else 8,
                   recommender=ModelBasketRecommender(llm) if selection_mode == "recommend" else None)

    def _recommend_unresolved(self):
        needs = [r for r in self.choices.requirements.values()
                 if r.status == "unresolved" and r.candidates and not r.force_user_choice]
        if not needs:
            return
        if self.recommender is None:
            raise RecommendationError("A model is required to recommend products")
        # Validate the full model batch before changing any requirement.
        fixed = [{"requirement_id": r.requirement_id, "product_id": r.selected_product_id,
                  "quantity": r.quantity,
                  "product": next((p for p in r.candidates if p["id"] == r.selected_product_id), None)}
                 for r in self.choices.requirements.values() if r.selected_product_id is not None]
        selections = self.recommender.select(self.env, self._active_intent(), needs, fixed_selections=fixed)
        for row in selections:
            requirement = self.choices.requirements[row["requirement_id"]]
            if row["product_id"] is None:
                requirement.force_user_choice = True
                continue
            product = next(p for p in requirement.candidates if p["id"] == row["product_id"])
            requirement.selected_product_id = product["id"]
            if requirement.rules:
                requirement.selection_revision += 1
                requirement.quantity_interpretation = None
            requirement.quantity = product["quantity"]
            requirement.status = "needs_quantity" if product["quantity"] is None else "selected"
        self.recommendation_history.append({"kind": "model_selection", "selections": selections,
                                            "proposal_revision": self.recommendation_revision + 1})

    def _target_cart(self):
        """Requirements describe FINAL quantities, not quantities to add again."""
        target = {}
        for requirement in self.choices.requirements.values():
            if requirement.selected_product_id is None or requirement.quantity is None:
                raise ValueError("Target cart requires resolved products and quantities")
            pid = requirement.selected_product_id
            target[pid] = target.get(pid, 0) + requirement.quantity
        preserve_unlisted = not self.intent.get("remove_unlisted_items", True)
        if self.intent.get("schema_version") != 2:
            preserve_unlisted = preserve_unlisted or self.intent.get("keep_existing_items")
        if preserve_unlisted:
            for pid, quantity in self.initial_cart.items():
                target.setdefault(pid, quantity)
        return target

    def _basket_proposal(self):
        target = self._target_cart()
        lines = [{"product_id": pid, "name": self.env.catalog[pid].name,
                  "package_size": self.env.catalog[pid].raw_size,
                  "quantity": quantity, "price_cents": self.env.catalog[pid].price_cents,
                  "line_total_cents": self.env.catalog[pid].price_cents * quantity}
                 for pid, quantity in sorted(target.items())]
        operations = []
        for pid in sorted(set(self.env.cart) | set(target)):
            before, after = self.env.cart.get(pid, 0), target.get(pid, 0)
            if before != after:
                operations.append({"product_id": pid, "from_quantity": before, "to_quantity": after,
                                   "action": "remove" if after == 0 else "add" if before == 0 else "update"})
        proposal = {"items": lines, "total_cents": sum(p["line_total_cents"] for p in lines),
                    "budget_cents": self.intent.get("budget_cents"), "operations": operations,
                    "assignments": [{"requirement_id": r.requirement_id,
                                     "product_id": r.selected_product_id, "quantity": r.quantity,
                                     **({"phase": r.phase, "quantity_interpretation": r.quantity_interpretation}
                                        if r.rules else {})}
                                    for r in self.choices.requirements.values()]}
        # Current cart can change after partial execution; approval describes
        # the target products/quantities/prices, not the remaining operations.
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in proposal.items() if k != "operations"},
                                                sort_keys=True).encode()).hexdigest()
        return proposal, fingerprint

    def _recommendation_boundary(self):
        proposal, fingerprint = self._basket_proposal()
        if self.approved_fingerprint == fingerprint:
            self.pending_recommendation = None
            return None
        self.approved_fingerprint = None
        if not self.pending_recommendation or self.pending_recommendation["fingerprint"] != fingerprint:
            self.recommendation_revision += 1
            reasons = {}
            for event in self.recommendation_history:
                if event.get("proposal_revision") == self.recommendation_revision:
                    for row in event.get("selections", []):
                        reasons[(row["requirement_id"], row["product_id"])] = row["reason"]
            for assignment in proposal["assignments"]:
                assignment["reason"] = reasons.get((assignment["requirement_id"], assignment["product_id"]),
                    "Selected product retained; current prices and basket total have been recalculated.")
            self.pending_recommendation = {"recommendation_id": f"basket_{self.recommendation_revision}",
                                           "fingerprint": fingerprint, **proposal}
            self.recommendation_history.append({"kind": "draft_presented",
                                                "draft": copy.deepcopy(self.pending_recommendation)})
        return {"status": "awaiting_basket_confirmation", "recommendation": self.pending_recommendation}

    def answer_recommendation(self, response):
        draft = self.pending_recommendation
        if not isinstance(response, Mapping) or not draft or response.get("recommendation_id") != draft["recommendation_id"]:
            raise ValueError("Unknown or expired recommendation ID")
        action = response.get("action")
        if action == "set_package_counts":
            updates = response.get("updates")
            if not isinstance(updates, list) or not updates:
                raise ValueError("Provide package-count updates")
            seen = set()
            for row in updates:
                if not isinstance(row, dict):
                    raise ValueError("Invalid quantity update")
                rid, amount = row.get("requirement_id"), row.get("amount")
                if (not isinstance(rid, str) or rid not in self.choices.requirements or rid in seen
                        or isinstance(amount, bool) or not isinstance(amount, int) or amount < 1):
                    raise ValueError("Each update requires a unique need and positive package count")
                seen.add(rid)
            for row in updates:
                r = self.choices.requirements[row["requirement_id"]]
                self._apply_package_answer(r, row["amount"], r.selected_product_id)
            self.intent_revisions.append({"kind": "set_package_counts", "answer": copy.deepcopy(dict(response)), "created_at": time.time()})
            self._invalidate_approval()
        elif action == "set_budget":
            budget = response.get("budget_cents")
            if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
                raise ValueError("Budget must be a nonnegative integer in cents")
            self.intent_revisions.append({"kind": "set_budget", "old_budget_cents": self.intent.get("budget_cents"),
                                          "answer": copy.deepcopy(dict(response)), "created_at": time.time()})
            self.intent["budget_cents"] = budget
            self._invalidate_approval()
        elif action == "select_history":
            self._select_history(response)
        elif action == "accept":
            if response.get("requirement_ids"):
                raise ValueError("Accept does not take replacement requirements")
            self.approved_fingerprint = draft["fingerprint"]
            self.pending_recommendation = None
            self.recommendation_history.append({"kind": "accepted", "recommendation_id": draft["recommendation_id"]})
        elif action in {"replace", "choose_candidates"}:
            ids = response.get("requirement_ids")
            if (not isinstance(ids, list) or not ids or any(not isinstance(rid, str) for rid in ids)
                    or len(set(ids)) != len(ids) or any(rid not in self.choices.requirements for rid in ids)):
                raise ValueError("Provide unique known requirement_ids to replace")
            self.pending_recommendation = None
            self.approved_fingerprint = None
            for rid in ids:
                requirement = self.choices.requirements[rid]
                old = requirement.selected_product_id
                # Not chosen in this draft does not mean permanently rejected.
                self._forget_package_quantity(requirement)
                requirement.selected_product_id = None
                requirement.status = "unresolved"
                requirement.force_user_choice = not requirement.rules or action == "choose_candidates"
                if requirement.rules:
                    requirement.quantity_interpretation = None
                    requirement.selection_revision += 1
                    if action == "replace":
                        requirement.candidates = [p for p in requirement.candidates if p["id"] != old]
            self.recommendation_history.append({"kind": "replacement_requested", "requirement_ids": ids})
        else:
            raise ValueError("Recommendation action must be accept, replace or choose_candidates")

    def _select_history(self, response):
        rid, pid = response.get("requirement_id"), response.get("product_id")
        if not isinstance(rid, str) or rid not in self.choices.requirements or not isinstance(pid, str):
            raise ValueError("A known requirement and historical product ID are required")
        r = self.choices.requirements[rid]
        if not r.rules or self.discovery is None or not any(pid in h.get("offered_product_ids", []) for h in r.candidate_history):
            raise ValueError("Product was not an eligible historical candidate")
        detail = self.env.get_product(pid)
        if not detail.ok:
            raise ValueError("Could not refresh historical product")
        staged = copy.deepcopy(r)
        if staged.quantity_product_id is not None and staged.quantity_product_id != pid:
            staged.quantity_product_id = None
            staged.quantity = staged.target_min = staged.target_max = None
        # An explicit return to a historical primary candidate may satisfy the
        # original primary again after stock recovery. Verify semantics first.
        selected_phase = None
        matched = []
        for phase in dict.fromkeys((r.phase, "primary")):
            staged.phase = phase
            active = staged.active_requirement()
            staged.required_tags = active["required_tags"]
            staged.required_brand = active.get("brand")
            staged.required_product_ids = active["product_ids"]
            rows = self.discovery.review(self.env, active, [detail.data])
            if rows[0]["verdict"] != "related":
                continue
            matched = self.choices.filter_products(self.env, staged, [detail.data], self.intent.get("budget_cents"))
            if matched:
                selected_phase = phase
                break
        if selected_phase is None:
            raise ValueError("Historical product does not satisfy current/original authorized scope and hard constraints")
        if r.selected_product_id != pid:
            self._forget_package_quantity(r)
        r.phase = selected_phase
        active = r.active_requirement()
        r.search_query, r.required_brand = active["search_query"], active.get("brand")
        r.required_tags, r.required_product_ids = active["required_tags"], active["product_ids"]
        r.selected_product_id, r.quantity = pid, matched[0]["quantity"]
        r.candidates = matched
        r.quantity_interpretation = None
        r.selection_revision += 1
        r.status = "needs_quantity" if r.quantity is None else "selected"
        self.intent_revisions.append({"kind": "select_history", "answer": copy.deepcopy(dict(response)), "created_at": time.time()})
        self._invalidate_approval()

    def _substitution_boundary(self):
        blocked = [r for r in self.choices.requirements.values() if r.status == "needs_substitution_permission"]
        if blocked:
            if not self.pending_substitution_questions:
                self.pending_substitution_questions = [{
                    "question_id": f"sub_{r.requirement_id}_{r.selection_revision}",
                    "requirement_id": r.requirement_id, "primary": r.rules["primary"],
                    "availability_observations": copy.deepcopy(r.availability_observations),
                    "question": "The requested product was unavailable at the recorded observation. May I recommend a substitute? Specify the permitted scope, or decline.",
                    "constraints": r.active_requirement().get("constraints", [])} for r in blocked]
            return {"status": "needs_substitution_permission", "questions": self.pending_substitution_questions}
        declined = [r.requirement_id for r in self.choices.requirements.values() if r.status == "substitution_declined"]
        if declined:
            return {"status": "substitution_declined", "requirement_ids": declined,
                    "message": "Request remains unfulfilled; waiting for an explicit shopper revision."}
        return None

    def answer_substitutions(self, response):
        answers = response.get("answers")
        pending = {q["question_id"]: q for q in self.pending_substitution_questions}
        if not pending or not isinstance(answers, list) or len(answers) != len(pending):
            raise ValueError("Answer every pending substitution question")
        validated = []
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("question_id") not in pending:
                raise ValueError("Unknown or duplicate substitution question")
            question = pending.pop(answer["question_id"])
            if answer.get("action") not in {"allow_scope", "decline"}:
                raise ValueError("Use allow_scope with text, or decline")
            scope = answer.get("scope")
            if answer["action"] == "allow_scope" and (not isinstance(scope, str) or not scope.strip() or len(scope) > 1000):
                raise ValueError("An explicit substitute scope is required; bare approval is insufficient")
            # Recheck before committing ANY answer: an old observation is not
            # sufficient to enter fallback after a long user pause.
            recovered = False
            r = self.choices.requirements[question["requirement_id"]]
            if answer["action"] == "allow_scope":
                unavailable_ids = [pid for pid, data in r.availability_observations.items()
                                   if data.get("in_stock") is False]
                if not unavailable_ids:
                    raise ValueError("Missing confirmed stock observation; cannot activate substitution")
                latest_id = max(unavailable_ids, key=lambda pid: r.availability_observations[pid]["observed_at"])
                detail = self.env.get_product(latest_id)
                if not detail.ok or not isinstance(detail.data.get("in_stock"), bool):
                    raise ValueError("Cannot recheck availability; substitution answer remains pending")
                recovered = detail.data["in_stock"]
            validated.append((question, answer, recovered))
        for question, answer, recovered in validated:
            r = self.choices.requirements[question["requirement_id"]]
            self.intent_revisions.append({"kind": "substitution_permission", "question": question,
                                          "answer": copy.deepcopy(answer), "created_at": time.time()})
            if answer["action"] == "decline":
                r.status = "substitution_declined"
                continue
            scope = answer["scope"].strip()
            r.rules["fallback"] = {"trigger": "confirmed_out_of_stock", "description": scope,
                "search_query": scope, "brand": None, "product_ids": [], "constraints": [],
                "evidence": [{"source": "revision", "quote": scope}]}
            r.phase = "primary" if recovered else "fallback"
            active = r.active_requirement()
            r.search_query, r.required_brand = active["search_query"], active.get("brand")
            r.required_product_ids, r.required_tags = active["product_ids"], active["required_tags"]
            if recovered:
                r.search_attempts = [a for a in r.search_attempts if a.get("phase") != "primary"]
            r.status = "unresolved"
        self.pending_substitution_questions = []
        self._invalidate_approval()

    def _interpret_quantities(self):
        """Return true only when a stock event requires fresh discovery."""
        self.pending_quantity_reviews = []
        for r in self.choices.requirements.values():
            if not r.rules or r.status not in {"selected", "needs_quantity", "added"}:
                continue
            observed = self.env.get_product(r.selected_product_id)
            if not observed.ok:
                self.pending_issue = {"status": "product_refresh_error", "requirement_id": r.requirement_id,
                                      "error": observed.message}
                self._invalidate_approval()
                return False
            detail = observed.data
            if detail.get("in_stock") is False:
                if r.status == "added":
                    self._remove_added(r)
                self._mark_unavailable(r, r.selected_product_id)
                return True
            fp = quantity_fingerprint(detail)
            if r.quantity_interpretation and r.quantity_interpretation.get("facts_fingerprint") == fp:
                result = r.quantity_interpretation
            elif r.quantity_product_id == detail["id"]:
                result = {"status": "proposal", "purchase_packages": r.quantity, "product_id": detail["id"],
                          "explanation": "Shopper confirmed this exact product and package count.",
                          "facts_fingerprint": fp, "selection_revision": r.selection_revision, "source": "user",
                          "normalized_contents": ({"amount": detail["size"] * r.quantity, "unit": detail["unit"]}
                                                   if detail.get("unit") in {"ct", "g", "ml"} else None)}
            else:
                if self.quantity_interpreter is None:
                    raise QuantityInterpretationError("A model is required for the quantity interpretation step")
                result = self.quantity_interpreter.interpret(self.env, r, detail, self.intent.get("source_records", {}))
            r.quantity_interpretation = result
            for p in r.candidates:
                if p["id"] == detail["id"]:
                    p.update(detail)
            if result["status"] == "proposal":
                r.quantity = result["purchase_packages"]
                if r.status != "added":
                    r.status = "selected"
                for p in r.candidates:
                    if p["id"] == detail["id"]:
                        p["quantity"] = r.quantity
            elif result["status"] == "needs_clarification" and r.target_min is None:
                r.status = "needs_quantity"
            else:
                self._invalidate_approval()
                self.pending_quantity_reviews.append({
                    "question_id": f"interpret_{r.requirement_id}_{r.selection_revision}",
                    "requirement_id": r.requirement_id, "product": detail, "interpretation": result,
                    "reason_code": result.get("reason_code"),
                    "question": result["question"], "actions": ["replace", "confirm_selected_package_count"]})
        return False

    def answer_quantity_reviews(self, response):
        answers = response.get("answers")
        pending = {q["question_id"]: q for q in self.pending_quantity_reviews}
        if not pending or not isinstance(answers, list) or len(answers) != len(pending):
            raise ValueError("Answer every pending quantity interpretation")
        validated = []
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("question_id") not in pending:
                raise ValueError("Unknown or stale interpretation question")
            q = pending.pop(answer["question_id"])
            r = self.choices.requirements[q["requirement_id"]]
            if r.selected_product_id != q["product"]["id"]:
                raise ValueError("Recommended product changed")
            action = answer.get("action")
            if action == "confirm_selected_package_count":
                amount = answer.get("amount")
                if (answer.get("acknowledge_product_change") is not True or isinstance(amount, bool)
                        or not isinstance(amount, int) or amount < 1):
                    raise ValueError("Confirm the displayed product change and a positive package count explicitly")
            elif action != "replace":
                raise ValueError("Use replace or confirm_selected_package_count")
            validated.append((q, answer))
        for q, answer in validated:
            r = self.choices.requirements[q["requirement_id"]]
            self.intent_revisions.append({"kind": "quantity_interpretation", "question": q,
                                          "answer": copy.deepcopy(answer), "created_at": time.time()})
            if answer["action"] == "replace":
                old = r.selected_product_id
                self._forget_package_quantity(r)
                r.candidates = [p for p in r.candidates if p["id"] != old]
                r.selected_product_id = None
                r.quantity_interpretation = None
                r.selection_revision += 1
                r.status = "unresolved"
            else:
                self._apply_package_answer(r, answer["amount"], q["product"]["id"])
                # The shopper explicitly accepted THIS displayed product and
                # package form. Preserve all tag/nutrition constraints.
                r.rules[r.phase]["description"] = q["product"]["name"]
                r.rules[r.phase]["search_query"] = q["product"]["name"]
                r.quantity_interpretation = None
        self.pending_quantity_reviews = []
        self._invalidate_approval()

    def _apply_package_answer(self, requirement, amount, product_id):
        override = {"amount": amount, "measure": "units", "product_id": product_id}
        self.quantity_overrides[requirement.requirement_id] = override
        requirement.measure = "units"
        requirement.target_min = requirement.target_max = amount
        requirement.quantity = amount
        requirement.quantity_product_id = product_id
        requirement.status = "selected"
        requirement.quantity_interpretation = None
        for item in self.intent["requirements"]:
            if item["id"] == requirement.requirement_id:
                item.update(measure="units", min=amount, max=amount)

    def _fallback_for_empty_primary(self, requirement_ids) -> bool:
        """Switch primary->fallback for needs whose primary found nothing eligible.

        Only when opted in, only for a fallback the intent recorded from the
        shopper's own words, and never after search/review infrastructure errors.
        """
        if not self.fallback_when_primary_empty:
            return False
        switched = False
        for rid in requirement_ids:
            r = self.choices.requirements[rid]
            if (not r.rules or r.phase != "primary" or not r.rules.get("fallback")
                    or r.uncertain_candidates or r.discovery_reason in {"search_error", "review_error"}):
                continue
            relaxed = self._conditional_preference_tags(r.rules)
            if relaxed:
                r.rules["constraints"] = [c for c in r.rules.get("constraints", []) if c not in relaxed]
            r.candidate_history.append({"phase": "primary", "observed_at": time.time(),
                                        "event": "fallback_no_eligible_primary", "reason": r.discovery_reason,
                                        "relaxed_constraints": copy.deepcopy(relaxed)})
            self.intent_revisions.append({"kind": "fallback_no_eligible_primary", "requirement_id": rid,
                                          "relaxed_constraints": copy.deepcopy(relaxed), "created_at": time.time()})
            r.phase = "fallback"
            active = r.active_requirement()
            r.search_query = active["search_query"]
            r.question = f"Which product for {active['description']}?"
            r.required_brand = active.get("brand")
            r.required_tags = active["required_tags"]
            r.required_product_ids = active["product_ids"]
            r.selected_product_id = None
            r.quantity_interpretation = None
            r.selection_revision += 1
            r.candidates = []
            r.status = "unresolved"
            switched = True
        if switched:
            self._invalidate_approval()
        return switched

    RELAXABLE_PREFERENCE_TAGS = frozenset({"organic", "non_gmo"})

    @classmethod
    def _conditional_preference_tags(cls, rules):
        """Preference tags stated only inside the shopper's fallback rule.

        "Organic when available, otherwise regular" yields an invariant
        organic tag whose evidence sits inside the fallback's evidence; that
        tag belongs to the primary only. Dietary/safety tags are never relaxed.
        """
        fallback_quotes = [e.get("quote", "") for e in (rules.get("fallback") or {}).get("evidence", [])]
        relaxed = []
        for c in rules.get("constraints", []):
            quotes = [e.get("quote", "") for e in c.get("evidence", [])]
            if (c.get("kind") == "tag" and c.get("value") in cls.RELAXABLE_PREFERENCE_TAGS and quotes
                    and all(q and any(q in f for f in fallback_quotes) for q in quotes)):
                relaxed.append(c)
        return relaxed

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
                if requirement.rules:
                    requirement.status = "needs_search_revision"
                    requirement.candidate_history.append({"phase": requirement.phase, "observed_at": time.time(),
                        "event": "uncertain_options_declined", "product_ids": [p["id"] for p in requirement.uncertain_candidates]})
                else:
                    requirement.excluded_product_ids.update(p["id"] for p in requirement.uncertain_candidates)
                requirement.discovery_reason = "user_declined"
            else:
                # Confirmation resolves semantics only. Hard product facts are
                # read and checked by Python again before any cart action.
                matched = self.choices.filter_products(self.env, requirement, [product],
                                                       self.intent.get("budget_cents"))
                self.choices.set_candidates(requirement.requirement_id, matched)
                if matched:
                    if requirement.rules:
                        requirement.selection_revision += 1
                        requirement.quantity_interpretation = None
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
                requirement = self.choices.requirements[question["requirement_id"]]
                self._apply_package_answer(requirement, value["amount"], value["product_id"])
                if requirement.rules:
                    self.intent_revisions.append({"kind": "quantity_answer", "question": question,
                                                  "answer": value, "created_at": time.time()})
                for candidate in requirement.candidates:
                    if candidate["id"] == requirement.selected_product_id:
                        candidate["quantity"] = value["amount"]
            else:
                self.clarifications.append({"question": question["question"], "answer": value})
        if free_text:
            self.intent = self.extract_intent(self.env, llm, self.clarifications, self.selection_mode)
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
                "question_id": (f"q_{requirement.requirement_id}_quantity" if self.selection_mode == "user_choice"
                                else f"q_{requirement.requirement_id}_quantity_{product['id']}_{requirement.selection_revision}_{self.recommendation_revision}"),
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
        if requirement.rules:
            self._invalidate_approval()
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
        if self.intent.get("schema_version") == 2:
            return self._refresh_v2_selected()
        invalidated = False
        for requirement in self.choices.requirements.values():
            if requirement.status not in {"selected", "added"}:
                continue
            product_id = requirement.selected_product_id
            observed = self.env.get_product(product_id)
            detail = observed.data if observed.ok else None
            valid = bool(detail and detail.get("in_stock") and detail.get("price_cents", 0) > 0
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

    def _refresh_v2_selected(self):
        for r in self.choices.requirements.values():
            if r.status not in {"selected", "added"}:
                continue
            result = self.env.get_product(r.selected_product_id)
            if not result.ok:
                self._invalidate_approval()
                self.pending_issue = {"status": "product_refresh_error", "requirement_id": r.requirement_id,
                                      "error": result.message}
                return False
            detail = result.data
            if detail.get("in_stock") is False:
                if r.status == "added":
                    self._remove_added(r)
                self._mark_unavailable(r, r.selected_product_id)
                return True
            violations = fact_violations(detail, r.active_requirement().get("constraints", []))
            if (detail.get("in_stock") is not True or detail.get("price_cents", 0) <= 0
                    or not choice_brand_matches(r.required_brand, r.question, detail)
                    or (r.required_product_ids and detail["id"] not in r.required_product_ids)):
                violations.append({"code": "invalid_current_product"})
            if violations:
                self._invalidate_approval()
                self.pending_issue = {"status": "product_constraint_conflict", "requirement_id": r.requirement_id,
                                      "violations": violations}
                return False
            if not r.quantity_interpretation or r.quantity_interpretation.get("facts_fingerprint") != quantity_fingerprint(detail):
                r.quantity_interpretation = None
                r.status = "selected"
                self._invalidate_approval()
                return True
            for candidate in r.candidates:
                if candidate["id"] == detail["id"]:
                    candidate.update(detail)
                    candidate["quantity"] = r.quantity
        return False

    def _planned_total_cents(self) -> int:
        return sum(self.env.catalog[pid].price_cents * quantity
                   for pid, quantity in self._target_cart().items())

    def verify_cart(self) -> dict:
        """Check the complete basket against each requirement and hard constraint."""
        violations = []
        expected = self._target_cart()
        for requirement in self.choices.requirements.values():
            if requirement.status != "added":
                violations.append(f"{requirement.requirement_id} is not in the cart")
                continue
            product_id = requirement.selected_product_id
            product = self.env.catalog.get(product_id)
            if product is None:
                violations.append(f"{product_id} has no product details")
                continue
            details = product.public_details(self.env.stock.get(product_id, 0) > 0)
            if not details["in_stock"]:
                violations.append(f"{product_id} is unavailable")
            if not set(requirement.required_tags).issubset(details.get("dietary_tags", [])):
                violations.append(f"{product_id} lacks required dietary evidence")
            if requirement.rules and fact_violations(details, requirement.active_requirement().get("constraints", [])):
                violations.append(f"{product_id} violates current fact constraints")
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
        for pid in expected:
            product = self.env.catalog.get(pid)
            if product is None or self.env.stock.get(pid, 0) <= 0 or product.price_cents <= 0:
                violations.append(f"{pid} has invalid current availability or price")
            elif not set(self.intent.get("all_items_required_tags", [])).issubset(product.tags):
                violations.append(f"{pid} lacks basket-wide dietary evidence")
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
        if self.pending_quantity_reviews:
            return {"status": "needs_quantity_review", "questions": self.pending_quantity_reviews}
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
            self.pending_issue = None
            boundary = self._substitution_boundary()
            if boundary:
                return boundary
            declined_review = [r.requirement_id for r in self.choices.requirements.values() if r.status == "needs_search_revision"]
            if declined_review:
                return {"status": "needs_search_revision", "requirement_ids": declined_review,
                        "message": "Please revise the search preference or request reconsideration; no permanent rejection was recorded."}
            if any(r.status == "unresolved" and not r.candidates
                   for r in self.choices.requirements.values()):
                if self.semantic_discovery and self.discovery is None:
                    raise ValueError("Semantic discovery needs a model to continue")
                before = [(r.phase, r.status) for r in self.choices.requirements.values()]
                self.choices.search_unresolved(self.env, self.intent.get("budget_cents"),
                                               self.discovery, self.intent)
                if before != [(r.phase, r.status) for r in self.choices.requirements.values()]:
                    continue
            empty = [r.requirement_id for r in self.choices.requirements.values()
                     if r.status == "unresolved" and not r.candidates]
            if empty:
                issues = {rid: self.choices.requirements[rid].discovery_reason for rid in empty}
                error = next((reason for reason in issues.values()
                              if reason in {"search_error", "review_error"}), None)
                if error:
                    return {"status": error, "requirement_ids": empty, "reasons": issues}
                if self._fallback_for_empty_primary(empty):
                    continue
                questions = self._candidate_review_questions()
                if questions:
                    self.pending_candidate_reviews = questions
                    return {"status": "needs_candidate_review", "questions": questions}
                return {"status": "no_candidates", "requirement_ids": empty, "reasons": issues}

            if self.selection_mode == "recommend":
                try:
                    self._recommend_unresolved()
                except RecommendationError as error:
                    return {"status": "recommendation_error", "error": str(error)}
            decision = (self.choices.prepare_batch() if self.selection_mode == "recommend"
                        else self.choices.decide(self.auto_allowed))
            if decision["questions"]:
                return {"status": "waiting_for_user", "questions": decision["questions"]}

            if self.intent.get("schema_version") == 2:
                try:
                    if self._interpret_quantities():
                        continue
                except QuantityInterpretationError as error:
                    return {"status": "quantity_interpretation_error", "error": str(error)}
                if self.pending_issue:
                    return self.pending_issue
                if self.pending_quantity_reviews:
                    return {"status": "needs_quantity_review", "questions": self.pending_quantity_reviews}

            quantities = self._quantity_questions()
            if quantities:
                self.pending_clarifications = quantities
                return {"status": "needs_clarification", "questions": quantities}

            if self._refresh_selected():
                continue
            if self.pending_issue:
                return self.pending_issue

            # Unlisted initial items can be preserved by intent. They also
            # require current facts; keeping them cannot bypass the final check.
            selected_ids = {r.selected_product_id for r in self.choices.requirements.values()}
            for pid in self._target_cart().keys() - selected_ids:
                observed = self.env.get_product(pid)
                if not observed.ok or not observed.data.get("in_stock") or observed.data.get("price_cents", 0) <= 0:
                    self.pending_recommendation = None
                    self.approved_fingerprint = None
                    return {"status": "existing_item_unavailable", "product_id": pid}

            total = self._planned_total_cents()
            budget = self.intent.get("budget_cents")
            if budget is not None and total > budget:
                self.pending_recommendation = None
                self.approved_fingerprint = None
                return {"status": "budget_conflict", "total_cents": total,
                        "budget_cents": budget, "cart": dict(self.env.cart)}

            if self.selection_mode == "recommend":
                boundary = self._recommendation_boundary()
                if boundary:
                    return boundary

            retry = False
            target = self._target_cart()
            # Apply a target-cart diff: remove/reduce first, then add/increase.
            pids = sorted(set(self.env.cart) | set(target),
                          key=lambda pid: (target.get(pid, 0) > self.env.cart.get(pid, 0), pid))
            for product_id in pids:
                before, after = self.env.cart.get(product_id, 0), target.get(product_id, 0)
                if before == after:
                    continue
                if after == 0:
                    result = self.env.remove_from_cart(product_id)
                elif before == 0:
                    result = self.env.add_to_cart(product_id, after)
                else:
                    result = self.env.update_quantity(product_id, after)
                if not result.ok:
                    affected = [r for r in self.choices.requirements.values()
                                if r.selected_product_id == product_id]
                    if not affected:
                        return {"status": "cart_update_failed", "error": result.message}
                    for requirement in affected:
                        if requirement.rules:
                            reason = getattr(result, "reason", None) or (result.data or {}).get("reason")
                            if reason not in {None, "confirmed_out_of_stock"}:
                                self._invalidate_approval()
                                return {"status": "cart_update_failed", "reason": reason, "error": result.message}
                            refreshed = self.env.get_product(product_id)
                            if not refreshed.ok or refreshed.data.get("in_stock") is not False:
                                self._invalidate_approval()
                                return {"status": "cart_update_failed", "reason": "unconfirmed_failure",
                                        "error": result.message, "requirement_id": requirement.requirement_id}
                        self._mark_unavailable(requirement, product_id)
                    retry = True
            for requirement in self.choices.requirements.values():
                if (requirement.status == "selected" and
                        self.env.cart.get(requirement.selected_product_id) == target[requirement.selected_product_id]):
                    self.choices.mark_added(requirement.requirement_id)
            if retry:
                continue
            if self._refresh_selected():
                continue
            if self.pending_issue:
                return self.pending_issue
            if budget is not None and self.env.total_cents > budget:
                self.approved_fingerprint = None
                return {"status": "budget_conflict", "total_cents": self.env.total_cents,
                        "budget_cents": budget, "cart": dict(self.env.cart)}
            if self.selection_mode == "recommend":
                boundary = self._recommendation_boundary()
                if boundary:
                    return boundary
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
        ids = list(requirement_ids)
        if not ids or len(set(ids)) != len(ids) or any(rid not in self.choices.requirements for rid in ids):
            raise ValueError("Provide distinct known requirement IDs")
        for requirement_id in ids:
            requirement = self.choices.requirements[requirement_id]
            if requirement.rules and requirement.status == "substitution_declined":
                requirement.selection_revision += 1
                requirement.status = "needs_substitution_permission"
                self.pending_substitution_questions = []
                continue
            if requirement.status == "added" and not requirement.rules:
                self._remove_added(requirement)
            self._forget_package_quantity(requirement)
            requirement.selected_product_id = None
            requirement.status = "unresolved"
            requirement.force_user_choice = True
        self._invalidate_approval()
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
                "pending_candidate_reviews": self.pending_candidate_reviews,
                "selection_mode": self.selection_mode, "initial_cart": self.initial_cart,
                "pending_recommendation": self.pending_recommendation,
                "recommendation_revision": self.recommendation_revision,
                "recommendation_history": self.recommendation_history,
                "approved_fingerprint": self.approved_fingerprint,
                "schema_version": self.intent.get("schema_version", 1),
                "original_request": self.original_request, "intent_revisions": self.intent_revisions,
                "pending_substitution_questions": self.pending_substitution_questions,
                "pending_quantity_reviews": self.pending_quantity_reviews,
                "fallback_when_primary_empty": self.fallback_when_primary_empty}

    @classmethod
    def from_checkpoint(cls, env, snapshot: Mapping, discovery=None, recommender=None) -> "InteractiveShoppingSession":
        session = cls(env, snapshot["intent"], ChoiceCoordinator.from_checkpoint(snapshot["choices"])
                      if snapshot["choices"] else None,
                      snapshot.get("auto_allowed", ()), snapshot.get("max_rounds", 8), discovery,
                      snapshot.get("selection_mode", "user_choice"), recommender)
        session.initial_cart = dict(snapshot.get("initial_cart", env.cart))
        session.pending_recommendation = snapshot.get("pending_recommendation")
        session.recommendation_revision = snapshot.get("recommendation_revision", 0)
        session.recommendation_history = list(snapshot.get("recommendation_history", []))
        session.approved_fingerprint = snapshot.get("approved_fingerprint")
        session.original_request = copy.deepcopy(snapshot.get("original_request", env.observation()))
        session.intent_revisions = copy.deepcopy(snapshot.get("intent_revisions", []))
        session.pending_substitution_questions = copy.deepcopy(snapshot.get("pending_substitution_questions", []))
        session.pending_quantity_reviews = copy.deepcopy(snapshot.get("pending_quantity_reviews", []))
        session.fallback_when_primary_empty = bool(snapshot.get("fallback_when_primary_empty", False))
        session.semantic_discovery = snapshot.get("semantic_discovery", False)
        session.pending_candidate_reviews = list(snapshot.get("pending_candidate_reviews") or [])
        session.rounds = snapshot["rounds"]
        session.pending_clarifications = list(snapshot.get("pending_clarifications") or [])
        session.clarifications = list(snapshot.get("clarifications") or [])
        session.quantity_overrides = dict(snapshot.get("quantity_overrides") or {})
        session.clarification_rounds = snapshot.get("clarification_rounds", 0)
        env.cart.clear()
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
                    if requirement.rules:
                        current = env.get_product(product_id)
                        if not current.ok or current.data.get("in_stock") is not False:
                            raise ValueError(f"Could not restore cart item {product_id}; failure is not confirmed out of stock")
                    session._mark_unavailable(requirement, product_id)
        return session
