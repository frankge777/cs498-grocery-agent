#!/usr/bin/env python3
"""Continue previously quantity-blocked benchmark episodes using shopper profiles.

This is a checkpoint-replay diagnostic, not a fresh 60-episode benchmark.
Old intent, choices and prior tool state are retained. Any subsequent model
calls (e.g. stock recovery review) still use the configured real model.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.discovery import ModelDiscovery  # noqa: E402
from grocery_agent.interactive import InteractiveShoppingSession  # noqa: E402
from grocery_agent.interactive_benchmark import InteractiveBenchmarkAgent  # noqa: E402
from grocery_agent.llm import DeepSeekClient  # noqa: E402
from grocery_agent.simulated_user import ScriptedQuantityUser  # noqa: E402
from grocery_bench.data import Instance, KROGER_CATALOG_PATH, KROGER_SCENARIOS_PATH, load_catalog, load_scenarios  # noqa: E402
from grocery_bench.runner import _run_episode, write_outputs  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "results/interactive_kroger_20261127/deepseek-flash/kroger/interactive")
    parser.add_argument("--output", type=Path, default=ROOT / "results/quantity_dialogue_replay_20261127")
    parser.add_argument("--user-profiles", type=Path, default=ROOT / "benchmark/interactive_user_profiles_kroger.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output directory exists; use --output with a new directory to preserve prior runs")
    records = [json.loads(l) for l in (args.source / "trajectories.jsonl").read_text().splitlines()]
    prior_trials = {(r["scenario_id"], r["variant"], r["run"]): r for r in (
        json.loads(l) for l in (args.source / "trials.jsonl").read_text().splitlines())}
    selected = [r for r in records if r["agent_notes"].get("stop_reason") == "quantity_not_specified"]
    if not selected:
        parser.error("No quantity-blocked records in the source run")
    user = ScriptedQuantityUser.load(args.user_profiles)
    llm = DeepSeekClient(temperature=0)
    scenarios = {s.id: s for s in load_scenarios(KROGER_SCENARIOS_PATH)}
    catalog = load_catalog(KROGER_CATALOG_PATH)
    output = []
    for record in selected:
        key = record["scenario_id"], record["variant"], record["run"]
        prior = prior_trials[key]

        class ReplayAgent(InteractiveBenchmarkAgent):
            name = "interactive_quantity_replay"

            def run(self, env):
                # Reconstruct the benchmark environment as it was at the pause.
                # This harness restoration is not a production HTTP checkpoint.
                env.cart.clear()
                session = InteractiveShoppingSession.from_checkpoint(env,
                    record["agent_notes"]["session"], discovery=ModelDiscovery(llm))
                env.stock.update({pid: 0 for pid in prior["fired_events"]})
                for pid in prior["fired_events"]:
                    env._pending_events.pop(pid, None)
                env.fired_events = list(prior["fired_events"])
                env.trajectory = list(record["trajectory"])
                for field in ("tool_calls", "model_calls", "input_tokens", "cached_input_tokens",
                              "output_tokens", "cart_modifications"):
                    setattr(env, field, prior[field])
                env._started -= prior["runtime_seconds"]
                self.notes["checkpoint_replay"] = True
                self.notes["original_stop_reason"] = "quantity_not_specified"
                self.notes["prior_interaction_events"] = record["agent_notes"]["interaction_events"]
                self.continue_session(env, session, session.advance())

        trial = _run_episode(lambda: ReplayAgent(llm, quantity_user=user), catalog,
                             Instance(scenarios[key[0]], key[1]), key[2], None)
        output.append(trial)
        print(json.dumps({"scenario": key[0], "variant": key[1], "success": trial["success"],
            "stop_reason": (trial["agent_notes"] or {}).get("stop_reason"),
            "quantity_answers": len((trial["agent_notes"] or {}).get("quantity_dialogue", [])),
            "new_model_calls": trial["model_calls"] - prior["model_calls"]}), flush=True)
    summary = write_outputs(output, args.output, agent_meta={
        "name": "interactive_quantity_replay", "protocol": "checkpoint-replay diagnostic",
        "source": str(args.source), "llm": llm.describe(),
        "user_profiles_sha256": hashlib.sha256(args.user_profiles.read_bytes()).hexdigest(),
        "source_trials_sha256": hashlib.sha256((args.source / "trials.jsonl").read_bytes()).hexdigest(),
        "source_trajectories_sha256": hashlib.sha256((args.source / "trajectories.jsonl").read_bytes()).hexdigest(),
        "runtime_note": "runtime_seconds measures resumed portion; tool/token counters include original prefix",
    }, catalog_path=KROGER_CATALOG_PATH, scenarios_path=KROGER_SCENARIOS_PATH)
    print(json.dumps({"episodes": len(output), "successes": sum(t["success"] for t in output),
        "quantity_answered_episodes": sum(bool((t["agent_notes"] or {}).get("quantity_dialogue")) for t in output),
        "infra_failures": summary["n_infra_failures"], "output": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()
