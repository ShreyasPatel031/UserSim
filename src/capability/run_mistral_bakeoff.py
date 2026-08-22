"""Mistral API + Browser Use bakeoff (full10 / smoke / etc.).

Agent = Mistral (ChatOpenAI @ api.mistral.ai). Judge stays gemini-2.5-flash.
Do NOT use capability.run_bakeoff for Mistral evals — that defaults to Vertex Gemini.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import MAX_ACTIONS, OUT_DIR
from capability.browser_use_harness import browser_use_arm, stage1_enabled
from capability.manifest import rebuild_manifest, upsert_run, write_manifest
from capability.manifest_writer import ManifestWriter
from capability.mistral_browser_use_runner import run_mistral_browser_use
from capability.mistral_config import DEFAULT_MISTRAL_MODEL
from capability.browserbase_client import browserbase_enabled, browserbase_max_workers
from capability.site_preflight import KNOWN_BLOCKED_WEBSITES
from capability.tasks import (
    ALL_INDICES,
    BAKEOFF5_INDICES,
    SMOKE_INDICES,
    TASK_INDICES,
    load_tasks,
)


def _model_slug(model: str) -> str:
    return model.replace(".", "").replace("/", "-")


def _err(task: dict, model: str, exc: Exception) -> dict:
    run_id = f"err_{task['eval_index']}_{uuid.uuid4().hex[:8]}"
    run_dir = OUT_DIR / "traces" / f"mistral_{task['eval_index']}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "start_url": task["start_url"],
        "success": False,
        "status": "FAILURE",
        "failure_category": "HARNESS",
        "stop_reason": str(exc)[:400],
        "num_actions": 0,
        "actions": [],
        "estimated_cost_usd": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "final_url": task["start_url"],
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def _run_one(task: dict, model: str, max_actions: int, *, preflight: bool) -> dict:
    print(
        f"START mistral | {task['website']} | idx={task['eval_index']} | model={model}",
        flush=True,
    )
    try:
        result = run_mistral_browser_use(task, model=model, max_actions=max_actions, preflight=preflight)
    except Exception as exc:  # noqa: BLE001
        result = _err(task, model, exc)
    result["max_actions_budget"] = max_actions
    print(
        f"DONE  mistral | {task['website']} | idx={task['eval_index']} | {result.get('status')} "
        f"success={result.get('success')} actions={result.get('num_actions')} "
        f"cost=${float(result.get('estimated_cost_usd') or 0):.4f}",
        flush=True,
    )
    return result


def _known_blocked_stub(task: dict, model: str) -> dict:
    return {
        "run_id": f"skip_{task['eval_index']}",
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "success": False,
        "status": "BLOCKED",
        "failure_category": "BLOCKED",
        "stop_reason": "known_blocked_website",
        "num_actions": 0,
        "actions": [],
        "estimated_cost_usd": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "final_url": task["start_url"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mistral + Browser Use capability bakeoff")
    ap.add_argument(
        "--stage",
        choices=["smoke", "bakeoff5", "full10", "full100", "one"],
        default="full10",
    )
    ap.add_argument("--model", default=DEFAULT_MISTRAL_MODEL)
    ap.add_argument("--eval-index", type=int, default=None)
    ap.add_argument("--max-actions", type=int, default=MAX_ACTIONS)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--shard-id", type=int, default=None, help="Fleet shard index (0-based)")
    ap.add_argument("--num-shards", type=int, default=None, help="Total fleet shards")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="Merge manifest from traces + log DONE lines, then exit (or continue with --resume)",
    )
    ap.add_argument(
        "--skip-known-blocked",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip websites known blocked from this IP (uniqlo, apartments)",
    )
    ap.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Check start URL for WAF/CAPTCHA before agent loop (zero LLM cost if blocked)",
    )
    args = ap.parse_args()

    if args.stage == "smoke":
        indices = SMOKE_INDICES
    elif args.stage == "bakeoff5":
        indices = BAKEOFF5_INDICES
    elif args.stage == "full10":
        indices = TASK_INDICES
    elif args.stage == "full100":
        indices = ALL_INDICES
    else:
        if args.eval_index is None:
            raise SystemExit("--eval-index required for --stage one")
        indices = [args.eval_index]

    if (args.shard_id is None) ^ (args.num_shards is None):
        raise SystemExit("--shard-id and --num-shards must be used together")
    if args.shard_id is not None:
        if args.num_shards < 1 or not 0 <= args.shard_id < args.num_shards:
            raise SystemExit(f"shard-id must be in [0, {args.num_shards})")
        indices = [idx for i, idx in enumerate(indices) if i % args.num_shards == args.shard_id]

    tasks = load_tasks(indices)
    tag = args.tag or f"{_model_slug(args.model)}_m{args.max_actions}"
    arm = browser_use_arm()
    if args.tag is None and arm not in {"", "0"}:
        tag = f"{tag}_arm{arm}"
    if args.shard_id is not None and args.tag is None:
        tag = f"{tag}_shard{args.shard_id}"
    if stage1_enabled() and args.tag is None:
        tag = f"{tag}_stage1"
    out_name = f"{args.stage}_mistral_{tag}"
    out_path = OUT_DIR / f"{out_name}.json"
    log_path = OUT_DIR / f"{out_name}_run.log"

    runs: list[dict] = []
    if args.resume or args.rebuild:
        runs = rebuild_manifest(
            out_path,
            stage=args.stage,
            model=args.model,
            max_actions=args.max_actions,
            tasks=tasks,
            log_path=log_path if log_path.is_file() else None,
        )
        if runs:
            write_manifest(
                out_path,
                runs,
                stage=args.stage,
                model=args.model,
                max_actions=args.max_actions,
                slim=True,
            )
            print(f"Rebuild: {len(runs)} runs merged -> {out_path.name}", flush=True)
        elif out_path.is_file():
            prev = json.loads(out_path.read_text())
            runs = list(prev.get("runs") or [])
            print(f"Resume: {len(runs)} runs from {out_path.name}", flush=True)

    if args.rebuild and not args.resume:
        return 0

    done: set[int | str] = {r.get("eval_index") for r in runs}

    pending = [t for t in tasks if t["eval_index"] not in done]
    workers = browserbase_max_workers(args.workers) if browserbase_enabled() else args.workers
    workers = max(1, min(workers, len(pending) or 1))
    if browserbase_enabled() and workers < args.workers:
        print(
            f"Browserbase: capping workers {args.workers} -> {workers} "
            f"(max concurrent sessions)",
            flush=True,
        )
    print(
        f"Mistral bakeoff | {len(pending)}/{len(tasks)} tasks | workers={workers} | "
        f"model={args.model} -> {out_name}.json",
        flush=True,
    )

    lock = threading.Lock()
    writer = ManifestWriter(
        out_path,
        stage=args.stage,
        model=args.model,
        max_actions=args.max_actions,
        runs=runs,
        lock=lock,
    )

    if args.skip_known_blocked:
        skipped = [t for t in pending if t["website"] in KNOWN_BLOCKED_WEBSITES]
        pending = [t for t in pending if t["website"] not in KNOWN_BLOCKED_WEBSITES]
        for t in skipped:
            stub = _known_blocked_stub(t, args.model)
            stub["max_actions_budget"] = args.max_actions
            stub["created_at"] = datetime.now(timezone.utc).isoformat()
            with lock:
                upsert_run(runs, stub)
            done.add(t["eval_index"])
            print(
                f"SKIP  mistral | {t['website']} | idx={t['eval_index']} | known_blocked",
                flush=True,
            )
        if skipped:
            writer.request_save()

    def _on_done(row: dict) -> None:
        with lock:
            upsert_run(runs, row)
            n, ok = len(runs), sum(1 for r in runs if r.get("success"))
            cost = sum(float(r.get("estimated_cost_usd") or 0) for r in runs)
        print(f"PROGRESS {n}/{len(tasks)} success={ok} cost=${cost:.2f}", flush=True)
        writer.request_save()

    if not pending:
        writer.flush()
        print("Nothing to run.", flush=True)
        return 0

    if workers == 1:
        for t in pending:
            _on_done(_run_one(t, args.model, args.max_actions, preflight=args.preflight))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_run_one, t, args.model, args.max_actions, preflight=args.preflight)
                for t in pending
            ]
            for fut in as_completed(futs):
                _on_done(fut.result())

    writer.flush()
    print(f"Wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
