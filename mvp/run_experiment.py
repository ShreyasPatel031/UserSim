#!/usr/bin/env python3
"""Run a UserSim experiment from a spec file.

Usage:
  # Dry run (no real browsers):
  python mvp/run_experiment.py mvp/experiments/retell-study.json --dry-run

  # Live run with Browserbase:
  BROWSERBASE_API_KEY=... python mvp/run_experiment.py mvp/experiments/retell-study.json
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Load secrets if available
sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))


async def main():
    parser = argparse.ArgumentParser(description="Run a UserSim experiment")
    parser.add_argument("spec", type=Path, help="Path to experiment spec JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without real browsers")
    parser.add_argument("--max-concurrent", type=int, default=2, help="Max concurrent browser sessions")
    parser.add_argument("--no-save", action="store_true", help="Don't save results to disk")
    args = parser.parse_args()
    
    from mvp.experiment_runner import ExperimentSpec, ExperimentRunner
    
    if not args.spec.is_file():
        print(f"Error: Spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)
    
    spec = ExperimentSpec.from_file(args.spec)
    print(f"Loaded experiment: {spec.product_name} ({spec.id})")
    print(f"  Personas: {len(spec.personas)}")
    print(f"  Tasks: {len(spec.tasks)}")
    print(f"  Assignments: {len(spec.assignments)}")
    print(f"  Dry run: {args.dry_run}")
    print()
    
    def on_progress(msg, data):
        print(f"  → {msg}")
    
    runner = ExperimentRunner(
        spec,
        dry_run=args.dry_run,
        max_concurrent=args.max_concurrent,
        on_progress=on_progress,
    )
    
    result = await runner.run()
    
    print()
    print(f"Experiment complete: {result.status}")
    print(f"  Total runs: {len(result.agent_results)}")
    print(f"  Successes: {sum(1 for r in result.agent_results if r.get('success'))}")
    
    if not args.no_save:
        path = result.save()
        print(f"  Results saved to: {path}")
    
    # Print summary
    study = result.to_study_dict()
    print()
    print("=== Study Summary ===")
    print(json.dumps(study.get("summary", {}), indent=2))
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
