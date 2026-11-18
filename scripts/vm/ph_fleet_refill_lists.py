#!/usr/bin/env python3
"""Refill pdeep work once, centrally: have_complete.txt + per-VM pdeep_list from fresh queues.

VMs must never discover "already done" people one gsutil call at a time. When have_index.jsonl or
raw/_cursor/fleet_work_queue.txt (population rewrites it after every merge cycle) changes, or FORCE=1, this:
  1. writes people_live/have_complete.txt (handles with complete=true, minus anyone in the work queue) for the pdeep
     in-memory skip;
  2. builds the work list: the work queue in file order (complete people kept: population queues them for re-reads), deduped (need_list too only when
     FLEET_REFILL_NEED_LIST=1), minus raw/_cursor/signedin_needed.txt: those people only lack a signed-in upvotes
     queue entry, so they get that entry (_pacetest/shared/_signedin_upvotes/<h>.json) instead of a whole re-pull;
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
UPVOTE |= set((os.environ.get("FLEET_LIVE_SLOTS") or "39").split())
STATE = ART / "refill_state.json"
SIGNEDIN_NEEDED = f"{G}/_cursor/signedin_needed.txt"
SIGNEDIN_Q = f"{G}/_pacetest/shared/_signedin_upvotes"


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
        "signedin_needed": generation(SIGNEDIN_NEEDED),
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
        upv: dict[str, dict] = {}
        for ln in (t / "have_index.jsonl").open():
            try:
                j = json.loads(ln)
            except Exception:
                continue
            hh = (j.get("handle") or "").lower().lstrip("@")
            if hh:
                upv[hh] = ((j.get("tabs") or {}).get("upvotes") or {})
            if j.get("complete"):
                h = (j.get("handle") or "").lower().lstrip("@")
                if h:
                    complete.add(h)
        work: list[str] = []
        n_queue = 0
        job_split = os.environ.get("FLEET_REFILL_JOB_SPLIT") == "1"
        refresh_excl: set[str] = set()
        n_incomplete = 0
        n_new = 0
        if job_split:
            rp = os.environ.get("FLEET_REFRESH_PRIORITY_QUEUE", f"{G}/_cursor/refresh_priority_latest.txt")
            if not rp.startswith("gs://"):
                rp = f"gs://{BKT}/{rp.lstrip('/')}"
            gs("cp", rp, str(t / "refresh_priority.txt"), check=False)
            if (t / "refresh_priority.txt").is_file():
                for ln in (t / "refresh_priority.txt").read_text().splitlines():
                    h = handle(ln)
                    if h:
                        refresh_excl.add(h)
            cq = os.environ.get("FLEET_COMPLETION_QUEUE", "")
            if cq and not cq.startswith("gs://"):
                cq = f"gs://{BKT}/{cq.lstrip('/')}"
            if not cq:
                listed = gs("ls", f"{G}/_cursor/completion_queue_*.txt", check=False).strip().split()
                cq = listed[-1] if listed else ""
            if cq:
                gs("cp", cq, str(t / "completion_queue.txt"))
                inc_order: list[str] = []
                for ln in (t / "completion_queue.txt").read_text().splitlines():
                    if ln.lstrip().startswith("#"):
                        continue
                    h = handle(ln)
                    if h and h not in complete and h not in refresh_excl:
                        inc_order.append(h)
                n_incomplete = len(inc_order)
                work = inc_order
            if queue:
                gs("cp", queue, str(t / "queue.txt"))
                fleet_order: list[str] = []
                inc_set = set(work)
                for ln in (t / "queue.txt").read_text().splitlines():
                    if ln.lstrip().startswith("#"):
                        continue
                    h = handle(ln)
                    if h:
                        fleet_order.append(h)
                n_queue = len(fleet_order)
                new_part = [
                    h for h in fleet_order
                    if h not in complete and h not in inc_set and h not in refresh_excl
                ]
                n_new = len(new_part)
                work = work + new_part
            sig["completion_queue"] = cq
            sig["completion_queue_gen"] = generation(cq) if cq else ""
            sig["refresh_priority"] = rp
        elif queue:
            gs("cp", queue, str(t / "queue.txt"))
            for ln in (t / "queue.txt").read_text().splitlines():
                if ln.lstrip().startswith("#"):
                    continue
                h = handle(ln)
                if h:
                    work.append(h)
            n_queue = len(work)
        # Population puts complete people in the queue on purpose (refresh_priority re-reads); route those to
        # upvote slots only when FLEET_REFILL_JOB_SPLIT=1. Otherwise pdeep may skip anyone in have_complete.txt
        # unless they are requeued.
        skip_complete_queued = (
            os.environ.get("FLEET_REFILL_SKIP_COMPLETE_QUEUED") == "1" or job_split
        )
        requeued = complete & set(work) if not skip_complete_queued else set()
        (t / "have_complete.txt").write_text("\n".join(sorted(complete - requeued)) + "\n")
        gs("cp", str(t / "have_complete.txt"), f"{LIVE}/have_complete.txt")
        rows = []
        if not job_split and os.environ.get("FLEET_REFILL_NEED_LIST") == "1":
            gs("cp", f"{LIVE}/need_list.jsonl", str(t / "need_list.jsonl"), check=False)
        if (t / "need_list.jsonl").is_file():
            for ln in (t / "need_list.jsonl").open():
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
        tier = {"likely": 0, "active_rest": 1, "other": 2}
        rows.sort(key=lambda x: (tier.get(x.get("tier"), 3), x.get("rank") or 1e9))
        if not job_split:
            work += [(x.get("handle") or "").lower().lstrip("@") for x in rows]
        signedin: list[str] = []
        gs("cp", SIGNEDIN_NEEDED, str(t / "signedin_needed.txt"), check=False)
        if (t / "signedin_needed.txt").is_file():
            signedin = [h for h in (handle(ln) for ln in (t / "signedin_needed.txt").read_text().splitlines()
                                    if not ln.lstrip().startswith("#")) if h]
        queued = {u.rsplit("/", 1)[-1][:-5].lower() for u in gs("ls", f"{SIGNEDIN_Q}/", check=False).split() if u.endswith(".json")}
        to_queue = [h for h in dict.fromkeys(signedin) if h not in queued]
        if to_queue:
            sq = t / "sq"
            sq.mkdir()
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for h in to_queue:
                u = upv.get(h) or {}
                (sq / f"{h}.json").write_text(json.dumps({"header": u.get("header"), "got": u.get("n"), "utc": now, "vm": "fleet-refill"}))
            gs("cp", *[str(p) for p in sorted(sq.iterdir())], f"{SIGNEDIN_Q}/")
        if job_split:
            work = [
                h for h in dict.fromkeys(work)
                if h and h not in refresh_excl and h not in complete and h not in signedin
            ]
        else:
            skip = (complete - requeued) | set(signedin)
            work = [h for h in dict.fromkeys(work) if h and h not in skip]

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
        "complete_requeued": len(requeued),
        "need_rows": len(rows),
        "work": len(work),
        "signedin_needed": len(set(signedin)),
        "signedin_queued_now": len(to_queue),
        "slots": len(parts),
        "per_slot": round(len(work) / max(1, len(parts)), 1),
        "job_split": job_split,
        "pdeep_incomplete": n_incomplete,
        "pdeep_new": n_new,
        "refresh_priority_excluded": len(refresh_excl) if job_split else 0,
    }
    STATE.write_text(json.dumps({**summary, "sig": sig}, indent=1))
    print(json.dumps({"refill": "built", **summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
