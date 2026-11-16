#!/usr/bin/env python3
"""Run an agent on the grocery benchmark (20 scenarios x 3 variants x N runs)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_bench import KeywordBaseline, OracleAgent, load_catalog, load_scenarios, run_trials, write_outputs
from grocery_bench.data import CATALOG_PATH, KROGER_CATALOG_PATH, KROGER_SCENARIOS_PATH, SCENARIOS_PATH

from grocery_agent.agents import DirectFunctionAgent, IntentGroundedAgent
from grocery_agent.bench_adapter import BenchmarkAgent

AGENTS = {
    "keyword_baseline": KeywordBaseline,
    "oracle_validation": OracleAgent,
    # Prototype agents (rule-based parser), run unchanged through an adapter.
    "direct_function": lambda: BenchmarkAgent(DirectFunctionAgent()),
    "intent_grounded": lambda: BenchmarkAgent(IntentGroundedAgent()),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=sorted(AGENTS), default="keyword_baseline")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--dataset", choices=["synthetic", "kroger"], default="synthetic")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    catalog_path = KROGER_CATALOG_PATH if args.dataset == "kroger" else CATALOG_PATH
    scenarios_path = KROGER_SCENARIOS_PATH if args.dataset == "kroger" else SCENARIOS_PATH
    catalog = load_catalog(catalog_path)
    scenarios = load_scenarios(scenarios_path)
    output_dir = args.output_dir or ROOT / "results" / "bench" / args.dataset / args.agent
    trials = run_trials(AGENTS[args.agent], scenarios=scenarios, catalog=catalog, runs=args.runs)
    summary = write_outputs(trials, output_dir, agent_meta={"name": args.agent, "dataset": args.dataset},
                            catalog_path=catalog_path, scenarios_path=scenarios_path)
    print(json.dumps({k: summary[k] for k in ("agent", "n_trials", "macro_success", "macro_success_ci95",
                                              "success_by_variant", "success_by_category")}, indent=2))


if __name__ == "__main__":
    main()
