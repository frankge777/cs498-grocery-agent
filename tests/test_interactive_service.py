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

    def test_choose_both_packages_before_batched_quantity_questions(self):
        intent = {"requirements": [
            {"id": "r1", "description": "carrots", "search_query": "carrots",
             "quantity_explicit": False, "min": None, "max": None},
            {"id": "r2", "description": "yogurt", "search_query": "yogurt",
             "quantity_explicit": False, "min": None, "max": None},
        ]}
        llm = ScriptedLLM(lambda messages, tools, json_mode: {"content": json.dumps(intent)})
        started = interactive_service.start("Buy carrots and yogurt", source="snapshot",
                                            llm=llm, signing_secret=self.SECRET)
        self.assertEqual(started["status"], "waiting_for_user")
        self.assertEqual([q["requirement_id"] for q in started["questions"]], ["r1", "r2"])
        self.assertEqual(started["cart"]["items"], [])
        answer = {"answers": []}
        chosen_products = []
        for question in started["questions"]:
            chosen = min(question["options"], key=lambda item: item["price_cents"])
            self.assertIsNone(chosen["quantity"])
            self.assertIsNone(chosen["line_total_cents"])
            chosen_products.append(chosen["product_id"])
            answer["answers"].append({"decision_id": question["decision_id"],
                                      "selected_option_id": chosen["option_id"]})
        resumed = interactive_service.resume(started["session_token"], answers=answer,
                                             signing_secret=self.SECRET)
        self.assertEqual(resumed["status"], "needs_clarification")
        self.assertEqual([r["status"] for r in resumed["requirement_states"]],
                         ["needs_quantity", "needs_quantity"])
        self.assertEqual([q["product_id"] for q in resumed["questions"]], chosen_products)
        self.assertTrue(all(q["package_size"] for q in resumed["questions"]))
        self.assertEqual(resumed["cart"]["items"], [])
        complete = interactive_service.resume(resumed["session_token"], clarification_answers={"answers": [
            {"question_id": "q_r1_quantity", "amount": 1, "measure": "units"},
            {"question_id": "q_r2_quantity", "amount": 2, "measure": "units"},
        ]}, signing_secret=self.SECRET)
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(sorted(item["quantity"] for item in complete["cart"]["items"]), [1, 2])

    def test_known_content_count_selects_pack_without_quantity_question(self):
        # These are actual pack sizes in the frozen Kroger snapshot.
        for product_id, packages in (("0001111060906", 2), ("0001111060903", 1)):
            with self.subTest(product_id=product_id):
                intent = {"requirements": [{"id": "r1", "description": "12 eggs",
                           "search_query": "eggs", "measure": "count", "min": 12, "max": 12}]}
                llm = ScriptedLLM(lambda messages, tools, json_mode: {"content": json.dumps(intent)})
                started = interactive_service.start("Buy exactly 12 eggs", source="snapshot",
                                                    llm=llm, signing_secret=self.SECRET)
                question = started["questions"][0]
                option = next(p for p in question["options"] if p["product_id"] == product_id)
                self.assertEqual(option["quantity"], packages)
                completed = interactive_service.resume(started["session_token"], answers={"answers": [
                    {"decision_id": question["decision_id"], "selected_option_id": option["option_id"]},
                ]}, signing_secret=self.SECRET)
                self.assertEqual(completed["status"], "complete")
                self.assertEqual(completed["cart"]["items"][0]["quantity"], packages)
                self.assertTrue(completed["verification"]["ok"])

    def test_invalid_clarification_does_not_advance(self):
        intent = {"requirements": [{"id": "r1", "description": "yogurt",
                                    "search_query": "yogurt", "quantity_explicit": False}]}
        llm = ScriptedLLM(lambda messages, tools, json_mode: {"content": json.dumps(intent)})
        started = interactive_service.start("Buy yogurt", source="snapshot",
                                            llm=llm, signing_secret=self.SECRET)
        question = started["questions"][0]
        started = interactive_service.resume(started["session_token"], answers={"answers": [
            {"decision_id": question["decision_id"],
             "selected_option_id": question["options"][0]["option_id"]},
        ]}, signing_secret=self.SECRET)
        with self.assertRaises(service.ServiceError):
            interactive_service.resume(started["session_token"], clarification_answers={"answers": [
                {"question_id": "q_r1_quantity", "amount": 0, "measure": "units"},
            ]}, signing_secret=self.SECRET)

    def test_free_text_clarification_is_reextracted_after_user_answer(self):
        def response(messages, tools, json_mode):
            answered = "Answers from the shopper" in messages[-1]["content"]
            return {"content": json.dumps({
                "requirements": [{"id": "r1", "description": "one yogurt",
                                  "search_query": "yogurt", "min": 1, "max": 1,
                                  "required_tags": ["vegan"] if answered else []}],
                "open_questions": [] if answered else [
                    {"question": "Which dietary restriction must this satisfy?"}],
            })}
        llm = ScriptedLLM(response)
        started = interactive_service.start("Buy one yogurt for my dietary restriction",
                                            source="snapshot", llm=llm,
                                            signing_secret=self.SECRET)
        self.assertEqual(started["status"], "needs_clarification")
        resumed = interactive_service.resume(started["session_token"], clarification_answers={"answers": [
            {"question_id": "q_open_1", "text": "vegan"},
        ]}, llm=llm, signing_secret=self.SECRET)
        self.assertIn(resumed["status"], {"waiting_for_user", "no_candidates", "complete"})
        self.assertNotEqual(resumed["status"], "needs_clarification")

    def test_missing_product_name_asks_before_search(self):
        def response(messages, tools, json_mode):
            answered = "Answers from the shopper" in messages[-1]["content"]
            requirements = ([{"id": "r1", "description": "one yogurt", "search_query": "yogurt",
                              "min": 1, "max": 1}] if answered else [])
            return {"content": json.dumps({"requirements": requirements})}
        llm = ScriptedLLM(response)
        started = interactive_service.start("Buy something", source="snapshot",
                                            llm=llm, signing_secret=self.SECRET)
        self.assertEqual(started["status"], "needs_clarification")
        self.assertEqual(started["questions"][0]["question_id"], "q_product")
        resumed = interactive_service.resume(started["session_token"], clarification_answers={"answers": [
            {"question_id": "q_product", "text": "One yogurt"},
        ]}, llm=llm, signing_secret=self.SECRET)
        self.assertEqual(resumed["status"], "waiting_for_user")

    def test_mandatory_restriction_is_asked_before_selecting_unknown_quantity(self):
        def response(messages, tools, json_mode):
            answered = "Answers from the shopper" in messages[-1]["content"]
            return {"content": json.dumps({"requirements": [
                {"id": "r1", "description": "yogurt", "quantity_explicit": False,
                 "required_tags": ["nut_free"] if answered else []}],
                "open_questions": [] if answered else [
                    {"question": "What restriction must the yogurt satisfy?"}],
            })}
        llm = ScriptedLLM(response)
        started = interactive_service.start("Buy yogurt for my dietary restriction", source="snapshot",
                                            llm=llm, signing_secret=self.SECRET)
        self.assertEqual(started["status"], "needs_clarification")
        self.assertEqual([q["kind"] for q in started["questions"]], ["free_text"])
        state = interactive_service._decode(started["session_token"], self.SECRET.encode())["session"]
        self.assertIsNone(state["choices"])
        resumed = interactive_service.resume(started["session_token"], clarification_answers={"answers": [
            {"question_id": "q_open_1", "text": "Must be nut-free"},
        ]}, llm=llm, signing_secret=self.SECRET)
        # If Kroger supplies no adequate tag evidence, it must not offer unsafe choices.
        self.assertIn(resumed["status"], {"no_candidates", "waiting_for_user", "needs_clarification"})
        if resumed["status"] == "needs_clarification":
            self.assertTrue(all(q["kind"] == "quantity" and q.get("product_id")
                                for q in resumed["questions"]))


if __name__ == "__main__":
    unittest.main()
