"""The HTTP service can pause and resume without keeping Python objects alive."""

import json
import unittest

from grocery_agent.llm import ScriptedLLM
from grocery_web import interactive_service, service


class InteractiveServiceTests(unittest.TestCase):
    SECRET = "test-only-secret-must-have-32-chars"

    def test_snapshot_start_and_resume_with_two_product_answers(self):
        intent = {"budget_cents": 800, "requirements": [
            {"id": "r1", "description": "carrots", "search_query": "carrots", "min": 1, "max": 1},
            {"id": "r2", "description": "yogurt", "search_query": "yogurt", "min": 1, "max": 1},
        ]}
        llm = ScriptedLLM(lambda messages, tools, json_mode: {"content": json.dumps(intent)})
        started = interactive_service.start("Buy carrots and yogurt under $8", source="snapshot",
                                            llm=llm, signing_secret=self.SECRET)
        self.assertEqual(started["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in started["questions"]], ["r1", "r2"])
        carrots, yogurt = started["questions"]
        carrot = min(carrots["options"], key=lambda option: option["price_cents"])
        chosen = next(option for option in yogurt["options"] if "Greek" in option["name"])
        finished = interactive_service.resume(started["session_token"],
            {"answers": [
                {"decision_id": carrots["decision_id"], "selected_option_id": carrot["option_id"]},
                {"decision_id": yogurt["decision_id"], "selected_option_id": chosen["option_id"]},
            ]},
            signing_secret=self.SECRET)
        self.assertEqual(finished["status"], "complete")
        self.assertEqual(len(finished["cart"]["items"]), 2)
        self.assertLessEqual(finished["cart"]["total_cents"], 800)

    def test_tampered_token_is_rejected(self):
        with self.assertRaises(service.ServiceError):
            interactive_service.resume("tampered.token", signing_secret=self.SECRET)


if __name__ == "__main__":
    unittest.main()
