import unittest

from grocery_agent.agents import DirectFunctionAgent, IntentGroundedAgent
from grocery_agent.catalog import load_catalog, load_tasks
from grocery_agent.environment import GroceryEnvironment
from grocery_agent.evaluator import evaluate_run
from grocery_agent.intent import IntentParser


class GroceryAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.tasks = load_tasks()

    def test_benchmark_has_twenty_unique_tasks(self):
        self.assertEqual(len(self.tasks), 20)
        self.assertEqual(len({task.id for task in self.tasks}), 20)

    def test_parser_extracts_bundle_and_constraints(self):
        intent = IntentParser().parse("Plan a vegan lunch under $15 with no nuts.")
        self.assertEqual({item.category for item in intent.requirements}, {"hummus", "pita", "carrots"})
        self.assertIn("vegan", intent.required_tags)
        self.assertIn("contains_nuts", intent.forbidden_tags)
        self.assertEqual(intent.budget, 15.0)

    def test_environment_fires_inventory_event(self):
        env = GroceryEnvironment(
            self.catalog,
            [
                {
                    "trigger_after_adds": 1,
                    "product_id": "bar_value_peanut",
                    "trigger_on_attempt": True,
                }
            ],
        )
        self.assertTrue(env.add_to_cart("water_value_6pk").ok)
        self.assertFalse(env.add_to_cart("bar_value_peanut").ok)

    def test_every_task_is_feasible_for_intent_agent(self):
        agent = IntentGroundedAgent()
        failures = []
        for task in self.tasks:
            env = GroceryEnvironment(self.catalog, task.events)
            run = agent.run(task.id, task.instruction, env)
            result = evaluate_run(run, task, self.catalog)
            if not result.success:
                failures.append((task.id, result, run.parsed_intent, run.trace))
        self.assertFalse(failures, failures)

    def test_dynamic_tasks_require_recovery(self):
        agent = IntentGroundedAgent()
        replans = 0
        for task in self.tasks:
            if task.task_type != "dynamic":
                continue
            env = GroceryEnvironment(self.catalog, task.events)
            run = agent.run(task.id, task.instruction, env)
            replans += run.replans
        self.assertGreater(replans, 0)

    def test_baseline_and_proposed_run_same_interface(self):
        task = self.tasks[0]
        for agent in (DirectFunctionAgent(), IntentGroundedAgent()):
            env = GroceryEnvironment(self.catalog, task.events)
            run = agent.run(task.id, task.instruction, env)
            self.assertEqual(run.task_id, task.id)
            self.assertGreater(run.tool_calls, 0)


if __name__ == "__main__":
    unittest.main()
