"""Validation for the fixed, real-Kroger snapshot benchmark."""

import json
import re
import unittest
from collections import Counter

from grocery_bench import VARIANTS, GroceryEnv, OracleAgent, evaluate_env, load_catalog, load_scenarios, run_trials
from grocery_bench.data import KROGER_CATALOG_PATH, KROGER_SCENARIOS_PATH
from grocery_bench.evaluator import need_matches


class KrogerBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_catalog = json.loads(KROGER_CATALOG_PATH.read_text(encoding="utf-8"))
        cls.catalog = load_catalog(KROGER_CATALOG_PATH)
        cls.scenarios = load_scenarios(KROGER_SCENARIOS_PATH)

    def test_snapshot_has_real_provenance_and_no_query_failures(self):
        source = self.raw_catalog["source"]
        self.assertEqual(source["provider"], "Kroger Public API")
        self.assertEqual(source["location"]["locationId"], "02100946")
        self.assertEqual(source["zip_code"], "61820")
        self.assertGreaterEqual(len(self.catalog), 700)
        self.assertEqual(self.raw_catalog["failures"], [])
        self.assertTrue(all(product.source == "kroger_live" for product in self.catalog.values()))

    def test_roster_shape(self):
        self.assertEqual([scenario.id for scenario in self.scenarios], [f"K{i:02d}" for i in range(1, 21)])
        self.assertEqual(Counter(s.category for s in self.scenarios),
                         {"explicit": 5, "constrained": 5, "goal": 5, "recovery": 5})
        self.assertEqual(Counter(s.difficulty for s in self.scenarios), {"E": 4, "M": 8, "H": 8})
        for scenario in self.scenarios:
            self.assertEqual(set(scenario.variants), set(VARIANTS), scenario.id)
            self.assertEqual(len(set(scenario.variants.values())), 3, scenario.id)

    def test_every_referenced_product_is_a_real_in_stock_upc(self):
        for scenario in self.scenarios:
            referenced = set(scenario.initial_cart) | set(scenario.stock_overrides)
            referenced |= {event["product_id"] for event in scenario.events}
            for need in scenario.needs:
                referenced |= set(need["select"].get("product_ids", []))
            for cart in scenario.reference_carts:
                referenced |= set(cart)
            for product_id in referenced:
                with self.subTest(scenario=scenario.id, product_id=product_id):
                    self.assertRegex(product_id, re.compile(r"^\d{13}$"))
                    self.assertIn(product_id, self.catalog)
                    self.assertGreater(self.catalog[product_id].stock, 0)

    def test_needs_are_bounded_and_do_not_invent_portions(self):
        for scenario in self.scenarios:
            for need in scenario.needs:
                self.assertIsNotNone(need.get("max"), f"{scenario.id}:{need['id']}")
                self.assertFalse(need["measure"].startswith("portions:"), f"{scenario.id}:{need['id']}")
                self.assertTrue(any(need_matches(product, need) for product in self.catalog.values()),
                                f"{scenario.id}:{need['id']}")

    def test_dietary_and_protein_constraints_have_explicit_metadata(self):
        for scenario in self.scenarios:
            for need in scenario.needs:
                select = need["select"]
                for product_id in select.get("product_ids", []):
                    product = self.catalog[product_id]
                    self.assertTrue(set(select.get("tags_all", [])).issubset(product.tags),
                                    f"{scenario.id}:{need['id']}:{product_id}")
                    if "min_protein_g" in select:
                        self.assertIsNotNone(product.protein_g, f"{scenario.id}:{need['id']}:{product_id}")
                        self.assertGreaterEqual(product.protein_g, select["min_protein_g"])

    def test_recovery_references_avoid_failed_products(self):
        for scenario in self.scenarios:
            if scenario.category != "recovery":
                continue
            failed = {event["product_id"] for event in scenario.events}
            self.assertTrue(failed, scenario.id)
            for cart in scenario.reference_carts:
                self.assertTrue(failed.isdisjoint(cart), scenario.id)

    def test_every_reference_cart_passes_through_real_tools(self):
        for scenario in self.scenarios:
            self.assertTrue(scenario.reference_carts, scenario.id)
            for reference_index in range(len(scenario.reference_carts)):
                for variant in VARIANTS:
                    with self.subTest(scenario=scenario.id, reference=reference_index, variant=variant):
                        env = GroceryEnv(self.catalog, scenario, variant)
                        OracleAgent(reference_index).run(env)
                        result = evaluate_env(env)
                        self.assertEqual(result.success, 1, [(p.id, p.detail) for p in result.predicates if not p.passed])

    def test_runner_uses_injected_real_catalog(self):
        trials = run_trials(
            OracleAgent,
            scenarios=self.scenarios[:1],
            variants=["high"],
            runs=1,
            catalog=self.catalog,
        )
        self.assertEqual(trials[0]["scenario_id"], "K01")
        self.assertEqual(trials[0]["success"], 1)
        self.assertEqual(trials[0]["final_cart"], {"0001111040601": 2})

    def test_k10_accepts_equivalent_real_kroger_salsa_and_cheese(self):
        scenario = next(value for value in self.scenarios if value.id == "K10")
        cart = {
            "0001111005265": 1,
            "0001111072567": 2,
            "0001111066759": 1,
            "0001111050204": 1,
        }
        env = GroceryEnv(self.catalog, scenario, "high")
        for product_id, quantity in cart.items():
            self.assertTrue(env.add_to_cart(product_id, quantity).ok)
        env.finish("equivalent Kroger products")
        self.assertEqual(evaluate_env(env).success, 1)

    def test_k16_accepts_any_curated_explicit_dairy_and_nut_free_milk(self):
        scenario = next(value for value in self.scenarios if value.id == "K16")
        env = GroceryEnv(self.catalog, scenario, "high")
        self.assertFalse(env.add_to_cart("0004410015618", 1).ok)
        self.assertTrue(env.add_to_cart("0004410019080", 1).ok)
        env.finish("equivalent labeled oat milk")
        self.assertEqual(evaluate_env(env).success, 1)


if __name__ == "__main__":
    unittest.main()
