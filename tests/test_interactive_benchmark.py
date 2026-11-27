import json
import unittest

from grocery_agent.interactive_benchmark import InteractiveBenchmarkAgent, RecommendedBenchmarkAgent
from grocery_agent.simulated_user import ScriptedBasketUser
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario
from tests.test_interactive_service import ScriptedLLM
from tests.test_recommendation import basket_llm


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
        self.assertEqual(agent.notes["stop_reason"], "quantity_answer_unavailable")

    def test_recommended_agent_uses_model_choice_instead_of_cheapest_simulated_choice(self):
        scenario = Scenario(id="model-choice", category="development", difficulty="M", title="Model choice",
            variants={v: "Buy one yogurt" for v in ("high", "medium", "low")}, context={}, needs=[])
        env = GroceryEnv(load_catalog(), scenario, "high")
        llm = basket_llm({"r1": "yogurt_fresh_greek"}, {"requirements": [
            {"id": "r1", "description": "yogurt", "min": 1, "max": 1}]})
        agent = RecommendedBenchmarkAgent(llm)
        agent.run(env)
        self.assertEqual(agent.notes["stop_reason"], "complete")
        self.assertEqual(env.cart, {"yogurt_fresh_greek": 1})
        self.assertEqual(agent.notes["first_recommendation"]["cart"], env.cart)
        self.assertEqual(agent.notes["dialogue_metrics"]["prompt_batches"], 1)

    def test_private_shopper_feedback_replaces_only_one_product_without_leaking_profile_to_model(self):
        scenario = Scenario(id="feedback", category="development", difficulty="M", title="Feedback",
            variants={v: "Buy one yogurt and one carrots" for v in ("high", "medium", "low")}, context={}, needs=[])
        env = GroceryEnv(load_catalog(), scenario, "high")
        llm = basket_llm(intent={"requirements": [
            {"id": "r1", "description": "carrots", "min": 1, "max": 1},
            {"id": "r2", "description": "yogurt", "min": 1, "max": 1}]})
        user = ScriptedBasketUser({"feedback": [{"need_words": ["yogurt"], "prefer_words": ["greek"]}]})
        agent = RecommendedBenchmarkAgent(llm, basket_user=user)
        agent.run(env)
        self.assertEqual(agent.notes["stop_reason"], "complete")
        self.assertEqual(env.cart, {"carrots_value_1lb": 1, "yogurt_fresh_greek": 1})
        self.assertEqual(agent.notes["dialogue_metrics"]["replacement_requests"], 1)
        self.assertEqual([e["status"] for e in agent.notes["interaction_events"]],
                         ["awaiting_basket_confirmation", "waiting_for_user", "awaiting_basket_confirmation", "complete"])
        self.assertEqual([q["requirement_id"] for e in agent.notes["interaction_events"]
                          if e["status"] == "waiting_for_user" for q in e["questions"]], ["r2"])


if __name__ == "__main__":
    unittest.main()
