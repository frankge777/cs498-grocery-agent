import unittest

from grocery_agent.agents import IntentGroundedAgent
from grocery_agent.catalog import load_catalog, load_tasks
from grocery_agent.environment import GroceryEnvironment

try:
    from grocery_agent.graph_agent import LangGraphIntentAgent
except ImportError:  # langgraph not installed
    LangGraphIntentAgent = None


@unittest.skipIf(LangGraphIntentAgent is None, "langgraph not installed")
class LangGraphEquivalenceTests(unittest.TestCase):
    """The LangGraph port must behave exactly like the hand-written loop."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.tasks = load_tasks()

    def _run(self, agent, task):
        env = GroceryEnvironment(self.catalog, task.events)
        return agent.run(task.id, task.instruction, env), env

    def test_matches_hand_written_agent_on_every_task(self):
        reference, graph = IntentGroundedAgent(), LangGraphIntentAgent()
        for task in self.tasks:
            with self.subTest(task=task.id):
                ref_run, ref_env = self._run(reference, task)
                graph_run, graph_env = self._run(graph, task)
                self.assertEqual(graph_run.cart, ref_run.cart)
                self.assertEqual(graph_run.total_cost, ref_run.total_cost)
                self.assertEqual(graph_run.tool_calls, ref_run.tool_calls)
                self.assertEqual(graph_run.replans, ref_run.replans)
                self.assertEqual(graph_env.log, ref_env.log)
                self.assertEqual(graph_run.trace, ref_run.trace)

    def test_step_limit_stops_graph(self):
        task = next(t for t in self.tasks if t.task_type == "underspecified")
        run, _ = self._run(LangGraphIntentAgent(max_steps=1), task)
        self.assertEqual(sum(1 for t in run.trace if t.get("phase") == "execute"), 1)


if __name__ == "__main__":
    unittest.main()
