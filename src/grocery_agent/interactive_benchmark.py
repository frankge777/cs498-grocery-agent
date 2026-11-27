"""Evaluate the interactive workflow without exposing hidden shopping answers.

The simulated shopper selects the cheapest offered line total, with UPC as a
tie breaker. It answers mandatory free-text questions only through ask_user.
Quantity questions can be answered by an explicitly configured shopper profile.
It cannot resolve semantic uncertainty or read the benchmark's hidden needs.
"""

from .interactive import InteractiveShoppingSession
from .simulated_user import QuantityAnswerUnavailable


class InteractiveBenchmarkAgent:
    name = "interactive"

    def __init__(self, llm, quantity_user=None):
        self.llm = llm
        self.quantity_user = quantity_user
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

    def _run(self, env):
        session = InteractiveShoppingSession.from_model(env, self.llm)
        result = session.advance()
        self.continue_session(env, session, result)

    def continue_session(self, env, session, result):
        """Also permits an explicitly labeled replay from a saved checkpoint."""
        for _ in range(16):
            self.notes["interaction_events"].append({
                "status": result["status"], "questions": result.get("questions", []),
                "reasons": result.get("reasons"),
            })
            if result["status"] == "waiting_for_user":
                answers = []
                for question in result["questions"]:
                    chosen = min(question["options"],
                                 key=lambda p: (p["line_total_cents"] if p["line_total_cents"] is not None
                                                else p["price_cents"], p["product_id"]))
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
            else:
                self.notes["stop_reason"] = result["status"]
                break
        self.notes["session"] = session.checkpoint()
