"""Strip HTML from Mind2Web train_0.json into a small eval file."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RAW_TRAIN_JSON, SLIM_JSON

MAX_NEG = 80


def slim_candidate(c: dict) -> dict:
    return {
        "tag": c.get("tag"),
        "backend_node_id": str(c.get("backend_node_id")),
        "attributes": c.get("attributes"),
        "is_original_target": bool(c.get("is_original_target")),
        "is_top_level_target": bool(c.get("is_top_level_target")),
    }


def main() -> None:
    with RAW_TRAIN_JSON.open() as f:
        tasks = json.load(f)

    slim = []
    for task in tasks:
        actions = []
        for step in task.get("actions") or []:
            pos = [slim_candidate(c) for c in (step.get("pos_candidates") or [])]
            neg_raw = step.get("neg_candidates") or []
            rng = random.Random(step.get("action_uid") or "0")
            if len(neg_raw) > MAX_NEG:
                neg_raw = rng.sample(neg_raw, MAX_NEG)
            neg = [slim_candidate(c) for c in neg_raw]
            actions.append(
                {
                    "action_uid": step.get("action_uid"),
                    "operation": step.get("operation") or {},
                    "pos_candidates": pos,
                    "neg_candidates": neg,
                }
            )
        slim.append(
            {
                "annotation_id": task.get("annotation_id"),
                "website": task.get("website"),
                "domain": task.get("domain"),
                "subdomain": task.get("subdomain"),
                "confirmed_task": task.get("confirmed_task"),
                "action_reprs": task.get("action_reprs") or [],
                "actions": actions,
            }
        )

    random.Random(0).shuffle(slim)
    SLIM_JSON.parent.mkdir(parents=True, exist_ok=True)
    SLIM_JSON.write_text(json.dumps(slim, indent=None, separators=(",", ":")))
    n_steps = sum(len(t["actions"]) for t in slim)
    n_gold = sum(
        1
        for t in slim
        for s in t["actions"]
        if s["pos_candidates"]
    )
    print(f"wrote {SLIM_JSON}  tasks={len(slim)} steps={n_steps} with_gold={n_gold}")


if __name__ == "__main__":
    main()
