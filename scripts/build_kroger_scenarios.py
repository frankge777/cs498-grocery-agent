#!/usr/bin/env python3
"""Build the fixed real-Kroger benchmark tasks from curated snapshot UPCs.

The selections below are intentionally explicit.  Every UPC, price, package
size, stock flag, dietary declaration, and protein value is validated against
the frozen Kroger snapshot by ``tests/test_kroger_benchmark.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmark" / "scenarios_kroger.json"


def need(identifier, description, product_ids, measure="units", minimum=1, maximum=1, **selector):
    return {
        "id": identifier,
        "desc": description,
        "select": {"product_ids": product_ids, **selector},
        "measure": measure,
        "min": minimum,
        "max": maximum,
    }


def scenario(identifier, category, difficulty, title, high, medium, low, needs, references, **extra):
    return {
        "id": identifier,
        "category": category,
        "difficulty": difficulty,
        "title": title,
        "variants": {"high": high, "medium": medium, "low": low},
        "context": extra.pop("context", {}),
        **extra,
        "needs": needs,
        "reference_carts": references,
    }


# UPC aliases keep the task definitions readable while preserving the exact
# Kroger identifiers in the generated JSON.
WHOLE_GALLON = "0001111040101"
WHOLE_HALF = "0001111040601"
SOY_ORIGINAL = "0001111009431"
SOY_VANILLA = "0001111009433"
OAT_ORIGINAL = "0004410015618"
OAT_CREAMY = "0004410015619"
OAT_UNSWEETENED = "0004410019080"
OAT_BARISTA = "0004410019092"
OATLY_CHURROS = "0019064663242"
BREAD_WHEAT = "0001111008450"
BREAD_WHITE = "0001111008485"
EGGS_24 = "0001111015097"
EGGS_12 = "0001111060903"
EGGS_6 = "0001111060906"
ORANGE = "0000000003107"
ORANGE_ORGANIC = "0000000093107"
RICE_BASMATI = "0001111015342"
RICE_JASMINE_POUCH = "0001111001950"
PASTA_DITALINI = "0001111011693"
PASTA_PENNE = "0001111085033"
OATS_ORGANIC = "0001111002805"
OATS_PROTEIN = "0001111001177"
FLOUR = "0001111085401"
SUGAR = "0001111011888"
SUGAR_ORGANIC = "0001111084930"
BEANS = "0001111072567"
BEANS_NO_SALT = "0001111012209"
TOFU = "0001111091342"
SPINACH = "0001111008631"
CARROTS = "0001111091620"
TORTILLAS = "0001111005265"
SALSA = "0001111002269"
SALSA_ALT = "0001111066759"
CHEESE = "0001111050170"
CHEESE_ALT = "0001111050159"
CHEESE_MEXICAN = "0001111050204"
BAR_KROGER = "0001111011125"
BAR_PURE = "0074982600016"
YOGURT = "0003663201953"
PROTEIN_POWDER = "0085177000392"
CREATINE = "0074892707339"
GF_SPAGHETTI = "0001111013338"
GF_PENNE = "0001111013339"
GF_ROTINI = "0001111013340"
TOMATO_SAUCE_GF = "0001111011969"
SAUCE_MARINARA = "0001111013416"
SAUCE_TOMATO_BASIL = "0001111013414"
COFFEE_BREAKFAST = "0001111010738"
COFFEE_COLOMBIAN = "0001111010741"

DAIRY_NUT_FREE_OAT_OR_SOY_MILKS = [
    OAT_ORIGINAL,
    OAT_CREAMY,
    OAT_UNSWEETENED,
    OAT_BARISTA,
    OATLY_CHURROS,
    SOY_VANILLA,
]


SCENARIOS = [
    scenario(
        "K01", "explicit", "E", "Two named half-gallon milk cartons",
        "Add exactly two Kroger Vitamin D Whole Milk Half Gallon cartons, nothing else.",
        "Get two half-gallons of the Kroger whole milk.",
        "Get two of my usual half-gallon milk.",
        [need("milk", "two named half-gallon cartons", [WHOLE_HALF], minimum=2, maximum=2)],
        [{WHOLE_HALF: 2}],
        context={"usual_milk": "Kroger Vitamin D Whole Milk Half Gallon"},
    ),
    scenario(
        "K02", "explicit", "E", "Bread, eggs, and four oranges",
        "Buy exactly one Kroger White Bread, twelve Kroger large white eggs, and four medium navel oranges.",
        "Get one Kroger white loaf, a dozen large white eggs, and four medium navel oranges.",
        "Pick up the three items and quantities on my weekly list.",
        [
            need("bread", "one Kroger white bread", [BREAD_WHITE]),
            need("eggs", "twelve eggs", [EGGS_12, EGGS_6], "count", 12, 12),
            need("oranges", "four oranges", [ORANGE], minimum=4, maximum=4),
        ],
        [{BREAD_WHITE: 1, EGGS_12: 1, ORANGE: 4}, {BREAD_WHITE: 1, EGGS_6: 2, ORANGE: 4}],
        context={"weekly_list": ["1 Kroger White Bread", "12 Kroger large white eggs", "4 medium navel oranges"]},
    ),
    scenario(
        "K03", "explicit", "E", "Exactly twenty-four eggs",
        "Buy exactly 24 large eggs. Either one 24-count Simple Truth carton or two 12-count Kroger cartons is acceptable.",
        "Get two dozen large eggs using the available carton sizes.",
        "Get the eggs needed for my two-dozen recipe.",
        [need("eggs", "exactly twenty-four eggs", [EGGS_24, EGGS_12], "count", 24, 24)],
        [{EGGS_24: 1}, {EGGS_12: 2}],
        context={"recipe": "Needs exactly 24 large eggs; no extra eggs."},
    ),
    scenario(
        "K04", "explicit", "E", "Five named pantry staples",
        "Add one package each of Kroger Basmati Rice, Kroger Penne Rigate Pasta, Simple Truth Organic Rolled Oats, Kroger 2 lb All Purpose Flour, and Smart Way 4 lb Granulated Sugar.",
        "Get one each of the named rice, penne, oats, flour, and sugar from my list.",
        "Restock every item on my pantry list once.",
        [
            need("rice", "one named rice", [RICE_BASMATI]),
            need("pasta", "one named pasta", [PASTA_PENNE]),
            need("oats", "one named oats", [OATS_ORGANIC]),
            need("flour", "one named flour", [FLOUR]),
            need("sugar", "one named sugar", [SUGAR]),
        ],
        [{RICE_BASMATI: 1, PASTA_PENNE: 1, OATS_ORGANIC: 1, FLOUR: 1, SUGAR: 1}],
        context={"pantry_list": ["Kroger Basmati Rice", "Kroger Penne Rigate", "Simple Truth Organic Rolled Oats", "Kroger 2 lb All Purpose Flour", "Smart Way 4 lb Granulated Sugar"]},
    ),
    scenario(
        "K05", "explicit", "M", "Correct a prefilled cart",
        "Fix my cart so it has one Planet Oat Original Oat Milk, one Kroger White Bread, and twelve Kroger large white eggs. Remove everything else.",
        "Replace the whole milk with Planet Oat Original, reduce the white bread to one, add a dozen Kroger eggs, and remove the sugar.",
        "Make the current cart match my corrected list.",
        [
            need("oat_milk", "one Planet Oat Original", [OAT_ORIGINAL]),
            need("bread", "one Kroger white bread", [BREAD_WHITE]),
            need("eggs", "twelve Kroger eggs", [EGGS_12], "count", 12, 12),
        ],
        [{OAT_ORIGINAL: 1, BREAD_WHITE: 1, EGGS_12: 1}],
        initial_cart={WHOLE_HALF: 1, BREAD_WHITE: 2, SUGAR: 1},
        context={"corrected_list": ["1 Planet Oat Original Oat Milk", "1 Kroger White Bread", "12 Kroger large white eggs"]},
    ),
    scenario(
        "K06", "constrained", "M", "Breakfast basics under ten dollars",
        "Buy one package of rolled oats, one half-gallon whole milk, twelve eggs, and one loaf of bread for at most $10.00.",
        "Get oats, a half-gallon of whole milk, a dozen eggs, and bread; keep the total under ten dollars.",
        "Restock my breakfast basics within my $10 budget.",
        [
            need("oats", "one oats", [OATS_ORGANIC, OATS_PROTEIN]),
            need("milk", "one half-gallon whole milk", [WHOLE_HALF]),
            need("eggs", "twelve eggs", [EGGS_12, EGGS_6], "count", 12, 12),
            need("bread", "one bread", [BREAD_WHEAT, BREAD_WHITE]),
        ],
        [{OATS_ORGANIC: 1, WHOLE_HALF: 1, EGGS_12: 1, BREAD_WHITE: 1}],
        budget_cents=1000,
        context={"breakfast_list": ["rolled oats", "half-gallon whole milk", "12 eggs", "bread"], "budget": "$10.00"},
    ),
    scenario(
        "K07", "constrained", "M", "Explicitly organic and vegan basket",
        "Buy one Simple Truth Organic Rolled Oats, one Simple Truth Organic Extra Firm Tofu, and one Simple Truth Organic Cane Sugar. Every item must be explicitly labeled organic and vegan. Spend at most $8.50.",
        "Get the named oats, tofu, and cane sugar; organic and vegan labels are required, with an $8.50 cap.",
        "Get the three items on my organic vegan list within its budget.",
        [need("oats", "one organic vegan oats", [OATS_ORGANIC]), need("tofu", "one organic vegan tofu", [TOFU]), need("sugar", "one organic vegan sugar", [SUGAR_ORGANIC])],
        [{OATS_ORGANIC: 1, TOFU: 1, SUGAR_ORGANIC: 1}],
        budget_cents=850,
        hard=[{"type": "all_items", "select": {"tags_all": ["organic", "vegan"]}}],
        context={"dietary_rule": "Every purchased product must explicitly say Organic and Vegan.", "budget": "$8.50"},
    ),
    scenario(
        "K08", "constrained", "M", "Breakfast basket with an organic-oats preference",
        "Buy rolled oats, a half-gallon whole milk, twelve eggs, and bread for at most $12.00. Prefer organic oats if the budget allows.",
        "Get my four breakfast basics under $12, choosing organic oats when possible.",
        "Restock breakfast within budget and honor my oats preference if possible.",
        [
            need("oats", "one oats", [OATS_ORGANIC, OATS_PROTEIN]),
            need("milk", "one milk", [WHOLE_HALF]),
            need("eggs", "twelve eggs", [EGGS_12, EGGS_6], "count", 12, 12),
            need("bread", "one bread", [BREAD_WHEAT, BREAD_WHITE]),
        ],
        [{OATS_ORGANIC: 1, WHOLE_HALF: 1, EGGS_12: 1, BREAD_WHITE: 1}, {OATS_PROTEIN: 1, WHOLE_HALF: 1, EGGS_12: 1, BREAD_WHEAT: 1}],
        budget_cents=1200,
        preferences=[{"id": "organic_oats", "weight": 1, "scope": {"product_ids": [OATS_ORGANIC, OATS_PROTEIN]}, "prefer": {"tags_all": ["organic"]}}],
        context={"breakfast_list": ["rolled oats", "half-gallon whole milk", "12 eggs", "bread"], "preference": "Organic oats preferred", "budget": "$12.00"},
    ),
    scenario(
        "K09", "constrained", "M", "Four to six verified high-protein bars",
        "Buy 4 to 6 protein bars total. Every selected bar must be explicitly gluten-free and list at least 10 g protein per labeled serving. Spend at most $8.00.",
        "Get 4-6 gluten-free bars with at least 10 g protein per serving, under $8.",
        "Get the verified protein bars for my trip within the snack budget.",
        [need("bars", "four to six qualifying bars", [BAR_KROGER, BAR_PURE], "count", 4, 6, tags_all=["gluten_free"], min_protein_g=10)],
        [{BAR_KROGER: 1}, {BAR_PURE: 1}],
        budget_cents=800,
        context={"trip_snacks": "4-6 bars; each product must explicitly be gluten-free and show at least 10 g protein per labeled serving.", "budget": "$8.00"},
    ),
    scenario(
        "K10", "constrained", "H", "Taco-night basket at a tight budget",
        "Buy one package of Kroger soft taco tortillas, exactly two cans of black beans, one Kroger mild salsa, and one 8 oz bag of Kroger shredded cheese. Spend at most $8.00.",
        "Get tortillas, two black-bean cans, mild salsa, and an 8 oz shredded cheese for taco night, under $8.",
        "Get my taco-night list without going over the saved budget.",
        [need("tortillas", "one tortillas", [TORTILLAS]), need("beans", "two bean cans", [BEANS, BEANS_NO_SALT], minimum=2, maximum=2), need("salsa", "one salsa", [SALSA, SALSA_ALT]), need("cheese", "one cheese", [CHEESE, CHEESE_ALT, CHEESE_MEXICAN])],
        [{TORTILLAS: 1, BEANS: 2, SALSA: 1, CHEESE: 1}, {TORTILLAS: 1, BEANS: 2, SALSA_ALT: 1, CHEESE_MEXICAN: 1}],
        budget_cents=800,
        context={"taco_list": ["1 Kroger soft taco tortillas", "2 black bean cans", "1 Kroger mild salsa", "1 Kroger 8 oz shredded cheese"], "budget": "$8.00"},
    ),
    scenario(
        "K11", "goal", "M", "Three-day breakfast restock",
        "For three breakfast days, buy one Simple Truth Organic Rolled Oats, one Kroger Whole Milk Half Gallon, and three medium navel oranges. Spend no more than $9.00.",
        "Set up three breakfasts with the saved oats, milk, and one orange per day, under $9.",
        "Restock the items in my three-day breakfast plan within its budget.",
        [need("oats", "one oats", [OATS_ORGANIC]), need("milk", "one milk", [WHOLE_HALF]), need("oranges", "three oranges", [ORANGE], minimum=3, maximum=3)],
        [{OATS_ORGANIC: 1, WHOLE_HALF: 1, ORANGE: 3}],
        budget_cents=900,
        context={"three_day_plan": ["1 package Simple Truth Organic Rolled Oats", "1 Kroger Whole Milk Half Gallon", "3 medium navel oranges"], "budget": "$9.00"},
    ),
    scenario(
        "K12", "goal", "H", "Vegan dinner-prep components",
        "Buy one package each of Simple Truth Extra Firm Tofu, Kroger 90 Second Jasmine Rice, and Kroger Leaf Spinach. Every item must be explicitly labeled vegan. Spend at most $5.00.",
        "Get tofu, a rice pouch, and spinach for dinner prep; verified vegan only, $5 max.",
        "Complete my vegan dinner-prep list within the saved budget.",
        [need("tofu", "one tofu", [TOFU]), need("rice", "one rice", [RICE_JASMINE_POUCH]), need("spinach", "one spinach", [SPINACH])],
        [{TOFU: 1, RICE_JASMINE_POUCH: 1, SPINACH: 1}],
        budget_cents=500,
        hard=[{"type": "all_items", "select": {"tags_all": ["vegan"]}}],
        context={"prep_list": ["Simple Truth Extra Firm Tofu", "Kroger 90 Second Jasmine Rice", "Kroger Leaf Spinach"], "rule": "Every purchased item must explicitly say Vegan.", "budget": "$5.00"},
    ),
    scenario(
        "K13", "goal", "H", "Fitness restock using labeled protein",
        "Restock one Orgain Organic Vegan Protein Powder, one Optimum Nutrition Creatine Stick Pack box, exactly four gluten-free protein bars with at least 20 g protein per labeled serving, and one four-count Oikos high-protein yogurt. Spend at most $50.00.",
        "Get my powder, creatine, four qualifying 20 g gluten-free bars, and the four-pack Oikos yogurt within $50.",
        "Complete my saved fitness restock without exceeding its budget.",
        [need("powder", "one named protein powder", [PROTEIN_POWDER]), need("creatine", "one named creatine", [CREATINE]), need("bars", "exactly four qualifying bars", [BAR_PURE], "count", 4, 4, tags_all=["gluten_free"], min_protein_g=20), need("yogurt", "one named yogurt four-pack", [YOGURT])],
        [{PROTEIN_POWDER: 1, CREATINE: 1, BAR_PURE: 1, YOGURT: 1}],
        budget_cents=5000,
        context={"fitness_list": ["Orgain Organic Vegan 21g Protein Powder", "Optimum Nutrition Creatine Stick Packs", "4 gluten-free bars with >=20g protein per labeled serving", "Oikos Triple Zero high-protein yogurt 4-pack"], "budget": "$50.00"},
    ),
    scenario(
        "K14", "goal", "M", "Restock pantry to target levels",
        "Restock exactly one rice, two pasta packages, one oats, three black-bean cans, and one flour package from my approved products. Spend at most $15.00.",
        "Top up the pantry to the target levels in my sheet, $15 maximum.",
        "Restock the pantry according to current and target stock.",
        [need("rice", "one rice", [RICE_BASMATI]), need("pasta", "two pasta", [PASTA_DITALINI, PASTA_PENNE], minimum=2, maximum=2), need("oats", "one oats", [OATS_ORGANIC]), need("beans", "three beans", [BEANS, BEANS_NO_SALT], minimum=3, maximum=3), need("flour", "one flour", [FLOUR])],
        [{RICE_BASMATI: 1, PASTA_PENNE: 2, OATS_ORGANIC: 1, BEANS: 3, FLOUR: 1}],
        budget_cents=1500,
        context={"pantry_sheet": [{"item": "Kroger Basmati Rice", "have": 1, "target": 2}, {"item": "approved Kroger pasta", "have": 0, "target": 2}, {"item": "Simple Truth Organic Rolled Oats", "have": 1, "target": 2}, {"item": "approved black-bean cans", "have": 1, "target": 4}, {"item": "Kroger 2 lb All Purpose Flour", "have": 0, "target": 1}], "rule": "Buy only the difference between have and target.", "budget": "$15.00"},
    ),
    scenario(
        "K15", "goal", "H", "Clarify an unstated milk restriction",
        "Add one carton of milk. A household restriction is not written down, so ask about it before choosing.",
        "Get one milk that works with our unstated dietary restriction; ask first.",
        "Grab milk for the household.",
        [need("milk", "one dairy-free nut-free milk", DAIRY_NUT_FREE_OAT_OR_SOY_MILKS, tags_all=["dairy_free", "nut_free"])],
        [{OAT_ORIGINAL: 1}, {OAT_CREAMY: 1}, {SOY_VANILLA: 1}, {OAT_UNSWEETENED: 1}],
        clarification=[{"id": "milk_restriction", "status": "required", "keywords": ["milk", "dairy", "nut", "allerg", "restriction", "diet"], "answer": "Choose exactly one product explicitly labeled both dairy-free and nut-free. Oat or soy is fine."}],
        interactions=[{"type": "clarify_before_add", "topic": "milk_restriction", "select": {"product_ids": DAIRY_NUT_FREE_OAT_OR_SOY_MILKS + [WHOLE_HALF, SOY_ORIGINAL]}}],
        context={"household_note": "A milk-related dietary restriction is missing from this note. Ask before selecting.", "quantity": "one carton"},
    ),
    scenario(
        "K16", "recovery", "M", "Substitute an unavailable oat milk",
        "Buy one Planet Oat Dairy Free Original Oat Milk. If it becomes unavailable, substitute one other milk explicitly labeled dairy-free and nut-free.",
        "Get Planet Oat Original, or another dairy-free nut-free carton if it is out.",
        "Get my usual milk and use the saved substitution rule if needed.",
        [need("milk", "one qualifying milk", DAIRY_NUT_FREE_OAT_OR_SOY_MILKS, tags_all=["dairy_free", "nut_free"])],
        [{OAT_CREAMY: 1}, {SOY_VANILLA: 1}, {OAT_UNSWEETENED: 1}],
        events=[{"product_id": OAT_ORIGINAL, "trigger": "first_attempt"}],
        context={"usual_milk": "Planet Oat Dairy Free Original Oat Milk", "substitution_rule": "One other product explicitly labeled dairy-free and nut-free."},
    ),
    scenario(
        "K17", "recovery", "H", "Replace unavailable gluten-free spaghetti",
        "Buy exactly 680 g of gluten-free pasta using two 340 g packages, plus one Kroger No Salt Added Tomato Sauce. Try Kroger Gluten Free Spaghetti first; if unavailable, use another approved gluten-free Kroger pasta. Spend at most $7.00.",
        "Get two 340 g gluten-free Kroger pastas and the no-salt tomato sauce, $7 max; substitute the pasta shape if needed.",
        "Get my saved gluten-free pasta-night list and recover from stock problems.",
        [need("pasta", "exactly 680 g gluten-free pasta", [GF_SPAGHETTI, GF_PENNE, GF_ROTINI], "weight_g", 680, 680, tags_all=["gluten_free"]), need("sauce", "one named gluten-free tomato sauce", [TOMATO_SAUCE_GF], tags_all=["gluten_free"])],
        [{GF_PENNE: 2, TOMATO_SAUCE_GF: 1}, {GF_ROTINI: 2, TOMATO_SAUCE_GF: 1}],
        events=[{"product_id": GF_SPAGHETTI, "trigger": "first_attempt"}],
        budget_cents=700,
        context={"pasta_night": "680 g total from two 340 g packages of explicitly gluten-free Kroger pasta, plus one Kroger No Salt Added Tomato Sauce.", "preferred": "Kroger Gluten Free Spaghetti", "budget": "$7.00"},
    ),
    scenario(
        "K18", "recovery", "H", "Recover taco night after cheese stock failure",
        "Buy Kroger soft taco tortillas, exactly two black-bean cans, Kroger mild salsa, and one 8 oz Kroger shredded cheese for at most $8.00. If the mild cheddar is unavailable, substitute another approved 8 oz Kroger shredded cheese.",
        "Get the taco-night list under $8 and replace the cheese if it goes out of stock.",
        "Finish my taco-night basket using the saved substitutions and budget.",
        [need("tortillas", "one tortillas", [TORTILLAS]), need("beans", "two beans", [BEANS, BEANS_NO_SALT], minimum=2, maximum=2), need("salsa", "one salsa", [SALSA]), need("cheese", "one cheese", [CHEESE, CHEESE_ALT])],
        [{TORTILLAS: 1, BEANS: 2, SALSA: 1, CHEESE_ALT: 1}],
        events=[{"product_id": CHEESE, "trigger": "first_attempt"}],
        budget_cents=800,
        context={"taco_list": ["Kroger soft taco tortillas", "2 black bean cans", "Kroger mild salsa", "Kroger 8 oz shredded cheese"], "preferred_cheese": "Kroger Mild Cheddar 8 oz", "substitution": "Kroger Mozzarella 8 oz is approved", "budget": "$8.00"},
    ),
    scenario(
        "K19", "recovery", "H", "Replace unavailable preferred coffee",
        "Buy one 11 oz Kroger Breakfast Blend Ground Coffee and one Planet Oat Original Oat Milk for at most $10.00. If the coffee is unavailable, use the approved 11 oz Kroger Colombian Ground Coffee.",
        "Get the breakfast-blend coffee and Planet Oat milk under $10; use the approved Colombian coffee if needed.",
        "Get my coffee supplies within the saved budget and substitution rule.",
        [need("coffee", "one approved coffee", [COFFEE_BREAKFAST, COFFEE_COLOMBIAN]), need("milk", "one Planet Oat Original", [OAT_ORIGINAL])],
        [{COFFEE_COLOMBIAN: 1, OAT_ORIGINAL: 1}],
        events=[{"product_id": COFFEE_BREAKFAST, "trigger": "first_attempt"}],
        budget_cents=1000,
        context={"coffee_supplies": ["Kroger Breakfast Blend Ground Coffee 11 oz", "Planet Oat Original Oat Milk"], "coffee_substitute": "Kroger Colombian Ground Coffee 11 oz", "budget": "$10.00"},
    ),
    scenario(
        "K20", "recovery", "H", "Preserve cart through two stock failures",
        "Keep the eggs and bread already in my cart. Add one Kroger pasta, one Kroger pasta sauce, and one bag of Kroger carrots. Spend at most $8.00 total and substitute approved alternatives if items become unavailable.",
        "Do not change the existing eggs or bread; add pasta, sauce, and carrots under $8, recovering from stock failures.",
        "Finish my dinner order without changing the current cart.",
        [need("eggs", "existing eggs", [EGGS_12]), need("bread", "existing bread", [BREAD_WHEAT]), need("pasta", "one approved pasta", [PASTA_PENNE, PASTA_DITALINI]), need("sauce", "one approved sauce", [SAUCE_MARINARA, SAUCE_TOMATO_BASIL]), need("carrots", "one carrots", [CARROTS])],
        [{EGGS_12: 1, BREAD_WHEAT: 1, PASTA_DITALINI: 1, SAUCE_TOMATO_BASIL: 1, CARROTS: 1}],
        initial_cart={EGGS_12: 1, BREAD_WHEAT: 1},
        events=[{"product_id": PASTA_PENNE, "trigger": "first_attempt"}, {"product_id": SAUCE_MARINARA, "trigger": "first_attempt"}],
        budget_cents=800,
        hard=[{"type": "preserve_initial"}],
        context={"keep": "Everything currently in the cart", "add": ["1 approved Kroger pasta", "1 approved Kroger pasta sauce", "1 Kroger carrot bag"], "substitutions": {"pasta": "Kroger Ditalini", "sauce": "Kroger Tomato Basil"}, "budget": "$8.00 total"},
    ),
]


def main() -> None:
    payload = {
        "version": "1.0.0-kroger-snapshot",
        "catalog": "kroger_snapshots/02100946-20261116.json",
        "notes": (
            "Twenty fixed tasks backed by the Kroger - Mt Zion snapshot retrieved on 2026-11-16. "
            "Product selectors use real Kroger UPCs. Dietary and protein constraints require explicit API metadata; "
            "unknown values never satisfy a constraint. Hidden acceptance predicates are not exposed to agents."
        ),
        "scenarios": SCENARIOS,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(SCENARIOS)} scenarios to {OUTPUT}")


if __name__ == "__main__":
    main()
