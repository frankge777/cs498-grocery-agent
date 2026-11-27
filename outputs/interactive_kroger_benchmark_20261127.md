# Interactive Kroger development evaluation — 2026-11-27

The current resumable shopping workflow completed 36 of 60 frozen Kroger
benchmark instances (60%). All 60 instances were scored. This is a one-run
development evaluation of `InteractiveShoppingSession` with `ModelDiscovery`.
It is not the historical `ours` agent and does not replace its old result.

## Protocol and provenance

- Dataset: `1.1.1-kroger-snapshot-audited`, 722 real products in a fixed snapshot.
- Catalog SHA-256: `2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`.
- Scenario SHA-256: `590c01667f938ab7e3509da03539b94e548906fa1da99e128af37272cfa3442e`.
- Model: `deepseek-flash`, temperature 0, thinking disabled, 4096 output-token limit.
- Scope: 20 scenarios × high/medium/low expressions × one run; eight workers.
- Real model API calls; frozen product reads and local simulated carts.
- Existing evaluator and default tool/model/time limits were retained.
- Simulated shopper selects cheapest offered line total, using unit price if
  quantity is unknown, and UPC to break ties. Free-text clarification answers
  come only from the environment's `ask_user` tool. Missing quantity and
  unresolved semantic confirmation stop the episode. No hidden need predicates
  or reference carts are accessed by the adapter.
- Core shopping source files were not changed during this run. The manifest
  records their hashes along with the simulator policy and dataset hashes.
- Original ReAct and Direct FC were not rerun in this evaluation.

Reproduce with:

```bash
.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents interactive --runs 1 --workers 8 --temperature 0 \
  --output-root results/interactive_kroger_20261127
```

Use a different output root to preserve these original run files.

## Results

- Success: 36/60 (60%). Scenario-bootstrap interval: 41.67%–76.67%; this does
  not measure run-to-run variability because each instance was sampled once.
- High expression: 13/20 (65%); medium: 11/20 (55%); low: 12/20 (60%).
- Explicit tasks: 11/15; constrained: 9/15; goal: 10/15; recovery: 6/15.
- Workflow completion (`finished`): 36. Stopped without completion: 24.
- Runner infrastructure-error count: 0. See the review-error caveat below.
- Elapsed wall time: approximately 117 seconds.
- Estimated model cost using the project's recorded price table: $0.521;
  this is not a provider billing statement.

Per-scenario success across the three expressions:

- K01: 3/3; K02: 3/3; K03: 3/3; K04: 2/3; K05: 0/3.
- K06: 1/3; K07: 1/3; K08: 3/3; K09: 1/3; K10: 3/3.
- K11: 3/3; K12: 1/3; K13: 0/3; K14: 3/3; K15: 3/3.
- K16: 0/3; K17: 2/3; K18: 2/3; K19: 2/3; K20: 0/3.

## Observed stop reasons and concrete failures

- `quantity_not_specified`: 10. The workflow leaves quantities unknown and
  waits for a shopper; the conservative simulator cannot answer them from
  hidden task answers. Some public expressions genuinely omit quantities;
  others expose an extraction issue, such as K04 low's instruction to restock
  every pantry-list item once. These cannot all be treated as the same cause.
- `review_error`: 6, at K09 high/low, K13 high/low, K16 high/low. The discovery
  implementation collapses model-call, JSON/schema, and evidence-validation
  errors into this state without retaining the underlying exception. This run
  therefore cannot distinguish these causes. A zero runner infrastructure
  count does not establish that all upstream calls succeeded.
- `no_candidates`: 4. K06 high/medium extracted the half-gallon target as
  exactly 1892 ml while the snapshot package is 1893 ml; strict range checks
  reject it. K17 medium inferred a `low_sodium` requirement from the exact
  named No Salt Added sauce; that tag is absent in the snapshot. K19 medium
  failed to retain a valid coffee substitute after the preferred item failed.
- `verification_failed`: 3, all K05. The existing-cart correction task still
  retains unwanted milk/sugar and increments bread instead of reducing it to
  the requested final quantity. Verification detects the wrong cart but the
  current workflow does not repair it.
- `budget_conflict`: 1, K20 high. Existing bread/eggs were represented again
  as outstanding requirements, inflating the planned basket total. K20's other
  expressions stopped for unresolved quantities.

## Interpretation

Search fallback and independent semantic review run in the complete pipeline,
but do not by themselves complete existing-cart reconciliation, quantity
dialogue simulation, substitution planning, or verification repair. The old
95% `ours` pilot used a different shopping loop, temperature and user policy;
comparing it directly with this 60% does not isolate the effect of semantic
review. No failed instance was removed, repaired, or rerun to improve this
recorded score.

Raw trials, trajectories, summary and manifest are stored under:
`results/interactive_kroger_20261127/deepseek-flash/kroger/interactive/`.
