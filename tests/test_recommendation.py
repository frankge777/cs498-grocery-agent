"""Contract and recovery tests. Scripted models do not measure model accuracy."""

import copy
import json
import unittest
from dataclasses import replace

from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.interactive_intent import normalize_interactive_intent
from grocery_agent.llm import ScriptedLLM
from grocery_agent.recommendation import ModelBasketRecommender
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario
from grocery_web import interactive_service
from tests.test_interactive_service import ScriptedLLM as DiscoveryLLM


def basket_llm(picks=None, intent=None):
    def respond(messages, tools, json_mode):
        if "Task: basket_recommendation" in messages[0]["content"]:
            body = json.loads(messages[-1]["content"])
            rows = []
            for need in body["needs"]:
                candidates = need["candidates"]
                pid = picks.get(need["requirement_id"]) if picks is not None else min(
                    candidates, key=lambda p: (p["price_cents"] * (p["quantity"] or 1), p["id"]))["id"]
                rows.append({"requirement_id": need["requirement_id"], "product_id": pid,
                             "reason": "Scripted recommendation"})
            return {"content": json.dumps({"selections": rows})}
        return {"content": json.dumps(intent or {})}
    return DiscoveryLLM(respond)


class RecommendationTests(unittest.TestCase):
    def env(self, initial=None, events=()):
        scenario = Scenario(id="recommend-test", category="development", difficulty="M", title="Recommendation",
            variants={v: "Buy one carrots and one yogurt" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True, initial_cart=initial or {}, events=list(events))
        return GroceryEnv(load_catalog(), scenario, "high")

    def intent(self, unknown=False):
        return normalize_interactive_intent({"budget_cents": 800, "requirements": [
            {"id": "r1", "description": "carrots", "min": 1, "max": 1},
            {"id": "r2", "description": "yogurt", "min": None if unknown else 1, "max": None if unknown else 1}]})

    def session(self, env=None, unknown=False, picks=None):
        return InteractiveShoppingSession(env or self.env(), self.intent(unknown), selection_mode="recommend",
                                          recommender=ModelBasketRecommender(basket_llm(picks)), max_rounds=32)

    def accept(self, session, result):
        session.answer_recommendation({"recommendation_id": result["recommendation"]["recommendation_id"],
                                       "action": "accept"})
        return session.advance()

    def test_model_recommends_but_does_not_mutate_cart_before_acceptance(self):
        session = self.session()
        result = session.advance()
        self.assertEqual(result["status"], "awaiting_basket_confirmation")
        self.assertEqual(session.env.cart, {})
        self.assertFalse(any(s["tool"] == "add_to_cart" for s in session.env.trajectory))
        self.assertEqual(result["recommendation"]["total_cents"], 278)
        self.assertEqual(self.accept(session, result)["status"], "complete")

    def test_replacement_only_reopens_requested_need_and_preserves_other_selection(self):
        session = self.session()
        result = session.advance()
        carrot = copy.deepcopy(session.choices.requirements["r1"])
        session.answer_recommendation({"recommendation_id": result["recommendation"]["recommendation_id"],
                                       "action": "replace", "requirement_ids": ["r2"]})
        options = session.advance()
        self.assertEqual(options["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in options["questions"]], ["r2"])
        self.assertEqual(session.choices.requirements["r1"], carrot)
        q = options["questions"][0]
        self.assertIn("yogurt_value_cup", [p["product_id"] for p in q["options"]])
        selected = next(p for p in q["options"] if p["product_id"] == "yogurt_fresh_greek")
        draft = session.advance({"answers": [{"decision_id": q["decision_id"],
                                              "selected_option_id": selected["option_id"]}]})
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        self.assertEqual(session.env.cart, {})
        preserved = next(a for a in draft["recommendation"]["assignments"] if a["requirement_id"] == "r1")
        self.assertIn("recalculated", preserved["reason"])
        with self.assertRaises(ValueError):
            session.answer_recommendation({"recommendation_id": result["recommendation"]["recommendation_id"], "action": "accept"})
        self.assertEqual(self.accept(session, draft)["cart"], {"carrots_value_1lb": 1, "yogurt_fresh_greek": 1})

    def test_unknown_quantity_is_asked_before_proposal_and_bound_to_package(self):
        session = self.session(unknown=True)
        result = session.advance()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(session.env.cart, {})
        q = result["questions"][0]
        session.answer_clarifications({"answers": [{"question_id": q["question_id"], "amount": 2}]})
        draft = session.advance()
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        session.answer_recommendation({"recommendation_id": draft["recommendation"]["recommendation_id"],
                                       "action": "replace", "requirement_ids": ["r2"]})
        choice = session.advance()["questions"][0]
        option = next(p for p in choice["options"] if p["product_id"] == "yogurt_fresh_greek")
        again = session.advance({"answers": [{"decision_id": choice["decision_id"],
                                              "selected_option_id": option["option_id"]}]})
        self.assertEqual(again["status"], "needs_clarification")
        self.assertNotEqual(again["questions"][0]["product_id"], q["product_id"])
        self.assertNotEqual(again["questions"][0]["question_id"], q["question_id"])
        with self.assertRaises(ValueError):
            session.answer_clarifications({"answers": [{"question_id": q["question_id"], "amount": 2}]})

    def test_unknown_upc_cannot_partially_apply_a_model_batch(self):
        session = self.session(picks={"r1": "carrots_value_1lb", "r2": "invented"})
        result = session.advance()
        self.assertEqual(result["status"], "recommendation_error")
        self.assertTrue(all(r.selected_product_id is None for r in session.choices.requirements.values()))
        self.assertEqual(session.env.cart, {})

    def test_model_provider_failure_is_not_wrapped_as_invalid_recommendation(self):
        class ProviderQuotaError(Exception):
            __module__ = "openai"
        def respond(*args):
            raise ProviderQuotaError("Insufficient Balance")
        session = self.session()
        session.recommender = ModelBasketRecommender(ScriptedLLM(respond))
        with self.assertRaises(ProviderQuotaError):
            session.advance()
        self.assertEqual(session.env.cart, {})

    def test_model_can_defer_ambiguous_product_to_shopper(self):
        session = self.session(picks={"r1": "carrots_value_1lb", "r2": None})
        result = session.advance()
        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in result["questions"]], ["r2"])

    def test_price_change_after_acceptance_produces_new_proposal(self):
        session = self.session()
        draft = session.advance()
        session.env.catalog["yogurt_value_cup"] = replace(session.env.catalog["yogurt_value_cup"], price_cents=170)
        again = self.accept(session, draft)
        self.assertEqual(again["status"], "awaiting_basket_confirmation")
        self.assertNotEqual(again["recommendation"]["recommendation_id"], draft["recommendation"]["recommendation_id"])
        self.assertEqual(session.env.cart, {})

    def test_partial_stock_failure_keeps_added_item_and_requests_new_acceptance(self):
        session = self.session(self.env(events=[{"product_id": "yogurt_fresh_greek", "trigger": "first_attempt"}]),
                               picks={"r1": "carrots_value_1lb", "r2": "yogurt_fresh_greek"})
        first = session.advance()
        options = self.accept(session, first)
        self.assertEqual(options["status"], "waiting_for_user")
        self.assertEqual(session.env.cart, {"carrots_value_1lb": 1})
        q = options["questions"][0]
        choice = next(p for p in q["options"] if p["product_id"] == "yogurt_value_cup")
        draft = session.advance({"answers": [{"decision_id": q["decision_id"], "selected_option_id": choice["option_id"]}]})
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        self.assertEqual(self.accept(session, draft)["cart"], {"carrots_value_1lb": 1, "yogurt_value_cup": 1})

    def test_existing_cart_uses_target_diff_without_double_charging_or_duplicating(self):
        session = self.session(self.env(initial={"carrots_value_1lb": 1}))
        session.intent["budget_cents"] = 300
        draft = session.advance()
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        self.assertEqual(draft["recommendation"]["total_cents"], 278)
        self.assertEqual([op["product_id"] for op in draft["recommendation"]["operations"]], ["yogurt_value_cup"])
        self.assertEqual(self.accept(session, draft)["cart"]["carrots_value_1lb"], 1)

    def test_excess_existing_quantity_and_unlisted_items_are_reduced_after_acceptance(self):
        session = self.session(self.env(initial={"carrots_value_1lb": 3, "milk_value_whole_1l": 1}))
        draft = session.advance()
        self.assertEqual(session.env.cart["carrots_value_1lb"], 3)
        complete = self.accept(session, draft)
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(complete["cart"], {"carrots_value_1lb": 1, "yogurt_value_cup": 1})

    def test_restore_does_not_duplicate_initial_cart_and_preserves_draft(self):
        session = self.session(self.env(initial={"carrots_value_1lb": 1}))
        draft = session.advance()
        saved = json.loads(json.dumps(session.checkpoint()))
        restored = InteractiveShoppingSession.from_checkpoint(self.env(initial={"carrots_value_1lb": 1}), saved,
                    recommender=ModelBasketRecommender(basket_llm()))
        self.assertEqual(restored.env.cart, {"carrots_value_1lb": 1})
        self.assertEqual(restored.advance()["recommendation"], draft["recommendation"])
        self.assertEqual(self.accept(restored, draft)["status"], "complete")

    def test_combined_budget_failure_never_produces_executable_proposal(self):
        session = self.session(picks={"r1": "carrots_value_1lb", "r2": "yogurt_fresh_greek"})
        session.intent["budget_cents"] = 300
        self.assertEqual(session.advance()["status"], "budget_conflict")
        self.assertIsNone(session.pending_recommendation)
        self.assertEqual(session.env.cart, {})

    def test_change_detected_in_final_refresh_requires_new_acceptance(self):
        session = self.session()
        draft = session.advance()
        original = session.env.get_product
        reads = 0
        def get_product(pid):
            nonlocal reads
            if pid == "yogurt_value_cup":
                reads += 1
                if reads == 2:
                    session.env.catalog[pid] = replace(session.env.catalog[pid], price_cents=170)
            return original(pid)
        session.env.get_product = get_product
        result = self.accept(session, draft)
        self.assertEqual(result["status"], "awaiting_basket_confirmation")
        self.assertEqual(result["recommendation"]["total_cents"], 349)
        self.assertFalse(session.env.done)

    def test_recommendation_model_cannot_select_products_blocked_by_hard_dietary_constraints(self):
        session = self.session(picks={"r1": "carrots_value_1lb", "r2": "yogurt_fresh_greek"})
        session.choices.requirements["r2"].required_tags = ["vegan"]
        result = session.advance()
        self.assertEqual(result["status"], "no_candidates")
        self.assertNotIn("yogurt_fresh_greek", [p["id"] for p in session.choices.requirements["r2"].candidates])
        self.assertEqual(session.env.cart, {})

    def test_preserved_unlisted_item_is_included_in_budget_once(self):
        session = self.session(self.env(initial={"milk_value_whole_1l": 1}))
        session.intent["keep_existing_items"] = True
        result = session.advance()
        self.assertEqual(result["status"], "awaiting_basket_confirmation")
        self.assertEqual(result["recommendation"]["total_cents"], 567)
        final = self.accept(session, result)
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["cart"]["milk_value_whole_1l"], 1)

    def test_development_reference_carts_are_feasible_on_frozen_kroger_catalog(self):
        from pathlib import Path
        from grocery_bench import load_scenarios
        from grocery_bench.data import KROGER_CATALOG_PATH
        from grocery_bench.evaluator import evaluate
        path = Path(__file__).resolve().parents[1] / "benchmark/recommendation_dialogue_kroger_development.json"
        catalog = load_catalog(KROGER_CATALOG_PATH)
        for scenario in load_scenarios(path):
            for cart in scenario.reference_carts:
                self.assertEqual(evaluate(scenario, "high", cart, catalog).success, 1, scenario.id)

    def test_http_default_recommends_and_accept_resume_does_not_need_old_in_memory_session(self):
        secret = "recommendation-test-signing-key-32-chars"
        llm = basket_llm(intent=self.intent())
        first = interactive_service.start("Buy one carrots and one yogurt", source="snapshot", llm=llm, signing_secret=secret)
        self.assertEqual(first["status"], "awaiting_basket_confirmation")
        self.assertEqual(first["cart"]["items"], [])
        with self.assertRaises(interactive_service.service.ServiceError):
            interactive_service.resume(first["session_token"], answers={"answers": []}, llm=llm, signing_secret=secret)
        final = interactive_service.resume(first["session_token"], recommendation_answer={
            "recommendation_id": first["recommendation"]["recommendation_id"], "action": "accept"}, llm=llm, signing_secret=secret)
        self.assertEqual(final["status"], "complete")
        self.assertNotIn("session_token", final)


if __name__ == "__main__":
    unittest.main()
