# Kroger LLM Smoke Test — 2026-11-18

## Purpose

This run checks the complete paid-model experiment path before launching the
full benchmark. It is not a final performance result: only four selected tasks,
the high-explicitness variant, and one stochastic run per task were used.

Configuration:

- Dataset: fixed Kroger - Mt Zion snapshot
- Catalog SHA-256: `2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`
- Scenarios SHA-256: `2df62aab3da3ccc7e63eb247e5d00dca00ce26d582973e4c73cbcde232cd8b8f`
- Model: `deepseek-flash`, thinking disabled, temperature 0.7
- Tasks: K10 (tight budget), K13 (complex fitness basket), K15 (required clarification), K16 (stock-failure recovery)
- Variant: high
- Runs: 1
- Total episodes: 12

## Audited final result

- Intent-grounded: 4/4 success; estimated cost `$0.015113`; 103,218 input tokens and 4,445 output tokens.
- ReAct: 4/4 success; estimated cost `$0.014399`; 130,684 input tokens and 3,632 output tokens.
- Direct function calling: 1/4 success; estimated cost `$0.005620`; 23,869 input tokens and 1,256 output tokens.
- Total estimated model cost: `$0.035132`.
- Infrastructure failures: 0.

Direct function calling succeeded on K10. It failed K13 with an empty cart,
failed to complete the cart after the required K15 clarification, and could not
recover after the preferred K16 milk became unavailable. These failures match
the baseline design: information is gathered once, cart actions are emitted in
one blind turn, and action results are not shown back to the model.

## Problems found and corrected before the final smoke run

The initial diagnostic run exposed benchmark and prompting problems rather
than valid agent failures:

1. K10 accepted only one mild Kroger salsa and two shredded-cheese UPCs even
   though the request allowed equivalent real Kroger products. The curated
   acceptance set now includes the other matching 16 oz mild salsa and 8 oz
   shredded cheese selected by the agents.
2. K15/K16 accepted only three milk UPCs even though other snapshot products
   were explicitly labeled both dairy-free and nut-free. The curated oat/soy
   milk acceptance set was expanded using explicit API declarations.
3. The intent prompt allowed "two cans" to be confused with an individual-item
   count. It now specifies that cans, jars, bags, cartons, boxes, and loaves use
   package `units`; `count` is for package contents such as 12 eggs or 4 bars.

Regression tests cover the equivalent K10 salsa/cheese and K16 oat-milk cases.
The intent correction reduced one K10 diagnostic run from 14 to 5 model calls,
from about 179k to 29k input tokens, and from 8 to 4 cart modifications.

## Interpretation limit

The 100% values for the two iterative agents must not be reported as final
benchmark scores. With four hand-picked tasks and one sample per task, the
confidence interval is not informative and stochastic variation is visible in
the diagnostic runs. The next experiment should first run all 20 tasks across
all three instruction variants once (180 episodes total), followed by the
pre-registered repeated run count if the pilot is clean.

Full per-episode records, trajectories, summaries, and manifests are under
`results/llm_smoke_kroger_20261118_final/deepseek-flash/kroger/`.
