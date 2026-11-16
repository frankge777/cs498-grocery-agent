# CS498 Intent-Grounded Grocery Agent

## Benchmark (draft release, follows the draft benchmark paper)

`benchmark/` + `src/grocery_bench/` implement the benchmark described in the
draft paper. It is independent of any agent architecture.

| Paper section | Implementation |
|---|---|
| 3.1 environment | `grocery_bench/environment.py`: fixed catalog (`benchmark/catalog.json`, integer cents, package size/unit, dietary tags, portions); 8 tools (`search_products`, `get_product`, `view_cart`, `add_to_cart`, `update_quantity`, `remove_from_cart`, `ask_user`, `finish`; schemas in `tools.py`); failed operations never change the cart; caps of 100 tool calls / 100 model calls / 300 s |
| 3.2–3.3 tasks | `benchmark/scenarios.json`: the 20 scenarios of Table 1 (5 per category, 4E/8M/8H), each with `high`/`medium`/`low` instruction variants sharing one set of acceptance predicates (60 instances), visible household context, initial carts, stock events, and 1–3 hand-checked reference carts |
| 3.4 clarification | scripted keyword responder; unsupported questions get a fixed "please rephrase" answer; scenario 15 requires clarification before milk is chosen |
| 4 evaluation | `evaluator.py`: Eq. (1) = need predicates × hard predicates (budget, only-allowed products, no unavailable SKU, scenario rules) × interaction predicates; coverage, hard satisfaction, weighted preference score (only when hard constraints hold), missed/unnecessary clarification |
| 4 protocol | `runner.py`: 5 runs per instance, macro-average over scenarios, results by variant/category/difficulty/scenario, bootstrap CIs that resample whole scenarios, paired system comparison, infrastructure failures flagged and excluded, release manifest with data hashes |
| 5 validation | `tests/test_bench_validation.py`: release structure, every reference cart solvable through the tools in every variant, and evaluator mutations (missing need, wrong quantity, invalid substitute, unknown dietary tag, one-cent budget overflow, extra product, missed clarification), stock failures that leave the cart unchanged, deterministic replay, caps |

Budgets, quantities and prices are tuned to the fixed catalog and differ in
places from the paper's illustrative numbers (e.g. scenario 10 uses $8, not $25).
The roster still needs to be reconciled with the originally drafted tasks and
reviewed by two people before it is frozen.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/run_benchmark.py --agent keyword_baseline --runs 5
```

`oracle_validation` replays hidden reference carts and is a validation tool
only. `keyword_baseline` is a non-LLM floor (8.3% macro success). The paper's
reference systems (direct function calling, ReAct, plan-then-execute) are LLM
agents that plug in through `GroceryEnv.call` + `TOOL_SPECS` and report each
model call with `env.record_model_call`.

## Earlier prototype

The rest of this README describes the first prototype (`src/grocery_agent/`,
`data/`). Its 100% result comes from a parser whose bundle table mirrors the
task answers, so it should not be reported as a benchmark result.

This repository contains a reproducible prototype for a grocery-shopping agent,
a 20-task benchmark, a direct function-calling baseline, and an automatic
evaluator. The agent orchestration is implemented from scratch and does not use
an agent framework.

## What is implemented

- A fixed catalog with prices, brands, dietary tags, and inventory state.
- Shopping tools for product search, cart updates, and cart inspection.
- Twenty original tasks split evenly across explicit, constrained,
  underspecified, and dynamic-replanning categories.
- A direct function-calling baseline that makes one literal plan and does not
  recover from failed actions.
- An intent-grounded agent with structured requirements, budget and constraint
  tracking, verification, and replanning after inventory changes.
- Automatic metrics for task success, item coverage, hard-constraint
  satisfaction, budget compliance, preference satisfaction, cost, tool calls,
  and replanning.
- Complete JSON trajectories for qualitative error analysis.

## Run the tests

The project has no third-party runtime dependencies and supports Python 3.9+.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Run the benchmark

```bash
python3 scripts/run_experiments.py --trials 3 --output-dir results
```

## Use real Kroger store data

There are now two Kroger modes:

- **Fixed experiment dataset:** `benchmark/kroger_snapshots/02100946-20261116.json`
  contains a frozen read of 722 real products from Kroger - Mt Zion
  (`locationId=02100946`, ZIP search `61820`).
  `benchmark/scenarios_kroger.json` contains 20 tasks built entirely from UPCs,
  prices, package sizes, availability, manufacturer declarations, allergens,
  and nutrition fields in that snapshot. This is the reproducible mode used to
  compare agents.
- **Live demonstration:** `KrogerLiveEnv` performs product reads from Kroger at
  run time. Prices and availability may change, so this mode demonstrates the
  application but should not be used to compare experimental systems.

Both modes keep cart operations inside the local environment. They cannot add
to a Kroger account cart, check out, or place an order.

Create an application in the Kroger Developer portal, then set its client
credentials locally (never commit them):

```bash
cp .env.example .env
# Edit .env and set KROGER_CLIENT_ID / KROGER_CLIENT_SECRET.
python3 scripts/snapshot_kroger.py --zip 61820 --location-id 02100946
python3 scripts/build_kroger_scenarios.py
python3 scripts/run_kroger_live.py --zip 61820 \
  --instruction "Buy one gallon of whole milk and a dozen eggs under $10"
```

The snapshot command records the store, retrieval time, real UPCs, current
prices, availability, allergens, manufacturer declarations, ingredients, and
nutrition under `benchmark/kroger_snapshots/`. Dietary tags are created only
from explicit Kroger declarations. Protein is recorded per labeled serving.
Missing metadata remains unknown and never satisfies a constraint. Kroger
exposes fulfillment availability/stock level rather than an exact inventory
count, and meal portions are deliberately not inferred.

Validate and run the fixed real-data benchmark without making network calls:

```bash
PYTHONPATH=src python3 -m unittest tests.test_kroger_benchmark -v
python3 scripts/run_benchmark.py --dataset kroger --agent oracle_validation --runs 1
```

Run the three LLM systems on the real snapshot (this uses the configured model
API and therefore may incur model cost):

```bash
python3 scripts/run_llm_experiments.py --dataset kroger \
  --agents ours react direct_fc --runs 3 --workers 16
```

Every output manifest records the selected catalog/scenario paths and their
SHA-256 hashes, so a result cannot silently mix synthetic tasks with the Kroger
catalog.

The command writes:

- `results/raw_results.csv`: one row per agent/task/trial.
- `results/summary.json`: aggregate results overall and by task type.
- `results/trajectories.json`: complete action and environment traces.

## Current preliminary result

Across 20 tasks and three deterministic trials per task, the intent-grounded
agent achieved 100% task success. The direct baseline achieved 60% overall:
100% on explicit and constrained tasks, 0% on underspecified tasks, and 40% on
dynamic tasks. These results validate the implementation and experimental
pipeline, but they do not establish general LLM performance: the current intent
parser is deterministic, and the tasks and parser were developed together.

## Repository layout

```text
data/                    Fixed catalog and 20 benchmark tasks
src/grocery_agent/       Environment, agents, parser, evaluator, experiment code
scripts/                 Experiment entry point
tests/                   End-to-end and feasibility tests
results/                 Generated metrics and trajectories
outputs/                 User-facing implementation report
```

