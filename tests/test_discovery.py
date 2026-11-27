"""Control-flow and evidence-boundary checks, not LLM accuracy measurements."""

import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from grocery_agent.discovery import DiscoveryError, ModelDiscovery
from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.interactive_intent import normalize_interactive_intent
from grocery_agent.llm import ScriptedLLM
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario
from grocery_bench.environment import Observation
from grocery_web import interactive_service


def reviewer(queries=(), classify=None):
    def respond(messages, tools, json_mode):
        body = json.loads(messages[-1]["content"])
        if "search_query_fallback" in messages[0]["content"]:
            return {"content": json.dumps({"queries": list(queries)})}
        rows = []
        for p in body["products"]:
            verdict = classify(p) if classify else "related"
            rows.append({"product_id": p["id"], "verdict": verdict,
                         "reason": "Scripted semantic judgment",
                         "evidence": [{"field": "name", "quote": p["name"]}]})
        return {"content": json.dumps({"reviews": rows})}
    return ScriptedLLM(respond)


class DiscoveryTests(unittest.TestCase):
    def env(self):
        scenario = Scenario(id="discovery", category="development", difficulty="M", title="Discovery",
            variants={v: "Buy exactly 12 large eggs" for v in ("high", "medium", "low")},
            context={}, needs=[], extras_allowed=True)
        return GroceryEnv(load_catalog(), scenario, "high")

    def intent(self, **overrides):
        return normalize_interactive_intent({"budget_cents": 1000, "requirements": [{
            "id": "r1", "description": "12 large eggs", "search_query": "large chicken eggs",
            "measure": "count", "min": 12, "max": 12, **overrides}]})

    def test_empty_search_simplifies_queries_without_changing_goal_or_quantity(self):
        env = self.env()
        actual = env.search_products
        seen = []
        def search(query, max_results=20):
            seen.append(query)
            return actual(query, max_results) if query == "eggs" else Observation(True, "0 results", {"products": []})
        intent = self.intent()
        before = copy.deepcopy(intent)
        session = InteractiveShoppingSession(env, intent, discovery=ModelDiscovery(
            reviewer(["large chicken eggs", "large eggs", "eggs", "other"])))
        with patch.object(env, "search_products", search):
            result = session.advance()
        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual(seen, ["large chicken eggs", "large eggs", "eggs"])
        self.assertEqual(session.intent, before)
        option = next(p for p in result["questions"][0]["options"] if p["product_id"] == "eggs_value_6")
        self.assertEqual(option["quantity"], 2)
        restored = InteractiveShoppingSession.from_checkpoint(self.env(),
            json.loads(json.dumps(session.checkpoint())), discovery=ModelDiscovery(reviewer()))
        r = restored.choices.requirements["r1"]
        self.assertEqual([row["query"] for row in r.search_attempts], seen)
        self.assertTrue(r.semantic_reviews)
        final = restored.advance({"answers": [{"decision_id": result["questions"][0]["decision_id"],
                                               "selected_option_id": option["option_id"]}]})
        self.assertEqual(final["status"], "complete")

    def test_queries_are_deduplicated_and_bounded_when_all_are_empty(self):
        env = self.env()
        discovery = ModelDiscovery(reviewer([" LARGE CHICKEN EGGS ", "large eggs", "eggs", "more eggs"]))
        with patch.object(env, "search_products", return_value=Observation(True, "empty", {"products": []})) as search:
            result = discovery.discover(env, self.intent()["requirements"][0])
        self.assertEqual(search.call_count, 3)
        self.assertEqual(result["reason"], "empty_search")
        self.assertEqual(len({r["query"] for r in result["attempts"]}), 3)

    def test_transient_search_failure_retries_same_query_then_reviews_results(self):
        env = self.env()
        product = env.catalog["eggs_value_12"].public_summary(True)
        with patch.object(env, "search_products", side_effect=[
            Observation(False, "temporary upstream failure"),
            Observation(True, "1 result", {"products": [product]}),
        ]) as search:
            result = ModelDiscovery(reviewer()).discover(env, self.intent()["requirements"][0])
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["reason"], "reviewed")
        self.assertEqual(result["reviews"][0]["verdict"], "related")

    def test_extra_model_fields_cannot_replace_observed_product_metadata(self):
        env = self.env()
        p = env.catalog["eggs_value_12"].public_summary(True)
        llm = ScriptedLLM(lambda *args: {"content": json.dumps({"reviews": [{
            "product_id": p["id"], "verdict": "related", "reason": "eggs",
            "dietary_tags": ["vegan"], "price_cents": 1,
            "evidence": [{"field": "name", "quote": p["name"]}]}]})})
        with patch.object(env, "search_products", return_value=Observation(True, "1 result", {"products": [p]})):
            result = ModelDiscovery(llm).discover(env, self.intent()["requirements"][0])
        self.assertEqual(result["products"][0]["price_cents"], p["price_cents"])
        self.assertNotIn("dietary_tags", result["products"][0])

    def test_tool_failure_retries_original_query_without_relaxing_or_replanning(self):
        env = self.env()
        llm = reviewer(["eggs"])
        with patch.object(env, "search_products", return_value=Observation(False, "timeout")) as search:
            result = ModelDiscovery(llm).discover(env, self.intent()["requirements"][0])
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["reason"], "search_error")
        self.assertEqual({row["query"] for row in result["attempts"]}, {"large chicken eggs"})
        self.assertEqual(env.model_calls, 0)

    def test_unrelated_product_is_removed_even_if_package_count_matches(self):
        env = self.env()
        egg = env.catalog["eggs_value_12"]
        env.catalog = {"real": replace(egg, id="real"),
                       "chocolate": replace(egg, id="chocolate", name="Chocolate candy eggs 12 ct")}
        env.stock = {pid: 10 for pid in env.catalog}
        session = InteractiveShoppingSession(env, self.intent(search_query="eggs"),
            discovery=ModelDiscovery(reviewer(classify=lambda p: "unrelated" if p["id"] == "chocolate" else "related")))
        result = session.advance()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(env.cart, {"real": 1})
        self.assertTrue(any(r["verdict"] == "unrelated" for r in session.choices.requirements["r1"].semantic_reviews))

    def test_related_verdict_cannot_invent_required_tag_or_bypass_hard_checks(self):
        env = self.env()
        session = InteractiveShoppingSession(env, self.intent(required_tags=["vegan"], search_query="eggs"),
                                             discovery=ModelDiscovery(reviewer()))
        result = session.advance()
        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(result["reasons"]["r1"], "hard_constraints")
        self.assertEqual(env.cart, {})

    def test_unusable_model_review_is_error_not_automatic_purchase(self):
        env = self.env()
        broken = ScriptedLLM(lambda *args: {"content": '{"reviews": []}'})
        session = InteractiveShoppingSession(env, self.intent(search_query="eggs"), discovery=ModelDiscovery(broken))
        self.assertEqual(session.advance()["status"], "review_error")
        self.assertEqual(env.cart, {})

    def test_fabricated_evidence_and_product_ids_are_rejected(self):
        env = self.env()
        products = [env.catalog["eggs_value_12"].public_summary(True)]
        for product_id, quote in [("invented", products[0]["name"]), (products[0]["id"], "certified organic")]:
            llm = ScriptedLLM(lambda *args: {"content": json.dumps({"reviews": [{
                "product_id": product_id, "verdict": "related", "reason": "yes",
                "evidence": [{"field": "name", "quote": quote}]}]})})
            with self.assertRaises(DiscoveryError):
                ModelDiscovery(llm).review(env, self.intent()["requirements"][0], products)

    def test_title_whitespace_is_anchored_to_original_field_without_inventing_words(self):
        env = self.env()
        product = {**env.catalog["eggs_value_12"].public_summary(True), "name": "Large\u00a0White Eggs\u200b"}
        llm = ScriptedLLM(lambda *args: {"content": json.dumps({"reviews": [{
            "product_id": product["id"], "verdict": "related", "reason": "Observed title",
            "evidence": [{"field": "name", "quote": "Large White Eggs"}]}]})})
        row = ModelDiscovery(llm).review(env, self.intent()["requirements"][0], [product])[0]
        evidence = row["evidence"][0]
        self.assertIn(evidence["quote"], product["name"])
        self.assertEqual(evidence["model_quote"], "Large White Eggs")
        self.assertEqual(env.model_calls, 1)

    def test_malformed_review_gets_one_repair_and_keeps_diagnostic(self):
        env = self.env()
        p = env.catalog["eggs_value_12"].public_summary(True)
        def respond(messages, tools, json_mode):
            payload = json.loads(messages[-1]["content"])
            if "previous_error" not in payload:
                return {"content": '{"reviews": []}'}
            self.assertEqual(payload["products"], [p])
            return {"content": json.dumps({"reviews": [{"product_id": p["id"], "verdict": "related",
                "reason": "Observed eggs", "evidence": [{"field": "name", "quote": p["name"]}]}]})}
        diagnostics = []
        rows = ModelDiscovery(ScriptedLLM(respond)).review(env, self.intent()["requirements"][0], [p], diagnostics)
        self.assertEqual(rows[0]["product_id"], p["id"])
        self.assertEqual(env.model_calls, 2)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn('"reviews": []', diagnostics[0]["raw_response"])

    def test_repair_is_bounded_and_cannot_make_fabricated_evidence_acceptable(self):
        env = self.env()
        p = env.catalog["eggs_value_12"].public_summary(True)
        llm = ScriptedLLM(lambda *args: {"content": json.dumps({"reviews": [{
            "product_id": p["id"], "verdict": "related", "reason": "Fake certification",
            "evidence": [{"field": "name", "quote": "certified organic"}]}]})})
        diagnostics = []
        with self.assertRaises(DiscoveryError):
            ModelDiscovery(llm).review(env, self.intent()["requirements"][0], [p], diagnostics)
        self.assertEqual(env.model_calls, 2)
        self.assertEqual(len(diagnostics), 2)

    def test_provider_quota_error_propagates_without_semantic_repair_or_reasoning_failure(self):
        class ProviderQuotaError(Exception):
            __module__ = "openai"
        env = self.env()
        p = env.catalog["eggs_value_12"].public_summary(True)
        def respond(*args):
            raise ProviderQuotaError("Insufficient Balance")
        llm = ScriptedLLM(respond)
        with self.assertRaises(ProviderQuotaError):
            ModelDiscovery(llm).review(env, self.intent()["requirements"][0], [p])
        self.assertEqual(llm.calls, 1)

    def test_uncertain_candidate_requires_explicit_confirmation_and_survives_checkpoint(self):
        env = self.env()
        discovery = ModelDiscovery(reviewer(classify=lambda p: "uncertain"))
        session = InteractiveShoppingSession(env, self.intent(search_query="eggs"), discovery=discovery)
        result = session.advance()
        self.assertEqual(result["status"], "needs_candidate_review")
        self.assertEqual(env.cart, {})
        restored = InteractiveShoppingSession.from_checkpoint(self.env(),
            json.loads(json.dumps(session.checkpoint())), discovery=discovery)
        question = result["questions"][0]
        restored.answer_candidate_reviews({"answers": [{"review_id": question["review_id"],
                                                         "selected_product_id": "eggs_value_6"}]})
        final = restored.advance()
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["cart"], {"eggs_value_6": 2})

    def test_rejecting_uncertain_products_does_not_automatically_reoffer_them(self):
        session = InteractiveShoppingSession(self.env(), self.intent(search_query="eggs"),
            discovery=ModelDiscovery(reviewer(classify=lambda p: "uncertain")))
        first = session.advance()
        session.answer_candidate_reviews({"answers": [{"review_id": first["questions"][0]["review_id"],
                                                        "selected_product_id": None}]})
        self.assertEqual(session.advance()["status"], "no_candidates")
        self.assertEqual(session.env.cart, {})

    def test_http_resume_candidate_review_uses_same_contract(self):
        secret = "test-only-signing-secret-with-32-characters"
        def respond(messages, tools, json_mode):
            if "Task: candidate_semantic_review" in messages[0]["content"]:
                return reviewer(classify=lambda p: "uncertain").responder(messages, tools, json_mode)
            return {"content": json.dumps({"requirements": [{"id": "r1", "description": "one yogurt",
                                                              "min": 1, "max": 1}]})}
        llm = ScriptedLLM(respond)
        first = interactive_service.start("Buy one yogurt", source="snapshot", selection_mode="user_choice", llm=llm, signing_secret=secret)
        self.assertEqual(first["status"], "needs_candidate_review")
        q = first["questions"][0]
        final = interactive_service.resume(first["session_token"], candidate_review_answers={"answers": [
            {"review_id": q["review_id"], "selected_product_id": q["options"][0]["id"]}]},
            llm=llm, signing_secret=secret)
        self.assertEqual(final["status"], "complete")
        self.assertTrue(final["discovery"][0]["reviews"])


if __name__ == "__main__":
    unittest.main()
