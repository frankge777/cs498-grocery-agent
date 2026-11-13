# Agent paper: experiments and results (notes for writing)

Purpose: tell whoever writes Sections 4–6 exactly what was run, what the
numbers are, and what they do and do not support. Not polished prose.
All numbers come from `results.md` in this folder (regenerate with
`.venv/bin/python scripts/make_report.py`). Raw trials are in `results/llm/deepseek-flash/`.

---

## 1. Systems compared

All LLM systems use the **same model, same tools, same caps, same task input**.

| Name in tables | What it is | Role in the paper |
|---|---|---|
| **Ours (intent-grounded)** | LangGraph agent: intent extraction (LLM, JSON) → optional clarification → LLM tool loop → **deterministic verifier** → repair (≤2 rounds) → finish. See `architecture.md`. | Proposed agent |
| **ReAct** | Thought → one tool call → observation loop until `finish` (≤40 turns). | Main baseline (closed loop, no explicit intent, no verifier) |
| **Direct function calling** | Turn 1: one batch of information calls (search/inspect/ask). Turn 2: one batch of all cart actions, executed **blind** (no results shown, no recovery). | Open-loop baseline (the paper's planned "direct function calling" reference system) |
| Ours w/o verifier | Ours, but the cart is accepted at the first `submit_cart`. | Ablation of the verifier |
| Ours w/o dedicated clarify node | Ours without node ③; `ask_user` still available inside the tool loop. | Ablation of the clarification *module* |
| Ours w/o any clarification | Ours without node ③ **and** without the `ask_user` tool. | Ablation of the clarification *capability* |
| Ours v1 prompts | First version of the intent prompt (before fix, see §5). | Transparency about prompt iteration |
| Rule-based prototypes, keyword baseline | Earlier non-LLM agents (regex/keyword parser). | Pilot floor only; show why an LLM is needed |

**Model and settings:** DeepSeek API, `deepseek-flash` (DeepSeek-V4.1-Flash), non-thinking mode, temperature 0.7, max 4,096 output tokens. Caps from the benchmark protocol: 100 tool calls, 100 model calls, 300 s per episode. Ours: ≤30 tool-loop turns per round, ≤2 verifier repair rounds, ≤3 clarification questions in 1 round.

## 2. Data and protocol

- **Main split:** the 20 benchmark scenarios × 3 instruction variants (high/medium/low) = 60 instances (see benchmark paper).
- **Stress split:** 5 extra, harder scenarios (`benchmark/scenarios_stress.json`), also × 3 variants = 15 instances. Added **after** the main split saturated; written and validated (oracle-feasible, evaluator mutation tests) **before any agent was run on them**. Reported separately, never mixed into main scores. Content: S1 twelve-item list with mixed units + 2 stock events + tight budget; S2 vegan + gluten-free + nut-free on every item + tight budget; S3 five dinners for two with pantry subtraction + stock event + a preference that does not fit the budget; S4 repair a prefilled cart after a new vegetarian/nut-free rule + stock event; S5 three cascading stock failures + tight budget.
- **Runs:** 3 independent runs per instance (benchmark paper specifies 5; draft uses 3). Ablations on clarification: scenario 15 only (the only scenario with a required clarification), 3 variants × 3 runs.
- **Metrics:** binary success per benchmark Eq. (1) (all need, hard and interaction predicates hold); **macro success** = mean over scenarios of each scenario's mean over variants and runs; 95% CI by bootstrapping whole scenarios (2,000 resamples); **pass^k** = share of instances where all k runs succeed (τ-bench style, consistency); coverage, hard-violation rate, clarification rates, tool/model calls, tokens, estimated cost. Paired system differences bootstrap per-scenario differences.
- **Cost:** all LLM runs including superseded ones (~1,200 episodes) cost ≈ US$2.8 at DeepSeek peak prices (upper bound; most ran off-peak at half price).

## 3. Research questions → experiments → results

### RQ1. Does closed-loop execution matter? (Ours/ReAct vs Direct FC)
- Main: Ours **100.0** [100, 100], ReAct **99.4** [98, 100], Direct FC **48.9** [29, 68]. Ours − Direct FC = **+51.1 pp** [+31.7, +70.6].
- Direct FC by category: explicit 97.8, constrained 57.8, goal 28.9, recovery **11.1**. By difficulty: E 97.2, M 62.5, H **11.1**.
- Stress: Direct FC **0.0** vs Ours 97.8.
- **Supported, strongly.** Open-loop agents handle explicit lists but collapse when they must react to tool results (stock failures, joint budget, portion arithmetic). This is the clearest finding.

### RQ2. Does structured intent + verification beat ReAct?
- Main: Ours 100.0 vs ReAct 99.4; Δ = **+0.6 pp** [0.0, +1.7]. Stress: 97.8 vs 97.8; Δ = **0.0** [−6.7, +6.7].
- **Not supported** with this model. ReAct is already near ceiling. Do **not** claim Ours outperforms ReAct.
- Reliability (pass^3): main Ours 100.0 vs ReAct 98.3; stress 93.3 vs 93.3. Slight edge on the main split only; not significant.
- Cost: Ours uses more resources (main: 5.2 vs 4.6 model calls, 13.9 vs 12.7 tool calls, ~15k vs ~13k input tokens per episode; ≈ +30% cost).

### RQ3a. Does the verifier help? (Ours vs Ours w/o verifier)
- Main: 100.0 vs 100.0 (no difference).
- Stress: 97.8 vs 93.3; Δ = **+4.4 pp** [0.0, +13.3] (indicative only, 5 scenarios). Without the verifier the agent failed S3 three times: twice over budget by **2 cents** (1352 vs cap 1350), once with a wrong product and over budget. With the verifier the same over-budget cart was caught and repaired.
- Verifier activity: it flagged violations on the first check in 4/180 main episodes and 7/45 stress episodes.
- **Two failure modes of the verifier itself (important for Discussion):**
  1. *False alarms from a wrong intent.* The intent sometimes uses `count` (individual items) for canned goods, whose unit is grams, so "4 cans" can never be satisfied; the agent then spends all repair rounds on an unfixable violation (e.g., S5, scenarios 14 and 17). Similar: a preferred brand extracted as required.
  2. *Repair that breaks something else.* S3 high run 1: the verifier correctly flagged a 2-cent budget overflow; the repair removed protein, and the final cart failed the protein quantity (8 vs required ≥10). This is Ours' only stress failure.
- **Partially supported**: the verifier catches real arithmetic/budget slips on harder tasks, but its value depends on the correctness of the extracted intent.

### RQ3b. Is clarification needed, and does it need a dedicated module? (scenario 15 only)
- With clarification (Ours): success 100% (9/9).
- Without a dedicated clarify node but with `ask_user`: 100% (9/9); the agent asks from inside the tool loop.
- Without any clarification capability: **0%** (9/9 fail; success requires the question by design). Looking only at the cart: 5/9 guessed a valid milk (soy), 2/9 bought lactose-free milk (not dairy-free: wrong), 2/9 bought nothing.
- **Capability matters, the dedicated module does not**: the ability to ask is necessary; a separate clarification step adds nothing over a tool the loop can call.
- Note: an earlier version of this ablation was invalid (the model called `ask_user` even though it was not offered, and the call was executed). Fixed by refusing tools that were not offered, rerun; the invalid data was discarded. All other experiments were checked and never called a tool that was not offered.

### RQ4. Does lower instruction specificity hurt?
- Main, Ours/ReAct: 100/100/100 and 100/100/98.3 for high/medium/low. Direct FC: 51.7/46.7/48.3. Stress: Ours 93.3/100/100, ReAct 100/100/93.3.
- **No specificity effect observed.** Likely cause (a finding about the benchmark): the household context exposes the full requirements (lists, quantities, budgets), so a low-specificity instruction plus context carries the same information as a high one. Recommend redesigning low variants (information spread across order history/notes, some only via clarification) for the final version.

### RQ5. Failure analysis (from `results.md` taxonomy and `examples.md`)
- Direct FC failures are dominated by **needs missing entirely** (e.g., the planned add failed on a stock event and was never replaced), plus quantity errors.
- Rule-based prototypes: 0–8% success; failures from unparsed phrasings ("at most $20.00"), package-vs-count confusion (bought 12 cartons for "12 eggs"), no cart repair, no clarification. Motivates an LLM-based intent step.
- Qualitative examples ready in `examples.md`: (a) scenario 13 low: Ours succeeds, ReAct under-buys fruit; (b) S1 low: ReAct exceeds the $55 budget by $0.95 on a 12-item list, Ours stays at $54.15; (c) S3 high: Ours' verifier-triggered repair breaks the protein requirement; (d) S3: Ours w/o verifier ends 2 cents over budget, full Ours catches it.

## 4. One-paragraph storyline

Closed-loop execution is the decisive factor (+51 pp over an open-loop function-calling agent, which collapses on recovery and hard tasks). With a strong current model, a plain ReAct loop is already near ceiling on this benchmark, so making intent explicit and verifying the cart adds little on average: the verifier catches real budget/arithmetic slips on harder tasks, but it is only as good as the intent it checks, and wrong intents cause unfixable false alarms or repairs that break other constraints. Asking the user is necessary (0% without it), while a dedicated clarification module is not. The benchmark's main split is saturated for closed-loop LLM agents and its specificity manipulation has no effect, mainly because the household context reveals everything; this motivates harder, less self-describing tasks.

## 5. Caveats that must appear in the paper

1. **One model only** (deepseek-flash, non-thinking). Generalization to other models untested; deepseek-v4-pro was skipped for budget reasons.
2. **Prompt iteration on the main split:** the intent prompt was revised once (v1 → v2: use stated upper limits as `max`; do not turn a preferred/substitutable brand into a hard requirement) after inspecting main-split runs. v1 results are reported (100.0 with 1 run, more verifier false alarms). The stress split was created and run only after v2 was fixed, so it is held out for prompts and agent design.
3. **Stress split added post hoc** and only 5 scenarios: wide intervals; indicative only.
4. **3 runs per instance** instead of the benchmark's 5.
5. **Clarification ablations use scenario 15 only.**
6. Estimated cost uses DeepSeek's list prices (peak); actual billing may be lower.

## 6. What not to claim

- That Ours is better than ReAct (differences are within noise).
- That the verifier is clearly beneficial (indicative on stress only; it also causes failures).
- That instruction specificity affects performance (not observed).
- Any result for models other than deepseek-flash.

## 7. File map

| File | Content |
|---|---|
| `results.md` | All tables (main, by variant/category/difficulty, per scenario, paired tests, ablations, stress split, failure taxonomy, cost) |
| `results_table.tex` | Main table for the ICLR template |
| `fig_by_variant.pdf/png`, `fig_by_category.pdf/png` | Figures (main split) |
| `examples.md` | Full traces for the qualitative examples |
| `architecture.md` | Architecture diagram source + component table |
| `src/grocery_agent/prompts.py` | All prompts (appendix) |
| `results/llm/deepseek-flash/**/manifest.json` | Model settings and data hashes per run |

---

# Part B: Draft text for Section 3 (Agent Design) and Section 4 (Experimental Setup)

Draft for teammates to edit. Every implementation detail below matches the code
(`src/grocery_agent/llm_agents.py`, `prompts.py`, `llm.py`). `[CITE: …]` marks
citations to add; `[FIG]`/`[TAB]` mark figures and tables. The draft is a bit long on
purpose; cut to fit ~1.5 pages (Sec. 3) and ~0.5 page (Sec. 4).

## 3 Agent Design

### 3.1 Overview

Our central observation is that, for grocery shopping, *a successful tool call is not
evidence that the shopper's goal is met*: an add-to-cart can succeed while the cart
holds the wrong quantity (12 cartons instead of 12 eggs), violates a dietary rule
(lactose-free is not dairy-free), or exceeds the budget once all items are combined.
The intent-grounded agent therefore separates *understanding*, *acting*, and
*checking*. An LLM first converts the request into a structured, unit-aware
specification of what a correct cart must satisfy. A second LLM component shops
with tools against that specification. Before the agent may finish, deterministic
code checks the actual cart against the specification and returns concrete
violations for repair.

The agent is a single-agent state machine implemented in LangGraph [CITE: LangGraph]
with six nodes (Fig. [FIG: architecture, from `architecture.md`]):
(1) **Observe** reads the current cart (some tasks start with a prefilled cart);
(2) **Intent extraction** (LLM) produces the structured intent;
(3) **Clarify** asks the shopper for missing *mandatory* information, then re-runs (2);
(4) **Shopping loop** (LLM with tool calling) searches, inspects, and edits the cart, ending with `submit_cart`;
(5) **Verifier** (deterministic) checks the cart against the intent;
(6) **Finish** ends the episode.
Conditional edges route (2)→(3) when mandatory information is missing (at most one
clarification round), and (5)→(4) when violations remain (at most two repair rounds);
otherwise (5)→(6). Blue/green colouring in the figure distinguishes LLM calls from
deterministic code.

### 3.2 Technical approach

**Input processing (intent extraction).** The agent sees only the public episode
input: the shopper instruction (at one of three specificity levels), the household
context (lists, pantry stock, budgets, dietary notes, preferred brands), and the
current cart. The intent-extraction call uses JSON mode and returns:
- `requirements`: one entry per distinct need, each with a free-text description, a
  search query, a **measure** (`units` = packages, `count` = individual items,
  `volume_ml`, `weight_g`, or `portions:<role>` for meal roles such as protein or
  grain), a `[min, max]` interval in that measure, required dietary tags, and an
  optional required brand or product id;
- `budget_cents` (hard cap), tags required on every item, soft `preferences`,
  whether existing cart items must be kept, and `open_questions` for mandatory
  information that cannot be determined from the request and context.
The prompt instructs the model to subtract pantry stock, to use exact amounts only
when the shopper asks for them and stated upper limits otherwise, and to treat a
brand as required only when no substitute is acceptable. The output is normalized
(e.g., unknown measures default to packages; a missing `max` defaults to `min`).

**Clarification.** If `open_questions` is non-empty, the agent asks up to three
questions through the benchmark's `ask_user` tool, appends the answers to the
input, and re-extracts the intent once. The shopping loop can also call `ask_user`.

**Planning and execution (shopping loop).** A tool-calling LLM receives the request,
context, clarification answers, and the structured intent as a checklist. It may
call all benchmark tools except `finish` (search, product details, view/add/update/
remove cart items, ask the user) plus an agent-internal `submit_cart` tool. Planning
is implicit in this loop: the model is instructed to choose products *jointly* so
that every requirement's measure falls inside its interval, required tags are
present, and the total stays within budget, and to prefer preferred brands only when
hard constraints still hold. `submit_cart` carries an explicit **assignment of each
cart product to a requirement id**, which makes the cart checkable without any
hard-coded mapping from products to needs. The loop runs for at most 30 LLM turns
per round; if the model replies without a tool call it is nudged to continue.

**Verification.** The verifier is ordinary code. It fetches product details for any
cart item not yet inspected and reports a violation when: a requirement's summed
measure over its assigned products is outside `[min, max]` (per-package amounts come
from size/unit or portion metadata); an assigned product contributes nothing to the
requirement's measure; a required tag is missing (a tag that is not listed counts as
unknown, not satisfied); a required brand or product id is not met; an item is not
assigned to any requirement (an unrequested extra) unless it is an initial item that
must be kept; a kept item was reduced; an item is out of stock; or the total exceeds
the budget. Preferences are soft and are never verifier violations. Violations are
returned to the shopping loop as a bullet list with an instruction to repair the
cart and resubmit; if the model believes a violation comes from a wrong requirement,
it is told to follow the shopper's original request.

**Memory and state.** LangGraph's typed state holds the intent, the clarification
Q&A, the complete shopping message history (kept across repair rounds, so the model
remembers what it tried), a cache of inspected product details, and all verifier
reports. Nodes return partial state updates; there is no long-term memory across episodes.

**Error handling.** Failed tool calls (e.g., an item that becomes out of stock on the
first add attempt) are returned to the model as observations, and the model chooses
a substitute. Invalid JSON from intent extraction is retried once with the parse
error; blank JSON-mode replies are retried up to two times; API and network errors are
retried by the client (up to 5 retries). Calls to tools that were not offered in the
current step are refused with an error message. The verifier bounds repair to two
rounds; the environment enforces 100 tool calls, 100 model calls, and 300 s per
episode, and LangGraph's recursion limit bounds graph steps.

### 3.3 Implementation details

- **Model:** DeepSeek `deepseek-flash` (DeepSeek-V4.1-Flash) through the
  OpenAI-compatible API, non-thinking mode, temperature 0.7, at most 4,096 output
  tokens per call. Every call reports token usage (including cache hits) to the
  environment for cost accounting.
- **Prompting:** role-specific system prompts (intent extraction, shopping, ReAct,
  direct function calling) that all share one block of store rules (prices in cents,
  package size vs. count, unknown tags, no extra items, use the household context,
  ask only for mandatory information); JSON mode with an explicit schema and guidance
  for intent extraction; native function calling with JSON-Schema tool definitions;
  structured verifier feedback for repair. Full prompts: Appendix [A] (`prompts.py`).
- **Tools:** the benchmark's eight tools (`search_products`, `get_product`,
  `view_cart`, `add_to_cart`, `update_quantity`, `remove_from_cart`, `ask_user`,
  `finish`) plus the agent-internal `submit_cart`.
- **Code:** Python, LangGraph 1.2; about 400 lines for the three agents. The
  rule-based prototype is a LangGraph port of an earlier hand-written loop, verified
  to produce identical trajectories.

### 3.4 Design decisions and trade-offs

1. **Deterministic verifier vs. LLM self-critique** (e.g., Reflexion-style reflection
   [CITE: Reflexion]). Code checks are cheap, exact on arithmetic (budgets, unit
   sums), auditable, and do not share the model's blind spots. Trade-off: the check is
   only as good as the extracted intent. In our experiments a wrong measure (counting
   canned goods as individual items) produced false alarms that the model could not
   fix (Sec. 6).
2. **Unit-aware structured intent vs. a free-text plan.** A structured intent makes
   "done" checkable and forces explicit choices about units and bounds. Trade-off: a
   fixed schema must cover every need type, and misclassifying a measure creates errors.
3. **LLM tool loop vs. a combinatorial solver.** An integer program could pick the
   cheapest feasible cart exactly, but it needs the full catalog up front and an exact
   model of every task; real catalogs are only reachable through search. We keep the
   LLM for open-ended search and selection and use code only for checking.
4. **Model-provided assignment of products to requirements.** This avoids a
   hand-written category map (which would leak benchmark structure into the agent) but
   relies on the LLM assigning correctly.
5. **Clarification as a node vs. as a tool.** We made clarification an explicit step so
   that questions are asked before selection. The ablation shows that offering
   `ask_user` inside the loop is enough (Sec. 5).
6. **LangGraph vs. a hand-written loop or multi-agent frameworks** (CrewAI, AutoGen
   [CITE]). The task is a single-agent control loop with clear stages, which matches a
   typed state machine with conditional edges and step limits. Role-based teams or
   conversational multi-agent designs add coordination cost without a clear benefit here.
7. **Bounded repair (two rounds) and non-thinking mode.** Both cap cost and latency.
   Thinking mode was not evaluated (future work).

## 4 Experimental Setup

**Benchmark.** We evaluate on the intent-grounded grocery benchmark [CITE: our
benchmark paper]: 20 scenarios in four categories (explicit, constrained, goal-based,
recovery), each with three instruction-specificity variants (60 instances), a fixed
catalog with integer-cent prices, package sizes, dietary tags and portion metadata,
scripted clarification answers, and deterministic stock events. Success is binary and
checked on the final state (need, hard-constraint, and interaction predicates). Because
the main split saturated for closed-loop agents, we also report a **stress split** of
five harder scenarios (long mixed-unit lists, stacked dietary constraints under tight
budgets, pantry subtraction with stock events, repair of a prefilled cart after a new
household rule, and cascading stock failures). The stress split was created and
validated before any agent was run on it and is reported separately.

**Baselines.** All LLM systems use the same model, decoding settings, tools, caps, and
shared store rules; only the control strategy differs.
(i) **ReAct** [CITE: ReAct]: the model writes a short thought before each tool call and
observes the result, until it calls `finish` (at most 40 turns). This is the standard
closed-loop tool-using agent and isolates the effect of explicit intent and verification.
(ii) **Direct function calling**: one turn of information-gathering calls, then one turn
that emits every cart action at once, executed without showing results or allowing
recovery. This open-loop agent tests whether observing tool results matters.
(iii) **Ablations of our agent**: without the verifier; without the dedicated
clarification node (the `ask_user` tool remains); without any clarification
(no node and no `ask_user`).
(iv) **Rule-based prototypes** (a keyword/regex parser with a direct or replanning
executor) as a non-LLM floor from our pilot.

**Metrics.** Primary: **macro success**, the mean over scenarios of each scenario's mean
success over variants and runs, with 95% CIs from bootstrapping whole scenarios
(2,000 resamples); paired differences between systems use the same scenario bootstrap.
Consistency: **pass^k** [CITE: τ-bench], the share of instances solved in all k runs.
Secondary: need coverage, hard-constraint violation rate, missed and unnecessary
clarification rates, tool calls, model calls, input/output tokens, and estimated cost.

**Experimental details.** Each instance is run 3 times (the benchmark protocol
specifies 5; 3 in this draft), giving 180 main-split and 45 stress-split episodes per
system. Clarification ablations run on scenario 15 (the only scenario that requires a
clarifying question), 3 variants × 3 runs. Settings: `deepseek-flash`, non-thinking,
temperature 0.7, max 4,096 output tokens; caps of 100 tool calls, 100 model calls, and
300 s per episode; at a cap the current cart is scored. Episodes run in parallel
(24 threads), each in a freshly reset environment. No preprocessing: agents receive
only the instruction, household context, and tool outputs, never the evaluator's
predicates or reference carts. The intent prompt was revised once after inspecting
main-split runs (v1→v2); v1 results are reported for transparency, and the stress split
was run only with the final prompt. Total cost for all runs was about US$2.8 at list
(peak) prices.

---

# Part C: Extra facts for the writers (for intro, related work, discussion)

**For the introduction (problem / limitations / approach / results preview).**
- Problem: shopping agents must satisfy interacting constraints (quantities in mixed
  units, dietary rules, a joint budget, stock changes), and correct tool calls do not
  guarantee a correct cart.
- Limitations of existing agents (as motivated by our pilot and baselines):
  rule/keyword parsers break on paraphrases and units (prototypes 0–8% success);
  open-loop function calling cannot recover from stock failures (11% on recovery tasks).
- Approach: structured unit-aware intent + deterministic verification + repair, with clarification.
- Results preview: closed loop +51 pp over open loop; ReAct already ~99% with this model,
  so the verifier helps only on harder tasks (+4.4 pp on stress, not significant) and
  can hurt when the intent is wrong; asking is necessary (0% without it).

**Candidate related agent systems (4–6 needed; agent systems, not benchmarks).**
- ReAct (Yao et al., 2023): reasoning + acting loop; our main baseline.
- Reflexion (Shinn et al., 2023): verbal self-reflection after failure; contrast with our code-based verifier.
- Plan-and-Solve (Wang et al., 2023) / plan-then-execute agents: explicit planning before acting; our intent is a plan of *constraints*, not of steps.
- Toolformer (Schick et al., 2023) / native function calling: tool use without an outer verification loop; relates to our direct baseline.
- WebShop agents (Yao et al., 2022, and later LLM agents evaluated on WebShop): single-product web shopping; we target multi-item baskets with joint constraints.
- LLM + verifier / program-aided approaches (e.g., PAL, Gao et al., 2023; LLM-Modulo planning, Kambhampati et al., 2024): external checkers for LLM outputs; closest in spirit to our verifier.
Check the exact citations before use.

**Numbers you may want in the text** (all from `results.md`):
mean per-episode cost Ours $0.0024 vs ReAct $0.0018 vs Direct FC $0.0009; mean runtime
8.5 s vs 7.0 s vs 2.9 s; verifier flagged violations on the first check in 4/180 main
and 7/45 stress episodes; v1 prompt: 7/60 first-check flags on the main split, mostly
false alarms (ranges collapsed to exact amounts, substitutable brands treated as required).
