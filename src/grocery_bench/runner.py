"""Experiment protocol (paper Section 4).

* every (scenario, variant) instance is run ``runs`` times (default 5) in a
  fresh environment with identical tools and limits;
* at a cap the current cart is scored and the termination reason recorded;
  no best-of-run selection;
* infrastructure failures (exceptions other than episode termination) are
  flagged and excluded from scores, with counts reported;
* success is macro-averaged: per-scenario mean over variants and runs, then
  mean over scenarios; bootstrap CIs resample whole scenarios.
"""

from __future__ import annotations

import json
import random
import time
import traceback
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .data import (
    VARIANTS,
    Scenario,
    iter_instances,
    load_catalog,
    load_scenarios,
    release_hashes,
)
from .environment import TOOL_SCHEMA_VERSION, EpisodeTerminated, GroceryEnv
from .evaluator import evaluate_env

DEFAULT_RUNS = 5
BOOTSTRAP_SAMPLES = 2000


def run_trials(
    agent_factory: Callable[[], object],
    scenarios: Optional[Sequence[Scenario]] = None,
    variants: Sequence[str] = VARIANTS,
    runs: int = DEFAULT_RUNS,
    limits: Optional[dict] = None,
    workers: int = 1,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[dict]:
    """Run every (scenario, variant, run) in a fresh environment.

    ``workers > 1`` runs episodes in threads (for network-bound LLM agents);
    results are returned in a deterministic order regardless of completion order.
    """
    catalog = load_catalog()
    scenarios = list(scenarios) if scenarios is not None else load_scenarios()
    jobs = [(instance, run) for instance in iter_instances(scenarios, tuple(variants)) for run in range(1, runs + 1)]

    def one(job):
        instance, run = job
        return _run_episode(agent_factory, catalog, instance, run, limits)

    if workers <= 1:
        trials = []
        for index, job in enumerate(jobs, 1):
            trials.append(one(job))
            if progress:
                progress(index, len(jobs))
        return trials

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, job): index for index, job in enumerate(jobs)}
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]] = future.result()
            if progress:
                progress(done, len(jobs))
    return [results[index] for index in range(len(jobs))]


def _run_episode(agent_factory, catalog, instance, run, limits) -> dict:
    agent = agent_factory()
    env = GroceryEnv(catalog, instance.scenario, instance.variant, limits=limits)
    started = time.monotonic()
    infra_error = None
    try:
        agent.run(env)
    except EpisodeTerminated:
        pass
    except Exception:  # noqa: BLE001 - recorded as an infrastructure failure
        infra_error = traceback.format_exc(limit=5)
    if env.termination_reason is None:
        env.termination_reason = "agent_returned" if infra_error is None else "infrastructure_error"
    result = evaluate_env(env)
    return {
        "agent": getattr(agent, "name", type(agent).__name__),
        "scenario_id": instance.scenario.id,
        "category": instance.scenario.category,
        "difficulty": instance.scenario.difficulty,
        "variant": instance.variant,
        "run": run,
        "infra_failure": infra_error is not None,
        "infra_error": infra_error,
        "termination_reason": env.termination_reason,
        "runtime_seconds": round(time.monotonic() - started, 4),
        "tool_calls": env.tool_calls,
        "model_calls": env.model_calls,
        "input_tokens": env.input_tokens,
        "cached_input_tokens": env.cached_input_tokens,
        "output_tokens": env.output_tokens,
        "cart_modifications": env.cart_modifications,
        "final_cart": dict(env.cart),
        "fired_events": list(env.fired_events),
        **{k: v for k, v in result.to_dict().items() if k not in ("scenario_id", "variant")},
        "agent_notes": getattr(agent, "notes", None),
        "trajectory": env.trajectory,
    }


# ------------------------------------------------------------------ summary
def _scored(trials: Iterable[dict]) -> List[dict]:
    return [t for t in trials if not t["infra_failure"]]


def per_scenario_success(trials: Iterable[dict]) -> Dict[str, float]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for trial in _scored(trials):
        groups[trial["scenario_id"]].append(trial["success"])
    return {sid: mean(values) for sid, values in sorted(groups.items())}


def bootstrap_ci(values: Sequence[float], samples: int = BOOTSTRAP_SAMPLES, seed: int = 0, alpha: float = 0.05):
    if not values:
        return None
    rng = random.Random(seed)
    stats = sorted(mean(rng.choice(values) for _ in values) for _ in range(samples))
    low = stats[int((alpha / 2) * samples)]
    high = stats[int((1 - alpha / 2) * samples) - 1]
    return [round(low, 4), round(high, 4)]


def _macro(trials: List[dict]) -> Optional[float]:
    per = per_scenario_success(trials)
    return round(mean(per.values()), 4) if per else None


def _rate(values: List[float]) -> Optional[float]:
    return round(mean(values), 4) if values else None


def _efficiency(trials: List[dict]) -> dict:
    keys = [
        "tool_calls", "model_calls", "input_tokens", "cached_input_tokens", "output_tokens",
        "runtime_seconds", "cart_modifications",
    ]
    return {key: _rate([t[key] for t in trials]) for key in keys} | {"n": len(trials)}


def summarize(trials: List[dict]) -> dict:
    scored = _scored(trials)
    per = per_scenario_success(scored)

    def grouped(field: str) -> dict:
        out = {}
        for value in sorted({t[field] for t in scored}):
            out[value] = _macro([t for t in scored if t[field] == value])
        return out

    required = [t for t in scored if t["required_clarification_missed"] is not None]
    budgeted = [t for t in scored if t["budget_ok"] is not None]
    prefs = [t["preference_score"] for t in scored if t["preference_score"] is not None]
    terminations: Dict[str, int] = defaultdict(int)
    for trial in trials:
        terminations[trial["termination_reason"]] += 1

    return {
        "agent": scored[0]["agent"] if scored else None,
        "n_trials": len(trials),
        "n_scored": len(scored),
        "n_infra_failures": len(trials) - len(scored),
        "macro_success": _macro(scored),
        "macro_success_ci95": bootstrap_ci(list(per.values())),
        "success_by_variant": grouped("variant"),
        "success_by_category": grouped("category"),
        "success_by_difficulty": grouped("difficulty"),
        "success_by_scenario": {k: round(v, 4) for k, v in per.items()},
        "secondary": {
            "coverage": _rate([t["coverage"] for t in scored]),
            "hard_violation_rate": _rate([float(t["hard_satisfaction"] < 1) for t in scored]),
            "budget_compliance": {"rate": _rate([float(t["budget_ok"]) for t in budgeted]), "n": len(budgeted)},
            "preference_score": {"mean": _rate(prefs), "n": len(prefs)},
            "missed_required_clarification": {
                "rate": _rate([float(t["required_clarification_missed"]) for t in required]),
                "n": len(required),
            },
            "unnecessary_clarification_rate": _rate([float(t["unnecessary_clarifications"] > 0) for t in scored]),
        },
        "efficiency_all": _efficiency(scored),
        "efficiency_successful": _efficiency([t for t in scored if t["success"]]),
        "termination_reasons": dict(sorted(terminations.items())),
    }


def compare_systems(trials_a: List[dict], trials_b: List[dict], samples: int = BOOTSTRAP_SAMPLES, seed: int = 0) -> dict:
    """Paired macro-success difference (A - B), bootstrapping whole scenarios."""
    a, b = per_scenario_success(trials_a), per_scenario_success(trials_b)
    shared = sorted(set(a) & set(b))
    diffs = [a[s] - b[s] for s in shared]
    return {
        "n_scenarios": len(shared),
        "mean_difference": round(mean(diffs), 4) if diffs else None,
        "ci95": bootstrap_ci(diffs, samples=samples, seed=seed),
    }


def write_outputs(trials: List[dict], output_dir: Path, agent_meta: Optional[dict] = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(trials)
    with (output_dir / "trials.jsonl").open("w", encoding="utf-8") as handle:
        for trial in trials:
            handle.write(json.dumps({k: v for k, v in trial.items() if k not in ("trajectory", "agent_notes")}) + "\n")
    with (output_dir / "trajectories.jsonl").open("w", encoding="utf-8") as handle:
        for trial in trials:
            key = {k: trial[k] for k in ("agent", "scenario_id", "variant", "run")}
            handle.write(
                json.dumps({**key, "trajectory": trial["trajectory"], "agent_notes": trial.get("agent_notes")}) + "\n"
            )
    manifest = {
        **release_hashes(),
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "agent": agent_meta or {"name": summary["agent"]},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary
