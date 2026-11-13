# Agent paper results (deepseek-flash)

## Main results

| System | Runs/inst. | Macro success % [95% CI] | pass^k % | Coverage % | Hard-violation % | Missed clarif. % | Unneeded clarif. % | Tool calls | Model calls | Tokens in/out (k) | Cost/episode (USD) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ours (intent-grounded) | 3 | 100.0 [100, 100] | 100.0 (k=3) | 100.0 | 0.0 | 0.0 | 0.6 | 13.9 | 5.2 | 15/1.1 | 0.0024 |
| Ours v1 prompts (1 run) | 1 | 100.0 [100, 100] | 100.0 (k=1) | 100.0 | 0.0 | 0.0 | 3.3 | 15.3 | 6.0 | 20/1.3 | 0.0029 |
| ReAct | 3 | 99.4 [98, 100] | 98.3 (k=3) | 99.9 | 0.0 | 0.0 | 0.6 | 12.7 | 4.6 | 13/0.8 | 0.0018 |
| Direct function calling | 3 | 48.9 [29, 68] | 43.3 (k=3) | 60.6 | 2.8 | 0.0 | 0.6 | 10.1 | 2.0 | 3/0.4 | 0.0009 |
| Rule-based intent agent (prototype) | 1 | 6.7 [0, 18] | 6.7 (k=1) | 24.1 | 20.0 | 100.0 | 0.0 | 4.9 | 0.0 | – | – |
| Rule-based direct agent (prototype) | 1 | 0.0 [0, 0] | 0.0 (k=1) | 18.8 | 20.0 | 100.0 | 0.0 | 4.8 | 0.0 | – | – |
| Keyword baseline (non-LLM floor) | 1 | 8.3 [2, 17] | 8.3 (k=1) | 24.8 | 33.3 | 100.0 | 0.0 | 4.4 | 0.0 | – | – |

Macro success averages each scenario's mean over variants and runs, then over the 20 scenarios; CIs bootstrap whole scenarios (2,000 resamples). Rule-based rows are deterministic pilot references.

## Success by instruction specificity (macro %, 95% CI)

| System | high | medium | low |
|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Ours v1 prompts (1 run) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 98.3 [95, 100] |
| Direct function calling | 51.7 [32, 72] | 46.7 [25, 67] | 48.3 [28, 67] |
| Rule-based intent agent (prototype) | 10.0 [0, 25] | 5.0 [0, 15] | 5.0 [0, 15] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 20.0 [5, 40] | 5.0 [0, 15] | 0.0 [0, 0] |

## Success by task category (macro %, 95% CI)

| System | explicit | constrained | goal | recovery |
|---|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Ours v1 prompts (1 run) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 97.8 [93, 100] | 100.0 [100, 100] |
| Direct function calling | 97.8 [93, 100] | 57.8 [20, 96] | 28.9 [4, 64] | 11.1 [0, 29] |
| Rule-based intent agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] | 26.7 [0, 67] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 13.3 [0, 40] | 13.3 [0, 27] | 6.7 [0, 20] | 0.0 [0, 0] |

## Success by difficulty (macro %, 95% CI)

| System | E | M | H |
|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Ours v1 prompts (1 run) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 98.6 [96, 100] |
| Direct function calling | 97.2 [92, 100] | 62.5 [32, 92] | 11.1 [3, 24] |
| Rule-based intent agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 16.7 [0, 42] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 16.7 [0, 50] | 12.5 [4, 25] | 0.0 [0, 0] |

## Per-scenario success (%)

| Scenario | Ours (intent-grounded) | Ours v1 prompts (1 run) | ReAct | Direct function calling | Rule-based intent agent (prototype) | Rule-based direct agent (prototype) | Keyword baseline (non-LLM floor) |
|---|---|---|---|---|---|---|---|
| 01 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 02 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 03 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 04 | 100.0 | 100.0 | 100.0 | 88.9 | 0.0 | 0.0 | 66.7 |
| 05 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 06 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 07 | 100.0 | 100.0 | 100.0 | 77.8 | 0.0 | 0.0 | 0.0 |
| 08 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 09 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 10 | 100.0 | 100.0 | 100.0 | 11.1 | 0.0 | 0.0 | 0.0 |
| 11 | 100.0 | 100.0 | 100.0 | 22.2 | 0.0 | 0.0 | 0.0 |
| 12 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 13 | 100.0 | 100.0 | 88.9 | 0.0 | 0.0 | 0.0 | 0.0 |
| 14 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 15 | 100.0 | 100.0 | 100.0 | 22.2 | 0.0 | 0.0 | 0.0 |
| 16 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 17 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 18 | 100.0 | 100.0 | 100.0 | 11.1 | 100.0 | 0.0 | 0.0 |
| 19 | 100.0 | 100.0 | 100.0 | 44.4 | 0.0 | 0.0 | 0.0 |
| 20 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 | 0.0 | 0.0 |

## Paired comparisons (Ours − other, macro success, scenario bootstrap)

| Comparison | Δ (pp) | 95% CI (pp) |
|---|---|---|
| Ours − ReAct | +0.6 | [+0.0, +1.7] |
| Ours − Direct function calling | +51.1 | [+31.7, +70.6] |
| Ours − Ours w/o verifier | +0.0 | [+0.0, +0.0] |
| Ours − Ours w/o dedicated clarify node (scenarios: 1) | +0.0 | [+0.0, +0.0] |
| Ours − Ours w/o any clarification (no ask_user) (scenarios: 1) | +44.4 | [+44.4, +44.4] |
| Ours − Rule-based intent agent (prototype) | +93.3 | [+81.7, +100.0] |

## Ablations

| Variant | Runs | Macro success % [CI] | Missed clarif. % | Verify rounds | Model calls |
|---|---|---|---|---|---|
| Ours (intent-grounded) | 3 | 100.0 [100, 100] | 0.0 | – | 5.2 |
| Ours w/o verifier | 3 | 100.0 [100, 100] | 0.0 | – | 5.2 |
| Ours w/o dedicated clarify node | 3 | 100.0 [100, 100] | 0.0 | – | 6.0 |
| Ours w/o any clarification (no ask_user) | 3 | 55.6 [56, 56] | 44.4 | – | 16.6 |

Note: ablations may use fewer runs than the main condition; compare against Ours with the same runs.

## Stress split (5 harder scenarios, reported separately)

| System | Runs/inst. | Macro success % [95% CI] | pass^k % | Coverage % | Hard-violation % | high | medium | low | Model calls | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| Ours (intent-grounded) | 3 | 97.8 [93, 100] | 93.3 (k=3) | 99.3 | 0.0 | 93.3 | 100.0 | 100.0 | 8.0 | 32.4 |
| Ours w/o verifier | 3 | 93.3 [80, 100] | 86.7 (k=3) | 99.3 | 6.7 | 100.0 | 93.3 | 86.7 | 7.2 | 29.6 |
| ReAct | 3 | 97.8 [93, 100] | 93.3 (k=3) | 100.0 | 2.2 | 100.0 | 100.0 | 93.3 | 7.0 | 26.6 |
| Direct function calling | 3 | 0.0 [0, 0] | 0.0 (k=3) | 38.5 | 11.1 | 0.0 | 0.0 | 0.0 | 2.0 | 18.7 |

Per-scenario success (%):

| Scenario | Ours (intent-grounded) | ReAct | Direct function calling | Ours w/o verifier |
|---|---|---|---|---|
| S1 | 100.0 | 88.9 | 0.0 | 100.0 |
| S2 | 100.0 | 100.0 | 0.0 | 100.0 |
| S3 | 88.9 | 100.0 | 0.0 | 66.7 |
| S4 | 100.0 | 100.0 | 0.0 | 100.0 |
| S5 | 100.0 | 100.0 | 0.0 | 100.0 |

| Paired (stress) | Δ (pp) | 95% CI (pp) |
|---|---|---|
| Ours − ReAct | +0.0 | [-6.7, +6.7] |
| Ours − Direct function calling | +97.8 | [+93.3, +100.0] |
| Ours − Ours w/o verifier | +4.4 | [+0.0, +13.3] |

With only 5 scenarios, scenario-bootstrap intervals are wide; treat as indicative.

- Stress failure modes, Ours (intent-grounded) (n=1): quantity below bound 1
- Stress failure modes, ReAct (n=1): over budget 1
- Stress failure modes, Direct function calling (n=45): need missing entirely 45, quantity below bound 8, quantity above bound 7, over budget 5, extra / disallowed product 5, dietary rule violated on some item 5
- Stress failure modes, Ours w/o verifier (n=3): over budget 3, extra / disallowed product 1, need missing entirely 1

## Failure taxonomy (share of failed trials showing each mode; multi-label)

| Failure mode | Ours (intent-grounded) (n=0) | Ours v1 prompts (1 run) (n=0) | ReAct (n=1) | Direct function calling (n=92) | Rule-based intent agent (prototype) (n=56) | Rule-based direct agent (prototype) (n=60) | Keyword baseline (non-LLM floor) (n=55) |
|---|---|---|---|---|---|---|---|
| need missing entirely | – | – | 0.0 | 94.6 | 85.7 | 86.7 | 87.3 |
| extra / disallowed product | – | – | 0.0 | 0.0 | 21.4 | 20.0 | 34.5 |
| quantity below bound | – | – | 100.0 | 1.1 | 26.8 | 25.0 | 16.4 |
| quantity above bound | – | – | 0.0 | 4.3 | 8.9 | 10.0 | 10.9 |
| missed required clarification | – | – | 0.0 | 0.0 | 5.4 | 5.0 | 5.5 |
| over budget | – | – | 0.0 | 5.4 | 0.0 | 0.0 | 1.8 |

## Termination reasons and cost

- Ours (intent-grounded): {'finished': 180}; total est. cost $0.43 (peak pricing upper bound), mean runtime 8.5s/episode
- Ours v1 prompts (1 run): {'finished': 60}; total est. cost $0.17 (peak pricing upper bound), mean runtime 9.6s/episode
- ReAct: {'finished': 180}; total est. cost $0.33 (peak pricing upper bound), mean runtime 7.0s/episode
- Direct function calling: {'finished': 180}; total est. cost $0.17 (peak pricing upper bound), mean runtime 2.9s/episode
- Ours w/o verifier: {'finished': 180}; total est. cost $0.41 (peak pricing upper bound), mean runtime 8.1s/episode
- Ours w/o dedicated clarify node: {'finished': 9}; total est. cost $0.01 (peak pricing upper bound), mean runtime 7.8s/episode
- Ours w/o any clarification (no ask_user): {'finished': 9}; total est. cost $0.04 (peak pricing upper bound), mean runtime 25.2s/episode
