from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Iterable, List

from .agents import DirectFunctionAgent, IntentGroundedAgent
from .catalog import load_catalog, load_tasks
from .environment import GroceryEnvironment
from .evaluator import evaluate_run


def run_experiment(output_dir: Path, trials: int = 3) -> dict:
    catalog = load_catalog()
    tasks = load_tasks()
    agents = [DirectFunctionAgent(), IntentGroundedAgent()]
    try:
        from .graph_agent import LangGraphIntentAgent
    except ImportError:
        pass  # langgraph is optional; install with `pip install -e .[langgraph]`
    else:
        agents.append(LangGraphIntentAgent())
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[dict] = []
    trajectories = []

    for trial in range(1, trials + 1):
        for task in tasks:
            for agent in agents:
                env = GroceryEnvironment(catalog, task.events)
                run = agent.run(task.id, task.instruction, env)
                evaluation = evaluate_run(run, task, catalog)
                rows.append({"trial": trial, **asdict(evaluation)})
                trajectories.append(
                    {
                        "trial": trial,
                        "task_id": task.id,
                        "agent": agent.name,
                        "instruction": task.instruction,
                        "cart": run.cart,
                        "total_cost": run.total_cost,
                        "trace": run.trace,
                    }
                )

    _write_csv(output_dir / "raw_results.csv", rows)
    (output_dir / "trajectories.json").write_text(
        json.dumps(trajectories, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = summarize(rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def summarize(rows: Iterable[dict]) -> dict:
    metrics = [
        "success",
        "item_coverage",
        "constraint_satisfaction",
        "budget_compliance",
        "preference_satisfaction",
        "total_cost",
        "tool_calls",
        "replans",
    ]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["agent"], "overall")].append(row)
        groups[(row["agent"], row["task_type"])].append(row)

    result = {"groups": {}}
    for (agent, task_type), items in sorted(groups.items()):
        key = f"{agent}:{task_type}"
        result["groups"][key] = {
            "agent": agent,
            "task_type": task_type,
            "n": len(items),
            **{metric: round(mean(float(item[metric]) for item in items), 4) for metric in metrics},
        }
    return result


def _write_csv(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

