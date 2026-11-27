"""Benchmark-only shopper quantity answers, separate from the shopping agent.

Profiles express shopper intentions, never evaluator predicates or accepted
UPCs. Unknown or ambiguous profile matches remain unanswered.
"""

import json
import re

from .llm_agents import amount_per_package


class QuantityAnswerUnavailable(ValueError):
    pass


class BasketAnswerUnavailable(ValueError):
    pass


class ScriptedBasketUser:
    """Private shopper preferences, never injected into the recommending model.

    This is a development simulator, not a general language understanding
    policy. Rules use public names, not evaluator predicates or accepted UPCs.
    An absent profile means accept the recommendation without preference feedback.
    """

    def __init__(self, profiles=None):
        self.profiles = profiles or {}

    @classmethod
    def load(cls, path):
        return cls(json.loads(path.read_text(encoding="utf-8"))["basket_profiles"])

    def review(self, scenario_id, draft):
        products = {p["product_id"]: p for p in draft["items"]}
        replacements = []
        for assignment in draft["assignments"]:
            words = _words(products[assignment["product_id"]]["name"])
            for preference in self.profiles.get(scenario_id, []):
                if (_words(" ".join(preference["need_words"])).issubset(words)
                        and not _words(" ".join(preference["prefer_words"])).issubset(words)):
                    replacements.append(assignment["requirement_id"])
        return {"recommendation_id": draft["recommendation_id"],
                "action": "replace" if replacements else "accept",
                **({"requirement_ids": sorted(set(replacements))} if replacements else {})}

    def choose(self, scenario_id, question):
        options = list(question["options"])
        for preference in self.profiles.get(scenario_id, []):
            need = _words(" ".join(preference["need_words"]))
            if any(need.issubset(_words(p["name"])) for p in options):
                wanted = _words(" ".join(preference["prefer_words"]))
                options = [p for p in options if need.issubset(_words(p["name"]))
                           and wanted.issubset(_words(p["name"]))]
                if not options:
                    raise BasketAnswerUnavailable("No offered option satisfies the shopper preference")
        return min(options, key=lambda p: (p["line_total_cents"] if p["line_total_cents"] is not None
                                          else p["price_cents"], p["product_id"]))


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
