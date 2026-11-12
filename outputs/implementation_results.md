# Implementation Results

## Delivered system

The repository now contains a complete, dependency-free prototype of the
intent-grounded grocery shopping project:

- deterministic stateful shopping sandbox;
- fixed product catalog with price, brand, dietary, and inventory attributes;
- 20 original benchmark tasks: five explicit, five constrained, five
  underspecified, and five dynamic tasks;
- direct function-calling baseline;
- intent-grounded agent with structured intent, planning, state tracking,
  verification, and replanning;
- automatic evaluator and full trajectory logging;
- six automated tests covering benchmark size, parsing, environment events,
  feasibility, dynamic recovery, and shared agent interfaces.

## Experiment protocol

- 20 tasks
- 2 agents
- 3 deterministic trials per condition
- 120 total runs
- Identical catalog, tools, budgets, and environment transitions for both agents

## Aggregate preliminary results

### Direct function-calling baseline

- Overall task success: **60%**
- Overall item coverage: **69.17%**
- Explicit task success: **100%**
- Constrained task success: **100%**
- Underspecified task success: **0%**
- Dynamic task success: **40%**
- Mean tool calls per run: **4.50**

### Intent-grounded agent

- Overall task success: **100%**
- Overall item coverage: **100%**
- Explicit task success: **100%**
- Constrained task success: **100%**
- Underspecified task success: **100%**
- Dynamic task success: **100%**
- Mean tool calls per run: **6.70**
- Mean replans per run: **0.15**

## Interpretation

Both systems solve literal and constrained requests. The direct baseline fails
on underspecified requests because it only extracts explicitly named products.
It also fails after selected items become unavailable because it does not revise
its initial plan. The intent-grounded agent expands goal-level requests into
structured requirements and re-enters its search/verification loop after a
failed action, producing the observed improvement at the cost of more tool
calls.

## Important limitation

These are implementation-validation results, not a final claim about LLM agent
performance. The current intent parser is deterministic, the environment is
synthetic, and the parser and task suite were developed together. A stronger
final evaluation should freeze the benchmark, replace or supplement the parser
with the planned LLM-backed component, add independently authored tasks, and
run stochastic trials across multiple models.

## Reproduction

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/run_experiments.py --trials 3 --output-dir results
```

