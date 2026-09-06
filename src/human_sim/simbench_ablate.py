"""SimBench prompt/harness ablation runner for Vertex Gemini.

Runs the same model under several prompt "arms" on one fixed stratified
subsample, then scores every arm with the official SimBench formula
(vendor/SimBench_release/calculate_simbench_score.py):

    S_i = 100 * (1 - TVD(pred_i, human_i) / mean_j TVD(human_j, uniform_j))

with the denominator taken per source dataset. Dataset norms are computed once
from the shared subsample so arms are directly comparable.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_ablate --arms base,no_persona --pop 25 --grouped 100
  PYTHONPATH=src python -m human_sim.simbench_ablate --score-only
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types

from auth import invalidate_credentials, vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, RESULTS_DIR, ROOT
from human_sim.simbench_cost import PRICES

DATA = ROOT / "data" / "simbench"
OUT_DIR = RESULTS_DIR / "simbench_ablate"

_thread_local = threading.local()

SYSTEM_PREFIX = "You are a group of individuals with these shared characteristics:\n"

RULES = (
    "1. Use whole numbers from 0 to 100\n"
    "2. Ensure the percentages sum to exactly 100\n"
    "3. Only include the numbers (no % symbols)\n"
    "4. Use this exact valid JSON format: {fmt} and do NOT include anything else.\n"
    "5. Only output your final answer and nothing else. "
    "No explanations or intermediate steps are needed.\n"
)


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


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError):
            return {}
    return {}


def load_split(split: str) -> pd.DataFrame:
    path = DATA / f"SimBench{split}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Download with: PYTHONPATH=src python -m human_sim.simbench_setup"
        )
    df = pd.read_csv(path)
    df["human_answer"] = df["human_answer"].map(_as_dict)
    df["group_prompt_variable_map"] = df["group_prompt_variable_map"].map(_as_dict)
    df = df[df["human_answer"].map(len) > 1].reset_index(drop=True)
    df["split"] = split
    return df


def _filled_persona(row) -> str:
    persona = str(row["group_prompt_template"])
    for variable, value in row["group_prompt_variable_map"].items():
        persona = persona.replace(f"{{{variable}}}", str(value))
    return persona


def stratified_sample(
    df: pd.DataFrame, per_dataset: int, seed: int, reserve: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split each dataset into (eval sample, reserve pool for few-shot demos)."""
    evals, pools = [], []
    for _, group in df.groupby("dataset_name"):
        shuffled = group.sample(frac=1.0, random_state=seed)
        pools.append(shuffled.iloc[:reserve])
        evals.append(shuffled.iloc[reserve : reserve + per_dataset])
    return (
        pd.concat(evals).reset_index(drop=True),
        pd.concat(pools).reset_index(drop=True) if reserve else pd.DataFrame(),
    )


# --------------------------------------------------------------------------- #
# arms: each returns (system, user, gen_kwargs)
# --------------------------------------------------------------------------- #


def _fmt(keys: list[str]) -> str:
    return "{" + ", ".join(f'"{k}": X' for k in keys) + "}"


def _official_user(question: str, keys: list[str]) -> str:
    return (
        f"**Question**: {question}\n"
        "\nEstimate what percentage of your group would choose each option. "
        "Follow these rules:\n" + RULES.format(fmt=_fmt(keys)) + "Replace X with your "
        "estimated percentages for each option.\n**Answer**:"
    )


def arm_base(row, ctx) -> tuple[str, str, dict]:
    keys = list(row["human_answer"].keys())
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        _official_user(row["input_template"], keys),
        {},
    )


def arm_no_persona(row, ctx) -> tuple[str, str, dict]:
    """Strip all group information: how much does the persona actually add?"""
    keys = list(row["human_answer"].keys())
    return (
        "You are a group of individuals.",
        _official_user(row["input_template"], keys),
        {},
    )


def arm_swap_persona(row, ctx) -> tuple[str, str, dict]:
    """Wrong-but-plausible persona from the same dataset: is conditioning real?"""
    keys = list(row["human_answer"].keys())
    own = _filled_persona(row)
    alternatives = ctx["personas_by_dataset"].get(row["dataset_name"], [])
    choices = [p for p in alternatives if p != own]
    rng = random.Random(f"{row['dataset_name']}|{row.name}")
    persona = rng.choice(choices) if choices else own
    return (
        SYSTEM_PREFIX + persona,
        _official_user(row["input_template"], keys),
        {},
    )


def arm_cot(row, ctx) -> tuple[str, str, dict]:
    """Official Appendix D zero-shot CoT prompt (text reasoning, not thinking tokens)."""
    keys = list(row["human_answer"].keys())
    user = (
        f"**Question**: {row['input_template']}\n"
        "\nEstimate what percentage of your group would choose each option.\n"
        "Think step by step about how people with your shared characteristics would "
        "reason about this question.\n"
        "Consider different perspectives within your group and what factors would "
        "influence their choices.\n"
        "Please provide your reasoning first, then give your final answer in JSON format.\n"
        "Follow these rules for your final answer:\n" + RULES.format(fmt=_fmt(keys)).replace(
            "5. Only output your final answer and nothing else. "
            "No explanations or intermediate steps are needed.\n",
            "5. Replace X with your estimated percentages for each option.\n",
        )
        + "**Answer**:"
    )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        user,
        {"json_mime": False, "max_output_tokens": 1200},
    )


def arm_think(row, ctx) -> tuple[str, str, dict]:
    """Official prompt but with a real thinking budget (inference-time compute)."""
    system, user, _ = arm_base(row, ctx)
    return system, user, {"thinking_budget": 1024, "max_output_tokens": 2048}


def arm_plural(row, ctx) -> tuple[str, str, dict]:
    """Anti-mode-seeking instruction: push back on alignment's entropy collapse."""
    keys = list(row["human_answer"].keys())
    system = (
        SYSTEM_PREFIX
        + _filled_persona(row)
        + "\n\nYour group is not uniform. Its members hold genuinely different views, "
        "and real survey responses from this group are usually spread across several "
        "options rather than concentrated on one. Report the spread you would actually "
        "observe, including minority positions."
    )
    return system, _official_user(row["input_template"], keys), {}


def arm_fewshot(row, ctx) -> tuple[str, str, dict]:
    """In-context calibration: real human distributions for other questions."""
    keys = list(row["human_answer"].keys())
    demos = ctx["demos_by_dataset"].get(row["dataset_name"], [])
    blocks = []
    for demo in demos:
        total = sum(demo["human_answer"].values()) or 1.0
        pct = {k: round(100 * v / total) for k, v in demo["human_answer"].items()}
        blocks.append(
            f"**Question**: {demo['input_template']}\n"
            f"**Answer**: {json.dumps(pct)}"
        )
    prefix = ""
    if blocks:
        prefix = (
            "Here are real response distributions previously measured for this group:\n\n"
            + "\n\n".join(blocks)
            + "\n\nNow estimate the same for a new question.\n\n"
        )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        prefix + _official_user(row["input_template"], keys),
        {},
    )


def arm_plural_fewshot(row, ctx) -> tuple[str, str, dict]:
    """Stack the two cheapest wins: plurality framing + in-context distributions."""
    plural_system, _, _ = arm_plural(row, ctx)
    _, fewshot_user, _ = arm_fewshot(row, ctx)
    return plural_system, fewshot_user, {}


def arm_ensemble(row, ctx) -> tuple[str, str, dict]:
    """Official prompt sampled k times at T=1, distributions averaged."""
    system, user, _ = arm_base(row, ctx)
    return system, user, {"samples": 5, "temperature": 1.0}


ARMS = {
    "base": arm_base,
    "no_persona": arm_no_persona,
    "swap_persona": arm_swap_persona,
    "cot": arm_cot,
    "think": arm_think,
    "plural": arm_plural,
    "fewshot": arm_fewshot,
    "plural_fewshot": arm_plural_fewshot,
    "ensemble": arm_ensemble,
}


# --------------------------------------------------------------------------- #
# model calls
# --------------------------------------------------------------------------- #


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


def _parse_dist(raw: str, keys: list[str]) -> dict[str, float] | None:
    matches = re.findall(r"\{[^{}]*\}", raw or "")
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
            vals = {k: float(data[k]) for k in keys}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        total = sum(vals.values())
        if total > 0:
            return {k: v / total for k, v in vals.items()}
    return None


def _call(model: str, system: str, user: str, opts: dict) -> tuple[str, int, int]:
    last: Exception | None = None
    for attempt in range(8):
        try:
            cfg_kwargs = {
                "system_instruction": system,
                "temperature": opts.get("temperature", 0.0),
                "max_output_tokens": opts.get("max_output_tokens", 512),
            }
            if opts.get("json_mime", True):
                cfg_kwargs["response_mime_type"] = "application/json"
            cfg = types.GenerateContentConfig(**cfg_kwargs)
            try:
                cfg.thinking_config = types.ThinkingConfig(
                    thinking_budget=opts.get("thinking_budget", 0)
                )
            except Exception:
                pass
            resp = _client().models.generate_content(
                model=model, contents=user, config=cfg
            )
            usage = getattr(resp, "usage_metadata", None)
            return (
                (resp.text or "").strip(),
                int(getattr(usage, "prompt_token_count", 0) or 0),
                int(getattr(usage, "candidates_token_count", 0) or 0),
            )
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_auth(exc) and attempt == 0:
                invalidate_credentials()
                _thread_local.client = None
                continue
            if _is_throttle(exc):
                time.sleep(min(60.0, (2**attempt) * 0.5))
                continue
            raise
    assert last is not None
    raise last


def _cost_usd(model: str, prompt_tok: int, output_tok: int) -> float:
    price = PRICES.get(model, PRICES["gemini-2.5-flash"])
    return prompt_tok / 1e6 * price["in"] + output_tok / 1e6 * price["out"]


def run_arm(
    arm: str, sample: pd.DataFrame, ctx: dict, model: str, workers: int
) -> dict:
    build = ARMS[arm]
    lock = threading.Lock()
    stats = {"prompt_tok": 0, "output_tok": 0, "ok": 0, "fail": 0, "done": 0}
    rows_out: list[dict] = []
    t0 = time.time()
    n = len(sample)

    def handle(item) -> dict:
        idx, row = item
        keys = list(row["human_answer"].keys())
        system, user, opts = build(row, ctx)
        n_samples = opts.get("samples", 1)
        dists, pt_sum, ot_sum = [], 0, 0
        raw_last = ""
        for _ in range(n_samples):
            raw, pt, ot = _call(model, system, user, opts)
            pt_sum += pt
            ot_sum += ot
            raw_last = raw
            dist = _parse_dist(raw, keys)
            if dist is not None:
                dists.append(dist)
        if not dists:
            return {
                "i": int(idx),
                "ok": False,
                "raw": raw_last[:200],
                "pt": pt_sum,
                "ot": ot_sum,
            }
        merged = {k: sum(d[k] for d in dists) / len(dists) for k in keys}
        return {
            "i": int(idx),
            "ok": True,
            "dataset_name": row["dataset_name"],
            "split": row["split"],
            "llm_answer": merged,
            "human_answer": dict(row["human_answer"]),
            "n_samples_ok": len(dists),
            "pt": pt_sum,
            "ot": ot_sum,
        }

    print(f"[{arm}] n={n} workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(handle, item) for item in sample.iterrows()]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)[:200], "pt": 0, "ot": 0}
            with lock:
                stats["prompt_tok"] += int(result.get("pt") or 0)
                stats["output_tok"] += int(result.get("ot") or 0)
                stats["done"] += 1
                stats["ok" if result.get("ok") else "fail"] += 1
                rows_out.append(result)
                if stats["done"] % 200 == 0 or stats["done"] == n:
                    cost = _cost_usd(model, stats["prompt_tok"], stats["output_tok"])
                    print(
                        f"[{arm}] {stats['done']}/{n} ok={stats['ok']} "
                        f"fail={stats['fail']} ~${cost:.3f}"
                    )

    rows_out.sort(key=lambda r: r.get("i", 10**9))
    return {
        "arm": arm,
        "model": model,
        "n": n,
        "ok": stats["ok"],
        "fail": stats["fail"],
        "prompt_tokens": stats["prompt_tok"],
        "output_tokens": stats["output_tok"],
        "estimated_cost_usd": round(
            _cost_usd(model, stats["prompt_tok"], stats["output_tok"]), 4
        ),
        "elapsed_s": round(time.time() - t0, 1),
        "rows": rows_out,
    }


# --------------------------------------------------------------------------- #
# scoring (official formula)
# --------------------------------------------------------------------------- #


def _norm(dist: dict) -> dict:
    total = sum(dist.values()) or 1.0
    return {k: v / total for k, v in dist.items()}


def tvd(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def dataset_norms(sample: pd.DataFrame) -> dict[str, float]:
    """mean_j TVD(human_j, uniform_j) per dataset -- the official denominator."""
    acc = defaultdict(list)
    for _, row in sample.iterrows():
        human = _norm(row["human_answer"])
        uniform = {k: 1.0 / len(human) for k in human}
        acc[row["dataset_name"]].append(tvd(human, uniform))
    return {ds: sum(vals) / len(vals) for ds, vals in acc.items()}


def score_arm(
    result: dict, norms: dict[str, float], shrink: float = 0.0
) -> dict:
    """SimBench S; shrink>0 interpolates the prediction toward uniform."""
    per_split = defaultdict(list)
    per_dataset = defaultdict(list)
    all_scores, tvds = [], []
    for row in result["rows"]:
        if not row.get("ok"):
            continue
        ds = row["dataset_name"]
        norm = norms.get(ds)
        if not norm:
            continue
        human = _norm(row["human_answer"])
        pred = _norm(row["llm_answer"])
        if shrink:
            k = len(pred)
            pred = {
                key: (1 - shrink) * val + shrink / k for key, val in pred.items()
            }
        distance = tvd(human, pred)
        score = 100 * (1 - distance / norm)
        all_scores.append(score)
        tvds.append(distance)
        per_split[row.get("split", "?")].append(score)
        per_dataset[ds].append(score)

    def mean(values):
        return round(sum(values) / len(values), 2) if values else None

    return {
        "arm": result["arm"],
        "n_scored": len(all_scores),
        "S": mean(all_scores),
        "mean_TVD": round(sum(tvds) / len(tvds), 4) if tvds else None,
        "S_by_split": {k: mean(v) for k, v in sorted(per_split.items())},
        "S_by_dataset": {k: mean(v) for k, v in sorted(per_dataset.items())},
        "cost_usd": result.get("estimated_cost_usd"),
        "fail": result.get("fail"),
    }


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #


def build_context(pop: pd.DataFrame, grouped: pd.DataFrame, pools: pd.DataFrame) -> dict:
    personas_by_dataset = defaultdict(set)
    for df in (pop, grouped):
        for _, row in df.iterrows():
            personas_by_dataset[row["dataset_name"]].add(_filled_persona(row))
    demos_by_dataset = defaultdict(list)
    if len(pools):
        for _, row in pools.iterrows():
            bucket = demos_by_dataset[row["dataset_name"]]
            if len(bucket) < 3:
                bucket.append(
                    {
                        "input_template": row["input_template"],
                        "human_answer": row["human_answer"],
                    }
                )
    return {
        "personas_by_dataset": {k: sorted(v) for k, v in personas_by_dataset.items()},
        "demos_by_dataset": dict(demos_by_dataset),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", default="base")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--pop", type=int, default=25, help="cases per Pop dataset")
    p.add_argument("--grouped", type=int, default=100, help="cases per Grouped dataset")
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--score-only", action="store_true")
    p.add_argument("--shrink-sweep", action="store_true")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pop_full = load_split("Pop")
    grouped_full = load_split("Grouped")
    pop_eval, pop_pool = stratified_sample(pop_full, args.pop, args.seed, reserve=3)
    grp_eval, grp_pool = stratified_sample(grouped_full, args.grouped, args.seed, reserve=3)
    sample = pd.concat([pop_eval, grp_eval]).reset_index(drop=True)
    pools = pd.concat([pop_pool, grp_pool]).reset_index(drop=True)
    norms = dataset_norms(sample)
    ctx = build_context(pop_full, grouped_full, pools)

    print(
        f"sample n={len(sample)} "
        f"(Pop {len(pop_eval)} / Grouped {len(grp_eval)}) "
        f"datasets={len(norms)}"
    )
    (OUT_DIR / "dataset_norms.json").write_text(json.dumps(norms, indent=2))

    arms = [a for a in args.arms.split(",") if a]
    summaries = []
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm}; choose from {sorted(ARMS)}")
        tag = f"p{args.pop}g{args.grouped}s{args.seed}"
        raw_path = OUT_DIR / f"{arm}_{args.model.replace('/', '_')}_{tag}.json"
        if args.score_only or raw_path.exists():
            if not raw_path.exists():
                print(f"[{arm}] no cached run, skipping")
                continue
            result = json.loads(raw_path.read_text())
            print(f"[{arm}] loaded cached run ({raw_path.name})")
        else:
            result = run_arm(arm, sample, ctx, args.model, args.workers)
            raw_path.write_text(json.dumps(result, indent=2))
        summary = score_arm(result, norms)
        if args.shrink_sweep:
            sweep = {
                f"{lam:.2f}": score_arm(result, norms, shrink=lam)["S"]
                for lam in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
            }
            summary["shrink_sweep_S"] = sweep
        summaries.append(summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "S_by_dataset"}, indent=2))

    if summaries:
        (OUT_DIR / "summary.json").write_text(json.dumps(summaries, indent=2))
        base = next((s for s in summaries if s["arm"] == "base"), None)
        print("\n=== SimBench S by arm ===")
        for s in sorted(summaries, key=lambda x: -(x["S"] or -999)):
            delta = (
                f"  ({s['S'] - base['S']:+.2f} vs base)"
                if base and s["S"] is not None and base["S"] is not None
                else ""
            )
            print(f"{s['arm']:<14} S={s['S']:<7} TVD={s['mean_TVD']:<7} n={s['n_scored']}{delta}")


if __name__ == "__main__":
    main()
