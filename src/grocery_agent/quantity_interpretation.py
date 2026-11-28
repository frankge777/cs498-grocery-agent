"""Model interprets a recommended package; code validates facts and arithmetic."""

import hashlib
import json

from grocery_bench.environment import EpisodeTerminated
from .discovery import _observed_quote
from .llm import is_provider_error
from .llm_agents import amount_per_package


QUANTITY_SYSTEM = """Task: recommended_quantity_interpretation. Return JSON:
{"status":"proposal|conflict|needs_clarification|insufficient_product_data",
"purchase_packages":2 or null,"explanation":"what outer packages and contents the shopper gets",
"question":"specific question if not proposal, otherwise null",
"evidence":[{"field":"raw_size","quote":"exact observed substring"}]}.
Interpret the original quantity wording against THIS recommended product's real
name and raw specification. Original user units are not blindly package counts.
For two bottles with a single-bottle product, propose 2 packages. Two bottles
with a 12-CAN pack is a conflict, not 2 packs or an equivalent unit conversion.
Two boxes of ice cream with 6 sticks/box can mean 2 boxes = 12 sticks, never
two sticks. Explain form ambiguities and seek confirmation. Explicit tubs are
incompatible with multi-stick boxes. Twelve eggs in a 6-count pack means 2 packs.
One half-gallon carton means ONE carton, not a demand for exactly 1892 mL.
Use current active requirement/phase; historical primary is not a fallback
restriction. Respect all unchanged user constraints and stated quantity ranges.
If quantity is unknown, needs_clarification, not guessed one. If specs don't
establish count/form, insufficient_product_data. A recommendation is not user
consent to change a unit, packaging form or amount. Cite actual top-level fields;
never fabricate product facts, tags or conversions. Program checks arithmetic
on normalized units afterward. You cannot authorize or write shopping carts.
"""


class QuantityInterpretationError(ValueError):
    pass


def quantity_fingerprint(product):
    fields = ("id", "name", "raw_size", "size", "unit", "portions")
    return hashlib.sha256(json.dumps({k: product.get(k) for k in fields}, sort_keys=True).encode()).hexdigest()


class ModelQuantityInterpreter:
    def __init__(self, llm):
        self.llm = llm

    def interpret(self, env, requirement, product, source_records):
        payload = {"sources": source_records, "active_requirement": requirement.active_requirement(),
                   "product": product, "selection_revision": requirement.selection_revision}
        for attempt in range(2):
            try:
                reply = self.llm.chat([{"role": "system", "content": QUANTITY_SYSTEM},
                                      {"role": "user", "content": json.dumps(payload)}], json_mode=True, env=env)
                data = json.loads(reply.content)
                return self.validate(data, requirement, product)
            except (EpisodeTerminated,):
                raise
            except Exception as error:
                if is_provider_error(error):
                    raise
                if attempt:
                    raise QuantityInterpretationError(str(error)) from error
                payload.update(previous_error=str(error), repair_instruction="Correct output once; never guess facts or change original requirements.")

    @staticmethod
    def validate(data, requirement, product):
        if not isinstance(data, dict) or data.get("status") not in {
                "proposal", "conflict", "needs_clarification", "insufficient_product_data"}:
            raise ValueError("Invalid quantity interpretation status")
        explanation = data.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("Quantity explanation is required")
        proof = data.get("evidence") or []
        anchored = []
        for row in proof:
            if not isinstance(row, dict) or row.get("field") not in product or not isinstance(row.get("quote"), str) or not row["quote"]:
                raise ValueError("Quantity evidence must reference a supplied product field")
            value = product[row["field"]]
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            quote = _observed_quote(text, row["quote"])
            if quote is None:
                raise ValueError("Quantity evidence was not observed")
            anchored.append({"field": row["field"], "quote": quote})
        packages = data.get("purchase_packages")
        reason_code = None
        proposed = None
        if data["status"] == "proposal":
            if not anchored or isinstance(packages, bool) or not isinstance(packages, int) or packages < 1:
                raise ValueError("Proposal needs positive integer package count and observed evidence")
            if requirement.target_min is None:
                proposed = packages
                packages = None
                data = {**data, "status": "needs_clarification",
                        "question": f"How many packages of {product['name']} would you like?"}
                explanation = "The extracted quantity is unknown; a model suggestion is not shopper confirmation. Please specify package count."
                reason_code = "unknown_quantity"
            else:
                amount = amount_per_package(product, requirement.measure) * packages
                if amount < requirement.target_min or (requirement.target_max is not None and amount > requirement.target_max):
                    proposed = packages
                    packages = None
                    data = {**data, "status": "conflict", "question":
                        f"The model proposes {proposed} package(s) of {product['name']}, but this conflicts with the extracted target {requirement.target_min}..{requirement.target_max} {requirement.measure}. Confirm the intended package count or choose another product."}
                    reason_code = "quantity_target_mismatch"
        else:
            packages = None
            if not isinstance(data.get("question"), str) or not data["question"].strip():
                raise ValueError("Non-executable interpretation needs a concrete clarification question")
        return {"status": data["status"], "purchase_packages": packages, "explanation": explanation[:1600],
                "question": data.get("question"), "evidence": anchored,
                "reason_code": reason_code, "proposed_purchase_packages": proposed,
                "normalized_contents": ({"amount": product["size"] * packages, "unit": product["unit"]}
                                        if packages is not None and product.get("unit") in {"ct", "g", "ml"} else None),
                "product_id": product["id"], "selection_revision": requirement.selection_revision,
                "facts_fingerprint": quantity_fingerprint(product)}
