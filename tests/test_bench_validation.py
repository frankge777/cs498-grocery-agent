"""Benchmark validation checks from Section 5 of the draft paper.

* structure of the release (20 scenarios, 5 per category, 4/8/8 difficulty,
  3 variants each, bounded needs);
* every reference cart is feasible through the real tool interface;
* evaluator mutations: missing need, wrong quantity, invalid substitute,
  unknown dietary tag, one-cent budget overflow, extra product, missed
  required clarification;
* stock failures never mutate the cart; replay is deterministic; caps work.
"""

import unittest
from collections import Counter
from dataclasses import replace

from grocery_bench import (
    VARIANTS,
    EpisodeTerminated,
    GroceryEnv,
    KeywordBaseline,
    OracleAgent,
    evaluate,
    evaluate_env,
    load_catalog,
    load_scenarios,
    run_trials,
    summarize,
)
from grocery_bench.evaluator import cart_total, matches, need_matches, unit_amount


class BenchTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.scenarios = load_scenarios()
        cls.by_id = {s.id: s for s in cls.scenarios}

    def eval_cart(self, scenario, cart, trajectory=()):
        return evaluate(scenario, "high", cart, self.catalog, trajectory)

    def failed(self, result):
        return {p.id for p in result.predicates if not p.passed}


class ReleaseStructureTests(BenchTestCase):
    def test_roster_shape(self):
        self.assertEqual([s.id for s in self.scenarios], [f"{i:02d}" for i in range(1, 21)])
        self.assertEqual(Counter(s.category for s in self.scenarios),
                         {"explicit": 5, "constrained": 5, "goal": 5, "recovery": 5})
        self.assertEqual(Counter(s.difficulty for s in self.scenarios), {"E": 4, "M": 8, "H": 8})

    def test_every_scenario_has_three_distinct_variants(self):
        for s in self.scenarios:
            self.assertEqual(set(s.variants), set(VARIANTS), s.id)
            self.assertEqual(len(set(s.variants.values())), 3, s.id)

    def test_needs_have_upper_bounds_and_known_products(self):
        for s in self.scenarios:
            for need in s.needs:
                self.assertIsNotNone(need.get("max"), f"{s.id}:{need['id']} needs an upper bound")
                self.assertTrue(any(need_matches(p, need) for p in self.catalog.values()), f"{s.id}:{need['id']}")
            referenced = set(s.initial_cart) | set(s.stock_overrides) | {e["product_id"] for e in s.events}
            for cart in s.reference_carts:
                referenced |= set(cart)
            self.assertFalse(referenced - set(self.catalog), s.id)

    def test_recovery_scenarios_have_events_and_alternatives(self):
        for s in self.scenarios:
            if s.category != "recovery":
                continue
            self.assertTrue(s.events, s.id)
            evented = {e["product_id"] for e in s.events}
            for cart in s.reference_carts:
                self.assertFalse(evented & set(cart), f"{s.id}: reference cart uses an event SKU")


class FeasibilityTests(BenchTestCase):
    def test_every_reference_cart_succeeds_through_tools_in_every_variant(self):
        for s in self.scenarios:
            self.assertTrue(s.reference_carts, s.id)
            for index in range(len(s.reference_carts)):
                for variant in VARIANTS:
                    with self.subTest(scenario=s.id, ref=index, variant=variant):
                        env = GroceryEnv(self.catalog, s, variant)
                        OracleAgent(index).run(env)
                        result = evaluate_env(env)
                        self.assertEqual(result.success, 1, self.failed(result))

    def test_empty_or_untouched_cart_never_succeeds(self):
        for s in self.scenarios:
            self.assertEqual(self.eval_cart(s, {}).success, 0, s.id)
            self.assertEqual(self.eval_cart(s, dict(s.initial_cart)).success, 0, s.id)

    def test_alternative_valid_carts_exist(self):
        multi = [s.id for s in self.scenarios if len(s.reference_carts) >= 2]
        self.assertGreaterEqual(len(multi), 12)


class EvaluatorMutationTests(BenchTestCase):
    def test_missing_need(self):
        for s in self.scenarios:
            ref = s.reference_carts[0]
            for need in s.needs:
                cart = {pid: q for pid, q in ref.items() if not need_matches(self.catalog[pid], need)}
                result = self.eval_cart(s, cart)
                self.assertEqual(result.success, 0, f"{s.id}:{need['id']}")
                self.assertIn(f"need:{need['id']}", self.failed(result))

    def test_wrong_quantity_over_upper_bound(self):
        for s in self.scenarios:
            ref = s.reference_carts[0]
            for need in s.needs:
                pid = next(p for p in ref if need_matches(self.catalog[p], need))
                per_unit = unit_amount(self.catalog[pid], need["measure"])
                cart = dict(ref)
                cart[pid] += need["max"] // per_unit + 1
                result = self.eval_cart(s, cart)
                self.assertIn(f"need:{need['id']}", self.failed(result), f"{s.id}:{need['id']}")

    def test_extra_product_rejected(self):
        for s in self.scenarios:
            cart = dict(s.reference_carts[0])
            cart["chips_value_potato"] = 1
            result = self.eval_cart(s, cart)
            self.assertIn("only_allowed_products", self.failed(result), s.id)

    def test_one_cent_budget_overflow(self):
        checked = 0
        for s in self.scenarios:
            if s.budget_cents is None:
                continue
            ref = s.reference_carts[0]
            total = cart_total(ref, self.catalog)
            self.assertEqual(self.eval_cart(replace(s, budget_cents=total), ref).success, 1, s.id)
            result = self.eval_cart(replace(s, budget_cents=total - 1), ref)
            self.assertIn("budget", self.failed(result), s.id)
            checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_unknown_dietary_tag_does_not_satisfy_requirement(self):
        """Swap a product for a same-category, same-size one that lacks the required tag."""
        checked = set()
        for s in self.scenarios:
            for need in s.needs:
                if "tags_all" not in need["select"]:
                    continue
                ref = s.reference_carts[0]
                pid = next(p for p in ref if need_matches(self.catalog[p], need))
                original = self.catalog[pid]
                swap = next(
                    (
                        p for p in self.catalog.values()
                        if p.category == original.category
                        and unit_amount(p, need["measure"]) == unit_amount(original, need["measure"])
                        and not matches(p, need["select"])
                        and not set(need["select"]["tags_all"]).issubset(p.tags)
                    ),
                    None,
                )
                if swap is None:
                    continue
                cart = dict(ref)
                cart[swap.id] = cart.pop(pid)
                self.assertEqual(self.eval_cart(s, cart).success, 0, f"{s.id}: {pid}->{swap.id}")
                checked.add(s.id)
        self.assertTrue({"07", "09", "15", "16"} <= checked, checked)

    def test_invalid_substitute_unavailable_sku(self):
        for s in self.scenarios:
            for event in s.events:
                cart = dict(s.reference_carts[0])
                cart[event["product_id"]] = 1
                result = self.eval_cart(s, cart)
                self.assertIn("no_unavailable_sku", self.failed(result), s.id)

    def test_missed_required_clarification(self):
        s = self.by_id["15"]
        # Correct cart, no question asked.
        env = GroceryEnv(self.catalog, s, "low")
        env.add_to_cart("milk_pure_soy_1l", 1)
        result = evaluate_env(env)
        self.assertEqual(result.success, 0)
        self.assertTrue(result.required_clarification_missed)
        # Question asked only after choosing the milk.
        env = GroceryEnv(self.catalog, s, "low")
        env.add_to_cart("milk_pure_soy_1l", 1)
        env.ask_user("Any milk restrictions?")
        self.assertEqual(evaluate_env(env).success, 0)
        # Asked first, then chose.
        env = GroceryEnv(self.catalog, s, "low")
        self.assertEqual(env.ask_user("Does anyone have a dairy allergy?").data["topic"], "milk_restriction")
        env.add_to_cart("milk_green_oat_1l", 1)
        result = evaluate_env(env)
        self.assertEqual(result.success, 1)
        self.assertFalse(result.required_clarification_missed)

    def test_preference_is_soft_and_conditional_on_hard_constraints(self):
        s = self.by_id["08"]
        preferred, other = s.reference_carts
        self.assertEqual(self.eval_cart(s, preferred).preference_score, 1.0)
        result = self.eval_cart(s, other)
        self.assertEqual(result.success, 1)
        self.assertEqual(result.preference_score, 0.0)
        over_budget = self.eval_cart(replace(s, budget_cents=100), preferred)
        self.assertIsNone(over_budget.preference_score)


class EnvironmentTests(BenchTestCase):
    def test_stock_failure_does_not_mutate_cart_and_persists(self):
        for s in self.scenarios:
            for event in s.events:
                env = GroceryEnv(self.catalog, s, "high")
                before = dict(env.cart)
                first = env.add_to_cart(event["product_id"], 1)
                self.assertFalse(first.ok, s.id)
                self.assertEqual(env.cart, before)
                self.assertFalse(env.update_quantity(event["product_id"], 2).ok)
                self.assertEqual(env.cart, before)
                self.assertFalse(env.get_product(event["product_id"]).data["in_stock"])

    def test_stock_override_visible_in_search(self):
        env = GroceryEnv(self.catalog, self.by_id["03"], "high")
        results = {p["id"]: p for p in env.search_products("Value whole milk").data["products"]}
        self.assertFalse(results["milk_value_whole_1l"]["in_stock"])
        self.assertTrue(results["milk_value_whole_500"]["in_stock"])

    def test_search_finds_category_and_tag_queries(self):
        env = GroceryEnv(self.catalog, self.by_id["07"], "high")
        top = env.search_products("dairy-free milk", max_results=3).data["products"]
        self.assertTrue(all(p["category"] == "milk" for p in top))
        names = [p["id"] for p in env.search_products("eggs").data["products"]]
        self.assertIn("eggs_value_12", names)

    def test_unsupported_question_gets_rephrase_and_counts_unnecessary(self):
        env = GroceryEnv(self.catalog, self.by_id["01"], "high")
        obs = env.ask_user("What is your favorite color?")
        self.assertIsNone(obs.data["topic"])
        env.add_to_cart("milk_green_whole_1l", 2)
        result = evaluate_env(env)
        self.assertEqual(result.success, 1)
        self.assertEqual(result.unnecessary_clarifications, 1)

    def test_replay_is_deterministic(self):
        for s in self.scenarios:
            logs = []
            for _ in range(2):
                env = GroceryEnv(self.catalog, s, "medium")
                OracleAgent().run(env)
                logs.append(env.trajectory)
            self.assertEqual(logs[0], logs[1], s.id)

    def test_tool_call_cap_terminates_and_scores_current_cart(self):
        s = self.by_id["01"]
        env = GroceryEnv(self.catalog, s, "high", limits={"max_tool_calls": 2})
        env.add_to_cart("milk_green_whole_1l", 1)
        env.add_to_cart("milk_green_whole_1l", 1)
        with self.assertRaises(EpisodeTerminated):
            env.view_cart()
        self.assertEqual(env.termination_reason, "tool_call_cap")
        self.assertEqual(evaluate_env(env).success, 1)
        with self.assertRaises(EpisodeTerminated):
            env.add_to_cart("milk_green_whole_1l", 1)

    def test_model_call_cap(self):
        env = GroceryEnv(self.catalog, self.by_id["01"], "high", limits={"max_model_calls": 1})
        env.record_model_call(10, 5)
        with self.assertRaises(EpisodeTerminated):
            env.record_model_call(10, 5)
        self.assertEqual(env.termination_reason, "model_call_cap")

    def test_invalid_arguments_fail_without_mutation(self):
        env = GroceryEnv(self.catalog, self.by_id["05"], "high")
        before = dict(env.cart)
        self.assertFalse(env.call("add_to_cart", {"product_id": "nope", "quantity": 1})["ok"])
        self.assertFalse(env.call("add_to_cart", {"product_id": "banana_value", "quantity": 0})["ok"])
        self.assertFalse(env.call("add_to_cart", {"product_id": "banana_value", "quantity": "2"})["ok"])
        self.assertFalse(env.call("teleport", {})["ok"])
        self.assertFalse(env.call("add_to_cart", {"sku": "banana_value"})["ok"])
        self.assertEqual(env.cart, before)


class RunnerTests(BenchTestCase):
    def test_oracle_scores_perfect_and_baseline_does_not(self):
        oracle = summarize(run_trials(OracleAgent, runs=1))
        self.assertEqual(oracle["macro_success"], 1.0)
        self.assertEqual(oracle["n_trials"], 60)
        baseline = summarize(run_trials(KeywordBaseline, runs=1))
        self.assertLess(baseline["macro_success"], 0.5)
        self.assertEqual(set(baseline["success_by_variant"]), set(VARIANTS))


if __name__ == "__main__":
    unittest.main()
