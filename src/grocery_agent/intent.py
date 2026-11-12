from __future__ import annotations

import re
from collections import OrderedDict
from typing import Dict, Iterable, List

from .models import ParsedIntent, Requirement


CATEGORY_ALIASES: Dict[str, Iterable[str]] = {
    "milk": ("oat milk", "milk"),
    "bread": ("bread", "loaf"),
    "banana": ("bananas", "banana"),
    "eggs": ("eggs", "egg"),
    "pasta": ("pasta", "spaghetti"),
    "pasta_sauce": ("pasta sauce", "tomato sauce", "marinara"),
    "cereal": ("cereal",),
    "protein_bar": ("protein bars", "protein bar", "snack bars"),
    "water": ("bottled water", "water pack", "water"),
    "tortillas": ("tortillas", "tortilla"),
    "beans": ("black beans", "beans"),
    "salsa": ("salsa",),
    "cheese": ("shredded cheese", "cheese"),
    "pancake_mix": ("pancake mix", "pancakes"),
    "syrup": ("maple syrup", "syrup"),
    "hummus": ("hummus",),
    "pita": ("pita bread", "pita"),
    "carrots": ("carrots", "carrot"),
    "soup": ("soup",),
    "crackers": ("crackers", "cracker"),
    "popcorn": ("popcorn",),
    "sparkling_water": ("sparkling water", "seltzer"),
    "cookies": ("cookies", "cookie"),
    "apples": ("apples", "apple"),
    "juice": ("juice",),
    "yogurt": ("yogurt",),
    "coffee": ("coffee",),
    "rice": ("rice",),
    "tofu": ("tofu",),
    "frozen_vegetables": ("frozen vegetables", "frozen veggies"),
}


BUNDLES: Dict[str, List[Requirement]] = {
    "taco night": [
        Requirement("tortillas", 1),
        Requirement("beans", 2),
        Requirement("salsa", 1),
        Requirement("cheese", 1),
    ],
    "pancake breakfast": [
        Requirement("pancake_mix", 1),
        Requirement("syrup", 1),
        Requirement("eggs", 1),
        Requirement("milk", 1),
    ],
    "movie night": [
        Requirement("popcorn", 2),
        Requirement("sparkling_water", 1),
        Requirement("cookies", 1),
    ],
    "school lunches": [
        Requirement("bread", 1),
        Requirement("hummus", 1),
        Requirement("apples", 1),
        Requirement("juice", 1),
    ],
    "quick pasta dinner": [Requirement("pasta", 1), Requirement("pasta_sauce", 1)],
    "healthy breakfast": [
        Requirement("cereal", 1),
        Requirement("milk", 1),
        Requirement("banana", 4),
        Requirement("yogurt", 2),
    ],
    "vegan lunch": [
        Requirement("hummus", 1),
        Requirement("pita", 1),
        Requirement("carrots", 1),
    ],
    "easy stir-fry": [
        Requirement("rice", 1),
        Requirement("tofu", 1),
        Requirement("frozen_vegetables", 1),
    ],
}


NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "eight": 8,
    "ten": 10,
    "twelve": 12,
    "dozen": 12,
}


class IntentParser:
    def __init__(self, infer_bundles: bool = True):
        self.infer_bundles = infer_bundles

    def parse(self, instruction: str) -> ParsedIntent:
        text = instruction.lower().replace("-", " ")
        requirements: "OrderedDict[str, int]" = OrderedDict()

        for category, aliases in CATEGORY_ALIASES.items():
            match_alias = next((alias for alias in sorted(aliases, key=len, reverse=True) if alias in text), None)
            if match_alias:
                requirements[category] = self._quantity_before(text, match_alias)

        if self.infer_bundles:
            for phrase, bundle in BUNDLES.items():
                if phrase in text:
                    for item in bundle:
                        requirements.setdefault(item.category, item.quantity)

        budget_match = re.search(r"(?:under|within|budget(?: of)?|no more than)\s*\$\s*(\d+(?:\.\d+)?)", text)
        if not budget_match:
            budget_match = re.search(r"\$\s*(\d+(?:\.\d+)?)\s*(?:budget|limit)", text)
        budget = float(budget_match.group(1)) if budget_match else None

        required_tags = set()
        forbidden_tags = set()
        if "gluten free" in text:
            required_tags.add("gluten_free")
        if "dairy free" in text:
            required_tags.add("dairy_free")
        if "vegan" in text:
            required_tags.add("vegan")
        if "low sodium" in text:
            required_tags.add("low_sodium")
        if "all organic" in text or "everything organic" in text:
            required_tags.add("organic")
        if "nut free" in text or "peanut allergy" in text or "no nuts" in text:
            forbidden_tags.add("contains_nuts")

        preferred_brand = None
        brand_match = re.search(r"prefer(?: the)? ([a-z]+) brand", text)
        if brand_match:
            preferred_brand = brand_match.group(1).title()

        ambiguities = []
        if not requirements:
            ambiguities.append("No concrete grocery requirements could be inferred")
        if budget is None:
            ambiguities.append("No explicit budget")

        return ParsedIntent(
            requirements=[Requirement(category, quantity) for category, quantity in requirements.items()],
            budget=budget,
            required_tags=required_tags,
            forbidden_tags=forbidden_tags,
            preferred_brand=preferred_brand,
            ambiguities=ambiguities,
        )

    @staticmethod
    def _quantity_before(text: str, alias: str) -> int:
        index = text.find(alias)
        prefix = text[max(0, index - 28) : index]
        match = re.search(
            r"(?:^|\s)(\d+|a|an|one|two|three|four|five|six|eight|ten|twelve|dozen)\s+(?:[a-z]+\s+){0,2}$",
            prefix,
        )
        if not match:
            return 1
        token = match.group(1)
        return int(token) if token.isdigit() else NUMBER_WORDS[token]

