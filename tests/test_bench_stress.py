"""Validation of the stress split (benchmark/scenarios_stress.json), same checks as the main release."""

import unittest

from grocery_bench import VARIANTS, GroceryEnv, OracleAgent, evaluate, evaluate_env, load_catalog, load_scenarios
from grocery_bench.data import BENCHMARK_DIR
from grocery_bench.evaluator import cart_total, need_matches, unit_amount


class StressSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.scenarios = load_scenarios(BENCHMARK_DIR / "scenarios_stress.json")

    def test_shape(self):
        self.assertEqual([s.id for s in self.scenarios], ["S1", "S2", "S3", "S4", "S5"])
        for s in self.scenarios:
            self.assertEqual(set(s.variants), set(VARIANTS))
            self.assertTrue(all(n.get("max") is not None for n in s.needs))

    def test_reference_carts_feasible_through_tools(self):
        for s in self.scenarios:
            for i in range(len(s.reference_carts)):
                for v in VARIANTS:
                    with self.subTest(s=s.id, ref=i, v=v):
                        env = GroceryEnv(self.catalog, s, v)
                        OracleAgent(i).run(env)
                        r = evaluate_env(env)
                        self.assertEqual(r.success, 1, [p for p in r.predicates if not p.passed])

    def test_mutations_fail(self):
        for s in self.scenarios:
            ref = s.reference_carts[0]
            self.assertEqual(evaluate(s, "high", {}, self.catalog).success, 0)
            self.assertEqual(evaluate(s, "high", dict(s.initial_cart), self.catalog).success, 0)
            for need in s.needs:
                cart = {p: q for p, q in ref.items() if not need_matches(self.catalog[p], need)}
                self.assertEqual(evaluate(s, "high", cart, self.catalog).success, 0, (s.id, need["id"]))
                pid = next(p for p in ref if need_matches(self.catalog[p], need))
                cart = dict(ref)
                cart[pid] += need["max"] // unit_amount(self.catalog[pid], need["measure"]) + 1
                self.assertEqual(evaluate(s, "high", cart, self.catalog).success, 0, (s.id, need["id"], "over"))
            total = cart_total(ref, self.catalog)
            self.assertLessEqual(total, s.budget_cents)
            for event in s.events:
                cart = dict(ref)
                cart[event["product_id"]] = 1
                self.assertEqual(evaluate(s, "high", cart, self.catalog).success, 0, (s.id, event))

    def test_budgets_are_tight(self):
        """Slack between the cheapest reference cart and the cap stays under 10%."""
        for s in self.scenarios:
            cheapest = min(cart_total(c, self.catalog) for c in s.reference_carts)
            self.assertLess((s.budget_cents - cheapest) / s.budget_cents, 0.10, s.id)


if __name__ == "__main__":
    unittest.main()
