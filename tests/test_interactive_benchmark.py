import json
import unittest

from grocery_agent.interactive_benchmark import InteractiveBenchmarkAgent
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario
from tests.test_interactive_service import ScriptedLLM


class InteractiveBenchmarkTests(unittest.TestCase):
    def run_agent(self, known_quantity):
        scenario = Scenario(id="public-policy", category="development", difficulty="M", title="Public policy",
            variants={v: "Buy yogurt" for v in ("high", "medium", "low")}, context={}, needs=[],
            reference_carts=[{"yogurt_fresh_greek": 1}], extras_allowed=True)
        env = GroceryEnv(load_catalog(), scenario, "high")
        item = {"id": "r1", "description": "yogurt", "search_query": "yogurt"}
        if known_quantity:
            item.update(min=1, max=1)
        else:
            item["quantity_explicit"] = False
        llm = ScriptedLLM(lambda *args: {"content": json.dumps({"requirements": [item]})})
        agent = InteractiveBenchmarkAgent(llm)
        agent.run(env)
        return env, agent

    def test_selects_cheapest_public_option_instead_of_hidden_reference_cart(self):
        env, agent = self.run_agent(True)
        self.assertEqual(env.cart, {"yogurt_value_cup": 1})
        self.assertEqual(agent.notes["stop_reason"], "complete")

    def test_does_not_use_hidden_cart_to_guess_missing_quantity(self):
        env, agent = self.run_agent(False)
        self.assertEqual(env.cart, {})
        self.assertEqual(agent.notes["stop_reason"], "quantity_not_specified")


if __name__ == "__main__":
    unittest.main()
