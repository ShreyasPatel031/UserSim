"""UserSim v0.1: what information in history causes the lift? Same 250 steps."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MAX_TRAJECTORIES, RESULTS_DIR, SLIM_JSON, WORKERS
from eval_offline import load_eval_steps, score
from history_variants import (
    behavioral_only,
    last_only,
    other_trajectory,
    progress_summary,
    shuffled,
)
from model import TokenMeter, _client, predict_next_action
from stats import cluster_bootstrap_delta, cluster_bootstrap_mean, mean


def load_catalog() -> list[dict]:
    tasks = json.loads(SLIM_JSON.read_text())[:MAX_TRAJECTORIES]
    return [
        {
            "annotation_id": t["annotation_id"],
            "website": t["website"],
            "action_reprs": t.get("action_reprs") or [],
        }
        for t in tasks
    ]


def spec_for(condition: str, step: dict, catalog: list[dict]):
    history = step["history"]
    seed = f"{step['annotation_id']}:{step['step_index']}"
    if condition == "shuffled":
        return shuffled(history, seed)
    if condition == "other":
        return other_trajectory(
            history_len=len(history),
            annotation_id=step["annotation_id"],
            website=step["website"],
            step_index=step["step_index"],
            catalog=catalog,
        )
    if condition == "last_only":
        return last_only(history)
    if condition == "summary":
        return progress_summary(history, step["step_index"], step["n_steps"])
    if condition == "behavioral":
        return behavioral_only(history)
    raise ValueError(condition)


def run_condition(steps: list[dict], condition: str, catalog: list[dict]):
    client = _client()
    meter = TokenMeter()
    out = [None] * len(steps)

    def one(idx: int, step: dict):
        spec = spec_for(condition, step, catalog)
        pred = predict_next_action(
            task=step["task"],
            website=step["website"],
            candidates=step["candidate_reprs"],
            history=spec.items or None,
            client=client,
            history_heading=spec.heading,
            number_history=spec.number,
        )
        return idx, pred, spec

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(one, i, s) for i, s in enumerate(steps)]
        done = 0
        for fut in as_completed(futs):
            idx, pred, spec = fut.result()
            meter.add(pred)
            step = steps[idx]
            out[idx] = {
                "annotation_id": step["annotation_id"],
                "website": step["website"],
                "domain": step["domain"],
                "task": step["task"],
                "step_index": step["step_index"],
                "history_len": len(step["history"]),
                "condition": condition,
                "history_preview": spec.items[:6],
                "gold_op": step["gold_op"],
                "gold_repr": step["gold_repr"],
                **score(pred, step),
            }
            done += 1
            if done % 25 == 0 or done == len(steps):
                print(f"  {condition:12s} {done}/{len(steps)}  cost=${meter.cost_usd:.3f}", flush=True)
    return out, meter


def summarize_rows(rows: list[dict], seed: int) -> dict:
    elem, elo, ehi = cluster_bootstrap_mean(rows, "element_correct", seed=seed)
    act, alo, ahi = cluster_bootstrap_mean(rows, "action_correct", seed=seed + 11)
    both, blo, bhi = cluster_bootstrap_mean(rows, "both_correct", seed=seed + 22)
    later = [r for r in rows if r["history_len"] > 0]
    later_elem, llo, lhi = cluster_bootstrap_mean(later, "element_correct", seed=seed + 33)
    return {
        "n_steps": len(rows),
        "n_trajectories": len({r["annotation_id"] for r in rows}),
        "element_acc": elem,
        "element_acc_ci95_clustered": [elo, ehi],
        "action_acc": act,
        "action_acc_ci95_clustered": [alo, ahi],
        "both_acc": both,
        "both_acc_ci95_clustered": [blo, bhi],
        "later_steps_n": len(later),
        "later_element_acc": later_elem,
        "later_element_acc_ci95_clustered": [llo, lhi],
        "errors": sum(1 for r in rows if r.get("error")),
    }


def index_rows(rows: list[dict]) -> dict:
    return {(r["annotation_id"], r["step_index"]): r for r in rows}


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    steps = load_eval_steps()
    catalog = load_catalog()
    print(f"v0.1 steps={len(steps)} traj={len({s['annotation_id'] for s in steps})}")

    baseline = json.loads((RESULTS_DIR / "predictions_baseline.json").read_text())
    correct = json.loads((RESULTS_DIR / "predictions_usersim.json").read_text())
    keys = [(s["annotation_id"], s["step_index"]) for s in steps]
    bmap, cmap = index_rows(baseline), index_rows(correct)
    missing = [k for k in keys if k not in bmap or k not in cmap]
    if missing:
        raise SystemExit(f"v0 predictions out of sync with eval steps: {missing[:5]}")
    baseline = [bmap[k] for k in keys]
    correct = [cmap[k] for k in keys]
    for row in baseline:
        row["condition"] = "baseline"
    for row in correct:
        row["condition"] = "correct"

    new_conditions = ["shuffled", "other", "last_only", "summary", "behavioral"]
    predictions = {"baseline": baseline, "correct": correct}
    meters = {}
    for cond in new_conditions:
        print(f"running {cond}")
        rows, meter = run_condition(steps, cond, catalog)
        predictions[cond] = rows
        meters[cond] = meter
        (RESULTS_DIR / f"predictions_{cond}.json").write_text(json.dumps(rows, indent=2))

    order = ["baseline", "correct", "shuffled", "other", "last_only", "summary", "behavioral"]
    conditions = {}
    for i, name in enumerate(order):
        conditions[name] = summarize_rows(predictions[name], seed=100 + i * 7)

    deltas = {}
    seed_for = {
        "correct": 401,
        "shuffled": 402,
        "other": 403,
        "last_only": 404,
        "summary": 405,
        "behavioral": 406,
    }
    for name in order:
        if name == "baseline":
            continue
        d, lo, hi = cluster_bootstrap_delta(
            predictions[name], predictions["baseline"], seed=seed_for[name]
        )
        deltas[f"{name}_minus_baseline"] = {"element_acc": d, "ci95_clustered": [lo, hi]}
    d, lo, hi = cluster_bootstrap_delta(predictions["correct"], predictions["other"], seed=901)
    deltas["correct_minus_other"] = {"element_acc": d, "ci95_clustered": [lo, hi]}
    d, lo, hi = cluster_bootstrap_delta(predictions["correct"], predictions["summary"], seed=902)
    deltas["correct_minus_summary"] = {"element_acc": d, "ci95_clustered": [lo, hi]}
    d, lo, hi = cluster_bootstrap_delta(predictions["correct"], predictions["behavioral"], seed=903)
    deltas["correct_minus_behavioral"] = {"element_acc": d, "ci95_clustered": [lo, hi]}
    d, lo, hi = cluster_bootstrap_delta(predictions["correct"], predictions["last_only"], seed=904)
    deltas["correct_minus_last_only"] = {"element_acc": d, "ci95_clustered": [lo, hi]}
    d, lo, hi = cluster_bootstrap_delta(predictions["correct"], predictions["shuffled"], seed=905)
    deltas["correct_minus_shuffled"] = {"element_acc": d, "ci95_clustered": [lo, hi]}

    spend = {
        "new_calls": sum(m.calls for m in meters.values()),
        "new_prompt_tokens": sum(m.prompt_tokens for m in meters.values()),
        "new_output_tokens": sum(m.output_tokens for m in meters.values()),
        "new_usd": round(sum(m.cost_usd for m in meters.values()), 4),
        "v0_usd": 0.204,
        "total_usd_approx": round(0.204 + sum(m.cost_usd for m in meters.values()), 4),
        "by_condition": {k: round(m.cost_usd, 4) for k, m in meters.items()},
    }

    summary = {
        "question": "What information in history causes the lift?",
        "model": "gemini-2.5-flash",
        "n_steps": len(steps),
        "n_trajectories": len({s["annotation_id"] for s in steps}),
        "bootstrap": "cluster by trajectory (40 tasks), 2000 resamples",
        "conditions": conditions,
        "deltas_vs_baseline_clustered": deltas,
        "spend_usd": spend,
        "caveat": (
            "Mind2Web trajectories are crowdsourced tasks, not repeated behavior "
            "from identifiable users. Other-trajectory is mismatched-task history, "
            "not Alice vs Bob personalization."
        ),
    }
    (RESULTS_DIR / "summary_v01.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
