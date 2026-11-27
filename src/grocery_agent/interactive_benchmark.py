"""Evaluate the interactive workflow without exposing hidden shopping answers.

The simulated shopper selects the cheapest offered line total, with UPC as a
tie breaker. It answers mandatory free-text questions only through ask_user.
It cannot resolve semantic uncertainty or infer a missing quantity from the
benchmark's hidden needs. Such interactions stop and are scored as failures.
"""

from .interactive import InteractiveShoppingSession


class InteractiveBenchmarkAgent:
    name = "interactive"

    def __init__(self, llm):
        self.llm = llm
        self.notes = {"llm": llm.describe(), "shopper_policy": "cheapest_offered_line_then_upc",
                      "interaction_events": []}

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
                if any(q["kind"] != "free_text" for q in result["questions"]):
                    self.notes["stop_reason"] = "quantity_not_specified"
                    break
                answers = [{"question_id": q["question_id"],
                            "text": env.ask_user(q["question"]).message} for q in result["questions"]]
                session.answer_clarifications({"answers": answers}, self.llm)
                result = session.advance()
            else:
                self.notes["stop_reason"] = result["status"]
                break
        self.notes["session"] = session.checkpoint()
