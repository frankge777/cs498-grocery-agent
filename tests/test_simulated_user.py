import json
import unittest
from pathlib import Path

from grocery_agent.interactive_benchmark import InteractiveBenchmarkAgent
from grocery_agent.simulated_user import QuantityAnswerUnavailable, ScriptedQuantityUser
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario
from tests.test_interactive_service import ScriptedLLM


class SimulatedUserTests(unittest.TestCase):
    def env(self):
        scenario = Scenario(id="user-test", category="development", difficulty="M", title="Quantity reply",
            variants={v: "Buy yogurt" for v in ("high", "medium", "low")}, context={}, needs=[],
            reference_carts=[{"yogurt_value_cup": 1}], extras_allowed=True)
        return GroceryEnv(load_catalog(), scenario, "high")

    def question(self, product_id, product_name):
        return {"question_id": "q_r1_quantity", "requirement_id": "r1", "kind": "quantity",
                "product_id": product_id, "product_name": product_name}

    def test_waiting_for_quantity_gets_reply_and_completes_without_defaulting_or_using_reference(self):
        user = ScriptedQuantityUser({"user-test": [{"words": ["yogurt"], "measure": "units", "min": 2, "max": 2}]})
        llm = ScriptedLLM(lambda *args: {"content": json.dumps({"requirements": [
            {"id": "r1", "description": "yogurt", "search_query": "yogurt", "quantity_explicit": False}]})})
        env = self.env()
        agent = InteractiveBenchmarkAgent(llm, quantity_user=user)
        agent.run(env)
        self.assertEqual(agent.notes["stop_reason"], "complete")
        self.assertEqual(env.cart, {"yogurt_value_cup": 2})
        self.assertIn("needs_clarification", [e["status"] for e in agent.notes["interaction_events"]])
        self.assertEqual(agent.notes["quantity_dialogue"][0]["answer"]["amount"], 2)

    def test_same_total_gets_different_answers_for_different_packages(self):
        env = self.env()
        user = ScriptedQuantityUser({"user-test": [{"words": ["eggs"], "measure": "count", "min": 12, "max": 12}]})
        for pid, packages in [("eggs_value_6", 2), ("eggs_value_12", 1)]:
            answer, _ = user.answer("user-test", self.question(pid, env.catalog[pid].name), env)
            self.assertEqual(answer["amount"], packages)

    def test_missing_and_ambiguous_intentions_are_not_guessed(self):
        env = self.env()
        q = self.question("yogurt_value_cup", "Yogurt Cup")
        for profiles in [{}, {"user-test": [
            {"words": ["yogurt"], "measure": "units", "min": 1, "max": 1},
            {"words": ["yogurt"], "measure": "units", "min": 2, "max": 2}]}]:
            with self.assertRaises(QuantityAnswerUnavailable):
                ScriptedQuantityUser(profiles).answer("user-test", q, env)

    def test_incompatible_package_does_not_get_a_quantity_that_breaks_target(self):
        user = ScriptedQuantityUser({"user-test": [{"words": ["eggs"], "measure": "count", "min": 10, "max": 10}]})
        with self.assertRaises(QuantityAnswerUnavailable):
            user.answer("user-test", self.question("eggs_value_6", "Eggs 6 ct"), self.env())

    def test_profiles_answer_all_ten_previously_blocked_batches(self):
        root = Path(__file__).resolve().parents[1]
        user = ScriptedQuantityUser.load(root / "benchmark/interactive_user_profiles_kroger.json")
        file = root / "results/interactive_kroger_20261127/deepseek-flash/kroger/interactive/trajectories.jsonl"
        batches = 0
        for line in file.read_text().splitlines():
            record = json.loads(line)
            notes = record["agent_notes"]
            if notes.get("stop_reason") != "quantity_not_specified":
                continue
            batches += 1
            for q in notes["session"]["pending_clarifications"]:
                answer, audit = user.answer(record["scenario_id"], q, self.env())
                self.assertGreater(answer["amount"], 0)
                self.assertEqual(audit["product_id"], q["product_id"])
        self.assertEqual(batches, 10)


if __name__ == "__main__":
    unittest.main()
