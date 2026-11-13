# Qualitative examples

## Success where ReAct failed

Scenario 13 (goal, H), variant `low`, run 1: **SUCCESS**, total 7505 cents, 32 tool calls, 5 model calls
Extracted intent: r1: Fresh fruit to cover the remaining 5 weekly portions (7 target minus 2 in pantry), allowing up to 4 extra portions [portions:fruit 5-9]; r2: Vegetables to cover 7 weekly portions, allowing up to 4 extra portions [portions:vegetable 7-11]; r3: Protein foods (eggs, beans, lentils, tofu, chicken) to cover the remaining 4 weekly portions (7 target minus 3 in pantry), allowing up to 4 extra portions [portions:protein 4-8]; r4: 7 protein snacks, each providing at least 10 g protein, at most 10 snacks total [portions:snack 7-10]; r5: Exactly 1 package of protein powder [units 1-1]; r6: Exactly 1 package of creatine [units 1-1]; budget=8000
```
 0 view_cart({}) -> ok: Current cart
 1 search_products({"query": "fresh fruit", "max_results": 15}) -> ok: 11 results
 2 search_products({"query": "fresh vegetables", "max_results": 15}) -> ok: 12 results
 3 search_products({"query": "eggs beans lentils tofu chicken", "max_results": 15}) -> ok: 10 results
 4 search_products({"query": "high protein snack", "max_results": 15}) -> ok: 9 results
 5 search_products({"query": "protein powder", "max_results": 15}) -> ok: 6 results
 6 search_products({"query": "creatine", "max_results": 15}) -> ok: 2 results
 7 get_product({"product_id": "oranges_fresh_each"}) -> ok: Product details
 8 get_product({"product_id": "berries_fresh_pint"}) -> ok: Product details
 9 get_product({"product_id": "broccoli_fresh_head"}) -> ok: Product details
10 get_product({"product_id": "frozen_veg_value"}) -> ok: Product details
11 get_product({"product_id": "bar_value_peanut"}) -> ok: Product details
12 get_product({"product_id": "bar_fresh_choc"}) -> ok: Product details
13 get_product({"product_id": "bar_pure_nutfree"}) -> ok: Product details
14 get_product({"product_id": "bar_fitcore_whey"}) -> ok: Product details
15 get_product({"product_id": "eggs_value_12"}) -> ok: Product details
16 get_product({"product_id": "tofu_fresh_firm"}) -> ok: Product details
17 get_product({"product_id": "beans_value_black"}) -> ok: Product details
18 get_product({"product_id": "lentils_value"}) -> ok: Product details
19 get_product({"product_id": "protein_powder_fitcore"}) -> ok: Product details
20 get_product({"product_id": "creatine_fitcore"}) -> ok: Product details
21 get_product({"product_id": "trail_mix_value"}) -> ok: Product details
22 get_product({"product_id": "yogurt_fresh_greek"}) -> ok: Product details
23 add_to_cart({"product_id": "protein_powder_fitcore", "quantity": 1}) -> ok: Added 1 x protein_powder_fitcore
24 add_to_cart({"product_id": "creatine_value", "quantity": 1}) -> ok: Added 1 x creatine_value
25 add_to_cart({"product_id": "berries_fresh_pint", "quantity": 2}) -> ok: Added 2 x berries_fresh_pint
26 add_to_cart({"product_id": "frozen_veg_value", "quantity": 2}) -> ok: Added 2 x frozen_veg_value
27 add_to_cart({"product_id": "tofu_fresh_firm", "quantity": 1}) -> ok: Added 1 x tofu_fresh_firm
28 add_to_cart({"product_id": "beans_value_black", "quantity": 1}) -> ok: Added 1 x beans_value_black
29 add_to_cart({"product_id": "bar_value_peanut", "quantity": 7}) -> ok: Added 7 x bar_value_peanut
30 get_product({"product_id": "creatine_value"}) -> ok: Product details
31 finish({"message": "intent-grounded agent done"}) -> ok: Episode finished
```
Verifier round 1: no violations

ReAct on the same instance:

Scenario 13 (goal, H), variant `low`, run 1: **FAIL**, total 7926 cents, 30 tool calls, 6 model calls
```
 0 view_cart({}) -> ok: Current cart
 1 view_cart({}) -> ok: Current cart
 2 search_products({"query": "protein powder FitCore", "max_results": 10}) -> ok: 7 results
 3 search_products({"query": "creatine FitCore", "max_results": 10}) -> ok: 4 results
 4 search_products({"query": "FreshPick fruit", "max_results": 15}) -> ok: 11 results
 5 search_products({"query": "FreshPick vegetables", "max_results": 15}) -> ok: 12 results
 6 search_products({"query": "protein eggs beans lentils tofu chicken", "max_results": 20}) -> ok: 16 results
 7 search_products({"query": "protein bar snack", "max_results": 20}) -> ok: 9 results
 8 get_product({"product_id": "oranges_fresh_each"}) -> ok: Product details
 9 get_product({"product_id": "berries_fresh_pint"}) -> ok: Product details
10 get_product({"product_id": "broccoli_fresh_head"}) -> ok: Product details
11 get_product({"product_id": "frozen_veg_value"}) -> ok: Product details
12 get_product({"product_id": "eggs_value_12"}) -> ok: Product details
13 get_product({"product_id": "lentils_value"}) -> ok: Product details
14 get_product({"product_id": "beans_value_black"}) -> ok: Product details
15 get_product({"product_id": "tofu_fresh_firm"}) -> ok: Product details
16 get_product({"product_id": "bar_fresh_choc"}) -> ok: Product details
17 get_product({"product_id": "bar_value_peanut"}) -> ok: Product details
18 get_product({"product_id": "bar_pure_nutfree"}) -> ok: Product details
19 get_product({"product_id": "bar_fitcore_whey"}) -> ok: Product details
20 get_product({"product_id": "protein_powder_fitcore"}) -> ok: Product details
21 get_product({"product_id": "creatine_fitcore"}) -> ok: Product details
22 add_to_cart({"product_id": "protein_powder_fitcore", "quantity": 1}) -> ok: Added 1 x protein_powder_fitcore
23 add_to_cart({"product_id": "creatine_fitcore", "quantity": 1}) -> ok: Added 1 x creatine_fitcore
24 add_to_cart({"product_id": "berries_fresh_pint", "quantity": 1}) -> ok: Added 1 x berries_fresh_pint
... (5 more steps)
```
Failed predicates: need:fruit (portions:fruit=3, required [5, 9])

## Failures
