# CS498 Intent-Grounded Grocery Agent

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

