"""Product-bound quantities survive pauses without becoming guessed targets."""

import json
import unittest

from grocery_agent.choices import SimulatedChoiceProvider
from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.interactive_intent import normalize_interactive_intent
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario


class PackageQuantityTests(unittest.TestCase):
    def env(self, stock_event=False):
        scenario = Scenario(
            id="package-first", category="choice", difficulty="development", title="Package first",
            variants={v: "Buy yogurt and eggs" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True,
            events=[{"product_id": "yogurt_fresh_greek", "trigger": "first_attempt"}]
            if stock_event else [],
        )
        return GroceryEnv(load_catalog(), scenario, "high")

    def session(self, requirements, stock_event=False, **other):
        return InteractiveShoppingSession(self.env(stock_event), normalize_interactive_intent(
            {"requirements": requirements, **other}))

    def answer_quantity(self, session, question, amount):
        session.answer_clarifications({"answers": [{"question_id": question["question_id"],
                                                    "amount": amount, "measure": "units"}]})

    def test_only_unknown_need_gets_package_question_and_known_target_is_preserved(self):
        session = self.session([
            {"id": "r1", "description": "yogurt", "quantity_explicit": False},
            {"id": "r2", "description": "12 eggs", "search_query": "eggs",
             "measure": "count", "min": 12, "max": 12},
        ])
        products = session.advance()
        self.assertEqual(products["status"], "waiting_for_user")
        quantities = session.advance(SimulatedChoiceProvider(
            {"r1": "yogurt_value_cup", "r2": "eggs_value_6"})(products))
        self.assertEqual([q["requirement_id"] for q in quantities["questions"]], ["r1"])
        self.assertEqual(session.choices.requirements["r2"].quantity, 2)
        self.assertEqual(session.env.cart, {})
        session = InteractiveShoppingSession.from_checkpoint(
            self.env(), json.loads(json.dumps(session.checkpoint())))
        self.answer_quantity(session, quantities["questions"][0], 3)
        completed = session.advance()
        self.assertEqual(completed["status"], "complete")
        self.assertEqual(completed["cart"], {"yogurt_value_cup": 3, "eggs_value_6": 2})

    def test_unique_product_still_requires_a_quantity(self):
        session = self.session([{"id": "r1", "description": "carrots", "quantity_explicit": False}])
        result = session.advance()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["questions"][0]["product_id"], "carrots_value_1lb")
        self.assertIsNone(session.choices.requirements["r1"].quantity)
        self.assertEqual(session.env.cart, {})

    def test_stock_substitution_reasks_only_the_quantity_bound_to_failed_upc(self):
        session = self.session([
            {"id": "r1", "description": "yogurt", "quantity_explicit": False},
            {"id": "r2", "description": "carrots", "min": 1, "max": 1},
        ], stock_event=True)
        first = session.advance()
        quantities = session.advance(SimulatedChoiceProvider({"r1": "yogurt_fresh_greek"})(first))
        self.answer_quantity(session, quantities["questions"][0], 2)
        replacement = session.advance()
        self.assertEqual(replacement["status"], "waiting_for_user")
        self.assertEqual(session.env.cart, {"carrots_value_1lb": 1})
        self.assertIsNone(session.intent["requirements"][0]["min"])
        again = session.advance(SimulatedChoiceProvider({"r1": "yogurt_value_cup"})(replacement))
        self.assertEqual(again["status"], "needs_clarification")
        self.assertEqual(again["questions"][0]["product_id"], "yogurt_value_cup")
        self.answer_quantity(session, again["questions"][0], 1)
        completed = session.advance()
        self.assertEqual(completed["status"], "complete")
        self.assertEqual(completed["cart"], {"carrots_value_1lb": 1, "yogurt_value_cup": 1})

    def test_after_quantity_budget_conflict_reselect_does_not_transfer_old_package_count(self):
        session = self.session([{"id": "r1", "description": "yogurt", "quantity_explicit": False}],
                               budget_cents=300)
        first = session.advance()
        quantities = session.advance(SimulatedChoiceProvider({"r1": "yogurt_value_cup"})(first))
        self.answer_quantity(session, quantities["questions"][0], 4)
        self.assertEqual(session.advance()["status"], "budget_conflict")
        self.assertEqual(session.env.cart, {})
        replacement = session.reconsider(["r1"])
        self.assertTrue(all(p["quantity"] is None for p in replacement["questions"][0]["options"]))
        quantities = session.advance(SimulatedChoiceProvider({"r1": "yogurt_fresh_greek"})(replacement))
        self.assertEqual(quantities["status"], "needs_clarification")
        self.answer_quantity(session, quantities["questions"][0], 1)
        self.assertEqual(session.advance()["status"], "complete")

    def test_invalid_batch_does_not_confirm_any_quantity(self):
        session = self.session([
            {"id": "r1", "description": "yogurt", "quantity_explicit": False},
            {"id": "r2", "description": "carrots", "quantity_explicit": False},
        ])
        first = session.advance()
        session.advance(SimulatedChoiceProvider({"r1": "yogurt_value_cup"})(first))
        before = json.dumps(session.checkpoint(), sort_keys=True)
        with self.assertRaises(ValueError):
            session.answer_clarifications({"answers": [
                {"question_id": "q_r1_quantity", "amount": 2, "measure": "units"},
                {"question_id": "q_r2_quantity", "amount": 0, "measure": "units"},
            ]})
        self.assertEqual(json.dumps(session.checkpoint(), sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
