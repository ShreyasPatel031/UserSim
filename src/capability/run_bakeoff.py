"""Capability bakeoff runner — successive-halving plan + full benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import (
    ACTION_BUFFER,
    BAKEOFF_MODEL,
    MAX_ACTIONS,
    MAX_HUMAN_STEPS,
    OUT_DIR,
    location_for,
)
from capability.browser_use_runner import run_browser_use, task_wall_timeout_s
from capability.gcs_checkpoint import restore_manifest, restore_traces, upload_trace_dir
from capability.manifest import rebuild_manifest, upsert_run, write_manifest
from capability.manifest_writer import ManifestWriter
from capability.native_cu import run_native_cu
from capability.site_preflight import KNOWN_BLOCKED_WEBSITES
from capability.tasks import (
    ALL_INDICES,
    BAKEOFF5_INDICES,
    FULL8_INDICES,
    FULL80_INDICES,
    GENUINE_FAIL_INDICES,
    HARD20_INDICES,
    SMOKE_INDICES,
    TASK_INDICES,
    load_tasks,
    load_product_tasks,
)


RUNNERS = {
    "native_cu": run_native_cu,
    "browser_use": run_browser_use,
}


def _model_slug(model: str) -> str:
    return model.replace(".", "").replace("/", "-")


def _err_result(task: dict, model: str, h: str, exc: Exception) -> dict:
    return {
        "run_id": f"err_{task['eval_index']}",
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": h,
        "success": False,
        "status": "FAILURE",
        "failure_category": "HARNESS",
        "stop_reason": f"exception:{exc}"[:400],
        "num_actions": 0,
        "actions": [],
        "estimated_cost_usd": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "final_url": "",
    }


def _save_manifest(name: str, runs: list[dict], *, model: str, stage: str, harness: str) -> Path:
    from collections import Counter

    path = OUT_DIR / f"{name}.json"
    eligible = [r for r in runs if r.get("status") != "BLOCKED"]
    successes_eligible = sum(1 for r in eligible if r.get("success"))
    summary = {
        "stage": stage,
        "harness": harness if harness != "browser_use" else "browser_use_oss",
        "provider": "vertex",
        "model": model,
        "location": location_for(model),
        "max_actions_budget": (runs[0].get("max_actions_budget") if runs else MAX_ACTIONS),
        "max_human_steps": MAX_HUMAN_STEPS,
        "action_buffer": ACTION_BUFFER,
        "n": len(runs),
        "n_total": len(runs),
        "n_eligible": len(eligible),
        "successes": sum(1 for r in runs if r.get("success")),
        "successes_eligible": successes_eligible,
        "success_rate_eligible": round(successes_eligible / max(1, len(eligible)), 4),
        "by_status": dict(Counter(r.get("status") for r in runs)),
        "by_harness": {},
        "total_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 4),
        "runs": runs,
    }
    for h in sorted({r.get("harness") for r in runs}):
        subset = [r for r in runs if r.get("harness") == h]
        summary["by_harness"][h] = {
            "n": len(subset),
            "success": sum(1 for r in subset if r.get("success")),
            "avg_actions": round(
                sum(r.get("num_actions") or 0 for r in subset) / max(1, len(subset)), 2
            ),
            "cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in subset), 4),
            "failures": dict(Counter(r.get("failure_category") for r in subset if not r.get("success"))),
        }
    path.write_text(json.dumps(summary, indent=2, default=str))
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "model",
                    "max_actions_budget",
                    "n",
                    "n_eligible",
                    "successes",
                    "successes_eligible",
                    "success_rate_eligible",
                    "by_status",
                    "total_cost_usd",
                )
            },
            indent=2,
        ),
        flush=True,
    )
    return path


def _known_blocked_stub(task: dict, model: str, harness: str) -> dict:
    return {
        "run_id": f"skip_{task['eval_index']}",
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss" if harness == "browser_use" else harness,
        "provider": "vertex",
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


def _wall_timeout_stub(task: dict, model: str, harness: str, timeout_s: float) -> dict:
    run_dir = OUT_DIR / "traces" / f"bu_{task['eval_index']}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "run_id": f"wall_{task['eval_index']}_{uuid.uuid4().hex[:8]}",
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss" if harness == "browser_use" else harness,
        "provider": "vertex",
        "start_url": task["start_url"],
        "success": False,
        "status": "FAILURE",
        "failure_category": "HARNESS",
        "stop_reason": f"worker_wall_timeout:{int(timeout_s)}s",
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


def _run_one(
    h: str,
    task: dict,
    model: str,
    max_actions: int,
    *,
    preflight: bool,
) -> dict:
    print(
        f"START {h} | {task['website']} | idx={task['eval_index']} | max_actions={max_actions}",
        flush=True,
    )
    try:
        if h == "browser_use":
            result = run_browser_use(
                task, model=model, max_actions=max_actions, preflight=preflight
            )
        else:
            result = RUNNERS[h](
                task, model=model, location=location_for(model), max_actions=max_actions
            )
    except TypeError:
        try:
            result = RUNNERS[h](task, model=model, max_actions=max_actions)
        except TypeError:
            try:
                result = RUNNERS[h](task, model=model)
            except Exception as exc:  # noqa: BLE001
                result = _err_result(task, model, h, exc)
        except Exception as exc:  # noqa: BLE001
            result = _err_result(task, model, h, exc)
    except Exception as exc:  # noqa: BLE001
        result = _err_result(task, model, h, exc)
    result["max_actions_budget"] = max_actions
    print(
        f"DONE  {h} | {task['website']} | idx={task['eval_index']} | {result.get('status')} "
        f"success={result.get('success')} actions={result.get('num_actions')} "
        f"cost=${result.get('estimated_cost_usd', 0):.3f}",
        flush=True,
    )
    return result


def _run_browser_use_fleet(
    tasks: list[dict],
    *,
    stage: str,
    model: str,
    max_actions: int,
    workers: int,
    out_path: Path,
    log_path: Path,
    preflight: bool,
    skip_known_blocked: bool,
    resume: bool,
    rebuild: bool,
) -> int:
    runs: list[dict] = []
    if resume or rebuild:
        restore_manifest(out_path)
        restore_traces(OUT_DIR / "traces")
        runs = rebuild_manifest(
            out_path,
            stage=stage,
            model=model,
            max_actions=max_actions,
            tasks=tasks,
            log_path=log_path if log_path.is_file() else None,
            harness="browser_use",
        )
        if runs:
            write_manifest(
                out_path,
                runs,
                stage=stage,
                model=model,
                max_actions=max_actions,
                harness="browser_use",
                slim=True,
            )
            print(f"Rebuild: {len(runs)} runs merged -> {out_path.name}", flush=True)
        elif out_path.is_file():
            prev = json.loads(out_path.read_text())
            runs = list(prev.get("runs") or [])
            print(f"Resume: {len(runs)} runs from {out_path.name}", flush=True)

    if rebuild and not resume:
        return 0

    done: set[int | str] = {r.get("eval_index") for r in runs}
    pending = [t for t in tasks if t["eval_index"] not in done]
    workers = max(1, min(workers, len(pending) or 1))

    lock = threading.Lock()
    writer = ManifestWriter(
        out_path,
        stage=stage,
        model=model,
        max_actions=max_actions,
        runs=runs,
        lock=lock,
    )

    if skip_known_blocked:
        skipped = [t for t in pending if t["website"] in KNOWN_BLOCKED_WEBSITES]
        pending = [t for t in pending if t["website"] not in KNOWN_BLOCKED_WEBSITES]
        for t in skipped:
            stub = _known_blocked_stub(t, model, "browser_use")
            stub["max_actions_budget"] = max_actions
            stub["created_at"] = datetime.now(timezone.utc).isoformat()
            with lock:
                upsert_run(runs, stub)
            done.add(t["eval_index"])
            print(
                f"SKIP  browser_use | {t['website']} | idx={t['eval_index']} | known_blocked",
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
        try:
            upload_trace_dir(row.get("trace_dir"))
        except Exception as exc:  # noqa: BLE001
            print(f"WARN trace checkpoint failed: {exc}", flush=True)

    if not pending:
        writer.flush()
        print("Nothing to run.", flush=True)
        return 0

    print(
        f"Browser Use fleet | {len(pending)}/{len(tasks)} tasks | workers={workers} | "
        f"model={model} -> {out_path.name}",
        flush=True,
    )

    if workers == 1:
        for t in pending:
            _on_done(_run_one("browser_use", t, model, max_actions, preflight=preflight))
    else:
        wall_s = task_wall_timeout_s(max_actions)
        grace_s = 60.0
        deadline_by_fut: dict = {}
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futs = []
            for t in pending:
                fut = pool.submit(
                    _run_one, "browser_use", t, model, max_actions, preflight=preflight
                )
                deadline_by_fut[fut] = time.monotonic() + wall_s + grace_s
                fut._task_ref = t  # type: ignore[attr-defined]
                futs.append(fut)
            pending_futs = set(futs)
            while pending_futs:
                done_futs, pending_futs = wait(
                    pending_futs, timeout=15.0, return_when=FIRST_COMPLETED
                )
                now = time.monotonic()
                for fut in done_futs:
                    deadline_by_fut.pop(fut, None)
                    try:
                        _on_done(fut.result())
                    except Exception as exc:  # noqa: BLE001
                        t = getattr(fut, "_task_ref", None)
                        if t is not None:
                            _on_done(_err_result(t, model, "browser_use", exc))
                overdue = [f for f in list(pending_futs) if now > deadline_by_fut.get(f, now)]
                for fut in overdue:
                    pending_futs.discard(fut)
                    deadline_by_fut.pop(fut, None)
                    t = getattr(fut, "_task_ref", None)
                    fut.cancel()
                    if t is not None:
                        print(
                            f"KILL   browser_use | {t['website']} | idx={t['eval_index']} | "
                            f"worker_wall_timeout={int(wall_s)}s",
                            flush=True,
                        )
                        stub = _wall_timeout_stub(t, model, "browser_use", wall_s)
                        stub["max_actions_budget"] = max_actions
                        _on_done(stub)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    writer.flush()
    print(f"Wrote {out_path}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage",
        required=True,
        help=(
            "smoke|bakeoff5|full8|...|product_all|product_persona|"
            "product_persona_p1|product_full270|product_full270_bland|..."
        ),
    )
    ap.add_argument("--harness", choices=["native_cu", "browser_use", "both"], default="both")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--eval-index", type=int, default=None)
    ap.add_argument(
        "--eval-indices",
        default=None,
        help="Comma-separated eval_index list (overrides --stage task selection)",
    )
    ap.add_argument(
        "--max-actions",
        type=int,
        default=None,
        help=(
            f"Override step budget (default derived: max_human={MAX_HUMAN_STEPS}"
            f"+buffer={ACTION_BUFFER} => {MAX_ACTIONS})."
        ),
    )
    ap.add_argument("--workers", type=int, default=1, help="Parallel task workers (ThreadPool).")
    ap.add_argument("--tag", default=None, help="Optional suffix for output filename.")
    ap.add_argument("--shard-id", type=int, default=None, help="Fleet shard index (0-based)")
    ap.add_argument("--num-shards", type=int, default=None, help="Total fleet shards")
    ap.add_argument("--resume", action="store_true", help="Skip finished eval_index+harness pairs.")
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="Merge manifest from traces + log DONE lines, then exit (or continue with --resume)",
    )
    ap.add_argument(
        "--skip-known-blocked",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Skip websites on KNOWN_BLOCKED_WEBSITES (uniqlo, apartments) without trying",
    )
    ap.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Check start URL for WAF/CAPTCHA before agent loop",
    )
    args = ap.parse_args()
    max_actions = args.max_actions if args.max_actions is not None else MAX_ACTIONS

    if args.eval_indices:
        indices = [int(x.strip()) for x in args.eval_indices.split(",") if x.strip()]
    elif args.stage == "smoke":
        indices = SMOKE_INDICES
    elif args.stage == "bakeoff5":
        indices = BAKEOFF5_INDICES
    elif args.stage == "full8":
        indices = FULL8_INDICES
    elif args.stage == "full10":
        indices = TASK_INDICES
    elif args.stage == "full80":
        indices = FULL80_INDICES
    elif args.stage == "full100":
        indices = ALL_INDICES
    elif args.stage == "hard20":
        indices = HARD20_INDICES
    elif args.stage == "genuine27":
        indices = GENUINE_FAIL_INDICES
    elif args.stage.startswith("product_"):
        tasks = load_product_tasks(args.stage)
        if args.shard_id is not None:
            tasks = [t for i, t in enumerate(tasks) if i % args.num_shards == args.shard_id]
        tag = args.tag or f"{_model_slug(args.model)}_m{max_actions}"
        out_name = f"{args.stage}_{args.harness}_{tag}"
        out_path = OUT_DIR / f"{out_name}.json"
        log_path = OUT_DIR / f"{out_name}_run.log"
        if args.harness in ("both", "browser_use"):
            return _run_browser_use_fleet(
                tasks,
                stage=args.stage,
                model=args.model,
                max_actions=max_actions,
                workers=args.workers,
                out_path=out_path,
                log_path=log_path,
                preflight=False,
                skip_known_blocked=False,
                resume=args.resume,
                rebuild=args.rebuild,
            )
        indices = [t["eval_index"] for t in tasks]
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
        if args.harness == "both":
            args.harness = "browser_use"

    tasks = load_tasks(indices)
    harnesses = (
        ["native_cu", "browser_use"] if args.harness == "both" else [args.harness]
    )

    tag = args.tag or f"{_model_slug(args.model)}_m{max_actions}"
    out_name = f"{args.stage}_{args.harness}_{tag}"
    out_path = OUT_DIR / f"{out_name}.json"
    log_path = OUT_DIR / f"{out_name}_run.log"

    fleet_mode = args.harness == "browser_use" and (
        args.shard_id is not None or args.resume or args.rebuild or args.skip_known_blocked
    )
    if fleet_mode and len(harnesses) == 1:
        return _run_browser_use_fleet(
            tasks,
            stage=args.stage,
            model=args.model,
            max_actions=max_actions,
            workers=args.workers,
            out_path=out_path,
            log_path=log_path,
            preflight=args.preflight,
            skip_known_blocked=args.skip_known_blocked,
            resume=args.resume,
            rebuild=args.rebuild,
        )

    jobs = [(h, task) for task in tasks for h in harnesses]

    runs: list[dict] = []
    done_keys: set[tuple] = set()
    if args.resume and out_path.exists():
        prev = json.loads(out_path.read_text())
        runs = list(prev.get("runs") or [])
        for r in runs:
            h = r.get("harness")
            if h == "browser_use_oss":
                done_keys.add((r.get("eval_index"), "browser_use"))
            else:
                done_keys.add((r.get("eval_index"), h))
        print(f"Resume: loaded {len(runs)} existing runs from {out_path.name}", flush=True)

    pending = [(h, t) for h, t in jobs if (t["eval_index"], h) not in done_keys]
    workers = max(1, min(args.workers, max(1, len(pending))))
    print(
        f"Running {len(pending)}/{len(jobs)} jobs with {workers} workers | model={args.model} "
        f"location={location_for(args.model)} max_actions={max_actions} "
        f"(human_max={MAX_HUMAN_STEPS}+buffer={ACTION_BUFFER}) -> {out_name}.json",
        flush=True,
    )

    lock = threading.Lock()
    harness_order = {h: i for i, h in enumerate(harnesses)}

    def _persist() -> None:
        with lock:
            ordered = sorted(
                runs,
                key=lambda r: (
                    r.get("eval_index", 0),
                    harness_order.get(
                        "browser_use" if r.get("harness") == "browser_use_oss" else r.get("harness"),
                        0,
                    ),
                ),
            )
            _save_manifest(
                out_name, ordered, model=args.model, stage=args.stage, harness=args.harness
            )

    def _on_done(result: dict) -> None:
        with lock:
            runs.append(result)
            n = len(runs)
            ok = sum(1 for r in runs if r.get("success"))
            cost = sum(float(r.get("estimated_cost_usd") or 0) for r in runs)
        print(f"PROGRESS {n}/{len(jobs)} success={ok} cost=${cost:.2f}", flush=True)
        if n % 5 == 0 or n == len(jobs):
            _persist()

    if not pending:
        print("Nothing to run (all jobs already present).", flush=True)
        _persist()
        return 0

    if workers == 1:
        for h, task in pending:
            _on_done(_run_one(h, task, args.model, max_actions, preflight=args.preflight))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_run_one, h, task, args.model, max_actions, preflight=args.preflight)
                for h, task in pending
            ]
            for fut in as_completed(futs):
                _on_done(fut.result())

    _persist()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
