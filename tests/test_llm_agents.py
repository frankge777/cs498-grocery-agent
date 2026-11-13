"""Offline tests for the LLM agents using a scripted LLM (no API key needed)."""

import json
import unittest

from grocery_bench import EpisodeTerminated, GroceryEnv, evaluate_env, load_catalog, load_scenarios

try:
    from grocery_agent.llm import ScriptedLLM
    from grocery_agent.llm_agents import (
        DirectFunctionCallingAgent,
        IntentGroundedLLMAgent,
        ReActAgent,
        check_cart,
        normalize_intent,
    )
except ImportError:  # langgraph not installed
    IntentGroundedLLMAgent = None


def sequence(replies):
    """Scripted LLM that returns replies in order; json-mode replies are dicts serialised to content."""
    queue = list(replies)

    def responder(messages, tools, json_mode):
        reply = queue.pop(0)
        if json_mode:
            return {"content": json.dumps(reply)}
        return reply

    return responder


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


MILK_INTENT = {
    "requirements": [{"id": "r1", "description": "Greenfarm whole milk 1 L", "search_query": "Greenfarm whole milk",
                      "measure": "units", "min": 2, "max": 2, "brand": "Greenfarm"}],
    "budget_cents": None,
}


@unittest.skipIf(IntentGroundedLLMAgent is None, "langgraph not installed")
class LLMAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.by_id = {s.id: s for s in load_scenarios()}

    def env(self, sid, variant="high", **limits):
        return GroceryEnv(self.catalog, self.by_id[sid], variant, limits=limits or None)

    def test_ours_happy_path(self):
        llm = ScriptedLLM(sequence([
            MILK_INTENT,
            {"tool_calls": [call("search_products", query="Greenfarm whole milk")]},
            {"tool_calls": [call("add_to_cart", product_id="milk_green_whole_1l", quantity=2)]},
            {"tool_calls": [call("submit_cart", assignments=[{"product_id": "milk_green_whole_1l", "requirement_id": "r1"}])]},
        ]))
        env = self.env("01")
        agent = IntentGroundedLLMAgent(llm)
        agent.run(env)
        self.assertEqual(env.termination_reason, "finished")
        self.assertEqual(evaluate_env(env).success, 1)
        self.assertEqual(agent.notes["verify_reports"][-1]["violations"], [])
        self.assertEqual(env.model_calls, 4)

    def test_ours_verifier_triggers_repair(self):
        llm = ScriptedLLM(sequence([
            MILK_INTENT,
            {"tool_calls": [call("add_to_cart", product_id="milk_green_whole_1l", quantity=1)]},
            {"tool_calls": [call("submit_cart", assignments=[{"product_id": "milk_green_whole_1l", "requirement_id": "r1"}])]},
            {"tool_calls": [call("update_quantity", product_id="milk_green_whole_1l", quantity=2)]},
            {"tool_calls": [call("submit_cart", assignments=[{"product_id": "milk_green_whole_1l", "requirement_id": "r1"}])]},
        ]))
        env = self.env("01")
        agent = IntentGroundedLLMAgent(llm)
        agent.run(env)
        reports = agent.notes["verify_reports"]
        self.assertEqual(len(reports), 2)
        self.assertTrue(any("units = 1" in v for v in reports[0]["violations"]))
        self.assertEqual(evaluate_env(env).success, 1)

    def test_ours_without_verifier_stops_after_first_submit(self):
        llm = ScriptedLLM(sequence([
            MILK_INTENT,
            {"tool_calls": [call("add_to_cart", product_id="milk_green_whole_1l", quantity=1)]},
            {"tool_calls": [call("submit_cart", assignments=[])]},
        ]))
        env = self.env("01")
        agent = IntentGroundedLLMAgent(llm, use_verifier=False)
        agent.run(env)
        self.assertEqual(agent.name, "ours_noverify")
        self.assertEqual(evaluate_env(env).success, 0)

    def test_ours_clarifies_then_reextracts(self):
        intent_q = {"requirements": [{"id": "r1", "description": "milk", "measure": "volume_ml", "min": 1000, "max": 1000}],
                    "open_questions": [{"question": "What is the milk-related dietary restriction?"}]}
        intent_a = {"requirements": [{"id": "r1", "description": "milk", "measure": "volume_ml", "min": 1000, "max": 1000,
                                      "required_tags": ["dairy_free", "nut_free"]}]}
        llm = ScriptedLLM(sequence([
            intent_q, intent_a,
            {"tool_calls": [call("add_to_cart", product_id="milk_pure_soy_1l", quantity=1)]},
            {"tool_calls": [call("submit_cart", assignments=[{"product_id": "milk_pure_soy_1l", "requirement_id": "r1"}])]},
        ]))
        env = self.env("15", "low")
        agent = IntentGroundedLLMAgent(llm)
        agent.run(env)
        result = evaluate_env(env)
        self.assertEqual(result.success, 1)
        self.assertFalse(result.required_clarification_missed)
        self.assertEqual(agent.notes["intent"]["requirements"][0]["required_tags"], ["dairy_free", "nut_free"])

    def test_model_call_cap_propagates_as_termination(self):
        llm = ScriptedLLM(lambda m, t, j: {"content": json.dumps(MILK_INTENT)} if j
                          else {"tool_calls": [call("view_cart")]})
        env = self.env("01", max_model_calls=5)
        with self.assertRaises(EpisodeTerminated):
            IntentGroundedLLMAgent(llm).run(env)
        self.assertEqual(env.termination_reason, "model_call_cap")

    def test_react_and_direct(self):
        react = ScriptedLLM(sequence([
            {"content": "Thought: add milk", "tool_calls": [call("add_to_cart", product_id="milk_green_whole_1l", quantity=2)]},
            {"content": "Thought: done", "tool_calls": [call("finish")]},
        ]))
        env = self.env("01")
        ReActAgent(react).run(env)
        self.assertEqual(evaluate_env(env).success, 1)

        direct = ScriptedLLM(sequence([
            {"tool_calls": [call("search_products", query="milk")]},
            {"tool_calls": [call("add_to_cart", product_id="milk_green_whole_1l", quantity=2)]},
        ]))
        env = self.env("01")
        DirectFunctionCallingAgent(direct).run(env)
        self.assertEqual(evaluate_env(env).success, 1)
        self.assertEqual(env.model_calls, 2)

    def test_check_cart_detects_unknown_tag_and_budget(self):
        intent = normalize_intent({"requirements": [{"id": "r1", "measure": "units", "min": 1, "max": 1,
                                                     "required_tags": ["dairy_free"]}], "budget_cents": 300})
        details = {"milk_fresh_lactosefree_1l": self.catalog["milk_fresh_lactosefree_1l"].public_details(True)}
        report = check_cart(intent, {"milk_fresh_lactosefree_1l": 1}, details,
                            [{"product_id": "milk_fresh_lactosefree_1l", "requirement_id": "r1"}], {}, 399)
        text = " ".join(report["violations"])
        self.assertIn("dairy_free", text)
        self.assertIn("exceeds budget", text)


if __name__ == "__main__":
    unittest.main()
