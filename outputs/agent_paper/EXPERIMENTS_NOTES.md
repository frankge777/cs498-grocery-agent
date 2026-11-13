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
