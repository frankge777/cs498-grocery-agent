# CS498 Intent-Grounded Grocery Agent

## Web app (frontend + backend, deploys to Vercel)

| Part | Path | What it does |
|---|---|---|
| Backend | `api/index.py` (FastAPI) → `src/grocery_web/service.py` / `interactive_service.py` | `GET /api/health`, `GET /api/locations?zip_code=`, `GET /api/products?q=`, `POST /api/agent/run`, `POST /api/agent/interactive/start`, `POST /api/agent/interactive/resume` |
| Frontend | `web/` (Vite + React) | request form → cart table, parsed intent, tool trajectory |

Data source is `live` (Kroger Public API; needs `KROGER_CLIENT_ID`/`KROGER_CLIENT_SECRET`)
or `snapshot` (frozen Mt Zion snapshot; works without Kroger keys). `auto` picks
live when the keys exist. Agent tools use a local simulation. A separate local
[real Kroger account bridge](docs/real-kroger-cart.md) now provides user OAuth,
fresh previews and explicitly confirmed additions to the real cart. It is not
automatically enabled in benchmark tools or the public web endpoints.

Local dev (two terminals):

```bash
.venv/bin/pip install -r requirements.txt uvicorn
.venv/bin/uvicorn api.index:app --reload --port 8000
cd web && npm install && npm run dev      # http://localhost:5173, /api proxied to :8000
```

Deploy: import the repo in Vercel (no framework preset; `vercel.json` sets the
build), and add `DEEPSEEK_API_KEY`, `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET`,
and a random `GROCERY_SESSION_SECRET` of at least 32 characters
under Project → Settings → Environment Variables. Agent runs can take up to a
few minutes; `maxDuration` is 300 s.

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

The core benchmark has no third-party runtime dependencies and supports Python
3.9+. LLM experiments use the optional OpenAI-compatible client:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[llm]'
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

### Product choice interface for a future frontend

`src/grocery_agent/choices.py` provides a backend-only product-choice protocol.
Create one `RequirementChoice` per requested item, supply candidate product
summaries from `search_products`, and call `ChoiceCoordinator.prepare_batch()`.
It returns a JSON-ready `{"questions": [...]}` with stable `decision_id`,
`requirement_id`, `option_id`, and product ID for each option. Render the
product names, sizes and prices from those options in the frontend. Submit a
JSON response of the form
`{"answers": [{"decision_id": "d1", "selected_option_id": "d1_o2"}]}`
to `apply_answers()`. The coordinator validates all answers before changing
any selection; `selected_product_id` then contains the chosen product ID.

The frontend can persist `checkpoint()` as JSON while awaiting a reply and
restore it with `ChoiceCoordinator.from_checkpoint()`. If a selected item
becomes unavailable, call `mark_unavailable(requirement_id, product_id)`;
the next batch includes only the affected requirement. Use
`selected_total_cents()` to check the combined basket against the budget
before adding products. `SimulatedChoiceProvider` implements the same response
contract for deterministic offline tests, with ranked fallback products.

The protocol now runs through an **opt-in interactive session** in
`src/grocery_agent/interactive.py` and `src/grocery_web/interactive_service.py`.
It is separate from the frozen benchmark agent and does not change its past
results. The React frontend still calls `/api/agent/run`; it has not been wired
to the new choice endpoints yet.

The endpoint now defaults to model basket recommendation followed by explicit
acceptance or local replacement. See [the current workflow](docs/recommended-basket-workflow.md)
for the new contract and remaining work. The following examples explicitly
select the retained `user_choice` mode.

Start a session with `POST /api/agent/interactive/start`:

```json
{"instruction":"Buy one bag of carrots and one yogurt under $5. Let me choose.","source":"snapshot","selection_mode":"user_choice"}
```

If only the quantity is missing, the first response offers product/package
choices with `status: "waiting_for_user"`. For `"Buy yogurt"`, choose a UPC
using the product-answer format below. Its option has `quantity: null` and
`line_total_cents: null`; `price_cents` is the price of one package, not a
confirmed basket total. Once a package is selected, the response has
`status: "needs_clarification"` with `q_r1_quantity`. This quantity question
includes `product_id`, `product_name`, `package_size`, and `price_cents` so the
shopper knows exactly which package they are counting. Submit the answer:

```json
{"session_token":"<token from start>","clarification_answers":{"answers":[{"question_id":"q_r1_quantity","amount":2,"measure":"units"}]}}
```

The post-selection quantity answer uses `measure: "units"`: how many packages
of this specific UPC to buy. The original request can still specify `count`
(contents), `volume_ml`, or `weight_g`. Preserve those targets and calculate
the package count automatically: twelve eggs can mean two cartons of six or
one carton of twelve; no extra quantity question is asked. Mandatory free-text
questions that block discovery (such as an unspecified restriction) are asked
before search, using the same endpoint with
`{"question_id":"q_open_1","text":"..."}`; the model extracts intent again
from the answer. The frontend should show all clarification questions together
and use the latest returned token on every resume call.

Product selection responses have `status: "waiting_for_user"`, a
`questions` array (one entry per product), and a signed `session_token`. Each
question has a `decision_id`, `requirement_id`, and `options` with `option_id`,
UPC, name, size, price, required package quantity, and line total. For example,
the choice for twelve eggs may show two cartons of six eggs. Show all questions
together. Send one answer per decision to
`POST /api/agent/interactive/resume`:

```json
{"session_token":"<token from start>","answers":{"answers":[{"decision_id":"d1","selected_option_id":"d1_o2"},{"decision_id":"d2","selected_option_id":"d2_o1"}]}}
```

Use the actual IDs from the response. The response may be `complete`,
`needs_clarification`, `waiting_for_user` (including a replacement choice after
stock changes), `budget_conflict`, `no_candidates`, `clarification_limit`,
`verification_failed`, or `round_limit`. A complete response includes a
deterministic `verification` report. For `budget_conflict`,
call resume with `{"session_token":"<token>",
"reconsider_requirement_ids":["r1"]}` to reopen one or more item choices.
The frontend should keep the latest token and show the latest questions.
`requirement_states` exposes each need's status, selected UPC, package quantity,
and target measure/range. A need moves through `unresolved` (not selected),
`needs_user` (product choice), `needs_quantity` (package selected but count
unknown), `selected` (product and quantity ready), and `added`.
Quantity answers preserve the chosen UPC and selection history. A package
count confirmed after selection is bound to that UPC; replacement or
reconsideration clears it and asks for a count for the new package. Targets
stated in the original request survive replacement and are recalculated.
Tokens expire after 30 minutes; the signed state contains the instruction and
selection history, so treat it as private user data. No database is needed for
this demo. Both snapshot and live modes only simulate the cart locally.

### Search fallback and independent semantic review

Sessions created through `interactive/start` now enable `ModelDiscovery`.
Search first uses the intent's original query. An empty result triggers a
separate model call proposing at most two distinct alternative search terms;
the original intent, quantity, budget, and restrictions are never rewritten.
There are at most three distinct queries per discovery pass. A failed search
tool call is retried once with the same query; persistent failure returns
`search_error`, not `no_candidates`. Query-planning or review-model failure
returns `review_error`. These responses retain the session token; an explicit
resume without an answer can retry discovery, within the session round limit.

Nonempty search results go to an independent model review using the original
request/context and current requirement. It returns `related`, `unrelated`,
or `uncertain` per observed product. Definite judgments require evidence:
`{"field":"name","quote":"exact text from the product"}`. The program
rejects malformed reviews, unknown/duplicate IDs, omitted products, and quotes
not present in the supplied fields. A model cannot supply replacement product
metadata. Evidence anchoring checks what was cited; it does not prove that
every model interpretation is correct.

Initially the reviewer sees search summaries. For up to five uncertain items,
the environment fetches real details and the model reviews those items once
more. The program then applies stock, valid price, UPC, brand, required tags,
package arithmetic, and budget checks using observed data. Confirmed semantic
matches are offered as product choices. When there are no usable confirmed
matches but some hard-eligible uncertain products, the response is
`needs_candidate_review`. Its questions have `review_id`, `requirement_id`,
and `options` containing observed product fields plus review reasons/evidence.
The caller can confirm an item as the intended product:

```json
{"session_token":"<latest token>","candidate_review_answers":{"answers":[{"review_id":"<returned review_id>","selected_product_id":"<offered product id>"}]}}
```

Submit one answer for each pending review. A null `selected_product_id`
declines all offered uncertain products for that requirement. Confirmation
resolves product meaning only; it cannot fill missing allergy/dietary facts
or override hard checks. A confirmed product goes to package-quantity questions
if its quantity is still unknown, otherwise to pre-execution checks. Definite
mismatches cannot be selected by forging a product ID.

Each response's `discovery` field exposes query attempts, semantic reviews,
and a diagnostic reason: `empty_search`, `semantic_mismatch`,
`semantic_uncertainty`, or `hard_constraints`. Attempts, reviews, excluded
products, and pending reviews also survive token checkpoints. The independent
review applies to discovered candidates; final cart validation remains the
existing deterministic checker. Resuming or repairing selected products uses
the existing price/availability refresh behavior.

The original three choice-development cases intentionally continue using
reference intents and deterministic discovery, so they are not measurements
of semantic review. Run `python -m unittest tests.test_discovery` for offline
control-flow/evidence checks. `scripts/run_discovery_review.py` calls the real
configured model (incurs API cost) on synthetic coffee, dish-detergent, and tea
development fixtures in `benchmark/discovery_review_development.json`.
Their expected labels are not sent to the model. This small development check
is separate from the frozen Kroger benchmark and is not held-out evidence of
generalization.

The choice workflow supports positive package counts and exact or bounded
counts, weights, and volumes when package metadata is sufficient. Missing
quantities remain unknown until the shopper answers; optional brand or flavor
fields do not create mandatory questions. Product choice and final hard checks
run in Python. The UI still needs to be connected to these endpoints. Search
can return many candidates; a ranking/shortlist policy is still needed for a
compact shopping experience. Meal-portion goals depend on portion metadata,
which is usually unknown for real Kroger products.

For offline development validation, run
`.venv/bin/python scripts/run_choice_validation.py`. Its three scenarios use
real Kroger snapshot products and a scripted shopper, but the input intent is
provided by the scenario. This checks the choice loop, stock recovery, and
budget reconsideration; it is not a measured LLM benchmark result.

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
python3 scripts/audit_kroger_benchmark.py
python3 scripts/run_benchmark.py --dataset kroger --agent oracle_validation --runs 1
```

The frozen task release is `1.1.1-kroger-snapshot-audited`. Its catalog and
scenario SHA-256 hashes are `2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`
and `590c01667f938ab7e3509da03539b94e548906fa1da99e128af37272cfa3442e`.
The audit checks all attribute-defined candidate sets against the complete
snapshot and replays all 102 accepted reference carts. See
`outputs/kroger_benchmark_audit_20261118.md` for the scenario-by-scenario
decisions.

Run the three LLM systems on the real snapshot (this uses the configured model
API and therefore may incur model cost):

```bash
.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents ours react direct_fc --runs 3 --workers 16
```

To evaluate the newer resumable workflow, use the separate `interactive` name:

```bash
.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents interactive --runs 1 --workers 8 --temperature 0 \
  --output-root results/interactive_kroger_quantity_user_20261127
```

For the model-recommended basket workflow (separate result label):

To use a GPT model through an already authenticated local Codex CLI, add
`--provider codex --model gpt-6-sol`; no OpenAI API key is required for this
local CLI path. See [GPT experiment commands and protocol limits](docs/gpt-experiments.md).
This adapter supports the JSON-only recommended/interactive workflows;
native function-calling baselines and the HTTP server default are unchanged.
The [actual GPT follow-up run](outputs/gpt_codex_experiments_20261127.md) completed
the live Kroger/local-cart demo; the four dialogue cases scored 1/4, with three
paused for missing bag-packaging evidence. This is separate from the DeepSeek
60/60 main run; the full main set has not been rerun with GPT.

```bash
.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents recommended --runs 1 --workers 3 --temperature 0 \
  --output-root results/recommended_kroger_new_run

.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents recommended --variants high --runs 1 --workers 3 --temperature 0 \
  --scenario-path benchmark/recommendation_dialogue_kroger_development.json \
  --user-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --basket-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --output-root results/recommended_dialogue_new_run
```

The first command accepts every draft and measures compatibility with the frozen
goals. The second runs four development cases with a private Greek-yogurt
preference in RD03 and explicit quantity answers. Neither is a held-out
personalization benchmark. Initial draft goal checks exclude execution
interaction predicates; final success retains the complete original evaluator.
The default recommended workflow now requests a v2 intent with source evidence,
per-item primary/fallback phases, and a dedicated model quantity interpretation
after product recommendation. Missing substitution permission and quantity/form
conflicts pause through resumable API responses. See [runtime and API](docs/shopping-v2-runtime.md)
and [v2 repair measurements](outputs/shopping_repair_v2_20261127.md).
The latest v2 check passed 180 offline tests and 60/60 frozen Kroger episodes
(one run, with simulated shopper answers). The live Kroger backend read check
passed; the DeepSeek follow-up dialogue/live-model checks were blocked by
insufficient balance after the main run. The separate GPT follow-up is linked above.
The [previous version report](outputs/recommended_workflow_20261127.md) preserves
the historical 53/60 result. These are single-run development results, not a
held-out architecture comparison. The separate account-backed addition bridge
is documented above; these experiment results concern the local-cart workflow.

This calls the real model for intent extraction, fallback queries, and semantic
review, while using the frozen Kroger snapshot for reproducibility. It retains
the same evaluator and limits. A deterministic simulated shopper picks the
lowest offered line total (unit price if quantity is unknown), breaking ties
by UPC. Mandatory free-text answers come only from `ask_user`. Quantity
questions are answered from the separate scripted shopper intentions in
`benchmark/interactive_user_profiles_kroger.json`, only after a specific package
has been selected and a question asked. Profiles contain item names and amounts,
not accepted UPC sets, scoring predicates, or reference carts. Every quantity
question/answer and its profile source is recorded in `agent_notes.quantity_dialogue`.
An unmatched or ambiguous intention remains unanswered; there is no blanket
default of one. User intentions are not included in the shopping model's
initial input. Unresolved semantic confirmation still stops the simulation.
Unsupported workflows, malformed model intent,
and unresolved interactions are scored failures, not silently skipped.
Infrastructure failures are reported separately under the existing protocol.

This is a development evaluation of a different workflow, not a replacement
for the historical `ours` score or a controlled architecture comparison. In
particular, cheap-choice simulation does not model individual preferences.
Manifests record the user policy, quantity-profile hash, dataset hashes, and
relevant source hashes. This is a development protocol change: profiles were
added after inspecting the previous run, so new results must be stored
separately. `--quantity-user none` retains the earlier stop-on-quantity-question
policy. Custom scenario files require explicit matching `--user-profiles`.

`scripts/replay_quantity_dialogues.py` resumes the ten quantity-blocked states
from the original November 27 pilot, retaining their extracted intent and
selected products. It is a checkpoint diagnostic; it does not rerun all 60
instances or replace the original 60% result. See
`outputs/quantity_dialogue_replay_20261127.md` for this diagnostic's outcome.

Every output manifest records the selected catalog/scenario paths and their
SHA-256 hashes, so a result cannot silently mix synthetic tasks with the Kroger
catalog.

A four-task, high-explicitness smoke test is recorded under
`results/llm_smoke_kroger_20261118_final/`. It is a pipeline check, not a final
benchmark result: each task was sampled only once, and it predates the final
`1.1.1` acceptance-set audit. See `outputs/kroger_smoke_test_20261118.md` for
the result and limitations.

A full-coverage 1.1.1 pilot is recorded under
`results/kroger_pilot_20261118_v111/`: 20 tasks × 3 instruction variants × 1
run for each of the three LLM systems (180 episodes, no infrastructure
failures). Intent-grounded scored 95%, ReAct 100%, and Direct FC 60%. This is a
single-run pilot, not a final repeated result. See
`outputs/kroger_pilot_results_20261118.md` for costs, paired intervals, failure
analysis, and the invalidated 1.1.0 diagnostic-run provenance.

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

