"""Normalize shopping intent without inventing quantities the shopper omitted."""

from __future__ import annotations

import re
from typing import Mapping

from .llm_agents import MEASURES


INTERACTIVE_INTENT_GUIDANCE = """
Interactive shopping rule: preserve missing information. For each requirement,
return quantity_explicit (boolean). If the shopper did not specify how much to
buy, set quantity_explicit=false, min=null, max=null. For example, "buy yogurt"
means yogurt with unknown quantity; it does NOT mean one package. "Buy one
yogurt" means units min=max=1. If the shopper specified 12 eggs, use count
min=max=12; if 1 L of milk, use volume_ml min=max=1000. Do not put missing
quantities in open_questions: the program asks for them. Use open_questions
only for other mandatory missing facts, such as an unspecified allergy. Do not
put a question about which brand or flavor to choose in open_questions.
"""


def normalize_interactive_intent(raw: Mapping) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("intent must be an object")
    requirements = []
    ids = set()
    for index, item in enumerate(raw.get("requirements") or []):
        if not isinstance(item, dict):
            raise ValueError("Each requirement must be an object")
        requirement_id = str(item.get("id") or f"r{index + 1}")
        if requirement_id in ids:
            raise ValueError(f"Duplicate requirement: {requirement_id}")
        ids.add(requirement_id)
        description = str(item.get("description") or "").strip()
        query = str(item.get("search_query") or description).strip()
        if not query:
            raise ValueError(f"Missing product description for {requirement_id}")
        measure = str(item.get("measure") or "units")
        if measure not in MEASURES and not measure.startswith("portions:"):
            raise ValueError(f"Unsupported quantity measure for {requirement_id}: {measure}")
        explicit = item.get("quantity_explicit") is not False
        minimum = item.get("min", item.get("quantity")) if explicit else None
        maximum = item.get("max", minimum) if explicit else None
        if minimum in (None, ""):
            minimum = maximum = None
        else:
            minimum = int(minimum)
            maximum = minimum if maximum in (None, "") else int(maximum)
            if minimum <= 0 or maximum < minimum:
                raise ValueError(f"Invalid quantity range for {requirement_id}")
        requirements.append({
            "id": requirement_id,
            "description": description or query,
            "search_query": query,
            "measure": measure,
            "min": minimum,
            "max": maximum,
            "required_tags": [str(value) for value in item.get("required_tags") or []],
            "product_ids": [str(value) for value in item.get("product_ids") or []
                            if re.fullmatch(r"\d{13}", str(value))],
            "brand": item.get("brand") or None,
        })
    budget = raw.get("budget_cents")
    budget = None if budget in (None, "") else int(budget)
    if budget is not None and budget < 0:
        raise ValueError("Budget cannot be negative")
    return {
        "requirements": requirements,
        "budget_cents": budget,
        "all_items_required_tags": [str(value) for value in raw.get("all_items_required_tags") or []],
        "preferences": list(raw.get("preferences") or []),
        "keep_existing_items": bool(raw.get("keep_existing_items", False)),
        "remove_unlisted_items": bool(raw.get("remove_unlisted_items", True)),
        "open_questions": [value for value in raw.get("open_questions") or [] if value],
    }


def clarification_questions(intent: Mapping) -> list:
    questions = []
    if not intent["requirements"] and not intent["open_questions"]:
        questions.append({"question_id": "q_product", "kind": "free_text",
                          "question": "What products would you like to buy?"})
    for item in intent["requirements"]:
        if item["min"] is None:
            questions.append({
                "question_id": f"q_{item['id']}_quantity",
                "kind": "quantity",
                "requirement_id": item["id"],
                "question": f"How much {item['description']} should I buy?",
                "suggested_measure": item["measure"],
                "allowed_measures": ["units", "count", "volume_ml", "weight_g"],
            })
    for index, item in enumerate(intent["open_questions"], 1):
        question = item.get("question") if isinstance(item, dict) else str(item)
        questions.append({"question_id": f"q_open_{index}", "kind": "free_text",
                          "question": str(question)})
    return questions
