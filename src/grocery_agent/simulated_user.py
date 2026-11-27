"""Benchmark-only shopper quantity answers, separate from the shopping agent.

Profiles express shopper intentions, never evaluator predicates or accepted
UPCs. Unknown or ambiguous profile matches remain unanswered.
"""

import json
import re

from .llm_agents import amount_per_package


class QuantityAnswerUnavailable(ValueError):
    pass


def _words(text):
    return {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", text.lower())}


class ScriptedQuantityUser:
    def __init__(self, profiles):
        self.profiles = profiles

    @classmethod
    def load(cls, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["profiles"])

    def answer(self, scenario_id, question, env):
        if question.get("kind") != "quantity" or "product_id" not in question:
            raise QuantityAnswerUnavailable("Not a package quantity question")
        words = _words(question.get("product_name", ""))
        matches = [item for item in self.profiles.get(scenario_id, [])
                   if set().union(*(_words(word) for word in item["words"])).issubset(words)
                   and not any(_words(word).issubset(words) for word in item.get("exclude_words", []))]
        targets = {(item["measure"], item["min"], item["max"]) for item in matches}
        if len(targets) != 1:
            raise QuantityAnswerUnavailable("No unique shopper intention for the selected product")
        measure, minimum, maximum = targets.pop()
        if measure == "units":
            amount = 1
        else:
            details = env.get_product(question["product_id"])
            if not details.ok:
                raise QuantityAnswerUnavailable("Cannot read selected package size")
            amount = amount_per_package(details.data, measure)
        if amount <= 0:
            raise QuantityAnswerUnavailable("Selected package cannot express the shopper's target")
        packages = (minimum + amount - 1) // amount
        if packages <= 0 or packages * amount > maximum:
            raise QuantityAnswerUnavailable("No exact permitted package count for the shopper's target")
        answer = {"question_id": question["question_id"], "amount": packages, "measure": "units"}
        audit = {"scenario_id": scenario_id, "requirement_id": question["requirement_id"],
                 "product_id": question["product_id"], "source": "scripted_shopper_profile",
                 "shopper_target": {"measure": measure, "min": minimum, "max": maximum},
                 "question": question, "answer": answer}
        return answer, audit
