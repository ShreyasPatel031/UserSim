"""History vs no-history next-action prediction on Mind2Web."""

from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    MAX_STEPS_PER_TASK,
    MAX_TRAJECTORIES,
    N_CANDIDATES,
    RESULTS_DIR,
    SLIM_JSON,
    WORKERS,
)
from elements import element_repr
from model import TokenMeter, _client, predict_next_action


def sample_candidates(step: dict, rng: random.Random) -> list[dict]:
    pos = list(step["pos_candidates"])
    neg = list(step["neg_candidates"])
    gold = pos[0]
    n_neg = N_CANDIDATES - 1
    if len(neg) > n_neg:
        neg = rng.sample(neg, n_neg)
    mixed = neg + [gold]
    rng.shuffle(mixed)
    return mixed


def load_eval_steps() -> list[dict]:
    tasks = json.loads(SLIM_JSON.read_text())
    steps = []
    for task in tasks[:MAX_TRAJECTORIES]:
        history: list[str] = []
        for i, step in enumerate(task["actions"]):
            if i >= MAX_STEPS_PER_TASK:
                break
            gold_repr = (task["action_reprs"] or [None])[i] if i < len(task.get("action_reprs") or []) else None
            if not step["pos_candidates"]:
                if gold_repr:
                    history.append(gold_repr)
                continue
            rng = random.Random(f"{task['annotation_id']}:{i}")
            candidates = sample_candidates(step, rng)
            gold_ids = {str(c["backend_node_id"]) for c in step["pos_candidates"]}
            op = (step.get("operation") or {}).get("op") or "CLICK"
            value = (step.get("operation") or {}).get("value") or ""
            steps.append(
                {
                    "annotation_id": task["annotation_id"],
                    "website": task["website"],
                    "domain": task.get("domain"),
                    "task": task["confirmed_task"],
                    "step_index": i,
                    "n_steps": len(task["actions"]),
                    "history": list(history),
                    "candidates": candidates,
                    "candidate_reprs": [element_repr(c) for c in candidates],
                    "gold_ids": sorted(gold_ids),
                    "gold_op": op,
                    "gold_value": value,
                    "gold_repr": gold_repr,
                    "gold_index": next(
                        j
                        for j, c in enumerate(candidates, start=1)
                        if str(c["backend_node_id"]) in gold_ids
                    ),
                }
            )
            if gold_repr:
                history.append(gold_repr)
    return steps


def score(pred, step: dict) -> dict:
    elem_ok = False
    if pred.element_index is not None:
        chosen = step["candidates"][pred.element_index - 1]
        elem_ok = str(chosen["backend_node_id"]) in set(step["gold_ids"])
    act_ok = pred.action == step["gold_op"]
    both_ok = elem_ok and act_ok
    return {
        "element_correct": elem_ok,
        "action_correct": act_ok,
        "both_correct": both_ok,
        "pred_index": pred.element_index,
        "pred_action": pred.action,
        "pred_value": pred.value,
        "pred_repr": (
            step["candidate_reprs"][pred.element_index - 1]
            if pred.element_index
            else None
        ),
        "raw": pred.raw,
        "error": pred.error,
        "prompt_tokens": pred.prompt_tokens,
        "output_tokens": pred.output_tokens,
    }


def run_condition(steps: list[dict], use_history: bool) -> tuple[list[dict], TokenMeter]:
    client = _client()
    meter = TokenMeter()
    out = [None] * len(steps)

    def one(idx: int, step: dict):
        hist = step["history"] if use_history else None
        pred = predict_next_action(
            task=step["task"],
            website=step["website"],
            candidates=step["candidate_reprs"],
            history=hist,
            client=client,
        )
        return idx, pred

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(one, i, s) for i, s in enumerate(steps)]
        done = 0
        for fut in as_completed(futs):
            idx, pred = fut.result()
            meter.add(pred)
            row = {
                "annotation_id": steps[idx]["annotation_id"],
                "website": steps[idx]["website"],
                "domain": steps[idx]["domain"],
                "task": steps[idx]["task"],
                "step_index": steps[idx]["step_index"],
                "history_len": len(steps[idx]["history"]),
                "use_history": use_history,
                "gold_op": steps[idx]["gold_op"],
                "gold_value": steps[idx]["gold_value"],
                "gold_repr": steps[idx]["gold_repr"],
                "gold_index": steps[idx]["gold_index"],
                **score(pred, steps[idx]),
            }
            out[idx] = row
            done += 1
            if done % 25 == 0 or done == len(steps):
                print(
                    f"  {('history' if use_history else 'no_history'):10s} {done}/{len(steps)}  "
                    f"cost=${meter.cost_usd:.3f}",
                    flush=True,
                )
    return out, meter


def mean(xs: list[bool]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(xs: list[bool], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    if not xs:
        return 0.0, 0.0
    stats = []
    for _ in range(n):
        sample = [xs[rng.randrange(len(xs))] for _ in xs]
        stats.append(mean(sample))
    stats.sort()
    lo = stats[int(0.025 * n)]
    hi = stats[min(len(stats) - 1, int(0.975 * n))]
    return lo, hi


def summarize(rows: list[dict], seed: int) -> dict:
    elem = [bool(r["element_correct"]) for r in rows]
    act = [bool(r["action_correct"]) for r in rows]
    both = [bool(r["both_correct"]) for r in rows]
    elo, ehi = bootstrap_ci(elem, seed=seed)
    alo, ahi = bootstrap_ci(act, seed=seed + 1)
    blo, bhi = bootstrap_ci(both, seed=seed + 2)
    return {
        "n": len(rows),
        "element_acc": mean(elem),
        "element_acc_ci95": [elo, ehi],
        "action_acc": mean(act),
        "action_acc_ci95": [alo, ahi],
        "both_acc": mean(both),
        "both_acc_ci95": [blo, bhi],
        "errors": sum(1 for r in rows if r.get("error")),
    }


def pick_examples(hist_rows: list[dict], base_rows: list[dict], k: int = 6) -> dict:
    paired = list(zip(hist_rows, base_rows))
    hist_win = [
        {"with_history": h, "no_history": b}
        for h, b in paired
        if h["element_correct"] and not b["element_correct"]
    ]
    hist_lose = [
        {"with_history": h, "no_history": b}
        for h, b in paired
        if (not h["element_correct"]) and b["element_correct"]
    ]
    both_ok = [
        {"with_history": h, "no_history": b}
        for h, b in paired
        if h["element_correct"] and b["element_correct"]
    ]
    both_miss = [
        {"with_history": h, "no_history": b}
        for h, b in paired
        if (not h["element_correct"]) and (not b["element_correct"])
    ]
    return {
        "history_helps": hist_win[:k],
        "history_hurts": hist_lose[:k],
        "both_correct": both_ok[:k],
        "both_wrong": both_miss[:k],
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    steps = load_eval_steps()
    print(f"eval steps={len(steps)} trajectories~={len({s['annotation_id'] for s in steps})}")

    print("running baseline (task + page, no history)")
    base_rows, base_meter = run_condition(steps, use_history=False)
    print("running usersim (task + page + history)")
    hist_rows, hist_meter = run_condition(steps, use_history=True)

    summary = {
        "model": "gemini-2.5-flash",
        "project": "project-amer-scs-sandbox",
        "n_candidates": N_CANDIDATES,
        "n_trajectories": len({s["annotation_id"] for s in steps}),
        "n_steps": len(steps),
        "baseline": summarize(base_rows, seed=1),
        "usersim": summarize(hist_rows, seed=2),
        "delta_element_acc": summarize(hist_rows, 2)["element_acc"]
        - summarize(base_rows, 1)["element_acc"],
        "delta_action_acc": summarize(hist_rows, 2)["action_acc"]
        - summarize(base_rows, 1)["action_acc"],
        "delta_both_acc": summarize(hist_rows, 2)["both_acc"]
        - summarize(base_rows, 1)["both_acc"],
        "spend_usd": {
            "baseline": round(base_meter.cost_usd, 4),
            "usersim": round(hist_meter.cost_usd, 4),
            "total": round(base_meter.cost_usd + hist_meter.cost_usd, 4),
            "prompt_tokens": base_meter.prompt_tokens + hist_meter.prompt_tokens,
            "output_tokens": base_meter.output_tokens + hist_meter.output_tokens,
            "calls": base_meter.calls + hist_meter.calls,
        },
        "action_prior": {
            "CLICK": mean([s["gold_op"] == "CLICK" for s in steps]),
            "TYPE": mean([s["gold_op"] == "TYPE" for s in steps]),
            "SELECT": mean([s["gold_op"] == "SELECT" for s in steps]),
        },
        "examples": pick_examples(hist_rows, base_rows),
    }

    (RESULTS_DIR / "predictions_baseline.json").write_text(json.dumps(base_rows, indent=2))
    (RESULTS_DIR / "predictions_usersim.json").write_text(json.dumps(hist_rows, indent=2))
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "examples"}, indent=2))


if __name__ == "__main__":
    main()
