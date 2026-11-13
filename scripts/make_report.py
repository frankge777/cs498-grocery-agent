#!/usr/bin/env python3
"""Build the agent-paper results package from saved trial files.

Reads results/llm/<model-tag>/<agent>/ and the rule-based pilot in
results/bench/<agent>/, and writes outputs/agent_paper/:
  results.md            tables (main, by specificity/category/difficulty, ablations,
                        paired tests, failure taxonomy, cost)
  results_table.tex     main table for the ICLR template
  fig_by_variant.pdf/png, fig_by_category.pdf/png
  examples.md           qualitative traces (successes and failures)
  architecture.mmd      LangGraph architecture diagram (mermaid)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.llm import estimate_cost_usd  # noqa: E402
from grocery_bench.runner import bootstrap_ci, compare_systems, per_scenario_success  # noqa: E402

MAIN = ["ours", "react", "direct_fc"]
ABLATIONS = ["ours", "ours_noverify", "ours_noclarify"]
PILOT = ["intent_grounded", "direct_function", "keyword_baseline"]
LABELS = {
    "ours": "Ours (intent-grounded)",
    "react": "ReAct",
    "direct_fc": "Direct function calling",
    "ours_noverify": "Ours w/o verifier",
    "ours_noclarify": "Ours w/o clarification",
    "intent_grounded": "Rule-based intent agent (prototype)",
    "direct_function": "Rule-based direct agent (prototype)",
    "keyword_baseline": "Keyword baseline (non-LLM floor)",
}
# Categorical slots 1-4 of the validated reference palette (light surface), fixed order.
COLORS = {"ours": "#2a78d6", "react": "#eb6834", "direct_fc": "#1baf7a", "intent_grounded": "#eda100"}
VARIANT_ORDER = ["high", "medium", "low"]
CATEGORY_ORDER = ["explicit", "constrained", "goal", "recovery"]


def load(dir_: Path):
    path = dir_ / "trials.jsonl"
    if not path.exists():
        return None
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def load_trajectories(dir_: Path):
    path = dir_ / "trajectories.jsonl"
    out = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            out[(row["scenario_id"], row["variant"], row["run"])] = row
    return out


def scored(trials):
    return [t for t in trials if not t["infra_failure"]]


def macro(trials, **filters):
    rows = [t for t in scored(trials) if all(t[k] == v for k, v in filters.items())]
    per = per_scenario_success(rows)
    return (mean(per.values()), bootstrap_ci(list(per.values()))) if per else (None, None)


def pct(value):
    return "–" if value is None else f"{100 * value:.1f}"


def ci_str(ci):
    return "–" if not ci else f"[{100 * ci[0]:.0f}, {100 * ci[1]:.0f}]"


def cost(trials, model):
    return sum(estimate_cost_usd(model, t["input_tokens"], t.get("cached_input_tokens", 0), t["output_tokens"])
               for t in trials)


def failure_modes(trial):
    modes = set()
    for p in trial["predicates"]:
        if p["passed"]:
            continue
        pid = p["id"]
        if pid.startswith("interaction:"):
            modes.add("missed required clarification")
        elif pid == "budget":
            modes.add("over budget")
        elif pid == "only_allowed_products":
            modes.add("extra / disallowed product")
        elif pid == "no_unavailable_sku":
            modes.add("unavailable SKU kept")
        elif pid == "preserve_initial":
            modes.add("removed items it had to keep")
        elif pid.startswith("all_items"):
            modes.add("dietary rule violated on some item")
        elif pid.startswith("need:"):
            m = re.search(r"=(\d+), required \[(\d+), (\d+|None)\]", p["detail"])
            if m and m.group(3) != "None" and int(m.group(1)) > int(m.group(3)):
                modes.add("quantity above bound")
            elif m and int(m.group(1)) == 0:
                modes.add("need missing entirely")
            else:
                modes.add("quantity below bound")
    return modes


def grouped_bar(path_stem, systems, data, groups, title, xlabel):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#3d3d3a",
                         "xtick.color": "#3d3d3a", "ytick.color": "#3d3d3a"})
    fig, ax = plt.subplots(figsize=(6.5, 3.2), dpi=200)
    n = len(systems)
    width = 0.8 / n
    for i, system in enumerate(systems):
        xs = [g + (i - (n - 1) / 2) * width for g in range(len(groups))]
        values = [data[system][grp][0] or 0 for grp in groups]
        cis = [data[system][grp][1] for grp in groups]
        ax.bar(xs, [100 * v for v in values], width=width - 0.02, color=COLORS.get(system, "#888"),
               label=LABELS[system], edgecolor="white", linewidth=1)
        for x, v, ci in zip(xs, values, cis):
            if ci:
                ax.plot([x, x], [100 * ci[0], 100 * ci[1]], color="#5f5e5a", linewidth=0.8)
            top = 100 * max(v, ci[1] if ci else v)
            ax.text(x, top + 1.5, f"{100 * v:.0f}", ha="center", va="bottom", fontsize=6, color="#3d3d3a")
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Macro success (%)")
    ax.set_ylim(0, 112)
    ax.yaxis.grid(True, color="#e8e7e2", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title(title, fontsize=9, loc="left", color="#1f1f1d")
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    fig.tight_layout()
    fig.savefig(path_stem.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path_stem.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)


def render_trace(row, trial, max_steps=40):
    lines = [f"Scenario {trial['scenario_id']} ({trial['category']}, {trial['difficulty']}), variant `{trial['variant']}`, "
             f"run {trial['run']}: **{'SUCCESS' if trial['success'] else 'FAIL'}**, total {trial['total_cents']} cents, "
             f"{trial['tool_calls']} tool calls, {trial['model_calls']} model calls"]
    notes = row.get("agent_notes") or {}
    if notes.get("intent"):
        reqs = [f"{r['id']}: {r['description']} [{r['measure']} {r['min']}-{r['max']}"
                f"{', tags=' + ','.join(r['required_tags']) if r['required_tags'] else ''}]"
                for r in notes["intent"]["requirements"]]
        lines.append("Extracted intent: " + "; ".join(reqs) +
                     (f"; budget={notes['intent']['budget_cents']}" if notes["intent"].get("budget_cents") else ""))
    for c in notes.get("clarifications") or []:
        lines.append(f"Clarification: Q: {c['question']} / A: {c['answer']}")
    lines.append("```")
    for step in row["trajectory"][:max_steps]:
        if step.get("tool") is None:
            lines.append(f"-- terminated: {step.get('reason')}")
            continue
        args = json.dumps(step["args"])
        lines.append(f"{step['step']:>2} {step['tool']}({args}) -> {'ok' if step['ok'] else 'FAIL'}: {step['message'][:90]}")
    if len(row["trajectory"]) > max_steps:
        lines.append(f"... ({len(row['trajectory']) - max_steps} more steps)")
    lines.append("```")
    for i, rep in enumerate(notes.get("verify_reports") or [], 1):
        lines.append(f"Verifier round {i}: " + ("no violations" if not rep["violations"] else "; ".join(rep["violations"])))
    failed = [f"{p['id']} ({p['detail']})" for p in trial["predicates"] if not p["passed"]]
    if failed:
        lines.append("Failed predicates: " + "; ".join(failed))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="deepseek-flash", help="results/llm/<tag>")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "agent_paper")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    llm_root = ROOT / "results" / "llm" / args.tag
    data = {name: load(llm_root / name) for name in set(MAIN + ABLATIONS)}
    data.update({name: load(ROOT / "results" / "bench" / name) for name in PILOT})
    data = {k: v for k, v in data.items() if v}
    present = [s for s in MAIN + PILOT if s in data]
    md = [f"# Agent paper results ({args.tag})", ""]

    # ---------------------------------------------------------- main table
    md += ["## Main results", "",
           "| System | Runs/inst. | Macro success % [95% CI] | Coverage % | Hard-violation % | Missed clarif. % | Unneeded clarif. % "
           "| Tool calls | Model calls | Tokens in/out (k) | Cost/episode (USD) |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    tex_rows = []
    for name in present:
        trials = scored(data[name])
        s, ci = macro(trials)
        runs = max(t["run"] for t in trials)
        req = [t for t in trials if t["required_clarification_missed"] is not None]
        is_llm = name in MAIN + ABLATIONS
        c = cost(trials, args.model) / len(trials) if is_llm else 0
        row = [LABELS[name], str(runs), f"{pct(s)} {ci_str(ci)}", pct(mean(t["coverage"] for t in trials)),
               pct(mean(float(t["hard_satisfaction"] < 1) for t in trials)),
               pct(mean(float(t["required_clarification_missed"]) for t in req)) if req else "–",
               pct(mean(float(t["unnecessary_clarifications"] > 0) for t in trials)),
               f"{mean(t['tool_calls'] for t in trials):.1f}", f"{mean(t['model_calls'] for t in trials):.1f}",
               f"{mean(t['input_tokens'] for t in trials) / 1000:.0f}/{mean(t['output_tokens'] for t in trials) / 1000:.1f}"
               if is_llm else "–",
               f"{c:.4f}" if is_llm else "–"]
        md.append("| " + " | ".join(row) + " |")
        tex_rows.append(" & ".join([row[0], row[2].replace("[", "{\\scriptsize[").replace("]", "]}"), row[3], row[4],
                                    row[7], row[8]]) + r" \\")
        infra = len(data[name]) - len(trials)
        if infra:
            md.append(f"| ↳ {infra} infrastructure failures excluded | | | | | | | | | | |")
    md += ["", "Macro success averages each scenario's mean over variants and runs, then over the 20 scenarios; "
           "CIs bootstrap whole scenarios (2,000 resamples). Rule-based rows are deterministic pilot references.", ""]
    (args.out / "results_table.tex").write_text(
        "\\begin{tabular}{lccccc}\n\\toprule\nSystem & Success (\\%) & Coverage & Hard viol. & Tool calls & Model calls \\\\\n"
        "\\midrule\n" + "\n".join(r.replace("%", "\\%") for r in tex_rows) + "\n\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8")

    # ------------------------------------------------------ breakdowns
    for field, order, title in [("variant", VARIANT_ORDER, "instruction specificity"),
                                ("category", CATEGORY_ORDER, "task category"),
                                ("difficulty", ["E", "M", "H"], "difficulty")]:
        md += [f"## Success by {title} (macro %, 95% CI)", "",
               "| System | " + " | ".join(order) + " |", "|---|" + "---|" * len(order)]
        for name in present:
            cells = []
            for value in order:
                s, ci = macro(data[name], **{field: value})
                cells.append(f"{pct(s)} {ci_str(ci)}")
            md.append(f"| {LABELS[name]} | " + " | ".join(cells) + " |")
        md.append("")

    # ------------------------------------------------------ per scenario
    md += ["## Per-scenario success (%)", "", "| Scenario | " + " | ".join(LABELS[n] for n in present) + " |",
           "|---|" + "---|" * len(present)]
    per = {n: per_scenario_success(data[n]) for n in present}
    for sid in sorted(per[present[0]]):
        md.append(f"| {sid} | " + " | ".join(pct(per[n].get(sid)) for n in present) + " |")
    md.append("")

    # ------------------------------------------------------ paired tests
    if "ours" in data:
        md += ["## Paired comparisons (Ours − other, macro success, scenario bootstrap)", "",
               "| Comparison | Δ (pp) | 95% CI (pp) |", "|---|---|---|"]
        for other in ["react", "direct_fc", "ours_noverify", "ours_noclarify", "intent_grounded"]:
            if other in data:
                comp = compare_systems(scored(data["ours"]), scored(data[other]))
                ci = comp["ci95"]
                scope = "" if comp["n_scenarios"] == 20 else f" (scenarios: {comp['n_scenarios']})"
                md.append(f"| Ours − {LABELS[other]}{scope} | {100 * comp['mean_difference']:+.1f} | "
                          f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}] |")
        md.append("")

    # ------------------------------------------------------ ablations
    abl = [a for a in ABLATIONS if a in data]
    if len(abl) > 1:
        md += ["## Ablations", "", "| Variant | Runs | Macro success % [CI] | Missed clarif. % | Verify rounds | Model calls |",
               "|---|---|---|---|---|---|"]
        for name in abl:
            trials = scored(data[name])
            s, ci = macro(trials)
            req = [t for t in trials if t["required_clarification_missed"] is not None]
            md.append(f"| {LABELS[name]} | {max(t['run'] for t in trials)} | {pct(s)} {ci_str(ci)} | "
                      f"{pct(mean(float(t['required_clarification_missed']) for t in req)) if req else '–'} | – | "
                      f"{mean(t['model_calls'] for t in trials):.1f} |")
        md += ["", "Note: ablations may use fewer runs than the main condition; compare against Ours with the same runs.", ""]

    # ------------------------------------------------------ failure taxonomy
    md += ["## Failure taxonomy (share of failed trials showing each mode; multi-label)", ""]
    systems_f = [n for n in present if n in data]
    counts = {n: Counter() for n in systems_f}
    totals = {}
    for n in systems_f:
        failed = [t for t in scored(data[n]) if not t["success"]]
        totals[n] = len(failed)
        for t in failed:
            counts[n].update(failure_modes(t))
    modes = sorted({m for c in counts.values() for m in c}, key=lambda m: -sum(c[m] for c in counts.values()))
    md += ["| Failure mode | " + " | ".join(f"{LABELS[n]} (n={totals[n]})" for n in systems_f) + " |",
           "|---|" + "---|" * len(systems_f)]
    for mode in modes:
        md.append(f"| {mode} | " + " | ".join(pct(counts[n][mode] / totals[n]) if totals[n] else "–" for n in systems_f) + " |")
    md.append("")

    # ------------------------------------------------------ termination + cost
    md += ["## Termination reasons and cost", ""]
    for name in [n for n in dict.fromkeys(MAIN + ABLATIONS) if n in data]:
        reasons = Counter(t["termination_reason"] for t in data[name])
        md.append(f"- {LABELS[name]}: {dict(reasons)}; total est. cost ${cost(data[name], args.model):.2f} "
                  f"(peak pricing upper bound), mean runtime {mean(t['runtime_seconds'] for t in data[name]):.1f}s/episode")
    md.append("")
    (args.out / "results.md").write_text("\n".join(md), encoding="utf-8")

    # ------------------------------------------------------ figures
    fig_systems = [s for s in ["ours", "react", "direct_fc", "intent_grounded"] if s in data]
    for field, order, stem, xlabel in [("variant", VARIANT_ORDER, "fig_by_variant", "Instruction specificity"),
                                       ("category", CATEGORY_ORDER, "fig_by_category", "Task category")]:
        table = {s: {v: macro(data[s], **{field: v}) for v in order} for s in fig_systems}
        grouped_bar(args.out / stem, fig_systems, table, order, f"Macro success by {xlabel.lower()}", xlabel)

    # ------------------------------------------------------ qualitative examples
    ex = ["# Qualitative examples", ""]
    if "ours" in data:
        traj = load_trajectories(llm_root / "ours")
        other = {(t["scenario_id"], t["variant"], t["run"]): t for t in data.get("react", [])}
        ours_trials = scored(data["ours"])
        wins = [t for t in ours_trials if t["success"] and not other.get((t["scenario_id"], t["variant"], t["run"]), {}).get("success", 1)
                and t["difficulty"] == "H"]
        fails = [t for t in ours_trials if not t["success"]]
        picks = [("Success where ReAct failed", wins[:2]), ("Failures", fails[:2])]
        for title, chosen in picks:
            ex += [f"## {title}", ""]
            for t in chosen:
                ex += [render_trace(traj[(t["scenario_id"], t["variant"], t["run"])], t), ""]
                if title.startswith("Success"):
                    key = (t["scenario_id"], t["variant"], t["run"])
                    rtraj = load_trajectories(llm_root / "react").get(key)
                    if rtraj:
                        ex += ["ReAct on the same instance:", "", render_trace(rtraj, other[key], max_steps=25), ""]
    (args.out / "examples.md").write_text("\n".join(ex), encoding="utf-8")

    # ------------------------------------------------------ architecture
    try:
        from grocery_agent.llm_agents import build_ours_graph

        (args.out / "architecture.mmd").write_text(build_ours_graph().get_graph().draw_mermaid(), encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print("architecture export failed:", error)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
