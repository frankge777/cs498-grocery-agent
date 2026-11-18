# Kroger Full Pilot — 2026-11-18

## Status

This is a full-coverage pilot, not the final repeated experiment. It evaluates
all 20 tasks in all three instruction variants once: 60 episodes per system and
180 episodes total. It measures the complete experimental pipeline and reveals
agent failure modes, but one stochastic sample per instance is not enough for a
final paper claim.

The valid pilot uses frozen benchmark release
`1.1.1-kroger-snapshot-audited` at Git commit `0c7f83c`.

- Catalog SHA-256: `2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`
- Scenario SHA-256: `590c01667f938ab7e3509da03539b94e548906fa1da99e128af37272cfa3442e`
- Model: `deepseek-flash`, thinking disabled, temperature 0.7, maximum 4,096 output tokens
- Runs per task/variant: 1
- Infrastructure failures: 0/180

## Main results

| System | Success | 95% scenario-bootstrap CI | Coverage | Hard-violation rate | Tool calls/episode | Model calls/episode | Peak-price cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Intent-grounded | 95.0% (57/60) | [86.7%, 100%] | 99.0% | 5.0% | 13.6 | 6.2 | $0.2506 |
| ReAct | 100% (60/60) | [100%, 100%] | 100% | 0% | 11.6 | 4.5 | $0.1787 |
| Direct function calling | 60.0% (36/60) | [40.0%, 80.0%] | 71.8% | 0% | 7.9 | 2.0 | $0.1056 |

Total estimated model cost was `$0.5349`, using the peak-rate table recorded in
`src/grocery_agent/llm.py`. Cached and uncached tokens are priced separately.

The hard-violation rate does not include missing required items. This is why
Direct FC can have 0% hard violations while succeeding on only 60% of episodes:
most of its failures leave required needs incomplete rather than adding a
forbidden or over-budget item.

## Success breakdown

| System | High | Medium | Low | Explicit | Constrained | Goal | Recovery |
|---|---:|---:|---:|---:|---:|---:|---:|
| Intent-grounded | 95% | 95% | 95% | 86.7% | 100% | 100% | 93.3% |
| ReAct | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Direct function calling | 55% | 60% | 65% | 93.3% | 93.3% | 53.3% | 0% |

Paired scenario-bootstrap comparisons:

- Intent-grounded minus ReAct: -5.0 percentage points, 95% CI [-13.3, 0.0].
- Intent-grounded minus Direct FC: +35.0 points, 95% CI [+15.0, +55.0].
- ReAct minus Direct FC: +40.0 points, 95% CI [+20.0, +60.0].

These intervals resample the 20 scenarios. They do not measure run-to-run model
variation because this pilot has only one run per task/variant.

## Failure inspection

Intent-grounded had three failures:

1. K04 high and low: the agent first added the exact requested Simple Truth
   Organic oats, then its verification phase incorrectly replaced them with the
   similarly named non-organic Protein Classic oats. The final cart therefore
   missed the named item and contained a disallowed substitute.
2. K20 medium: the agent successfully recovered from both scripted pasta and
   sauce stock failures. It then distrusted the exact named carrot because the
   Kroger API snapshot has `brand=Unknown` despite `Kroger` appearing in the
   product name. It replaced the correct $1.39 carrot with $1.99 Kroger carrot
   chips, causing both a wrong-item and an $8.26 budget failure.

These are agent selection/verification errors. The requested names, accepted
UPCs, prices, and failure events are visible and consistent in release 1.1.1.

ReAct had no failed episode in this one-run pilot. This should be reported as
60/60 for this sample, not as proof that its true success probability is 100%.

Direct FC had 24 failures. Its clearest limitation is recovery: it scored 0/15
on recovery episodes because its cart actions are generated before action
results are returned, so it cannot react to scripted stock failures. It also
left complex goal baskets empty or incomplete in several episodes.

## Diagnostic run and benchmark correction

The first 180-episode diagnostic run used release 1.1.0 and produced 83.3% for
Intent-grounded, 91.7% for ReAct, and 50.0% for Direct FC. Inspection found that
K07, K14, and K20 referred to approved or preferred products without exposing
all corresponding names in every instruction variant. Multiple systems then
selected reasonable Kroger products that the hidden set rejected.

Release 1.1.1 corrected only the public instructions/context. It did not change
hidden UPC sets, budgets, stock events, agent code, or evaluator rules. The
1.1.0 run is retained under `results/kroger_pilot_20261118/` for provenance but
must not be reported as a performance result. The valid 1.1.1 pilot is under
`results/kroger_pilot_20261118_v111/`.

## Interpretation and next experiment

The pipeline is ready for a repeated experiment: all 180 episodes terminated
normally, manifests match the frozen hashes, and the remaining failures are
traceable to agent behavior. However, this pilot does not support a claim that
the intent-grounded architecture beats ReAct. In this sample ReAct is both more
accurate and less expensive.

Before final evaluation, freeze the agent prompts and pre-register the number
of repeated runs. Then run at least three independent samples per task/variant
(540 episodes total). Do not change the benchmark or prompts after inspecting
those final runs. If the intent-grounded agent is improved using these pilot
failures, treat this pilot as development data and evaluate the improvement on
a separately frozen held-out task set.
