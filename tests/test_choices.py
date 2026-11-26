"""Product-choice protocol tests; no frontend, model, or network required."""

import json
import unittest

from grocery_bench import GroceryEnv, load_catalog, load_scenarios
from grocery_bench.data import KROGER_CATALOG_PATH, Scenario
from grocery_agent.choices import ChoiceCoordinator, RequirementChoice, SimulatedChoiceProvider, coordinator_from_intent
from grocery_agent.llm_agents import normalize_intent


def product(product_id, name, price):
    return {"id": product_id, "name": name, "brand": "Kroger", "raw_size": "1 each",
            "price_cents": price, "in_stock": True}


class ChoiceTests(unittest.TestCase):
    def test_single_vegetable_search_excludes_obvious_mixed_vegetables(self):
        scenario = Scenario(
            id="relevance", category="choice", difficulty="M", title="Carrots",
            variants={v: "Buy carrots" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
        )
        env = GroceryEnv(load_catalog(KROGER_CATALOG_PATH), scenario, "high")
        coordinator = coordinator_from_intent(normalize_intent({"requirements": [
            {"id": "r1", "description": "bag of carrots", "search_query": "carrots bag", "min": 1, "max": 1},
        ]}, strict_upc=True))
        coordinator.search_unresolved(env)
        offered = {p["id"] for p in coordinator.requirements["r1"].candidates}
        self.assertIn("0001111091620", offered)
        self.assertNotIn("0001111089741", offered)
        self.assertFalse(any("Spinach" in p["name"] or "Apples" in p["name"]
                             for p in coordinator.requirements["r1"].candidates))

    def test_intent_creates_independent_requirements_and_rejects_names_as_upcs(self):
        intent = normalize_intent({"requirements": [
            {"id": "r1", "description": "carrots", "search_query": "carrots", "min": 1, "max": 1,
             "product_ids": ["Baby Carrots", "0001111091620"]},
            {"id": "r2", "description": "yogurt", "search_query": "yogurt", "min": 1, "max": 1},
        ]}, strict_upc=True)
        self.assertEqual(intent["requirements"][0]["product_ids"], ["0001111091620"])
        coordinator = coordinator_from_intent(intent)
        self.assertEqual(coordinator.requirements["r1"].search_query, "carrots")
        self.assertEqual(coordinator.requirements["r2"].search_query, "yogurt")
        self.assertEqual(coordinator.requirements["r1"].quantity, 1)

    def coordinator(self):
        coordinator = ChoiceCoordinator([
            RequirementChoice("r1", "Which carrot?"),
            RequirementChoice("r2", "Which yogurt?"),
        ])
        coordinator.set_candidates("r1", [product("C1", "Baby Carrots", 139),
                                          product("C2", "Daikon", 179)])
        coordinator.set_candidates("r2", [product("Y1", "Plain Yogurt", 349),
                                          product("Y2", "Greek Yogurt", 399)])
        return coordinator

    def test_batch_answers_bind_to_independent_requirements_and_retry_only_failed_one(self):
        coordinator = self.coordinator()
        simulated_user = SimulatedChoiceProvider({"r1": ["C1"], "r2": ["Y2", "Y1"]})
        request = coordinator.ask_pending(simulated_user)
        self.assertEqual([q["requirement_id"] for q in request["questions"]], ["r1", "r2"])
        self.assertEqual(coordinator.requirements["r1"].selected_product_id, "C1")
        self.assertEqual(coordinator.requirements["r2"].selected_product_id, "Y2")
        self.assertEqual(coordinator.selected_total_cents({"r1": 1, "r2": 1}), 538)

        coordinator.mark_added("r1")
        coordinator.mark_unavailable("r2", "Y2")
        retry = coordinator.ask_pending(simulated_user)
        self.assertEqual([q["requirement_id"] for q in retry["questions"]], ["r2"])
        self.assertEqual([o["product_id"] for o in retry["questions"][0]["options"]], ["Y1"])
        self.assertEqual(coordinator.requirements["r1"].status, "added")
        self.assertEqual(coordinator.requirements["r2"].selected_product_id, "Y1")
        self.assertEqual(coordinator.selected_total_cents({"r1": 1, "r2": 1}), 488)

    def test_invalid_choice_does_not_partially_apply(self):
        coordinator = self.coordinator()
        request = coordinator.prepare_batch()
        first, second = request["questions"]
        with self.assertRaises(ValueError):
            coordinator.apply_answers({"answers": [
                {"decision_id": first["decision_id"], "selected_option_id": first["options"][0]["option_id"]},
                {"decision_id": second["decision_id"], "selected_option_id": "not-offered"},
            ]})
        self.assertIsNone(coordinator.requirements["r1"].selected_product_id)
        self.assertIsNone(coordinator.requirements["r2"].selected_product_id)

    def test_frontend_can_resume_from_json_checkpoint(self):
        coordinator = self.coordinator()
        request = coordinator.prepare_batch()
        snapshot = json.loads(json.dumps(coordinator.checkpoint()))
        resumed = ChoiceCoordinator.from_checkpoint(snapshot)
        response = SimulatedChoiceProvider({"r1": "C1", "r2": "Y2"})(request)
        resumed.apply_answers(response)
        self.assertEqual(resumed.requirements["r1"].selected_product_id, "C1")
        self.assertEqual(resumed.requirements["r2"].selected_product_id, "Y2")

    def test_filters_unavailable_and_invalid_prices(self):
        coordinator = self.coordinator()
        unavailable = product("C3", "No stock", 100)
        unavailable["in_stock"] = False
        coordinator.set_candidates("r1", [unavailable, product("C1", "Baby Carrots", 139),
                                          product("C1", "Baby Carrots", 139)])
        self.assertEqual([o["product_id"] for o in coordinator.prepare_batch()["questions"][0]["options"]], ["C1"])

    def test_searches_both_needs_with_public_tools_and_dietary_filter(self):
        catalog = load_catalog()
        scenario = load_scenarios()[0]
        env = GroceryEnv(catalog, scenario, "high")
        coordinator = ChoiceCoordinator([
            RequirementChoice("r1", "Which carrots?", search_query="carrots"),
            RequirementChoice("r2", "Which yogurt?", search_query="yogurt", required_tags=["nut_free"]),
        ])
        counts = coordinator.search_unresolved(env, budget_cents=300)
        self.assertGreaterEqual(counts["r1"], 1)
        self.assertGreaterEqual(counts["r2"], 1)
        self.assertTrue(all(p["price_cents"] <= 300 for r in coordinator.requirements.values()
                            for p in r.candidates))
        self.assertEqual(sum(row["tool"] == "search_products" for row in env.trajectory), 2)
        self.assertTrue(all("nut_free" in catalog[p["id"]].tags
                            for p in coordinator.requirements["r2"].candidates))

    def test_choice_policy_asks_for_multiple_and_auto_selects_only_with_authorization(self):
        coordinator = self.coordinator()
        decision = coordinator.decide()
        self.assertEqual([q["requirement_id"] for q in decision["questions"]], ["r1", "r2"])
        coordinator = self.coordinator()
        decision = coordinator.decide(auto_allowed=["r1"])
        self.assertEqual(decision["auto_selected"], {"r1": "C1"})
        self.assertEqual([q["requirement_id"] for q in decision["questions"]], ["r2"])


if __name__ == "__main__":
    unittest.main()
