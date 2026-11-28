"""Evaluate the interactive workflow without exposing hidden shopping answers.

The simulated shopper selects the cheapest offered line total, with UPC as a
tie breaker. It answers mandatory free-text questions only through ask_user.
Quantity questions can be answered by an explicitly configured shopper profile.
It cannot resolve semantic uncertainty or read the benchmark's hidden needs.
"""

from .interactive import InteractiveShoppingSession
from .simulated_user import QuantityAnswerUnavailable, BasketAnswerUnavailable, ScriptedBasketUser


class InteractiveBenchmarkAgent:
    name = "interactive"

    def __init__(self, llm, quantity_user=None):
        self.llm = llm
        self.quantity_user = quantity_user
        self.selection_mode = "user_choice"
        self.basket_user = None
        self.notes = {"llm": llm.describe(), "shopper_policy": "cheapest_offered_line_then_upc",
                      "interaction_events": [], "quantity_dialogue": []}

    def run(self, env):
        try:
            self._run(env)
        except (ValueError, KeyError, TypeError) as error:
            # Invalid model intent or workflow output is a scored agent failure,
            # not an infrastructure outage excluded from the denominator.
            self.notes["stop_reason"] = "invalid_agent_output"
            self.notes["error"] = f"{type(error).__name__}: {error}"
            if getattr(error, "diagnostics", None):
                self.notes["intent_errors"] = error.diagnostics

    def _run(self, env):
        session = InteractiveShoppingSession.from_model(env, self.llm, selection_mode=self.selection_mode)
        self.notes["intent_schema_version"] = session.intent.get("schema_version", 1)
        result = session.advance()
        self.continue_session(env, session, result)

    def continue_session(self, env, session, result):
        """Also permits an explicitly labeled replay from a saved checkpoint."""
        for _ in range(32):
            self.notes["interaction_events"].append({
                "status": result["status"], "questions": result.get("questions", []),
                "reasons": result.get("reasons"),
                "recommendation": result.get("recommendation"),
                "error": result.get("error"),
            })
            if result["status"] == "waiting_for_user":
                answers = []
                for question in result["questions"]:
                    try:
                        chosen = (self.basket_user.choose(env.observation()["scenario_id"], question)
                                  if self.basket_user else min(question["options"],
                                 key=lambda p: (p["line_total_cents"] if p["line_total_cents"] is not None
                                                else p["price_cents"], p["product_id"])))
                    except BasketAnswerUnavailable as error:
                        self.notes["stop_reason"] = "basket_answer_unavailable"
                        self.notes["basket_error"] = str(error)
                        self.notes["session"] = session.checkpoint()
                        return
                    answers.append({"decision_id": question["decision_id"],
                                    "selected_option_id": chosen["option_id"]})
                result = session.advance({"answers": answers})
            elif result["status"] == "needs_clarification":
                answers, dialogue = [], []
                try:
                    for question in result["questions"]:
                        if question["kind"] == "free_text":
                            answers.append({"question_id": question["question_id"],
                                            "text": env.ask_user(question["question"]).message})
                        else:
                            if self.quantity_user is None:
                                raise QuantityAnswerUnavailable("No scripted shopper profile configured")
                            answer, audit = self.quantity_user.answer(env.observation()["scenario_id"], question, env)
                            answers.append(answer)
                            dialogue.append(audit)
                except QuantityAnswerUnavailable as error:
                    self.notes["stop_reason"] = "quantity_answer_unavailable"
                    self.notes["quantity_error"] = str(error)
                    break
                self.notes["quantity_dialogue"].extend(dialogue)
                session.answer_clarifications({"answers": answers}, self.llm)
                result = session.advance()
            elif result["status"] == "awaiting_basket_confirmation":
                draft = result["recommendation"]
                if "first_recommendation" not in self.notes:
                    self.notes["first_recommendation"] = {
                        "cart": {p["product_id"]: p["quantity"] for p in draft["items"]},
                        "trajectory": list(env.trajectory),
                        "model_calls": env.model_calls,
                        "unavailable": sorted(env.unavailable_products()),
                    }
                answer = self.basket_user.review(env.observation()["scenario_id"], draft)
                self.notes.setdefault("basket_dialogue", []).append({"question": draft, "answer": answer})
                session.answer_recommendation(answer)
                result = session.advance()
            elif result["status"] == "needs_substitution_permission" and self.basket_user:
                try:
                    answers = [self.basket_user.authorize(env.observation()["scenario_id"], q)
                               for q in result["questions"]]
                except BasketAnswerUnavailable as error:
                    self.notes["stop_reason"] = "substitution_permission_unavailable"
                    self.notes["substitution_error"] = str(error)
                    break
                self.notes.setdefault("substitution_dialogue", []).append({"questions": result["questions"], "answers": answers})
                session.answer_substitutions({"answers": answers})
                result = session.advance()
            elif result["status"] == "needs_quantity_review" and self.quantity_user:
                answers, dialogue = [], []
                try:
                    for question in result["questions"]:
                        answer, audit = self.quantity_user.answer_review(env.observation()["scenario_id"], question, env)
                        answers.append(answer)
                        dialogue.append(audit)
                except QuantityAnswerUnavailable as error:
                    self.notes["stop_reason"] = "quantity_review_unavailable"
                    self.notes["quantity_error"] = str(error)
                    break
                self.notes["quantity_dialogue"].extend(dialogue)
                session.answer_quantity_reviews({"answers": answers})
                result = session.advance()
            else:
                self.notes["stop_reason"] = result["status"]
                break
        else:
            self.notes["stop_reason"] = "interaction_limit"
        events = self.notes["interaction_events"]
        self.notes["dialogue_metrics"] = {
            "prompt_batches": sum(e["status"] in {"waiting_for_user", "needs_clarification", "awaiting_basket_confirmation",
                                                   "needs_substitution_permission", "needs_quantity_review", "needs_candidate_review"}
                                  for e in events),
            "questions": sum(len(e["questions"]) + (e["status"] == "awaiting_basket_confirmation") for e in events),
            "replacement_requests": sum(d["answer"]["action"] == "replace" for d in self.notes.get("basket_dialogue", [])),
        }
        self.notes["session"] = session.checkpoint()


class RecommendedBenchmarkAgent(InteractiveBenchmarkAgent):
    """Separate protocol label; legacy interactive scores retain their meaning."""
    name = "recommended"

    def __init__(self, llm, quantity_user=None, basket_user=None):
        super().__init__(llm, quantity_user)
        self.selection_mode = "recommend"
        self.basket_user = basket_user or ScriptedBasketUser()
        self.notes["shopper_policy"] = "accept_draft_or_request_profile_preference_replacement"
