"""End-to-end offline tests for the opt-in multi-product choice loop."""

import json
import unittest
from dataclasses import replace

from grocery_agent.choices import SimulatedChoiceProvider
from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.llm_agents import normalize_intent
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import KROGER_CATALOG_PATH, Scenario


class InteractiveTests(unittest.TestCase):
    def env(self):
        scenario = Scenario(
            id="choice-demo", category="live", difficulty="M", title="Two products",
            variants={v: "Buy carrots and yogurt under $5" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
            events=[{"product_id": "yogurt_fresh_greek", "trigger": "first_attempt"}],
        )
        return GroceryEnv(load_catalog(), scenario, "high")

    def intent(self):
        return normalize_intent({"budget_cents": 500, "requirements": [
            {"id": "r1", "description": "carrots", "search_query": "carrots", "min": 1, "max": 1},
            {"id": "r2", "description": "yogurt", "search_query": "yogurt", "min": 1, "max": 1},
        ]})

    def test_batch_choice_pause_resume_and_only_failed_yogurt_reasked(self):
        env = self.env()
        session = InteractiveShoppingSession(env, self.intent())
        first = session.advance()
        self.assertEqual(first["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in first["questions"]], ["r2"])
        self.assertEqual(session.choices.requirements["r1"].selected_product_id, "carrots_value_1lb")
        # Simulate a later HTTP request by serializing and restoring state.
        checkpoint = json.loads(json.dumps(session.checkpoint()))
        session = InteractiveShoppingSession.from_checkpoint(self.env(), checkpoint)
        user = SimulatedChoiceProvider({"r2": ["yogurt_fresh_greek", "yogurt_value_cup"]})
        first_answer = user({"questions": first["questions"]})
        second = session.advance(first_answer)
        self.assertEqual(second["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in second["questions"]], ["r2"])
        self.assertEqual(session.env.cart, {"carrots_value_1lb": 1})
        third = session.advance(user({"questions": second["questions"]}))
        self.assertEqual(third["status"], "complete")
        self.assertEqual(third["cart"], {"carrots_value_1lb": 1, "yogurt_value_cup": 1})
        self.assertEqual(third["total_cents"], 278)

    def test_combined_budget_conflict_does_not_modify_cart(self):
        session = InteractiveShoppingSession(self.env(), self.intent())
        first = session.advance()
        user = SimulatedChoiceProvider({"r2": "yogurt_fresh_greek"})
        # The selected pair costs $3.28; a $3 cap forces a joint decision.
        session.intent["budget_cents"] = 300
        conflict = session.advance(user({"questions": first["questions"]}))
        self.assertEqual(conflict["status"], "budget_conflict")
        self.assertEqual(session.env.cart, {})
        new_choice = session.reconsider(["r2"])
        self.assertEqual(new_choice["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in new_choice["questions"]], ["r2"])
        cheaper = SimulatedChoiceProvider({"r2": "yogurt_value_cup"})
        finished = session.advance(cheaper({"questions": new_choice["questions"]}))
        self.assertEqual(finished["status"], "complete")
        self.assertEqual(finished["total_cents"], 278)

    def test_restore_reopens_only_an_added_product_that_became_unavailable(self):
        scenario = Scenario(
            id="restore-live", category="live", difficulty="M", title="Restore stock",
            variants={v: "Buy carrots and yogurt" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
        )
        catalog = load_catalog(KROGER_CATALOG_PATH)
        session = InteractiveShoppingSession(GroceryEnv(catalog, scenario, "high"), self.intent())
        first = session.advance()
        provider = SimulatedChoiceProvider({"r1": "0001111091620", "r2": "0003663200834"})
        complete = session.advance(provider({"questions": first["questions"]}))
        self.assertEqual(complete["status"], "complete")

        restarted_env = GroceryEnv(catalog, scenario, "high")
        restarted_env.stock["0001111091620"] = 0
        restored = InteractiveShoppingSession.from_checkpoint(
            restarted_env, json.loads(json.dumps(session.checkpoint())))
        again = restored.advance()
        self.assertEqual(again["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in again["questions"]], ["r1"])
        self.assertEqual(restarted_env.cart, {"0003663200834": 1})

    def test_count_and_volume_use_package_sizes_before_asking_for_choices(self):
        scenario = Scenario(
            id="package-math", category="choice", difficulty="M", title="Eggs and milk",
            variants={v: "Buy 12 eggs and 1 L milk" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
        )
        env = GroceryEnv(load_catalog(), scenario, "high")
        intent = normalize_intent({"budget_cents": 900, "requirements": [
            {"id": "r1", "description": "12 eggs", "search_query": "eggs",
             "measure": "count", "min": 12, "max": 12},
            {"id": "r2", "description": "1 L milk", "search_query": "milk",
             "measure": "volume_ml", "min": 1000, "max": 1000},
        ]})
        session = InteractiveShoppingSession(env, intent)
        first = session.advance()
        self.assertEqual(first["status"], "waiting_for_user")
        eggs, milk = first["questions"]
        six_eggs = next(option for option in eggs["options"]
                        if option["product_id"] == "eggs_value_6")
        half_liter = next(option for option in milk["options"]
                          if option["product_id"] == "milk_value_whole_500")
        self.assertEqual(six_eggs["quantity"], 2)
        self.assertEqual(half_liter["quantity"], 2)
        self.assertFalse(any(option["product_id"] == "milk_value_whole_2l"
                             for option in milk["options"]))
        complete = session.advance({"answers": [
            {"decision_id": eggs["decision_id"], "selected_option_id": six_eggs["option_id"]},
            {"decision_id": milk["decision_id"], "selected_option_id": half_liter["option_id"]},
        ]})
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(complete["cart"], {"eggs_value_6": 2, "milk_value_whole_500": 2})
        self.assertEqual(complete["total_cents"], 836)

    def test_price_change_after_user_choice_blocks_over_budget_cart(self):
        env = self.env()
        session = InteractiveShoppingSession(env, self.intent())
        session.intent["budget_cents"] = 300
        first = session.advance()
        env.catalog["yogurt_value_cup"] = replace(env.catalog["yogurt_value_cup"], price_cents=300)
        choice = SimulatedChoiceProvider({"r2": "yogurt_value_cup"})({"questions": first["questions"]})
        conflict = session.advance(choice)
        self.assertEqual(conflict["status"], "budget_conflict")
        self.assertEqual(env.cart, {})
        self.assertGreater(conflict["total_cents"], 300)

    def test_two_requirements_can_share_one_upc_and_final_verifier_checks_total(self):
        scenario = Scenario(
            id="shared-upc", category="choice", difficulty="M", title="Two carrot needs",
            variants={v: "Buy two carrots" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
        )
        env = GroceryEnv(load_catalog(), scenario, "high")
        intent = normalize_intent({"requirements": [
            {"id": "r1", "description": "carrots for lunch", "search_query": "carrots", "min": 1, "max": 1},
            {"id": "r2", "description": "carrots for dinner", "search_query": "carrots", "min": 1, "max": 1},
        ]})
        session = InteractiveShoppingSession(env, intent)
        complete = session.advance()
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(complete["cart"], {"carrots_value_1lb": 2})
        self.assertTrue(complete["verification"]["ok"])

    def test_global_dietary_requirement_filters_every_product(self):
        intent = normalize_intent({"all_items_required_tags": ["vegan"], "requirements": [
            {"id": "r1", "description": "yogurt", "search_query": "yogurt", "min": 1, "max": 1},
        ]})
        session = InteractiveShoppingSession(self.env(), intent)
        result = session.advance()
        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(session.env.cart, {})


if __name__ == "__main__":
    unittest.main()
