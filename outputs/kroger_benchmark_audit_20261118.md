# Kroger Benchmark Acceptance Audit — 2026-11-18

- Scenario version: `1.1.1-kroger-snapshot-audited`
- Catalog SHA-256: `2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`
- Scenario SHA-256: `590c01667f938ab7e3509da03539b94e548906fa1da99e128af37272cfa3442e`
- Catalog products: 722
- Scenarios: 20
- Reference-cart replays passed: 102/102

## Audit policy

Exact named products may use a narrow UPC set only when brand/type/size are visible to the agent. Attribute-defined requests must include every in-stock snapshot product satisfying the stated product type, package/count rule, explicit tags, and labeled protein threshold. Budget is scored independently and is never used to disguise an otherwise qualifying product as an invalid type. Unknown metadata never satisfies a required attribute.

## Exhaustive attribute-set checks

- PASS — K09 qualifying bars: 7 qualifying UPCs
- PASS — K13 qualifying bars: 3 qualifying UPCs
- PASS — K10 mild salsa: 2 qualifying UPCs
- PASS — K18 mild salsa: 2 qualifying UPCs
- PASS — K10 8 oz shredded cheese: 10 qualifying UPCs
- PASS — K15 dairy/nut-free oat or soy milk: 6 qualifying UPCs
- PASS — K16 dairy/nut-free oat or soy milk: 6 qualifying UPCs

## Scenario-by-scenario audit

### K01 — Two named half-gallon milk cartons

Public high-explicitness request: Add exactly two Kroger Vitamin D Whole Milk Half Gallon cartons, nothing else.

Public medium-explicitness request: Get two half-gallons of the Kroger whole milk.

Public low-explicitness request: Get two of my usual half-gallon milk.

Public context: `{"usual_milk": "Kroger Vitamin D Whole Milk Half Gallon"}`

Decision: Exact named Kroger half-gallon milk; one UPC is intentionally accepted.

- Need `milk`: units in [2, 2], selector `{"product_ids": ["0001111040601"]}`
  - `0001111040601` — Kroger® Vitamin D Whole Milk Half Gallon; $1.69; 1/2 gal; tags=kosher
- Reference cart 1: $3.38; `{"0001111040601": 2}`

### K02 — Bread, eggs, and four oranges

Public high-explicitness request: Buy exactly one Kroger White Bread, twelve Kroger large white eggs, and four medium navel oranges.

Public medium-explicitness request: Get one Kroger white loaf, a dozen large white eggs, and four medium navel oranges.

Public low-explicitness request: Pick up the three items and quantities on my weekly list.

Public context: `{"weekly_list": ["1 Kroger White Bread", "12 Kroger large white eggs", "4 medium navel oranges"]}`

Decision: Public list names Kroger White Bread, Kroger large white eggs, and medium navel oranges; accepted package sizes produce the exact requested counts.

- Need `bread`: units in [1, 1], selector `{"product_ids": ["0001111008485"]}`
  - `0001111008485` — Kroger® White Bread; $1.79; 20 oz; tags=vegan
- Need `eggs`: count in [12, 12], selector `{"product_ids": ["0001111060903", "0001111060906"]}`
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
  - `0001111060906` — Kroger® Grade A Large White Eggs; $0.97; 6 ct; tags=none
- Need `oranges`: units in [4, 4], selector `{"product_ids": ["0000000003107"]}`
  - `0000000003107` — Medium Fresh Navel Oranges- Each; $1.19; 1 each; tags=none
- Reference cart 1: $8.04; `{"0000000003107": 4, "0001111008485": 1, "0001111060903": 1}`
- Reference cart 2: $8.49; `{"0000000003107": 4, "0001111008485": 1, "0001111060906": 2}`

### K03 — Exactly twenty-four eggs

Public high-explicitness request: Buy exactly 24 large eggs. Either one 24-count Simple Truth carton or two 12-count Kroger cartons is acceptable.

Public medium-explicitness request: Get two dozen large eggs using the available carton sizes.

Public low-explicitness request: Get the eggs needed for my two-dozen recipe.

Public context: `{"recipe": "Needs exactly 24 large eggs; no extra eggs."}`

Decision: The two public alternatives (one 24-count Simple Truth or two 12-count Kroger cartons) exactly match the hidden set.

- Need `eggs`: count in [24, 24], selector `{"product_ids": ["0001111015097", "0001111060903"]}`
  - `0001111015097` — Simple Truth® Cage Free Grade A Large Brown Eggs; $4.99; 24 ct; tags=none
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
- Reference cart 1: $4.99; `{"0001111015097": 1}`
- Reference cart 2: $2.98; `{"0001111060903": 2}`

### K04 — Five named pantry staples

Public high-explicitness request: Add one package each of Kroger Basmati Rice, Kroger Penne Rigate Pasta, Simple Truth Organic Rolled Oats, Kroger 2 lb All Purpose Flour, and Smart Way 4 lb Granulated Sugar.

Public medium-explicitness request: Get one each of the named rice, penne, oats, flour, and sugar from my list.

Public low-explicitness request: Restock every item on my pantry list once.

Public context: `{"pantry_list": ["Kroger Basmati Rice", "Kroger Penne Rigate", "Simple Truth Organic Rolled Oats", "Kroger 2 lb All Purpose Flour", "Smart Way 4 lb Granulated Sugar"]}`

Decision: All five products are named with brand/type/size in the public list.

- Need `rice`: units in [1, 1], selector `{"product_ids": ["0001111015342"]}`
  - `0001111015342` — Kroger® Basmati Rice; $3.99; 2 lb; tags=gluten_free,non_gmo
- Need `pasta`: units in [1, 1], selector `{"product_ids": ["0001111085033"]}`
  - `0001111085033` — Kroger® Penne Rigate Pasta; $1.00; 16 oz; tags=kosher,non_gmo
- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
- Need `flour`: units in [1, 1], selector `{"product_ids": ["0001111085401"]}`
  - `0001111085401` — Kroger® All Purpose Bleached Enriched Flour; $1.59; 2 lbs; tags=vegan
- Need `sugar`: units in [1, 1], selector `{"product_ids": ["0001111011888"]}`
  - `0001111011888` — Smart Way™ Granulated Sugar; $2.79; 4 lb; tags=dairy_free,egg_free,fish_free,gluten_free,nut_free,peanut_free,soy_free,tree_nut_free
- Reference cart 1: $13.06; `{"0001111002805": 1, "0001111011888": 1, "0001111015342": 1, "0001111085033": 1, "0001111085401": 1}`

### K05 — Correct a prefilled cart

Public high-explicitness request: Fix my cart so it has one 52 fl oz Planet Oat Dairy Free Original Oat Milk, one Kroger White Bread, and twelve Kroger large white eggs. Remove everything else.

Public medium-explicitness request: Replace the whole milk with the 52 fl oz Planet Oat Original, reduce the white bread to one, add a dozen Kroger eggs, and remove the sugar.

Public low-explicitness request: Make the current cart match my corrected list.

Public context: `{"corrected_list": ["1 Planet Oat Dairy Free Original Oat Milk 52 fl oz", "1 Kroger White Bread", "12 Kroger large white eggs"]}`

Decision: The corrected list now names the 52 fl oz Planet Oat product, removing ambiguity with shelf-stable Original variants.

- Need `oat_milk`: units in [1, 1], selector `{"product_ids": ["0004410015618"]}`
  - `0004410015618` — Planet Oat Dairy Free Original Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
- Need `bread`: units in [1, 1], selector `{"product_ids": ["0001111008485"]}`
  - `0001111008485` — Kroger® White Bread; $1.79; 20 oz; tags=vegan
- Need `eggs`: count in [12, 12], selector `{"product_ids": ["0001111060903"]}`
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
- Reference cart 1: $6.97; `{"0001111008485": 1, "0001111060903": 1, "0004410015618": 1}`

### K06 — Breakfast basics under ten dollars

Public high-explicitness request: Buy one of my approved Simple Truth rolled oats, one Kroger half-gallon whole milk, twelve Kroger large white eggs, and one Kroger white or wheat bread for at most $10.00.

Public medium-explicitness request: Get one approved oats, Kroger half-gallon whole milk, a dozen Kroger large white eggs, and one approved Kroger bread; keep the total under ten dollars.

Public low-explicitness request: Restock my breakfast basics within my $10 budget.

Public context: `{"approved_breads": ["Kroger Soft Wheat Bread", "Kroger White Bread", "Kroger White Sandwich Bread", "Kroger Honey Wheat Bread"], "approved_oats": ["Simple Truth Organic 100% Whole Grain Rolled 1 Minute Oats", "Simple Truth Protein Classic Rolled Oats"], "breakfast_list": ["1 approved oats", "1 Kroger Vitamin D Whole Milk Half Gallon", "12 Kroger Grade A Large White Eggs", "1 Kroger white or wheat bread"], "budget": "$10.00"}`

Decision: Generic breakfast wording was replaced by visible approved oats/breads and named Kroger milk/eggs; hidden selectors match those visible lists.

- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805", "0001111001177"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
  - `0001111001177` — Simple Truth® Protein Classic Rolled Oats; $4.49; 16 oz; tags=kosher,non_gmo
- Need `milk`: units in [1, 1], selector `{"product_ids": ["0001111040601"]}`
  - `0001111040601` — Kroger® Vitamin D Whole Milk Half Gallon; $1.69; 1/2 gal; tags=kosher
- Need `eggs`: count in [12, 12], selector `{"product_ids": ["0001111060903", "0001111060906"]}`
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
  - `0001111060906` — Kroger® Grade A Large White Eggs; $0.97; 6 ct; tags=none
- Need `bread`: units in [1, 1], selector `{"product_ids": ["0001111008450", "0001111008485", "0001111008486", "0001111008449"]}`
  - `0001111008450` — Kroger® Soft Wheat Bread; $1.79; 20 oz; tags=none
  - `0001111008485` — Kroger® White Bread; $1.79; 20 oz; tags=vegan
  - `0001111008486` — Kroger® White Sandwich Bread; $1.79; 20 oz; tags=vegan
  - `0001111008449` — Kroger® Honey Wheat Bread; $2.29; 20 oz; tags=none
- Reference cart 1: $8.66; `{"0001111002805": 1, "0001111008485": 1, "0001111040601": 1, "0001111060903": 1}`

### K07 — Explicitly organic and vegan basket

Public high-explicitness request: Buy one Simple Truth Organic Rolled Oats, one Simple Truth Organic Extra Firm Tofu, and one Simple Truth Organic Cane Sugar. Every item must be explicitly labeled organic and vegan. Spend at most $8.50.

Public medium-explicitness request: Get the named oats, tofu, and cane sugar; organic and vegan labels are required, with an $8.50 cap.

Public low-explicitness request: Get the three items on my organic vegan list within its budget.

Public context: `{"budget": "$8.50", "dietary_rule": "Every purchased product must explicitly say Organic and Vegan.", "organic_vegan_list": ["Simple Truth Organic 100% Whole Grain Rolled 1 Minute Oats", "Simple Truth Organic Extra Firm Tofu", "Simple Truth Organic Cane Sugar"]}`

Decision: All three exact names are visible in every variant through the organic-vegan list; declarations are independently enforced.

- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
- Need `tofu`: units in [1, 1], selector `{"product_ids": ["0001111091342"]}`
  - `0001111091342` — Simple Truth Organic® Extra Firm Tofu; $1.99; 14 oz; tags=gluten_free,kosher,non_gmo,organic,vegan
- Need `sugar`: units in [1, 1], selector `{"product_ids": ["0001111084930"]}`
  - `0001111084930` — Simple Truth Organic® Cane Sugar; $2.59; 24 oz; tags=kosher,non_gmo,organic,vegan
- Reference cart 1: $8.27; `{"0001111002805": 1, "0001111084930": 1, "0001111091342": 1}`

### K08 — Breakfast basket with an organic-oats preference

Public high-explicitness request: Buy one of my approved Simple Truth rolled oats, one Kroger half-gallon whole milk, twelve Kroger large white eggs, and one approved Kroger white or wheat bread for at most $12.00. Prefer the organic oats if the budget allows.

Public medium-explicitness request: Get my four approved breakfast basics under $12, choosing the organic oats when possible.

Public low-explicitness request: Restock breakfast within budget and honor my oats preference if possible.

Public context: `{"approved_breads": ["Kroger Soft Wheat Bread", "Kroger White Bread", "Kroger White Sandwich Bread", "Kroger Honey Wheat Bread"], "approved_oats": ["Simple Truth Organic 100% Whole Grain Rolled 1 Minute Oats", "Simple Truth Protein Classic Rolled Oats"], "breakfast_list": ["1 approved oats", "1 Kroger Vitamin D Whole Milk Half Gallon", "12 Kroger Grade A Large White Eggs", "1 approved Kroger white or wheat bread"], "budget": "$12.00", "preference": "Organic oats preferred"}`

Decision: Visible approved candidate lists match hidden selectors; organic oats remain a soft preference after hard budget constraints.

- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805", "0001111001177"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
  - `0001111001177` — Simple Truth® Protein Classic Rolled Oats; $4.49; 16 oz; tags=kosher,non_gmo
- Need `milk`: units in [1, 1], selector `{"product_ids": ["0001111040601"]}`
  - `0001111040601` — Kroger® Vitamin D Whole Milk Half Gallon; $1.69; 1/2 gal; tags=kosher
- Need `eggs`: count in [12, 12], selector `{"product_ids": ["0001111060903", "0001111060906"]}`
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
  - `0001111060906` — Kroger® Grade A Large White Eggs; $0.97; 6 ct; tags=none
- Need `bread`: units in [1, 1], selector `{"product_ids": ["0001111008450", "0001111008485", "0001111008486", "0001111008449"]}`
  - `0001111008450` — Kroger® Soft Wheat Bread; $1.79; 20 oz; tags=none
  - `0001111008485` — Kroger® White Bread; $1.79; 20 oz; tags=vegan
  - `0001111008486` — Kroger® White Sandwich Bread; $1.79; 20 oz; tags=vegan
  - `0001111008449` — Kroger® Honey Wheat Bread; $2.29; 20 oz; tags=none
- Reference cart 1: $8.66; `{"0001111002805": 1, "0001111008485": 1, "0001111040601": 1, "0001111060903": 1}`
- Reference cart 2: $9.46; `{"0001111001177": 1, "0001111008450": 1, "0001111040601": 1, "0001111060903": 1}`

### K09 — Four to six verified high-protein bars

Public high-explicitness request: Buy 4 to 6 protein bars total. Every selected bar must be explicitly gluten-free and list at least 10 g protein per labeled serving. Spend at most $8.00.

Public medium-explicitness request: Get 4-6 gluten-free bars with at least 10 g protein per serving, under $8.

Public low-explicitness request: Get the verified protein bars for my trip within the snack budget.

Public context: `{"budget": "$8.00", "trip_snacks": "4-6 bars; each product must explicitly be gluten-free and show at least 10 g protein per labeled serving."}`

Decision: Accepted UPCs are exhaustively derived from in-stock protein bars with 4-6 count, explicit gluten-free, and at least 10 g labeled protein; budget is evaluated separately.

- Need `bars`: count in [4, 6], selector `{"min_protein_g": 10, "product_ids": ["0001111011125", "0001111011126", "0074982600016", "0002190814256", "0002190814302", "0074982600010", "0088884900385"], "tags_all": ["gluten_free"]}`
  - `0001111011125` — Kroger® Peanut Butter and Dark Chocolate Flavored Chewy Protein Bars; $3.19; 5 ct / 1.41 oz; tags=gluten_free
  - `0001111011126` — Kroger® Peanuts Dark Chocolate Flavored and Almonds Chewy Protein Bars; $3.19; 5 ct / 1.41 oz; tags=gluten_free
  - `0074982600016` — Pure Protein™ Gluten Free Galactic Brownie Protein Bar; $6.59; 4 ct / 1.76 oz; tags=gluten_free,organic
  - `0002190814256` — Larabar™ Peanut Butter Chocolate Creamy Nut Butter Protein Bars; $7.49; 5 ct / 1.59 oz; tags=gluten_free,kosher,non_gmo,plant_based,vegan,vegetarian
  - `0002190814302` — Larabar™ Cinnamon Nut Creamy Nut Butter Protein Bars; $7.49; 5 ct / 1.59 oz; tags=gluten_free,kosher,non_gmo,plant_based,vegan,vegetarian
  - `0074982600010` — Pure Protein™ Chocolate Peanut Caramel Protein Bars; $7.49; 4 ct / 1.76 oz; tags=gluten_free
  - `0088884900385` — Quest Chocolate Chip Cookie Dough Protein Bars; $10.99; 4 ct; tags=gluten_free,kosher
- Reference cart 1: $3.19; `{"0001111011125": 1}`
- Reference cart 2: $3.19; `{"0001111011126": 1}`
- Reference cart 3: $6.59; `{"0074982600016": 1}`
- Reference cart 4: $7.49; `{"0074982600010": 1}`

### K10 — Taco-night basket at a tight budget

Public high-explicitness request: Buy one package of Kroger soft taco tortillas, exactly two cans of black beans, one Kroger mild salsa, and one 8 oz bag of Kroger shredded cheese. Spend at most $8.00.

Public medium-explicitness request: Get tortillas, two black-bean cans, mild salsa, and an 8 oz shredded cheese for taco night, under $8.

Public low-explicitness request: Get my taco-night list without going over the saved budget.

Public context: `{"budget": "$8.00", "taco_list": ["1 Kroger soft taco tortillas", "2 black bean cans", "1 Kroger mild salsa", "1 Kroger 8 oz shredded cheese"]}`

Decision: Both in-stock Kroger mild salsas and every in-stock 8 oz Kroger shredded cheese are accepted; budget is evaluated separately.

- Need `tortillas`: units in [1, 1], selector `{"product_ids": ["0001111005265"]}`
  - `0001111005265` — Kroger® Soft Taco Size Flour Tortillas; $1.99; 10 ct / 17.5 oz; tags=none
- Need `beans`: units in [2, 2], selector `{"product_ids": ["0001111072567", "0001111012209"]}`
  - `0001111072567` — Kroger® Black Beans; $0.89; 15.25 oz; tags=dairy_free,egg_free,fish_free,kosher,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0001111012209` — Kroger® No Salt Added Black Beans; $0.89; 15.25 oz; tags=none
- Need `salsa`: units in [1, 1], selector `{"product_ids": ["0001111002269", "0001111066759"]}`
  - `0001111002269` — Kroger® Thick & Chunky Mild Salsa; $2.19; 16 oz; tags=dairy_free,egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111066759` — Kroger® Mild Traditional Salsa; $2.19; 16 oz; tags=dairy_free,egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free,vegan
- Need `cheese`: units in [1, 1], selector `{"product_ids": ["0001111050158", "0001111050159", "0001111050170", "0001111050171", "0001111050174", "0001111050183", "0001111050202", "0001111050204", "0001111050205", "0001111050339"]}`
  - `0001111050158` — Kroger® Sharp Cheddar Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050159` — Kroger® Mozzarella Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050170` — Kroger® Mild Cheddar Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050171` — Kroger® Reduced Fat Mexican Style Shredded Cheese; $1.99; 8 oz; tags=none
  - `0001111050174` — Kroger® Colby Jack Shredded Cheese; $1.99; 8 oz; tags=none
  - `0001111050183` — Kroger® Cheddar Jack Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050202` — Kroger® Monterey Jack Shredded Cheese; $1.99; 8 oz; tags=none
  - `0001111050204` — Kroger® Mexican Style Blend Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050205` — Kroger® Italian Style Blend Shredded Cheese; $1.99; 8 oz; tags=none
  - `0001111050339` — Kroger® Medium Cheddar Shredded Cheese; $1.99; 8 oz; tags=none
- Reference cart 1: $7.95; `{"0001111002269": 1, "0001111005265": 1, "0001111050170": 1, "0001111072567": 2}`
- Reference cart 2: $7.95; `{"0001111005265": 1, "0001111050204": 1, "0001111066759": 1, "0001111072567": 2}`

### K11 — Three-day breakfast restock

Public high-explicitness request: For three breakfast days, buy one Simple Truth Organic Rolled Oats, one Kroger Whole Milk Half Gallon, and three medium navel oranges. Spend no more than $9.00.

Public medium-explicitness request: Set up three breakfasts with the saved oats, milk, and one orange per day, under $9.

Public low-explicitness request: Restock the items in my three-day breakfast plan within its budget.

Public context: `{"budget": "$9.00", "three_day_plan": ["1 package Simple Truth Organic Rolled Oats", "1 Kroger Whole Milk Half Gallon", "3 medium navel oranges"]}`

Decision: All three products and quantities are explicitly named in the public three-day plan.

- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
- Need `milk`: units in [1, 1], selector `{"product_ids": ["0001111040601"]}`
  - `0001111040601` — Kroger® Vitamin D Whole Milk Half Gallon; $1.69; 1/2 gal; tags=kosher
- Need `oranges`: units in [3, 3], selector `{"product_ids": ["0000000003107"]}`
  - `0000000003107` — Medium Fresh Navel Oranges- Each; $1.19; 1 each; tags=none
- Reference cart 1: $8.95; `{"0000000003107": 3, "0001111002805": 1, "0001111040601": 1}`

### K12 — Vegan dinner-prep components

Public high-explicitness request: Buy one package each of Simple Truth Extra Firm Tofu, Kroger 90 Second Jasmine Rice, and Kroger Leaf Spinach. Every item must be explicitly labeled vegan. Spend at most $5.00.

Public medium-explicitness request: Get tofu, a rice pouch, and spinach for dinner prep; verified vegan only, $5 max.

Public low-explicitness request: Complete my vegan dinner-prep list within the saved budget.

Public context: `{"budget": "$5.00", "prep_list": ["Simple Truth Extra Firm Tofu", "Kroger 90 Second Jasmine Rice", "Kroger Leaf Spinach"], "rule": "Every purchased item must explicitly say Vegan."}`

Decision: All three products are explicitly named; every purchased item must also carry an explicit vegan declaration.

- Need `tofu`: units in [1, 1], selector `{"product_ids": ["0001111091342"]}`
  - `0001111091342` — Simple Truth Organic® Extra Firm Tofu; $1.99; 14 oz; tags=gluten_free,kosher,non_gmo,organic,vegan
- Need `rice`: units in [1, 1], selector `{"product_ids": ["0001111001950"]}`
  - `0001111001950` — Kroger® 90 Second Jasmine Rice Pouch; $1.39; 8.8 oz; tags=gluten_free,non_gmo,vegan
- Need `spinach`: units in [1, 1], selector `{"product_ids": ["0001111008631"]}`
  - `0001111008631` — Kroger® Leaf Spinach; $1.39; 13.5 oz; tags=non_gmo,paleo,vegan
- Reference cart 1: $4.77; `{"0001111001950": 1, "0001111008631": 1, "0001111091342": 1}`

### K13 — Fitness restock using labeled protein

Public high-explicitness request: Restock one Orgain Organic Vegan Protein Powder, one Optimum Nutrition Creatine Stick Pack box, exactly four gluten-free protein bars with at least 20 g protein per labeled serving, and one four-count Oikos high-protein yogurt. Spend at most $50.00.

Public medium-explicitness request: Get my powder, creatine, four qualifying 20 g gluten-free bars, and the four-pack Oikos yogurt within $50.

Public low-explicitness request: Complete my saved fitness restock without exceeding its budget.

Public context: `{"budget": "$50.00", "fitness_list": ["Orgain Organic Vegan 21g Protein Powder", "Optimum Nutrition Creatine Stick Packs", "4 gluten-free bars with >=20g protein per labeled serving", "Oikos Triple Zero high-protein yogurt 4-pack"]}`

Decision: Named powder/creatine/yogurt are exact; qualifying bar UPCs are exhaustively derived from 4-count, gluten-free products with at least 20 g labeled protein. Budget is separate.

- Need `powder`: units in [1, 1], selector `{"product_ids": ["0085177000392"]}`
  - `0085177000392` — Orgain Organic Vegan 21g Protein Powder, Vanilla Bean; $21.99; 1.02 lb; tags=dairy_free,gluten_free,kosher,non_gmo,organic,soy_free,vegan
- Need `creatine`: units in [1, 1], selector `{"product_ids": ["0074892707339"]}`
  - `0074892707339` — Optimum Nutrition® Unflavored Creatine Stick Packs; $15.99; 14 ct; tags=gluten_free
- Need `bars`: count in [4, 4], selector `{"min_protein_g": 20, "product_ids": ["0074982600016", "0074982600010", "0088884900385"], "tags_all": ["gluten_free"]}`
  - `0074982600016` — Pure Protein™ Gluten Free Galactic Brownie Protein Bar; $6.59; 4 ct / 1.76 oz; tags=gluten_free,organic
  - `0074982600010` — Pure Protein™ Chocolate Peanut Caramel Protein Bars; $7.49; 4 ct / 1.76 oz; tags=gluten_free
  - `0088884900385` — Quest Chocolate Chip Cookie Dough Protein Bars; $10.99; 4 ct; tags=gluten_free,kosher
- Need `yogurt`: units in [1, 1], selector `{"product_ids": ["0003663201953"]}`
  - `0003663201953` — Oikos Triple Zero Vanilla High Protein Nonfat Greek Yogurt Cups; $4.99; 5.3 oz., 4 pack; tags=non_gmo
- Reference cart 1: $49.56; `{"0003663201953": 1, "0074892707339": 1, "0074982600016": 1, "0085177000392": 1}`

### K14 — Restock pantry to target levels

Public high-explicitness request: Restock exactly one rice, two pasta packages, one oats, three black-bean cans, and one flour package from my approved products. Spend at most $15.00.

Public medium-explicitness request: Top up the pantry to the target levels in my sheet, $15 maximum.

Public low-explicitness request: Restock the pantry according to current and target stock.

Public context: `{"approved_black_beans": ["Kroger Black Beans", "Kroger No Salt Added Black Beans"], "approved_pasta": ["Kroger Ditalini Pasta", "Kroger Penne Rigate Pasta"], "budget": "$15.00", "pantry_sheet": [{"have": 1, "item": "Kroger Basmati Rice", "target": 2}, {"have": 0, "item": "approved Kroger pasta", "target": 2}, {"have": 1, "item": "Simple Truth Organic Rolled Oats", "target": 2}, {"have": 1, "item": "approved black-bean cans", "target": 4}, {"have": 0, "item": "Kroger 2 lb All Purpose Flour", "target": 1}], "rule": "Buy only the difference between have and target."}`

Decision: The public pantry sheet gives exact target differences and explicitly lists both approved pasta and black-bean choices.

- Need `rice`: units in [1, 1], selector `{"product_ids": ["0001111015342"]}`
  - `0001111015342` — Kroger® Basmati Rice; $3.99; 2 lb; tags=gluten_free,non_gmo
- Need `pasta`: units in [2, 2], selector `{"product_ids": ["0001111011693", "0001111085033"]}`
  - `0001111011693` — Kroger® Ditalini Pasta; $1.00; 16 oz; tags=kosher,non_gmo
  - `0001111085033` — Kroger® Penne Rigate Pasta; $1.00; 16 oz; tags=kosher,non_gmo
- Need `oats`: units in [1, 1], selector `{"product_ids": ["0001111002805"]}`
  - `0001111002805` — Simple Truth Organic® 100% Whole Grain Rolled 1 Minute Oats; $3.69; 18 oz; tags=kosher,non_gmo,organic,vegan
- Need `beans`: units in [3, 3], selector `{"product_ids": ["0001111072567", "0001111012209"]}`
  - `0001111072567` — Kroger® Black Beans; $0.89; 15.25 oz; tags=dairy_free,egg_free,fish_free,kosher,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0001111012209` — Kroger® No Salt Added Black Beans; $0.89; 15.25 oz; tags=none
- Need `flour`: units in [1, 1], selector `{"product_ids": ["0001111085401"]}`
  - `0001111085401` — Kroger® All Purpose Bleached Enriched Flour; $1.59; 2 lbs; tags=vegan
- Reference cart 1: $13.94; `{"0001111002805": 1, "0001111015342": 1, "0001111072567": 3, "0001111085033": 2, "0001111085401": 1}`

### K15 — Clarify an unstated milk restriction

Public high-explicitness request: Add one carton of milk. A household restriction is not written down, so ask about it before choosing.

Public medium-explicitness request: Get one milk that works with our unstated dietary restriction; ask first.

Public low-explicitness request: Grab milk for the household.

Public context: `{"household_note": "A milk-related dietary restriction is missing from this note. Ask before selecting.", "quantity": "one carton"}`

Decision: After required clarification, accepted UPCs exhaustively cover in-stock oat/soy milks explicitly labeled dairy-free and nut-free.

- Need `milk`: units in [1, 1], selector `{"product_ids": ["0004410015618", "0004410015619", "0004410019080", "0004410019092", "0019064663242", "0001111009433"], "tags_all": ["dairy_free", "nut_free"]}`
  - `0004410015618` — Planet Oat Dairy Free Original Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410015619` — Planet Oat® Dairy Free Extra Creamy Original Oat Milk; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410019080` — Planet Oat® Dairy Free Unsweeted Original Oat Milk; $3.69; 52 oz; tags=dairy_free,gluten_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410019092` — Planet Oat Dairy Free Barista Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free
  - `0019064663242` — Oatly Oatmilk Barista Churros; $5.99; 32 fl oz; tags=dairy_free,egg_free,fish_free,gluten_free,kosher,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111009433` — Simple Truth Organic® Vanilla Soymilk Half Gallon; $2.59; 1/2 gal; tags=dairy_free,fish_free,gluten_free,kosher,non_gmo,nut_free,organic,peanut_free,tree_nut_free,vegan
- Reference cart 1: $3.69; `{"0004410015618": 1}`
- Reference cart 2: $3.69; `{"0004410015619": 1}`
- Reference cart 3: $2.59; `{"0001111009433": 1}`
- Reference cart 4: $3.69; `{"0004410019080": 1}`

### K16 — Substitute an unavailable oat milk

Public high-explicitness request: Buy one Planet Oat Dairy Free Original Oat Milk. If it becomes unavailable, substitute one other milk explicitly labeled dairy-free and nut-free.

Public medium-explicitness request: Get Planet Oat Original, or another dairy-free nut-free carton if it is out.

Public low-explicitness request: Get my usual milk and use the saved substitution rule if needed.

Public context: `{"substitution_rule": "One other product explicitly labeled dairy-free and nut-free.", "usual_milk": "Planet Oat Dairy Free Original Oat Milk"}`

Decision: Preferred UPC has a scripted failure; substitute UPCs exhaustively cover in-stock oat/soy milks explicitly labeled dairy-free and nut-free.

- Need `milk`: units in [1, 1], selector `{"product_ids": ["0004410015618", "0004410015619", "0004410019080", "0004410019092", "0019064663242", "0001111009433"], "tags_all": ["dairy_free", "nut_free"]}`
  - `0004410015618` — Planet Oat Dairy Free Original Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410015619` — Planet Oat® Dairy Free Extra Creamy Original Oat Milk; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410019080` — Planet Oat® Dairy Free Unsweeted Original Oat Milk; $3.69; 52 oz; tags=dairy_free,gluten_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0004410019092` — Planet Oat Dairy Free Barista Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free
  - `0019064663242` — Oatly Oatmilk Barista Churros; $5.99; 32 fl oz; tags=dairy_free,egg_free,fish_free,gluten_free,kosher,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111009433` — Simple Truth Organic® Vanilla Soymilk Half Gallon; $2.59; 1/2 gal; tags=dairy_free,fish_free,gluten_free,kosher,non_gmo,nut_free,organic,peanut_free,tree_nut_free,vegan
- Scripted event UPCs: 0004410015618
- Reference cart 1: $3.69; `{"0004410015619": 1}`
- Reference cart 2: $2.59; `{"0001111009433": 1}`
- Reference cart 3: $3.69; `{"0004410019080": 1}`

### K17 — Replace unavailable gluten-free spaghetti

Public high-explicitness request: Buy exactly 680 g of gluten-free pasta using two 340 g packages, plus one Kroger No Salt Added Tomato Sauce. Try Kroger Gluten Free Spaghetti first; if unavailable, use another approved gluten-free Kroger pasta. Spend at most $7.00.

Public medium-explicitness request: Get two 340 g gluten-free Kroger pastas and the no-salt tomato sauce, $7 max; substitute the pasta shape if needed.

Public low-explicitness request: Get my saved gluten-free pasta-night list and recover from stock problems.

Public context: `{"budget": "$7.00", "pasta_night": "680 g total from two 340 g packages of explicitly gluten-free Kroger pasta, plus one Kroger No Salt Added Tomato Sauce.", "preferred": "Kroger Gluten Free Spaghetti"}`

Decision: All three in-stock 340 g Kroger gluten-free pasta shapes are accepted; sauce is exact and explicitly gluten-free.

- Need `pasta`: weight_g in [680, 680], selector `{"product_ids": ["0001111013338", "0001111013339", "0001111013340"], "tags_all": ["gluten_free"]}`
  - `0001111013338` — Kroger® Gluten Free Spaghetti; $1.99; 12 oz; tags=gluten_free,non_gmo
  - `0001111013339` — Kroger® Gluten Free Penne Rigate Pasta; $1.99; 12 oz; tags=gluten_free,non_gmo
  - `0001111013340` — Kroger® Gluten Free Rotini Pasta; $1.99; 12 oz; tags=gluten_free,non_gmo
- Need `sauce`: units in [1, 1], selector `{"product_ids": ["0001111011969"], "tags_all": ["gluten_free"]}`
  - `0001111011969` — Kroger No Salt Added Tomato Sauce; $0.59; 8 oz; tags=dairy_free,egg_free,fish_free,gluten_free,kosher,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
- Scripted event UPCs: 0001111013338
- Reference cart 1: $4.57; `{"0001111011969": 1, "0001111013339": 2}`
- Reference cart 2: $4.57; `{"0001111011969": 1, "0001111013340": 2}`

### K18 — Recover taco night after cheese stock failure

Public high-explicitness request: Buy Kroger soft taco tortillas, exactly two black-bean cans, Kroger mild salsa, and one 8 oz Kroger shredded cheese for at most $8.00. If the mild cheddar is unavailable, substitute another approved 8 oz Kroger shredded cheese.

Public medium-explicitness request: Get the taco-night list under $8 and replace the cheese if it goes out of stock.

Public low-explicitness request: Finish my taco-night basket using the saved substitutions and budget.

Public context: `{"budget": "$8.00", "preferred_cheese": "Kroger Mild Cheddar 8 oz", "substitution": "Kroger Mozzarella 8 oz is approved", "taco_list": ["Kroger soft taco tortillas", "2 black bean cans", "Kroger mild salsa", "Kroger 8 oz shredded cheese"]}`

Decision: Both Kroger mild salsas are accepted; the public context explicitly limits the cheese recovery to the named mozzarella substitute.

- Need `tortillas`: units in [1, 1], selector `{"product_ids": ["0001111005265"]}`
  - `0001111005265` — Kroger® Soft Taco Size Flour Tortillas; $1.99; 10 ct / 17.5 oz; tags=none
- Need `beans`: units in [2, 2], selector `{"product_ids": ["0001111072567", "0001111012209"]}`
  - `0001111072567` — Kroger® Black Beans; $0.89; 15.25 oz; tags=dairy_free,egg_free,fish_free,kosher,nut_free,peanut_free,soy_free,tree_nut_free,vegan
  - `0001111012209` — Kroger® No Salt Added Black Beans; $0.89; 15.25 oz; tags=none
- Need `salsa`: units in [1, 1], selector `{"product_ids": ["0001111002269", "0001111066759"]}`
  - `0001111002269` — Kroger® Thick & Chunky Mild Salsa; $2.19; 16 oz; tags=dairy_free,egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111066759` — Kroger® Mild Traditional Salsa; $2.19; 16 oz; tags=dairy_free,egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free,vegan
- Need `cheese`: units in [1, 1], selector `{"product_ids": ["0001111050170", "0001111050159"]}`
  - `0001111050170` — Kroger® Mild Cheddar Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111050159` — Kroger® Mozzarella Shredded Cheese; $1.99; 8 oz; tags=egg_free,fish_free,nut_free,peanut_free,soy_free,tree_nut_free
- Scripted event UPCs: 0001111050170
- Reference cart 1: $7.95; `{"0001111002269": 1, "0001111005265": 1, "0001111050159": 1, "0001111072567": 2}`
- Reference cart 2: $7.95; `{"0001111005265": 1, "0001111012209": 2, "0001111050159": 1, "0001111066759": 1}`

### K19 — Replace unavailable preferred coffee

Public high-explicitness request: Buy one 11 oz Kroger Breakfast Blend Ground Coffee and one 52 fl oz Planet Oat Dairy Free Original Oat Milk for at most $10.00. If the coffee is unavailable, use the approved 11 oz Kroger Colombian Ground Coffee.

Public medium-explicitness request: Get the breakfast-blend coffee and Planet Oat milk under $10; use the approved Colombian coffee if needed.

Public low-explicitness request: Get my coffee supplies within the saved budget and substitution rule.

Public context: `{"budget": "$10.00", "coffee_substitute": "Kroger Colombian Ground Coffee 11 oz", "coffee_supplies": ["Kroger Breakfast Blend Ground Coffee 11 oz", "Planet Oat Dairy Free Original Oat Milk 52 fl oz"]}`

Decision: Preferred and substitute 11 oz coffee UPCs and the 52 fl oz milk are explicitly visible.

- Need `coffee`: units in [1, 1], selector `{"product_ids": ["0001111010738", "0001111010741"]}`
  - `0001111010738` — Kroger® Breakfast Blend Mild Roast Ground Coffee; $6.00; 11 oz; tags=dairy_free,egg_free,fish_free,kosher,nut_free,peanut_free,soy_free,tree_nut_free
  - `0001111010741` — Kroger® 100% Colombian Medium Dark Roast Ground Coffee; $6.00; 11 oz; tags=dairy_free,egg_free,fish_free,kosher,nut_free,peanut_free,soy_free,tree_nut_free
- Need `milk`: units in [1, 1], selector `{"product_ids": ["0004410015618"]}`
  - `0004410015618` — Planet Oat Dairy Free Original Oat Milk 52 fl oz; $3.69; 52 fl oz; tags=dairy_free,kosher,lactose_free,non_gmo,nut_free,peanut_free,soy_free,tree_nut_free,vegan
- Scripted event UPCs: 0001111010738
- Reference cart 1: $9.69; `{"0001111010741": 1, "0004410015618": 1}`

### K20 — Preserve cart through two stock failures

Public high-explicitness request: Keep the eggs and bread already in my cart. Try one Kroger Penne Rigate Pasta, one Kroger Marinara Pasta Sauce, and one Kroger Cut and Peeled Baby Carrots bag. Spend at most $8.00 total and use the approved substitutions if an item becomes unavailable.

Public medium-explicitness request: Do not change the existing eggs or bread; add pasta, sauce, and carrots under $8, recovering from stock failures.

Public low-explicitness request: Finish my dinner order without changing the current cart.

Public context: `{"approved_carrots": ["Kroger Cut and Peeled Baby Carrots"], "approved_pasta": ["Kroger Penne Rigate Pasta", "Kroger Ditalini Pasta"], "approved_sauces": ["Kroger Marinara Pasta Sauce", "Kroger Tomato Basil Pasta Sauce"], "budget": "$8.00 total", "keep": "Everything currently in the cart", "preferred": {"carrots": "Kroger Cut and Peeled Baby Carrots", "pasta": "Kroger Penne Rigate Pasta", "sauce": "Kroger Marinara Pasta Sauce"}, "substitutions": {"pasta": "Kroger Ditalini Pasta", "sauce": "Kroger Tomato Basil Pasta Sauce"}}`

Decision: Initial items, preferred products, exact carrot, and both recovery substitutions are explicitly visible in the public context.

- Need `eggs`: units in [1, 1], selector `{"product_ids": ["0001111060903"]}`
  - `0001111060903` — Kroger® Grade A Large White Eggs; $1.49; 12 ct; tags=dairy_free,fish_free,nut_free,peanut_free,shellfish_free,soy_free,tree_nut_free
- Need `bread`: units in [1, 1], selector `{"product_ids": ["0001111008450"]}`
  - `0001111008450` — Kroger® Soft Wheat Bread; $1.79; 20 oz; tags=none
- Need `pasta`: units in [1, 1], selector `{"product_ids": ["0001111085033", "0001111011693"]}`
  - `0001111085033` — Kroger® Penne Rigate Pasta; $1.00; 16 oz; tags=kosher,non_gmo
  - `0001111011693` — Kroger® Ditalini Pasta; $1.00; 16 oz; tags=kosher,non_gmo
- Need `sauce`: units in [1, 1], selector `{"product_ids": ["0001111013416", "0001111013414"]}`
  - `0001111013416` — Kroger® Marinara Pasta Sauce; $1.99; 24 oz; tags=none
  - `0001111013414` — Kroger® Tomato Basil Pasta Sauce; $1.99; 24 oz; tags=none
- Need `carrots`: units in [1, 1], selector `{"product_ids": ["0001111091620"]}`
  - `0001111091620` — Kroger® Cut and Peeled Baby Carrots; $1.39; 16 oz; tags=non_gmo,vegan
- Scripted event UPCs: 0001111085033, 0001111013416
- Reference cart 1: $7.66; `{"0001111008450": 1, "0001111011693": 1, "0001111013414": 1, "0001111060903": 1, "0001111091620": 1}`

