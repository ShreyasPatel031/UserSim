"""Parallel Vertex Gemini runner for SimBench (verbalized distributions).

Uses UserSim auth (ADC / Vertex). Defaults to high concurrency; backs off on 429.

Smoke:
  PYTHONPATH=src python -m human_sim.simbench_run --split Pop --limit 20 --workers 8

Full under $5:
  PYTHONPATH=src python -m human_sim.simbench_run --split both --model gemini-2.5-flash --max-spend 5 --workers 64
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types

from auth import invalidate_credentials, vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, RESULTS_DIR, ROOT
from human_sim.simbench_cost import PRICES, _generate_prompt

DATA = ROOT / "data" / "simbench"

_thread_local = threading.local()


def _client() -> genai.Client:
    c = getattr(_thread_local, "client", None)
    if c is None:
        c = genai.Client(
            vertexai=True,
            project=GCP_PROJECT,
            location=GCP_LOCATION,
            credentials=vertex_credentials(),
        )
        _thread_local.client = c
    return c


def _parse_dist(raw: str, keys: list[str]) -> dict[str, float] | None:
    try:
        m = re.search(r"\{[\s\S]*?\}", raw)
        if not m:
            return None
        data = json.loads(m.group(0))
        vals = {k: float(data[k]) for k in keys}
        s = sum(vals.values())
        if s <= 0:
            return None
        return {k: v / s for k, v in vals.items()}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _cost_usd(model: str, prompt_tok: int, output_tok: int) -> float:
    price = PRICES.get(model, PRICES["gemini-2.5-flash"])
    return prompt_tok / 1e6 * price["in"] + output_tok / 1e6 * price["out"]


def _is_throttle(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        m in text
        for m in (
            "429",
            "resource_exhausted",
            "resource exhausted",
            "quota",
            "rate limit",
            "too many requests",
            "503",
            "unavailable",
        )
    )


def _is_auth(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unauthenticated" in text or "401" in text or "invalid authentication" in text


def _one_call(model: str, system: str, user: str, temperature: float) -> tuple[str, int, int]:
    """Returns (raw_text, prompt_tokens, output_tokens). Retries throttles."""
    last: Exception | None = None
    for attempt in range(8):
        try:
            gen_cfg = types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=512,
                response_mime_type="application/json",
            )
            try:
                gen_cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass
            resp = _client().models.generate_content(
                model=model,
                contents=user,
                config=gen_cfg,
            )
            raw = (resp.text or "").strip()
            usage = getattr(resp, "usage_metadata", None)
            pt = int(getattr(usage, "prompt_token_count", 0) or 0)
            ot = int(getattr(usage, "candidates_token_count", 0) or 0)
            return raw, pt, ot
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_auth(exc) and attempt == 0:
                invalidate_credentials()
                _thread_local.client = None
                continue
            if _is_throttle(exc):
                sleep_s = min(60.0, (2**attempt) * 0.5)
                time.sleep(sleep_s)
                continue
            raise
    assert last is not None
    raise last


def run_split(
    split: str,
    model: str,
    limit: int | None,
    temperature: float = 0.0,
    max_spend_usd: float = 5.0,
    spent_so_far: float = 0.0,
    workers: int = 64,
) -> dict:
    path = DATA / f"SimBench{split}.pkl"
    with path.open("rb") as f:
        df = pickle.load(f)
    if limit is not None:
        df = df.iloc[:limit].copy()

    n = len(df)
    rows_meta = []
    for i, (_, row) in enumerate(df.iterrows()):
        system, user = _generate_prompt(row)
        rows_meta.append(
            {
                "i": i,
                "system": system,
                "user": user,
                "keys": list(row["human_answer"].keys()),
                "dataset_name": row.get("dataset_name"),
                "human_answer": dict(row["human_answer"]),
            }
        )

    lock = threading.Lock()
    prompt_tok = 0
    output_tok = 0
    ok = fail = 0
    done = 0
    stopped_budget = False
    rows_out: list[dict] = []
    t0 = time.time()

    def remaining_budget() -> float:
        return max_spend_usd - (spent_so_far + _cost_usd(model, prompt_tok, output_tok))

    def handle(meta: dict) -> dict:
        raw, pt, ot = _one_call(model, meta["system"], meta["user"], temperature)
        dist = _parse_dist(raw, meta["keys"])
        if dist is None:
            return {
                "i": meta["i"],
                "error": "parse",
                "raw": raw[:300],
                "pt": pt,
                "ot": ot,
                "ok": False,
            }
        return {
            "i": meta["i"],
            "dataset_name": meta["dataset_name"],
            "llm_answer": dist,
            "human_answer": meta["human_answer"],
            "pt": pt,
            "ot": ot,
            "ok": True,
        }

    print(f"  [{split}] parallel workers={workers} n={n}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(handle, meta): meta["i"] for meta in rows_meta}
        for fut in as_completed(futures):
            with lock:
                if stopped_budget:
                    continue
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                with lock:
                    fail += 1
                    done += 1
                    rows_out.append({"i": futures[fut], "error": str(exc)[:300]})
                    result = None
            if result is not None:
                with lock:
                    prompt_tok += int(result.get("pt") or 0)
                    output_tok += int(result.get("ot") or 0)
                    done += 1
                    if result.get("ok"):
                        ok += 1
                    else:
                        fail += 1
                    rows_out.append(result)
            with lock:
                if done % 100 == 0 or done == 1 or done == n:
                    cost_now = spent_so_far + _cost_usd(model, prompt_tok, output_tok)
                    rate = done / max(time.time() - t0, 1e-6)
                    print(
                        f"  [{split}] {done}/{n} ok={ok} fail={fail} "
                        f"~${cost_now:.3f} {rate:.1f}/s workers={workers}"
                    )
                if remaining_budget() <= 0 and not stopped_budget:
                    stopped_budget = True
                    print(
                        f"  [{split}] HARD STOP at "
                        f"${spent_so_far + _cost_usd(model, prompt_tok, output_tok):.3f} "
                        f"(cap ${max_spend_usd})"
                    )
                    for other in futures:
                        other.cancel()

    # stable order
    rows_out.sort(key=lambda r: r.get("i", 10**9))
    cost = _cost_usd(model, prompt_tok, output_tok)
    return {
        "split": split,
        "model": model,
        "workers": workers,
        "n": n,
        "completed": ok + fail,
        "ok": ok,
        "fail": fail,
        "prompt_tokens": prompt_tok,
        "output_tokens": output_tok,
        "estimated_cost_usd": round(cost, 4),
        "max_spend_usd": max_spend_usd,
        "stopped_budget": stopped_budget,
        "elapsed_s": round(time.time() - t0, 1),
        "rows": rows_out,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=["Pop", "Grouped", "both"], default="Pop")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--workers", type=int, default=64, help="Parallel Vertex requests")
    p.add_argument(
        "--max-spend",
        type=float,
        default=5.0,
        help="Hard USD cap across this process (default 5.0).",
    )
    args = p.parse_args()

    from auth import _adc_path, vertex_credentials

    adc = _adc_path()
    if adc is None:
        raise SystemExit(
            "No Vertex credentials found. Expected secrets/vertex_adc.json "
            "(or VERTEX_ADC / GOOGLE_APPLICATION_CREDENTIALS). "
            "secrets/ is gitignored and was not injected into this cloud VM."
        )
    creds = vertex_credentials()
    print(f"Credentials OK via {adc} (token={bool(creds.token)})")
    print(f"Model={args.model}  workers={args.workers}  hard cap=${args.max_spend:.2f}")

    splits = ["Pop", "Grouped"] if args.split == "both" else [args.split]
    out_dir = Path(args.out) if args.out else RESULTS_DIR / "simbench"
    out_dir.mkdir(parents=True, exist_ok=True)

    spent = 0.0
    for split in splits:
        remaining = args.max_spend - spent
        if remaining <= 0:
            print(f"Skipping {split}: budget exhausted (${spent:.3f})")
            break
        print(
            f"Running SimBench{split} model={args.model} "
            f"limit={args.limit} workers={args.workers} remaining=${remaining:.2f}"
        )
        summary = run_split(
            split,
            args.model,
            args.limit,
            max_spend_usd=args.max_spend,
            spent_so_far=spent,
            workers=args.workers,
        )
        spent += summary["estimated_cost_usd"]
        out_path = out_dir / (
            f"SimBench{split}_{args.model.replace('/', '_')}"
            f"_w{args.workers}_n{summary['completed']}.json"
        )
        out_path.write_text(json.dumps(summary, indent=2))
        print(
            f"Done {split}: ok={summary['ok']} fail={summary['fail']} "
            f"completed={summary['completed']}/{summary['n']} "
            f"tok in={summary['prompt_tokens']} out={summary['output_tokens']} "
            f"~${summary['estimated_cost_usd']} (total ${spent:.3f}) "
            f"{summary['elapsed_s']}s budget_stop={summary['stopped_budget']} -> {out_path}"
        )


if __name__ == "__main__":
    main()
