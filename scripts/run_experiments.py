#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_agent.experiment import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the grocery agent benchmark")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    summary = run_experiment(args.output_dir, args.trials)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

