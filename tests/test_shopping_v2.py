"""Controlled state/authorization tests, not evidence of real-model accuracy."""

import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.intent_schema import normalize_v2, active_spec, source_text
from grocery_agent.discovery import ModelDiscovery
from grocery_agent.llm import ScriptedLLM
from grocery_agent.recommendation import ModelBasketRecommender
from grocery_agent.llm_agents import amount_per_package
from grocery_agent.interactive_benchmark import RecommendedBenchmarkAgent
from grocery_agent.simulated_user import ScriptedQuantityUser, QuantityAnswerUnavailable
from grocery_bench import GroceryEnv, load_catalog
from grocery_bench.data import Scenario, KROGER_CATALOG_PATH
from grocery_bench.environment import Observation
from grocery_web import interactive_service


P1, P2, P3, P4 = [f"{i:013d}" for i in range(1, 5)]
REQUEST = "Buy one Original Beverage. If unavailable, any other beverage explicitly dairy-free and nut-free is allowed."


def evidence(quote=REQUEST):
    return [{"source": "instruction", "quote": quote}]


def raw_intent(request=REQUEST, fallback=True, binding="user", quantity=None, tags=("dairy_free", "nut_free")):
    rule = {"description": "other beverage", "search_query": "beverage", "trigger": "confirmed_out_of_stock",
            "evidence": evidence(request)} if fallback else None
    return {"schema_version": 2, "requirements": [{"id": "r1", "primary": {
        "description": "Original Beverage" if binding == "user" else "beverage", "search_query": "beverage",
        "binding": binding, "evidence": evidence(request)}, "fallback": rule,
        "quantity_request": quantity or {"kind": "packages", "min": 1, "max": 1, "unit": "carton",
                                         "expression": request, "evidence": evidence(request)},
        "constraints": [{"kind": "tag", "value": tag, "evidence": evidence(request)} for tag in tags]}],
        "budget_cents": 1000}


def normalized(raw, request=REQUEST):
    return normalize_v2(raw, {"instruction": request, "context": "", "cart": "", "revision": ""})


def scripted_model(raw=None, quantity=None, queries=()):
    def respond(messages, tools, json_mode):
        system = messages[0]["content"]
        body = json.loads(messages[-1]["content"])
        if "Task: candidate_semantic_review" in system:
            target = body["requirement"]["description"].casefold()
            rows = []
            for p in body["products"]:
                match = target in p["name"].casefold() or (target == "other beverage" and "beverage" in p["name"].casefold())
                rows.append({"product_id": p["id"], "verdict": "related" if match else "unrelated",
                             "reason": "Controlled fixture semantics",
                             "evidence": [{"field": "name", "quote": p["name"]}]})
            return {"content": json.dumps({"reviews": rows})}
        if "Task: search_query_fallback" in system:
            return {"content": json.dumps({"queries": list(queries)})}
        if "Task: basket_recommendation" in system:
            return {"content": json.dumps({"selections": [{"requirement_id": n["requirement_id"],
                "product_id": min(n["candidates"], key=lambda p: (p["price_cents"], p["id"]))["id"],
                "reason": "Controlled recommendation"} for n in body["needs"]]})}
        if "Task: recommended_quantity_interpretation" in system:
            if quantity:
                return {"content": json.dumps(quantity(body))}
            req, product = body["active_requirement"], body["product"]
            unknown = req["min"] is None
            amount = amount_per_package(product, req["measure"])
            return {"content": json.dumps({"status": "needs_clarification" if unknown else "proposal",
                "purchase_packages": None if unknown else (req["min"] + amount - 1) // amount,
                "explanation": "Controlled quantity explanation", "question": "How many packages?" if unknown else None,
                "evidence": [{"field": "name", "quote": product["name"]}]})}
        return {"content": json.dumps(raw)}
    return ScriptedLLM(respond)


def environment(request=REQUEST, event=True):
    base = next(iter(load_catalog().values()))
    products = {
        P1: replace(base, id=P1, name="Original Beverage", category="beverage", price_cents=100,
                    size=1000, unit="ml", raw_size="1 L", tags=frozenset({"dairy_free", "nut_free"})),
        P2: replace(base, id=P2, name="Extra Creamy Beverage", category="beverage", price_cents=200,
                    size=1000, unit="ml", raw_size="1 L", tags=frozenset({"dairy_free", "nut_free"})),
        P3: replace(base, id=P3, name="Tree Nut Beverage", category="beverage", price_cents=50,
                    size=1000, unit="ml", raw_size="1 L", tags=frozenset({"dairy_free", "tree_nut_free"})),
        P4: replace(base, id=P4, name="Crackers", price_cents=50, size=1, unit="ct", tags=frozenset()),
    }
    scenario = Scenario(id="v2-development", title="Contract", category="development", difficulty="M",
        variants={v: request for v in ("high", "medium", "low")}, context={}, needs=[], extras_allowed=True,
        events=[{"product_id": P1, "trigger": "first_attempt"}] if event else [])
    return GroceryEnv(products, scenario, "high")


def session(raw=None, env=None, quantity=None, queries=()):
    env = env or environment()
    raw = raw or raw_intent()
    llm = scripted_model(raw, quantity, queries)
    return InteractiveShoppingSession(env, normalized(raw, env.observation()["instruction"]),
        selection_mode="recommend", max_rounds=32, discovery=ModelDiscovery(llm), recommender=ModelBasketRecommender(llm))


def accept(s, draft):
    s.answer_recommendation({"recommendation_id": draft["recommendation"]["recommendation_id"], "action": "accept"})
    return s.advance()


class IntentV2Tests(unittest.TestCase):
    def test_fallback_and_active_target_preserve_safety(self):
        intent = normalized(raw_intent())
        item = intent["requirements"][0]
        active = active_spec(item, "fallback")
        self.assertEqual(active["description"], "other beverage")
        self.assertEqual(active["required_tags"], ["dairy_free", "nut_free"])
        self.assertEqual(item["primary"]["description"], "Original Beverage")

    def test_fabricated_evidence_or_upc_is_rejected(self):
        for key in ("evidence", "product_ids"):
            raw = raw_intent()
            raw["requirements"][0]["primary"][key] = evidence("invented text") if key == "evidence" else [P1]
            with self.assertRaises(ValueError):
                normalized(raw)

    def test_no_added_salt_does_not_support_extra_low_sodium_tag(self):
        request = "Buy one Kroger No Salt Added Tomato Sauce."
        raw = raw_intent(request, fallback=False, tags=("low_sodium",))
        with self.assertRaisesRegex(ValueError, "low_sodium"):
            normalized(raw, request)
        raw["requirements"][0]["constraints"] = [{"kind": "description", "value": "No Salt Added", "evidence": evidence(request)}]
        self.assertEqual(normalized(raw, request)["requirements"][0]["required_tags"], [])

    def test_tree_nut_wording_cannot_create_nut_free_requirement(self):
        request = "Buy one beverage, tree-nut-free."
        with self.assertRaises(ValueError):
            normalized(raw_intent(request, tags=("nut_free",)), request)

    def test_package_half_gallon_is_one_package_not_1892_ml(self):
        request = "Buy one half-gallon milk carton."
        raw = raw_intent(request, fallback=False, tags=())
        item = normalized(raw, request)["requirements"][0]
        self.assertEqual((item["measure"], item["min"], item["max"]), ("units", 1, 1))

    def test_physical_unit_conversion_is_program_owned(self):
        request = "Buy half a gallon in total."
        raw = raw_intent(request, tags=(), quantity={"kind": "volume", "min": .5, "max": .5,
            "unit": "gal", "expression": request, "evidence": evidence(request)})
        item = normalized(raw, request)["requirements"][0]
        self.assertEqual((item["measure"], item["min"]), ("volume_ml", 1893))

    def test_nutrition_claim_cannot_invent_numeric_threshold(self):
        request = "Buy one low-sodium beverage."
        raw = raw_intent(request, tags=(), fallback=False)
        raw["requirements"][0]["constraints"] = [{"kind": "nutrition", "value": "sodium", "max": 140,
            "unit": "mg", "basis": "per_serving", "evidence": evidence(request)}]
        with self.assertRaisesRegex(ValueError, "threshold"):
            normalized(raw, request)

    def test_unsupported_sub_gram_precision_is_not_rounded_into_a_purchase(self):
        request = "Buy exactly 1.5 g."
        raw = raw_intent(request, tags=(), quantity={"kind": "weight", "min": 1.5, "max": 1.5,
            "unit": "g", "expression": request, "evidence": evidence(request)})
        with self.assertRaisesRegex(ValueError, "precision"):
            normalized(raw, request)

    def test_nested_context_has_an_actual_full_path_for_each_value(self):
        text = source_text({"substitutions": {"pasta": "Other Pasta", "sauce": "Other Sauce"}})
        self.assertIn("substitutions: sauce: Other Sauce", text)
        self.assertIn("substitutions: pasta: Other Pasta", text)

    def test_missing_quantity_cannot_be_made_one_by_citing_only_product_names(self):
        request = "Buy Original Beverage."
        raw = raw_intent(request, tags=(), fallback=False)
        with self.assertRaisesRegex(ValueError, "unknown"):
            normalized(raw, request)

    def test_nonempty_cart_cannot_be_replaced_without_source_evidence(self):
        raw = raw_intent()
        raw["cart_policy"] = {"mode": "replace_list", "evidence": []}
        with self.assertRaisesRegex(ValueError, "Removing unlisted"):
            normalize_v2(raw, {"instruction": REQUEST, "context": "", "cart": "items: quantity: 1", "revision": ""})

    def test_single_cart_policy_resolves_contradictory_legacy_flags(self):
        raw = raw_intent()
        raw.update(keep_existing_items=True, remove_unlisted_items=True,
                   cart_policy={"mode": "preserve_unlisted", "evidence": []})
        result = normalized(raw)
        self.assertTrue(result["keep_existing_items"])
        self.assertFalse(result["remove_unlisted_items"])


class ShoppingV2Tests(unittest.TestCase):
    def test_model_recommends_then_interprets_then_waits_for_plan_acceptance(self):
        s = session(env=environment(event=False))
        draft = s.advance()
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        self.assertEqual(s.env.cart, {})
        self.assertEqual(draft["recommendation"]["assignments"][0]["quantity_interpretation"]["status"], "proposal")
        self.assertEqual(accept(s, draft)["status"], "complete")
        self.assertEqual(s.choices.requirements["r1"].phase, "primary")

    def test_confirmed_stock_event_switches_scope_and_requests_new_acceptance(self):
        s = session()
        first = s.advance()
        second = accept(s, first)
        self.assertEqual(second["status"], "awaiting_basket_confirmation")
        self.assertEqual(s.choices.requirements["r1"].phase, "fallback")
        self.assertEqual(second["recommendation"]["items"][0]["product_id"], P2)
        self.assertNotIn(P1, s.choices.requirements["r1"].excluded_product_ids)
        self.assertEqual(s.env.cart, {})
        self.assertEqual(accept(s, second)["cart"], {P2: 1})

    def test_missing_explicit_nut_free_is_still_rejected(self):
        s = session()
        draft = accept(s, s.advance())
        self.assertEqual(draft["recommendation"]["items"][0]["product_id"], P2)
        self.assertTrue(any(P3 == v["product_id"] and v["code"] == "missing_tags"
                            for row in s.choices.requirements["r1"].filter_history for v in row["rejected"]))

    def test_exact_product_without_authorization_pauses_and_scope_answer_is_required(self):
        s = session(raw_intent(fallback=False))
        result = accept(s, s.advance())
        self.assertEqual(result["status"], "needs_substitution_permission")
        q = result["questions"][0]
        before = json.dumps(s.checkpoint(), sort_keys=True)
        with self.assertRaises(ValueError):
            s.answer_substitutions({"answers": [{"question_id": q["question_id"], "action": "allow_scope"}]})
        self.assertEqual(before, json.dumps(s.checkpoint(), sort_keys=True))
        s.answer_substitutions({"answers": [{"question_id": q["question_id"], "action": "allow_scope", "scope": "other beverage"}]})
        new = s.advance()
        self.assertEqual(new["status"], "awaiting_basket_confirmation")
        self.assertEqual(accept(s, new)["cart"], {P2: 1})

    def test_user_decline_does_not_delete_requirement_or_report_completion(self):
        s = session(raw_intent(fallback=False))
        q = accept(s, s.advance())["questions"][0]
        s.answer_substitutions({"answers": [{"question_id": q["question_id"], "action": "decline"}]})
        self.assertEqual(s.advance()["status"], "substitution_declined")
        self.assertIn("r1", s.choices.requirements)
        self.assertFalse(s.env.done)

    def test_model_chosen_upc_can_be_replaced_inside_original_open_scope(self):
        s = session(raw_intent(fallback=False, binding="open"))
        result = accept(s, s.advance())
        self.assertEqual(result["status"], "awaiting_basket_confirmation")
        self.assertEqual(s.choices.requirements["r1"].phase, "primary")
        self.assertEqual(accept(s, result)["cart"], {P2: 1})

    def test_service_failure_is_not_out_of_stock_or_substitution_authorization(self):
        s = session()
        first = s.advance()
        with patch.object(s.env, "add_to_cart", return_value=Observation(False, "network down", {"reason": "service_error"})):
            result = accept(s, first)
        self.assertEqual(result["status"], "cart_update_failed")
        self.assertEqual(s.choices.requirements["r1"].phase, "primary")

    def test_detail_failure_does_not_clear_or_replace_selected_product(self):
        s = session(env=environment(event=False))
        draft = s.advance()
        with patch.object(s.env, "get_product", return_value=Observation(False, "API unavailable")):
            result = accept(s, draft)
        self.assertEqual(result["status"], "product_refresh_error")
        self.assertEqual(s.choices.requirements["r1"].selected_product_id, P1)
        self.assertEqual(s.choices.requirements["r1"].phase, "primary")

    def test_checkpoint_preserves_fallback_rules_and_new_draft(self):
        s = session()
        new = accept(s, s.advance())
        saved = json.loads(json.dumps(s.checkpoint()))
        env = environment(event=False)
        env.stock[P1] = 0
        llm = scripted_model()
        restored = InteractiveShoppingSession.from_checkpoint(env, saved, ModelDiscovery(llm), ModelBasketRecommender(llm))
        self.assertEqual(restored.choices.requirements["r1"].phase, "fallback")
        self.assertEqual(restored.original_request, s.original_request)
        self.assertEqual(accept(restored, new)["cart"], {P2: 1})

    def test_unknown_quantity_waits_after_model_recommendation_without_guessing_one(self):
        request = "Buy Original Beverage."
        raw = raw_intent(request, tags=(), fallback=False, quantity={"kind": "unknown", "min": None, "max": None, "unit": ""})
        s = session(raw, environment(request, False))
        result = s.advance()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(s.choices.requirements["r1"].selected_product_id, P1)
        q = result["questions"][0]
        s.answer_clarifications({"answers": [{"question_id": q["question_id"], "amount": 2}]})
        self.assertEqual(accept(s, s.advance())["cart"], {P1: 2})

    def test_packaging_conflict_waits_for_explicit_revision(self):
        def conflict(body):
            return {"status": "conflict", "purchase_packages": None, "explanation": "Bottle vs can conflict",
                    "question": "Accept this product and specify package count?", "evidence": []}
        s = session(env=environment(event=False), quantity=conflict)
        result = s.advance()
        self.assertEqual(result["status"], "needs_quantity_review")
        self.assertEqual(s.env.cart, {})
        q = result["questions"][0]
        with self.assertRaises(ValueError):
            s.answer_quantity_reviews({"answers": [{"question_id": q["question_id"], "action": "confirm_selected_package_count", "amount": 2}]})
        s.answer_quantity_reviews({"answers": [{"question_id": q["question_id"], "action": "confirm_selected_package_count",
                                                 "amount": 2, "acknowledge_product_change": True}]})
        self.assertEqual(accept(s, s.advance())["cart"], {P1: 2})
        self.assertEqual(s.intent_revisions[-1]["kind"], "quantity_interpretation")

    def test_filter_empty_result_requeries_within_bounds(self):
        raw = raw_intent()
        raw["requirements"][0]["primary"]["description"] = "Extra Creamy Beverage"
        s = session(raw, environment(event=False), queries=("Extra Creamy Beverage", "beverage"))
        original = s.env.search_products
        def search(query, max_results=20):
            if query == "beverage":
                return Observation(True, "1 irrelevant hit", {"products": [s.env.catalog[P4].public_summary(True)]})
            return original(query, max_results)
        with patch.object(s.env, "search_products", search):
            draft = s.advance()
        self.assertEqual(draft["status"], "awaiting_basket_confirmation")
        self.assertEqual([r["query"] for r in s.choices.requirements["r1"].search_attempts], ["beverage", "Extra Creamy Beverage"])

    def test_one_stock_failure_keeps_other_added_need_and_does_not_double_add(self):
        request = REQUEST + " Also buy one Crackers."
        raw = raw_intent(request)
        raw["requirements"].append({"id": "r2", "primary": {"description": "Crackers", "search_query": "Crackers",
            "binding": "user", "evidence": evidence("one Crackers")}, "fallback": None, "constraints": [],
            "quantity_request": {"kind": "packages", "min": 1, "max": 1, "unit": "package",
                                 "expression": "one Crackers", "evidence": evidence("one Crackers")}})
        s = session(raw, environment(request))
        second = accept(s, s.advance())
        self.assertEqual(s.env.cart, {P4: 1})
        self.assertEqual(s.choices.requirements["r2"].status, "added")
        self.assertEqual(s.choices.requirements["r2"].phase, "primary")
        self.assertEqual(accept(s, second)["cart"], {P2: 1, P4: 1})

    def test_quantity_model_cannot_invent_missing_quantity_or_product_evidence(self):
        request = "Buy Original Beverage."
        raw = raw_intent(request, tags=(), fallback=False, quantity={"kind": "unknown", "min": None, "max": None})
        def guess(body):
            return {"status": "proposal", "purchase_packages": 1, "explanation": "Guess one",
                    "evidence": [{"field": "name", "quote": body["product"]["name"]}]}
        s = session(raw, environment(request, False), quantity=guess)
        self.assertEqual(s.advance()["status"], "needs_clarification")
        self.assertEqual(s.env.cart, {})

    def test_real_half_gallon_record_is_accepted_as_one_carton(self):
        request = "Buy one Kroger half-gallon whole milk carton."
        raw = raw_intent(request, tags=(), fallback=False)
        raw["requirements"][0]["primary"].update(description="Kroger", search_query="Kroger Vitamin D Whole Milk Half Gallon")
        env = environment(request, False)
        milk = load_catalog(KROGER_CATALOG_PATH)["0001111040601"]
        env.catalog = {milk.id: milk}
        env.stock = {milk.id: milk.stock}
        s = session(raw, env)
        result = accept(s, s.advance())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["cart"], {milk.id: 1})

    def test_expired_quantity_review_answer_cannot_apply_after_reselection(self):
        def conflict(body):
            return {"status": "conflict", "explanation": "Ambiguous form", "question": "Replace?", "evidence": []}
        s = session(env=environment(event=False), quantity=conflict)
        result = s.advance()
        q = result["questions"][0]
        s.answer_quantity_reviews({"answers": [{"question_id": q["question_id"], "action": "replace"}]})
        with self.assertRaises(ValueError):
            s.answer_quantity_reviews({"answers": [{"question_id": q["question_id"], "action": "confirm_selected_package_count",
                                                     "amount": 2, "acknowledge_product_change": True}]})

    def test_http_permission_question_survives_resume_and_exclusive_answer_contract(self):
        secret = "v2-contract-test-signing-secret-with-32-chars"
        start_env = environment(event=False)
        fail_env = environment(event=True)
        fallback_env = environment(event=False)
        fallback_env.stock[P1] = 0
        raw = raw_intent(fallback=False)
        llm = scripted_model(raw)
        with patch("grocery_web.service.build_env", side_effect=[start_env, fail_env, fallback_env]):
            first = interactive_service.start(REQUEST, source="snapshot", llm=llm, signing_secret=secret)
            self.assertEqual(first["schema_version"], 2)
            pending = interactive_service.resume(first["session_token"], recommendation_answer={
                "recommendation_id": first["recommendation"]["recommendation_id"], "action": "accept"},
                llm=llm, signing_secret=secret)
            self.assertEqual(pending["status"], "needs_substitution_permission")
            q = pending["questions"][0]
            next_draft = interactive_service.resume(pending["session_token"], substitution_answers={"answers": [
                {"question_id": q["question_id"], "action": "allow_scope", "scope": "other beverage"}]},
                llm=llm, signing_secret=secret)
            self.assertEqual(next_draft["status"], "awaiting_basket_confirmation")
            self.assertEqual(next_draft["requirement_states"][0]["phase"], "fallback")

    def test_shopper_can_edit_package_count_without_executing_before_new_confirmation(self):
        s = session(env=environment(event=False))
        first = s.advance()
        s.answer_recommendation({"recommendation_id": first["recommendation"]["recommendation_id"],
                                "action": "set_package_counts", "updates": [{"requirement_id": "r1", "amount": 3}]})
        second = s.advance()
        self.assertEqual(s.env.cart, {})
        self.assertEqual(second["recommendation"]["total_cents"], 300)
        self.assertEqual(accept(s, second)["cart"], {P1: 3})
        self.assertEqual(s.choices.requirements["r1"].rules["quantity_request"]["min"], 1)

    def test_budget_edit_is_explicit_and_does_not_silently_accept_overflow(self):
        s = session(env=environment(event=False))
        first = s.advance()
        s.answer_recommendation({"recommendation_id": first["recommendation"]["recommendation_id"],
                                "action": "set_budget", "budget_cents": 50})
        self.assertEqual(s.advance()["status"], "budget_conflict")
        self.assertEqual(s.env.cart, {})

    def test_historical_candidate_can_return_after_fresh_stock_and_price_read(self):
        s = session()
        draft = accept(s, s.advance())
        s.env.stock[P1] = 20
        s.env.catalog[P1] = replace(s.env.catalog[P1], price_cents=175)
        s.answer_recommendation({"recommendation_id": draft["recommendation"]["recommendation_id"],
                                "action": "select_history", "requirement_id": "r1", "product_id": P1})
        new = s.advance()
        self.assertEqual(new["recommendation"]["total_cents"], 175)
        self.assertEqual(accept(s, new)["cart"], {P1: 1})

    def test_historical_selection_cannot_use_unapproved_or_currently_unavailable_product(self):
        s = session()
        draft = accept(s, s.advance())
        for pid in (P1, P3, P4):
            with self.assertRaises(ValueError):
                s.answer_recommendation({"recommendation_id": draft["recommendation"]["recommendation_id"],
                                        "action": "select_history", "requirement_id": "r1", "product_id": pid})
        self.assertEqual(s.pending_recommendation["recommendation_id"], draft["recommendation"]["recommendation_id"])

    def test_two_independent_stock_events_switch_only_their_own_scopes(self):
        request = REQUEST + " Also buy one Crackers; if unavailable use other snack."
        raw = raw_intent(request)
        raw["requirements"].append({"id": "r2", "primary": {"description": "Crackers", "search_query": "Crackers",
            "binding": "user", "evidence": evidence("one Crackers")}, "fallback": {
                "trigger": "confirmed_out_of_stock", "description": "Other Snack", "search_query": "Other Snack",
                "evidence": evidence("if unavailable use other snack")}, "constraints": [],
            "quantity_request": {"kind": "packages", "min": 1, "max": 1, "unit": "package",
                                 "expression": "one Crackers", "evidence": evidence("one Crackers")}})
        env = environment(request)
        alternate = "0000000000005"
        env.catalog[alternate] = replace(env.catalog[P4], id=alternate, name="Other Snack", price_cents=60)
        env.stock[alternate] = 20
        env._pending_events[P4] = {"product_id": P4, "trigger": "first_attempt"}
        s = session(raw, env)
        second = accept(s, s.advance())
        self.assertEqual([r.phase for r in s.choices.requirements.values()], ["fallback", "fallback"])
        self.assertEqual(accept(s, second)["cart"], {P2: 1, alternate: 1})

    def test_explicit_remove_unlisted_takes_precedence_over_keep_flag(self):
        raw = raw_intent()
        raw.update(keep_existing_items=True, remove_unlisted_items=True)
        env = environment(event=False)
        env.cart[P4] = 2
        s = session(raw, env)
        draft = s.advance()
        self.assertIn({"product_id": P4, "from_quantity": 2, "to_quantity": 0, "action": "remove"},
                      draft["recommendation"]["operations"])
        self.assertEqual(accept(s, draft)["cart"], {P1: 1})

    def test_independent_user_total_can_correct_package_vs_content_extraction_conflict(self):
        request = "Buy four Snack Bars."
        raw = raw_intent(request, fallback=False, tags=(), quantity={"kind": "packages", "min": 4, "max": 4,
            "unit": "bars", "expression": "four Snack Bars", "evidence": evidence("four Snack Bars")})
        raw["requirements"][0]["primary"].update(description="Snack Bars", search_query="Snack Bars")
        env = environment(request, False)
        env.catalog = {P1: replace(env.catalog[P1], name="Snack Bars", raw_size="4 ct", size=4, unit="ct")}
        env.stock = {P1: 20}
        def interpret(body):
            return {"status": "proposal", "purchase_packages": 1, "explanation": "One 4-count package supplies four bars",
                    "evidence": [{"field": "raw_size", "quote": "4 ct"}]}
        user = ScriptedQuantityUser({"v2-development": [{"words": ["bar"], "measure": "count", "min": 4, "max": 4}]})
        agent = RecommendedBenchmarkAgent(scripted_model(raw, quantity=interpret), quantity_user=user)
        agent.run(env)
        self.assertEqual(agent.notes["stop_reason"], "complete")
        self.assertEqual(env.cart, {P1: 1})
        self.assertEqual(agent.notes["quantity_dialogue"][0]["source"], "scripted_independent_total_confirmation")

    def test_simulator_cannot_use_total_profile_to_accept_semantic_form_conflict(self):
        user = ScriptedQuantityUser({"v2-development": [{"words": ["beverage"], "measure": "count", "min": 4, "max": 4}]})
        q = {"reason_code": None, "question_id": "conflict", "requirement_id": "r1", "product": {"id": P1, "name": "Original Beverage"},
             "interpretation": {"status": "conflict", "proposed_purchase_packages": 1}}
        with self.assertRaises(QuantityAnswerUnavailable):
            user.answer_review("v2-development", q, environment(event=False))

    def test_mixed_review_batch_withholds_invalid_fact_row_without_approving_it(self):
        env = environment(event=False)
        products = [env.catalog[p].public_details(True) for p in (P1, P2)]
        def respond(*args):
            return {"content": json.dumps({"reviews": [
                {"product_id": P1, "verdict": "related", "reason": "Actual title", "evidence": [{"field": "name", "quote": products[0]["name"]}]},
                {"product_id": P2, "verdict": "related", "reason": "Invented ingredient", "evidence": [{"field": "allergens", "quote": "made_up_allergen"}]}
            ]})}
        diagnostics = []
        rows = ModelDiscovery(ScriptedLLM(respond)).review(env, {"description": "beverage"}, products, diagnostics)
        by_id = {r["product_id"]: r for r in rows}
        self.assertEqual(by_id[P1]["verdict"], "related")
        self.assertTrue(by_id[P2]["withheld"])
        self.assertEqual(by_id[P2]["evidence"], [])
        self.assertTrue(any(r["stage"] == "withheld_review_row" for r in diagnostics))

    def test_primary_already_out_of_stock_at_first_search_uses_authorized_fallback(self):
        env = environment(event=False)
        env.stock[P1] = 0
        s = session(env=env)
        result = s.advance()
        self.assertEqual(result["status"], "awaiting_basket_confirmation")
        self.assertEqual(result["recommendation"]["items"][0]["product_id"], P2)
        self.assertEqual(s.choices.requirements["r1"].phase, "fallback")

    def test_initial_out_of_stock_exact_product_without_rule_asks_permission(self):
        env = environment(event=False)
        env.stock[P1] = 0
        s = session(raw_intent(fallback=False), env)
        self.assertEqual(s.advance()["status"], "needs_substitution_permission")

    def test_declined_substitution_can_be_reopened_with_a_new_question_id(self):
        s = session(raw_intent(fallback=False))
        first_question = accept(s, s.advance())["questions"][0]
        s.answer_substitutions({"answers": [{"question_id": first_question["question_id"], "action": "decline"}]})
        self.assertEqual(s.advance()["status"], "substitution_declined")
        again = s.reconsider(["r1"])
        self.assertEqual(again["status"], "needs_substitution_permission")
        self.assertNotEqual(first_question["question_id"], again["questions"][0]["question_id"])

    def test_intent_repair_sees_independent_quantity_and_quote_failures(self):
        raw = raw_intent()
        raw["requirements"][0]["quantity_request"]["evidence"] = evidence("Original Beverage")
        second = copy.deepcopy(raw["requirements"][0])
        second["id"] = "r2"
        second["primary"]["evidence"] = evidence("a fictional quotation")
        raw["requirements"].append(second)
        with self.assertRaises(ValueError) as caught:
            normalized(raw)
        self.assertIn("No quantity wording", str(caught.exception))
        self.assertIn("a fictional quotation", str(caught.exception))

    def test_permission_rechecks_primary_recovery_before_fallback(self):
        s = session(raw_intent(fallback=False))
        q = accept(s, s.advance())["questions"][0]
        s.env.stock[P1] = 20
        s.answer_substitutions({"answers": [{"question_id": q["question_id"], "action": "allow_scope", "scope": "other beverage"}]})
        self.assertEqual(s.choices.requirements["r1"].phase, "primary")
        draft = s.advance()
        self.assertEqual(draft["recommendation"]["items"][0]["product_id"], P1)

    def test_reconsider_validates_batch_before_mutating(self):
        s = session()
        s.advance()
        before = s.checkpoint()
        with self.assertRaises(ValueError):
            s.reconsider(["r1", "missing"])
        self.assertEqual(before, s.checkpoint())


if __name__ == "__main__":
    unittest.main()
