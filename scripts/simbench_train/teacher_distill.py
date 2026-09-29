#!/usr/bin/env python3
"""Teacher distillation script for SimBench distribution prediction.

Uses Vertex AI Claude Sonnet 5 to generate target distributions for the
distillation prompt pool. Includes:
- Hard USD cap with per-call cost ledger
- Resumable execution (saves progress to JSON)
- Official SimBench verbalized prompt format
- JSON parsing with the official parser

Usage:
  # Dry-run with mocked responses (no paid calls)
  python teacher_distill.py --dry-run --limit 5

  # Actual run with USD cap
  python teacher_distill.py --max-usd 50.0

  # Resume from checkpoint
  python teacher_distill.py --max-usd 50.0 --resume
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add eval kit to path for official parser
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "simbench_eval_kit"))

# Vertex AI pricing (as of 2026)
# Claude 3.7/5 Sonnet: $3.00/1M input, $15.00/1M output
SONNET_INPUT_COST_PER_TOKEN = 3.00 / 1_000_000
SONNET_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000
MAX_OUTPUT_TOKENS = 250


@dataclass
class CostLedger:
    """Track API costs with hard cap enforcement."""
    max_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    
    @property
    def total_usd(self) -> float:
        return (
            self.input_tokens * SONNET_INPUT_COST_PER_TOKEN +
            self.output_tokens * SONNET_OUTPUT_COST_PER_TOKEN
        )
    
    def can_afford(self, est_input: int = 500, est_output: int = 100) -> bool:
        est_cost = (
            est_input * SONNET_INPUT_COST_PER_TOKEN +
            est_output * SONNET_OUTPUT_COST_PER_TOKEN
        )
        return self.total_usd + est_cost <= self.max_usd
    
    def record(self, input_tokens: int, output_tokens: int):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        if self.total_usd > self.max_usd:
            raise BudgetExceeded(f"Budget exceeded: ${self.total_usd:.4f} > ${self.max_usd:.2f}")
    
    def to_dict(self) -> dict:
        return {
            "max_usd": self.max_usd,
            "spent_usd": round(self.total_usd, 4),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
        }


class BudgetExceeded(Exception):
    pass


def call_claude_vertex(
    system: str,
    user: str,
    model: str = "claude-sonnet-5@20260601",
    max_tokens: int = MAX_OUTPUT_TOKENS,
    dry_run: bool = False,
) -> tuple[str, int, int]:
    """Call Claude via Vertex AI anthropic SDK.
    
    Returns (response_text, input_tokens, output_tokens)
    """
    if dry_run:
        # Mock response for testing
        import random
        mock_keys = ["A", "B", "C", "D"][:random.randint(2, 4)]
        mock_dist = {k: random.randint(5, 50) for k in mock_keys}
        total = sum(mock_dist.values())
        mock_dist = {k: round(v * 100 / total) for k, v in mock_dist.items()}
        # Adjust to sum to 100
        diff = 100 - sum(mock_dist.values())
        if diff != 0:
            mock_dist[mock_keys[0]] += diff
        
        response = json.dumps(mock_dist)
        # Estimate tokens
        input_tokens = len(system.split()) + len(user.split())
        output_tokens = len(response.split())
        return response, input_tokens, output_tokens
    
    from anthropic import AnthropicVertex
    
    # Initialize client (uses ADC from GOOGLE_APPLICATION_CREDENTIALS)
    # Set GOOGLE_CLOUD_PROJECT and VERTEX_LOCATION env vars
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("VERTEX_LOCATION")
    
    if not project_id or not location:
        raise ValueError("Set GOOGLE_CLOUD_PROJECT and VERTEX_LOCATION environment variables")
    
    client = AnthropicVertex(project_id=project_id, region=location)
    
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    
    text = response.content[0].text if response.content else ""
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    
    return text, input_tokens, output_tokens


def parse_distribution(response: str, expected_keys: list[str]) -> Optional[dict]:
    """Parse response using official SimBench parser."""
    from simbench_common import parse_verbalized
    
    try:
        probs = parse_verbalized(response, expected_keys)
        return {k: round(p * 100) for k, p in zip(expected_keys, probs)}
    except Exception:
        return None


def run_distillation(
    pool_path: Path,
    output_path: Path,
    ledger: CostLedger,
    dry_run: bool = False,
    limit: int = 0,
    resume: bool = False,
):
    """Run teacher distillation on the prompt pool."""
    # Load pool
    with open(pool_path) as f:
        pool = [json.loads(line) for line in f if line.strip()]
    
    if limit > 0:
        pool = pool[:limit]
    
    # Load existing results if resuming
    completed = {}
    if resume and output_path.exists():
        with open(output_path) as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    completed[item["source_id"]] = item
        print(f"Resuming from {len(completed)} completed items")
    
    # Open output for appending
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    skipped = 0
    
    with open(output_path, "a" if resume else "w") as f:
        for i, item in enumerate(pool):
            source_id = item["source_id"]
            
            # Skip if already completed
            if source_id in completed:
                skipped += 1
                continue
            
            # Check budget
            if not ledger.can_afford():
                print(f"Budget limit reached after {i} items")
                break
            
            # Call teacher
            try:
                response, in_tok, out_tok = call_claude_vertex(
                    system=item["system"],
                    user=item["user_verbalized"],
                    dry_run=dry_run,
                )
                ledger.record(in_tok, out_tok)
                
                # Parse response
                parsed = parse_distribution(response, item["keys"])
                
                result = {
                    "source_id": source_id,
                    "source": item.get("source", "unknown"),
                    "keys": item["keys"],
                    "raw_response": response,
                    "teacher_dist": parsed,
                    "parse_ok": parsed is not None,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                }
                
                f.write(json.dumps(result) + "\n")
                f.flush()
                
                if parsed:
                    success += 1
                else:
                    failed += 1
                
                if (i + 1) % 10 == 0:
                    print(f"Progress: {i+1}/{len(pool)}, success={success}, failed={failed}, "
                          f"cost=${ledger.total_usd:.4f}")
                
            except BudgetExceeded:
                print(f"Budget exceeded at item {i}")
                break
            except Exception as e:
                print(f"Error at item {i}: {e}")
                failed += 1
                time.sleep(1)  # Rate limit backoff
    
    return {
        "total": len(pool),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "ledger": ledger.to_dict(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", default="/tmp/simbench_train_data/distill_pool.jsonl")
    parser.add_argument("--output", default="/tmp/simbench_train_data/teacher_responses.jsonl")
    parser.add_argument("--max-usd", type=float, default=0.0, help="Hard USD cap")
    parser.add_argument("--limit", type=int, default=0, help="Limit items to process")
    parser.add_argument("--dry-run", action="store_true", help="Use mocked responses")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    
    if not args.dry_run and args.max_usd <= 0:
        parser.error("--max-usd is required for actual runs (use --dry-run for testing)")
    
    pool_path = Path(args.pool)
    output_path = Path(args.output)
    
    if not pool_path.exists():
        parser.error(f"Pool file not found: {pool_path}")
    
    # Initialize ledger
    ledger = CostLedger(max_usd=args.max_usd if not args.dry_run else float("inf"))
    
    print(f"Starting teacher distillation")
    print(f"  Pool: {pool_path}")
    print(f"  Output: {output_path}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Max USD: ${args.max_usd:.2f}")
    print(f"  Limit: {args.limit or 'none'}")
    
    result = run_distillation(
        pool_path=pool_path,
        output_path=output_path,
        ledger=ledger,
        dry_run=args.dry_run,
        limit=args.limit,
        resume=args.resume,
    )
    
    print("\n" + "="*60)
    print("Distillation complete!")
    print(json.dumps(result, indent=2))
    
    # Save summary
    summary_path = output_path.with_suffix(".summary.json")
    with open(summary_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
