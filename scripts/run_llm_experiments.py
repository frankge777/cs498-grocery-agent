#!/usr/bin/env python3
"""Run the LLM agents (ours, baselines, ablations) on the grocery benchmark.

Examples:
  # 1-episode smoke test per agent
  .venv/bin/python scripts/run_llm_experiments.py --smoke
  # main experiment
  .venv/bin/python scripts/run_llm_experiments.py --agents ours react direct_fc --runs 3 --workers 24
  # ablations
  .venv/bin/python scripts/run_llm_experiments.py --agents ours_noverify ours_noclarify --runs 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.llm import DEFAULT_MODEL, DeepSeekClient, estimate_cost_usd  # noqa: E402
from grocery_agent.llm_agents import DirectFunctionCallingAgent, IntentGroundedLLMAgent, ReActAgent  # noqa: E402
from grocery_agent.interactive_benchmark import InteractiveBenchmarkAgent, RecommendedBenchmarkAgent  # noqa: E402
from grocery_agent.simulated_user import ScriptedQuantityUser, ScriptedBasketUser  # noqa: E402
from grocery_bench.evaluator import evaluate  # noqa: E402
from grocery_bench import load_catalog, load_scenarios, run_trials, write_outputs  # noqa: E402
from grocery_bench.data import (  # noqa: E402
    BENCHMARK_DIR,
    CATALOG_PATH,
    KROGER_CATALOG_PATH,
    KROGER_SCENARIOS_PATH,
    SCENARIOS_PATH,
)


def factories(llm, quantity_user=None, basket_user=None):
    return {
        "interactive": lambda: InteractiveBenchmarkAgent(llm, quantity_user=quantity_user),
        "recommended": lambda: RecommendedBenchmarkAgent(llm, quantity_user=quantity_user, basket_user=basket_user),
        "ours": lambda: IntentGroundedLLMAgent(llm),
        "ours_noverify": lambda: IntentGroundedLLMAgent(llm, use_verifier=False),
        "ours_noclarify": lambda: IntentGroundedLLMAgent(llm, use_clarify=False),
        "ours_noask": lambda: IntentGroundedLLMAgent(llm, allow_ask=False),
        "react": lambda: ReActAgent(llm),
        "direct_fc": lambda: DirectFunctionCallingAgent(llm),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agents", nargs="+", default=["ours", "react", "direct_fc"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--thinking", action="store_true", help="enable DeepSeek thinking mode")
    parser.add_argument("--scenarios", nargs="*", help="subset of scenario ids, e.g. 01 15")
    parser.add_argument("--variants", nargs="*", default=["high", "medium", "low"])
    parser.add_argument("--smoke", action="store_true", help="one instance (scenario 15, low) per agent, 1 run")
    parser.add_argument("--split", choices=["main", "stress"], default="main",
                        help="main = 20-scenario release; stress = benchmark/scenarios_stress.json")
    parser.add_argument("--dataset", choices=["synthetic", "kroger"], default="synthetic",
                        help="synthetic release or the fixed real Kroger snapshot/tasks")
    parser.add_argument("--catalog-path", type=Path, help="override the selected catalog JSON")
    parser.add_argument("--scenario-path", type=Path, help="override the selected scenario JSON")
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "llm")
    parser.add_argument("--user-profiles", type=Path, help="scripted quantity-answer profiles for interactive evaluation")
    parser.add_argument("--basket-profiles", type=Path, help="private development shopper preferences; omitted = accept all drafts")
    parser.add_argument("--quantity-user", choices=["profiles", "none"], default="profiles",
                        help="profiles answers quantity questions; none preserves the original stop-on-question policy")
    args = parser.parse_args()

    if args.dataset == "kroger" and args.split == "stress":
        parser.error("--split stress is only defined for the synthetic dataset")
    default_catalog = KROGER_CATALOG_PATH if args.dataset == "kroger" else CATALOG_PATH
    default_scenarios = KROGER_SCENARIOS_PATH if args.dataset == "kroger" else SCENARIOS_PATH
    catalog_path = args.catalog_path or default_catalog
    scenario_path = args.scenario_path or default_scenarios
    if args.split == "stress":
        scenario_path = BENCHMARK_DIR / "scenarios_stress.json"

    llm = DeepSeekClient(model=args.model, temperature=args.temperature, thinking=args.thinking)
    tag = args.model + ("-thinking" if args.thinking else "")
    catalog = load_catalog(catalog_path)
    scenarios = load_scenarios(scenario_path)
    if args.smoke:
        args.scenarios, args.variants, args.runs = ["K15" if args.dataset == "kroger" else "15"], ["low"], 1
    if args.scenarios:
        scenarios = [s for s in scenarios if s.id in set(args.scenarios)]

    profiles_path = args.user_profiles
    if profiles_path is None and args.dataset == "kroger" and not args.scenario_path:
        profiles_path = BENCHMARK_DIR / "interactive_user_profiles_kroger.json"
    quantity_user = (ScriptedQuantityUser.load(profiles_path)
                     if args.quantity_user == "profiles" and profiles_path
                     and {"interactive", "recommended"}.intersection(args.agents) else None)
    basket_user = ScriptedBasketUser.load(args.basket_profiles) if args.basket_profiles else ScriptedBasketUser()
    available = factories(llm, quantity_user=quantity_user, basket_user=basket_user)
    for name in args.agents:
        if name not in available:
            sys.exit(f"unknown agent {name}; choose from {sorted(available)}")
        started = time.time()

        def progress(done, total, name=name):
            if done == total or done % 20 == 0:
                print(f"  [{name}] {done}/{total} episodes ({time.time() - started:.0f}s)", flush=True)

        print(f"Running {name} on {len(scenarios)} scenarios x {len(args.variants)} variants x {args.runs} runs", flush=True)
        trials = run_trials(available[name], scenarios=scenarios, variants=args.variants, runs=args.runs,
                            catalog=catalog,
                            workers=args.workers, progress=progress)
        suffix = "smoke" if args.smoke else ""
        split_dir = "stress" if args.split == "stress" else args.dataset
        base = args.output_root / tag / split_dir
        out = base / (name + (f"_{suffix}" if suffix else ""))
        meta = {"name": name, "split": args.split, "dataset": args.dataset,
                "catalog_path": str(catalog_path), "scenario_path": str(scenario_path),
                "llm": llm.describe(), "runs": args.runs, "variants": args.variants,
                "scenarios": [s.id for s in scenarios], "started_utc": datetime.now(timezone.utc).isoformat()}
        if name in {"interactive", "recommended"}:
            meta["workflow"] = "InteractiveShoppingSession with ModelDiscovery"
            meta["shopper_policy"] = {
                "selection": "cheapest offered line total (unit price if quantity unknown), then UPC",
                "free_text": "environment ask_user only",
                "quantity": "scripted shopper profile after question" if quantity_user else "stop if quantity unknown",
                "unresolved_semantics": "stop; no hidden needs or reference carts accessed",
                "comparison_note": "interactive workflow with simulated shopper, separate from legacy ours",
            }
            if quantity_user:
                meta["user_profiles_path"] = str(profiles_path)
                meta["user_profiles_sha256"] = hashlib.sha256(profiles_path.read_bytes()).hexdigest()
            if name == "recommended":
                meta["workflow"] += " + ModelBasketRecommender + explicit draft acceptance + target cart diff"
                meta["workflow"] += " + v2 active scopes + stock recovery + ModelQuantityInterpreter (v1 compatibility retained)"
                meta["shopper_policy"]["selection"] = "model recommends; simulator selects only deferred/replacement choices"
                meta["shopper_policy"]["basket_review"] = "private scripted preferences" if args.basket_profiles else "accept all drafts"
                meta["shopper_policy"]["substitution_permission"] = "explicit private profiles only; no default authorization"
                meta["shopper_policy"]["quantity_conflict"] = "confirm only target-mismatch proposals matching an independent same-dimension count/volume/weight profile; stop for form/semantic ambiguity"
                meta["protocol_version"] = "recommended-v2-development"
                meta["comparison_note"] = "Frozen goals unchanged. Accept-all is compatibility, not preference adaptation evidence."
                if args.basket_profiles:
                    meta["basket_profiles_path"] = str(args.basket_profiles)
                    meta["basket_profiles_sha256"] = hashlib.sha256(args.basket_profiles.read_bytes()).hexdigest()
                scenario_map = {s.id: s for s in scenarios}
                for trial in trials:
                    draft = (trial.get("agent_notes") or {}).get("first_recommendation")
                    trial["initial_recommendation_goal_success"] = (
                        evaluate(replace(scenario_map[trial["scenario_id"]], interactions=[]),
                                 trial["variant"], draft["cart"], catalog,
                                 unavailable=set(draft["unavailable"])).success if draft else None)
                meta["initial_recommendation_metric"] = "Original frozen needs and hard constraints at first draft; execution interaction predicates excluded. Missing drafts reported separately."
            meta["code_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [ROOT / "src/grocery_agent" / filename for filename in (
                    "interactive.py", "interactive_intent.py", "choices.py", "discovery.py",
                    "interactive_benchmark.py", "simulated_user.py", "recommendation.py", "intent_schema.py",
                    "quantity_interpretation.py", "prompts.py", "llm.py")]}
        summary = write_outputs(trials, out, agent_meta=meta, catalog_path=catalog_path, scenarios_path=scenario_path)
        cost = sum(estimate_cost_usd(args.model, t["input_tokens"], t["cached_input_tokens"], t["output_tokens"])
                   for t in trials)
        print(json.dumps({
            "agent": name, "out": str(out), "macro_success": summary["macro_success"],
            "ci95": summary["macro_success_ci95"], "by_variant": summary["success_by_variant"],
            "infra_failures": summary["n_infra_failures"], "terminations": summary["termination_reasons"],
            "est_cost_usd_peak": round(cost, 3), "minutes": round((time.time() - started) / 60, 1),
        }, indent=1), flush=True)
        for t in trials:
            if t["infra_failure"]:
                print("INFRA ERROR", t["scenario_id"], t["variant"], t["infra_error"].splitlines()[-1], flush=True)
                break


if __name__ == "__main__":
    main()
