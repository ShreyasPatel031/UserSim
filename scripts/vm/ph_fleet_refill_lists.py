#!/usr/bin/env python3
"""Refill pdeep work once, centrally: have_complete.txt + per-VM pdeep_list from fresh queues.

VMs must never discover "already done" people one gsutil call at a time. When have_index.jsonl or
raw/_cursor/fleet_work_queue.txt (population rewrites it after every merge cycle) changes, or FORCE=1, this:
  1. writes people_live/have_complete.txt (handles with complete=true) for the pdeep in-memory skip;
  2. builds the work list: the work queue in file order, minus complete, deduped (need_list too only when
     FLEET_REFILL_NEED_LIST=1);
  3. partitions it round-robin over the non-upvote slots in slots.tsv and uploads pdeep_list.<vm>.txt.
Prints one JSON summary line.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = (os.environ.get("PACE_FLEET_RUN_ID") or (ROOT / "results/ph_fleet_full/latest_run.txt").read_text().strip()).lower()
ART = Path(os.environ.get("FLEET_ART") or ROOT / f"results/ph_fleet_full/{RUN_ID}")
BKT = os.environ["MVP_GCS_BUCKET"]
G = f"gs://{BKT}/usersim_sim/raw"
LIVE = f"{G}/ph_population/people_live"
UPVOTE = set((os.environ.get("FLEET_UPVOTE_SLOTS") or os.environ.get("UPVOTE_SLOTS") or "9 27 38").split())
STATE = ART / "refill_state.json"


def gs(*a: str, check: bool = True) -> str:
    r = subprocess.run(["gcloud", "storage", *a], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"gcloud storage {' '.join(a[:2])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def generation(url: str) -> str:
    out = gs("objects", "describe", url, "--format=value(generation)", check=False).strip()
    return out


def handle(s: str) -> str:
    return s.strip().split("\t", 1)[0].split()[0].lower().lstrip("@") if s.strip() else ""


def main() -> int:
    queue = os.environ.get("FLEET_WORK_QUEUE") or f"{G}/_cursor/fleet_work_queue.txt"
    if queue and not queue.startswith("gs://"):
        queue = f"gs://{BKT}/{queue.lstrip('/')}"
    sig = {
        "have_index": generation(f"{LIVE}/have_index.jsonl"),
        "need_list": generation(f"{LIVE}/need_list.jsonl"),
        "queue": queue,
        "queue_gen": generation(queue) if queue else "",
        "slots": sorted(
            ln.split("\t", 1)[0] for ln in (ART / "slots.tsv").read_text().splitlines() if ln[:1].isdigit()
        ),
    }
    old = json.loads(STATE.read_text()) if STATE.is_file() else {}
    if os.environ.get("FORCE") != "1" and old.get("sig") == sig:
        print(json.dumps({"refill": "unchanged", **{k: old.get(k) for k in ("utc", "work", "complete")}}))
        return 0

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        gs("cp", f"{LIVE}/have_index.jsonl", str(t / "have_index.jsonl"))
        complete: set[str] = set()
        for ln in (t / "have_index.jsonl").open():
            try:
                j = json.loads(ln)
            except Exception:
                continue
            if j.get("complete"):
                h = (j.get("handle") or "").lower().lstrip("@")
                if h:
                    complete.add(h)
        (t / "have_complete.txt").write_text("\n".join(sorted(complete)) + "\n")
        gs("cp", str(t / "have_complete.txt"), f"{LIVE}/have_complete.txt")

        work: list[str] = []
        n_queue = 0
        if queue:
            gs("cp", queue, str(t / "queue.txt"))
            for ln in (t / "queue.txt").read_text().splitlines():
                if ln.lstrip().startswith("#"):
                    continue
                h = handle(ln)
                if h:
                    work.append(h)
            n_queue = len(work)
        rows = []
        if os.environ.get("FLEET_REFILL_NEED_LIST") == "1":
            gs("cp", f"{LIVE}/need_list.jsonl", str(t / "need_list.jsonl"), check=False)
        if (t / "need_list.jsonl").is_file():
            for ln in (t / "need_list.jsonl").open():
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
        tier = {"likely": 0, "active_rest": 1, "other": 2}
        rows.sort(key=lambda x: (tier.get(x.get("tier"), 3), x.get("rank") or 1e9))
        work += [(x.get("handle") or "").lower().lstrip("@") for x in rows]
        work = [h for h in dict.fromkeys(work) if h and h not in complete]

        slots = [s for s in sorted(sig["slots"], key=int) if s not in UPVOTE]
        parts = {s: work[i :: len(slots)] for i, s in enumerate(slots)} if slots else {}
        for s, part in parts.items():
            f = t / f"pdeep_list.{s}.txt"
            f.write_text("\n".join(part) + ("\n" if part else ""))
        if parts:
            up = t / "up"
            up.mkdir()
            for s in parts:
                (t / f"pdeep_list.{s}.txt").rename(up / f"pdeep_list.feeder-fleet-{RUN_ID}-{s}.txt")
            gs("cp", *[str(p) for p in sorted(up.iterdir())], f"{LIVE}/vm/")

    from datetime import datetime, timezone

    summary = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "complete": len(complete),
        "queue": queue.rsplit("/", 1)[-1],
        "queue_handles": n_queue,
        "need_rows": len(rows),
        "work": len(work),
        "slots": len(parts),
        "per_slot": round(len(work) / max(1, len(parts)), 1),
    }
    STATE.write_text(json.dumps({**summary, "sig": sig}, indent=1))
    print(json.dumps({"refill": "built", **summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
