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
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.llm import DEFAULT_MODEL, DeepSeekClient, estimate_cost_usd  # noqa: E402
from grocery_agent.llm_agents import DirectFunctionCallingAgent, IntentGroundedLLMAgent, ReActAgent  # noqa: E402
from grocery_bench import load_scenarios, run_trials, write_outputs  # noqa: E402
from grocery_bench.data import BENCHMARK_DIR  # noqa: E402


def factories(llm):
    return {
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
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "llm")
    args = parser.parse_args()

    llm = DeepSeekClient(model=args.model, temperature=args.temperature, thinking=args.thinking)
    tag = args.model + ("-thinking" if args.thinking else "")
    scenarios = load_scenarios(BENCHMARK_DIR / "scenarios_stress.json") if args.split == "stress" else load_scenarios()
    if args.smoke:
        args.scenarios, args.variants, args.runs = ["15"], ["low"], 1
    if args.scenarios:
        scenarios = [s for s in scenarios if s.id in set(args.scenarios)]

    available = factories(llm)
    for name in args.agents:
        if name not in available:
            sys.exit(f"unknown agent {name}; choose from {sorted(available)}")
        started = time.time()

        def progress(done, total, name=name):
            if done == total or done % 20 == 0:
                print(f"  [{name}] {done}/{total} episodes ({time.time() - started:.0f}s)", flush=True)

        print(f"Running {name} on {len(scenarios)} scenarios x {len(args.variants)} variants x {args.runs} runs", flush=True)
        trials = run_trials(available[name], scenarios=scenarios, variants=args.variants, runs=args.runs,
                            workers=args.workers, progress=progress)
        suffix = "smoke" if args.smoke else ""
        base = args.output_root / tag / ("stress" if args.split == "stress" else "")
        out = base / (name + (f"_{suffix}" if suffix else ""))
        meta = {"name": name, "split": args.split, "llm": llm.describe(), "runs": args.runs, "variants": args.variants,
                "scenarios": [s.id for s in scenarios], "started_utc": datetime.now(timezone.utc).isoformat()}
        summary = write_outputs(trials, out, agent_meta=meta)
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
