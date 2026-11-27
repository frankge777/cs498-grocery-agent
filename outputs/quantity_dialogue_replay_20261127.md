# Quantity dialogue repair — 2026-11-27

All ten previously quantity-blocked episodes received shopper answers and
continued execution: 28 per-product quantity answers in total. Six then passed
the unchanged benchmark evaluator. Four revealed other failures after the
quantity wait was resolved. No production intent prompt, product choice,
search/review policy or evaluator was changed for this repair.

## What changed

The previous simulated shopper could select a product but could not answer a
package-quantity question. It terminated those episodes at
`quantity_not_specified`. A request for necessary clarification should instead
be followed by a simulated user answer when that intention is defined.

The new quantity user reads independently stored shopper-intention profiles
in `benchmark/interactive_user_profiles_kroger.json`. These were authored from
the task's public descriptions/detailed request variants for all 20 scenarios.
They contain item-name matching rules and intended amounts, without UPCs,
accepted-product sets, predicates or reference carts. The shopping workflow
receives only the answer to its actual question, after package selection.
Unknown/ambiguous profile matches have no fallback quantity.

This changes the development interaction protocol after inspecting failures;
it is not held-out evaluation. User-profile matching rules belong to the
benchmark's simulated user and are not production product-search rules.

## Replay protocol

The original 60-instance run remains unchanged at
`results/interactive_kroger_20261127/deepseek-flash/kroger/interactive/`.
The diagnostic resumed precisely the ten stored quantity-wait checkpoints,
preserving their extracted intent, selected products, cart, prior tool/model
counters, and simulated stock events. New model calls were used only if later
recovery needed them. Question/answer pairs are retained in the new trajectories.
Runtime measures the resumed portion, while tool/token counters include the
original prefix. The same benchmark evaluator grades the resulting carts.

Reproduce into a new directory to preserve this record:

```bash
.venv/bin/python scripts/replay_quantity_dialogues.py \
  --output results/quantity_dialogue_replay_another_run
```

## Outcomes

- K04 low: all five quantity questions answered; workflow returned complete,
  but benchmark failed because the selected instant basmati rice pouch is not
  the specifically requested rice. This is a product-matching failure, not a
  quantity-answer failure. The internal verifier did not detect it.
- K07 medium/low: three quantity answers each; both passed.
- K12 medium/low: three quantity answers each; both passed.
- K13 medium: powder and creatine quantities answered; passed.
- K16 medium: quantity answered; subsequent stock recovery returned
  `no_candidates`, so the task still failed.
- K18 high: tortilla and salsa quantities answered; passed.
- K20 medium/low: three quantity answers each; both then stopped at
  `budget_conflict`, consistent with the unresolved existing-cart double-count
  problem.

There were zero unanswered quantity batches and zero runner infrastructure
errors in this replay. The six passing instances do not establish a new full
benchmark success rate; the other 50 instances were not freshly rerun, and
later model calls can vary. All four remaining failures are retained.

Results and manifests: `results/quantity_dialogue_replay_20261127/`.
