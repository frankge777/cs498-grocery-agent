# Agent paper results (deepseek-flash)

## Main results

| System | Runs/inst. | Macro success % [95% CI] | Coverage % | Hard-violation % | Missed clarif. % | Unneeded clarif. % | Tool calls | Model calls | Tokens in/out (k) | Cost/episode (USD) |
|---|---|---|---|---|---|---|---|---|---|---|
| Ours (intent-grounded) | 1 | 100.0 [100, 100] | 100.0 | 0.0 | 0.0 | 3.3 | 15.3 | 6.0 | 20/1.3 | 0.0029 |
| ReAct | 1 | 100.0 [100, 100] | 100.0 | 0.0 | 0.0 | 0.0 | 12.6 | 4.5 | 12/0.8 | 0.0018 |
| Direct function calling | 1 | 53.3 [32, 73] | 64.5 | 1.7 | 0.0 | 0.0 | 9.9 | 2.0 | 3/0.4 | 0.0011 |
| Rule-based intent agent (prototype) | 1 | 6.7 [0, 18] | 24.1 | 20.0 | 100.0 | 0.0 | 4.9 | 0.0 | – | – |
| Rule-based direct agent (prototype) | 1 | 0.0 [0, 0] | 18.8 | 20.0 | 100.0 | 0.0 | 4.8 | 0.0 | – | – |
| Keyword baseline (non-LLM floor) | 1 | 8.3 [2, 17] | 24.8 | 33.3 | 100.0 | 0.0 | 4.4 | 0.0 | – | – |

Macro success averages each scenario's mean over variants and runs, then over the 20 scenarios; CIs bootstrap whole scenarios (2,000 resamples). Rule-based rows are deterministic pilot references.

## Success by instruction specificity (macro %, 95% CI)

| System | high | medium | low |
|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Direct function calling | 50.0 [30, 70] | 55.0 [35, 75] | 55.0 [35, 75] |
| Rule-based intent agent (prototype) | 10.0 [0, 25] | 5.0 [0, 15] | 5.0 [0, 15] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 20.0 [5, 40] | 5.0 [0, 15] | 0.0 [0, 0] |

## Success by task category (macro %, 95% CI)

| System | explicit | constrained | goal | recovery |
|---|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Direct function calling | 100.0 [100, 100] | 66.7 [27, 100] | 26.7 [0, 67] | 20.0 [0, 60] |
| Rule-based intent agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] | 26.7 [0, 67] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 13.3 [0, 40] | 13.3 [0, 27] | 6.7 [0, 20] | 0.0 [0, 0] |

## Success by difficulty (macro %, 95% CI)

| System | E | M | H |
|---|---|---|---|
| Ours (intent-grounded) | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| ReAct | 100.0 [100, 100] | 100.0 [100, 100] | 100.0 [100, 100] |
| Direct function calling | 100.0 [100, 100] | 70.8 [42, 100] | 12.5 [0, 38] |
| Rule-based intent agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 16.7 [0, 42] |
| Rule-based direct agent (prototype) | 0.0 [0, 0] | 0.0 [0, 0] | 0.0 [0, 0] |
| Keyword baseline (non-LLM floor) | 16.7 [0, 50] | 12.5 [4, 25] | 0.0 [0, 0] |

## Per-scenario success (%)

| Scenario | Ours (intent-grounded) | ReAct | Direct function calling | Rule-based intent agent (prototype) | Rule-based direct agent (prototype) | Keyword baseline (non-LLM floor) |
|---|---|---|---|---|---|---|
| 01 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 02 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 03 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 04 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 66.7 |
| 05 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 06 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 07 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 08 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 09 | 100.0 | 100.0 | 33.3 | 0.0 | 0.0 | 0.0 |
| 10 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 11 | 100.0 | 100.0 | 33.3 | 0.0 | 0.0 | 0.0 |
| 12 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 13 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 14 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 |
| 15 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 16 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 17 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 18 | 100.0 | 100.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| 19 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| 20 | 100.0 | 100.0 | 0.0 | 33.3 | 0.0 | 0.0 |

## Paired comparisons (Ours − other, macro success, scenario bootstrap)

| Comparison | Δ (pp) | 95% CI (pp) |
|---|---|---|
| Ours − ReAct | +0.0 | [+0.0, +0.0] |
| Ours − Direct function calling | +46.7 | [+26.7, +68.3] |
| Ours − Ours w/o verifier | +0.0 | [+0.0, +0.0] |
| Ours − Ours w/o clarification (scenarios: 1) | +0.0 | [+0.0, +0.0] |
| Ours − Rule-based intent agent (prototype) | +93.3 | [+81.7, +100.0] |

## Ablations

| Variant | Runs | Macro success % [CI] | Missed clarif. % | Verify rounds | Model calls |
|---|---|---|---|---|---|
| Ours (intent-grounded) | 1 | 100.0 [100, 100] | 0.0 | – | 6.0 |
| Ours w/o verifier | 1 | 100.0 [100, 100] | 0.0 | – | 5.3 |
| Ours w/o clarification | 3 | 100.0 [100, 100] | 0.0 | – | 6.0 |

Note: ablations may use fewer runs than the main condition; compare against Ours with the same runs.

## Failure taxonomy (share of failed trials showing each mode; multi-label)

| Failure mode | Ours (intent-grounded) (n=0) | ReAct (n=0) | Direct function calling (n=28) | Rule-based intent agent (prototype) (n=56) | Rule-based direct agent (prototype) (n=60) | Keyword baseline (non-LLM floor) (n=55) |
|---|---|---|---|---|---|---|
| need missing entirely | – | – | 92.9 | 85.7 | 86.7 | 87.3 |
| extra / disallowed product | – | – | 0.0 | 21.4 | 20.0 | 34.5 |
| quantity below bound | – | – | 3.6 | 26.8 | 25.0 | 16.4 |
| quantity above bound | – | – | 7.1 | 8.9 | 10.0 | 10.9 |
| missed required clarification | – | – | 0.0 | 5.4 | 5.0 | 5.5 |
| over budget | – | – | 3.6 | 0.0 | 0.0 | 1.8 |

## Termination reasons and cost

- Ours (intent-grounded): {'finished': 60}; total est. cost $0.17 (peak pricing upper bound), mean runtime 9.6s/episode
- ReAct: {'finished': 60}; total est. cost $0.11 (peak pricing upper bound), mean runtime 6.8s/episode
- Direct function calling: {'finished': 60}; total est. cost $0.07 (peak pricing upper bound), mean runtime 2.8s/episode
- Ours w/o verifier: {'finished': 60}; total est. cost $0.14 (peak pricing upper bound), mean runtime 8.3s/episode
- Ours w/o clarification: {'finished': 9}; total est. cost $0.01 (peak pricing upper bound), mean runtime 7.8s/episode
