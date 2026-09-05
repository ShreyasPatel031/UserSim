"""Launch the UserSim video experiment as parallel Runloop Devboxes.

Required local environment:
  RUNLOOP_API_KEY          authenticates the Runloop SDK
  USERSIM_REPO_URL         repository URL visible to the Devbox

Required Runloop account secrets (values are never read by this launcher):
  USERSIM_GITHUB_TOKEN     injected as GITHUB_TOKEN
  USERSIM_GOOGLE_ADC_JSON  injected as GOOGLE_ADC_JSON

The Google secret must contain a service-account/ADC JSON value with only the
Vertex AI permissions needed by the experiment. YouTube browser state is not a
fleet-wide secret: attach an authenticated profile to dedicated trusted seeds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from runloop_api_client import AsyncRunloopSDK


@dataclass
class ShardResult:
    shard_id: int
    devbox_id: str
    exit_code: int | None
    stdout: str
    stderr: str


def command_for(args: argparse.Namespace, shard_id: int) -> str:
    repo = shlex.quote(args.repo_url)
    state = shlex.quote(args.youtube_state)
    out = f"results/runloop_video/shard_{shard_id}"
    return " && ".join(
        [
            "set -euo pipefail",
            "printf '%s' \"$GOOGLE_ADC_JSON\" > /tmp/google-adc.json",
            "chmod 600 /tmp/google-adc.json",
            "export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-adc.json",
            "export PYTHONPATH=src:.",
            "export MVP_CHROME_PATH=$(command -v chromium-browser || command -v chromium)",
            "gh auth setup-git",
            f"git clone --depth 1 {repo} ~/usersim",
            "cd ~/usersim",
            f"mkdir -p {shlex.quote(out)}",
            (
                "python scripts/runloop/video_experiment_shard_runloop.py "
                f"--shard-id {shard_id} --num-shards {args.shards} "
                f"--workers {args.workers} --max-steps {args.max_steps} "
                f"--state {state} --out-dir {shlex.quote(out)} "
                f"--trace-dir {shlex.quote(out + '/traces')}"
            ),
            "rm -f /tmp/google-adc.json",
        ]
    )


async def run_shard(
    sdk: AsyncRunloopSDK, args: argparse.Namespace, shard_id: int
) -> ShardResult:
    devbox = await sdk.devbox.create(
        name=f"usersim-video-{args.run_id}-{shard_id:02d}",
        blueprint_name=args.blueprint,
        secrets={
            "GITHUB_TOKEN": args.github_secret,
            "GOOGLE_ADC_JSON": args.google_secret,
        },
    )
    try:
        execution = await devbox.cmd.exec(command=command_for(args, shard_id))
        return ShardResult(
            shard_id=shard_id,
            devbox_id=devbox.id,
            exit_code=execution.exit_code,
            stdout=await execution.stdout(),
            stderr=await execution.stderr(),
        )
    finally:
        if not args.keep:
            await devbox.shutdown()


async def main_async(args: argparse.Namespace) -> int:
    sdk = AsyncRunloopSDK()
    started = time.monotonic()
    results = await asyncio.gather(
        *(run_shard(sdk, args, shard) for shard in range(args.shards)),
        return_exceptions=True,
    )
    rows = []
    for shard_id, result in enumerate(results):
        if isinstance(result, Exception):
            rows.append({"shard_id": shard_id, "error": f"{type(result).__name__}: {result}"})
        else:
            rows.append(asdict(result))
    summary = {
        "run_id": args.run_id,
        "blueprint": args.blueprint,
        "shards": args.shards,
        "workers_per_shard": args.workers,
        "elapsed_s": round(time.monotonic() - started, 3),
        "ok": sum(row.get("exit_code") == 0 for row in rows),
        "results": rows,
    }
    target = Path(args.summary)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary["ok"] == args.shards else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blueprint", default="usersim-video-v1")
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--repo-url", default=os.environ.get("USERSIM_REPO_URL", ""))
    parser.add_argument("--shards", type=int, default=12)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=18)
    parser.add_argument("--youtube-state", default="secrets/site_states/www.youtube.com.json")
    parser.add_argument("--github-secret", default="USERSIM_GITHUB_TOKEN")
    parser.add_argument("--google-secret", default="USERSIM_GOOGLE_ADC_JSON")
    parser.add_argument("--summary", default="results/runloop_video/latest.json")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if not args.repo_url:
        parser.error("--repo-url or USERSIM_REPO_URL is required")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
