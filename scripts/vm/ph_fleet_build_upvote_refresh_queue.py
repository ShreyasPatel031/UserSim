#!/usr/bin/env python3
"""Build full COMPLETE-person upvote_refresh queue (orchestrator Nov 16).

All complete people from have_index.jsonl; order = count of held upvotes on launches
dated d-30..d-1 (from store_v3 events.parquet: hunted/launched launch dates), ties random.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = None  # type: ignore


def _download(bucket: str, obj: str, dest: Path) -> None:
    subprocess.run(
        ["gcloud", "storage", "cp", f"gs://{bucket}/{obj}", str(dest)],
        check=True,
        capture_output=True,
    )


def _stream_have_index(bucket: str, key: str) -> tuple[dict[str, str], int]:
    """handle -> person_id for complete=true; also return count."""
    proc = subprocess.Popen(
        ["gcloud", "storage", "cat", f"gs://{bucket}/{key}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout
    by_handle: dict[str, str] = {}
    n_complete = 0
    n_lines = 0
    for raw in proc.stdout:
        for ln in raw.decode("utf-8", errors="replace").splitlines():
            n_lines += 1
            try:
                row = json.loads(ln)
            except Exception:
                continue
            if not row.get("complete"):
                continue
            h = (row.get("handle") or "").lower().lstrip("@")
            pid = row.get("person_id") or ""
            if h and pid:
                by_handle[h] = pid
                n_complete += 1
    proc.wait()
    return by_handle, n_complete if n_lines else 0


def _launch_dates(events_path: Path) -> dict[str, datetime]:
    launch_day: dict[str, datetime] = {}
    pf = pq.ParquetFile(events_path)
    for batch in pf.iter_batches(
        batch_size=250_000,
        columns=["kind", "target_id", "ts_hi"],
    ):
        kinds = batch.column(0).to_pylist()
        targets = batch.column(1).to_pylist()
        ts_his = batch.column(2).to_pylist()
        for kind, tid, ts in zip(kinds, targets, ts_his):
            if kind not in ("hunted", "launched") or not tid or ts is None:
                continue
            tid_s = str(tid)
            prev = launch_day.get(tid_s)
            if prev is None or ts > prev:
                launch_day[tid_s] = ts
    return launch_day


def _score_upvotes(
    events_path: Path,
    launch_day: dict[str, datetime],
    window_start: datetime,
    window_end: datetime,
) -> tuple[dict[str, int], int]:
    in_window = {
        tid for tid, ts in launch_day.items() if window_start <= ts <= window_end
    }
    scores: dict[str, int] = defaultdict(int)
    pf = pq.ParquetFile(events_path)
    for batch in pf.iter_batches(
        batch_size=250_000,
        columns=["kind", "person_id", "target_id"],
    ):
        kinds = batch.column(0).to_pylist()
        pids = batch.column(1).to_pylist()
        targets = batch.column(2).to_pylist()
        for kind, pid, tid in zip(kinds, pids, targets):
            if kind != "upvote" or not pid or not tid:
                continue
            if str(tid) not in in_window:
                continue
            scores[str(pid)] += 1
    return dict(scores), len(in_window)


def main() -> None:
    if pq is None:
        print("pyarrow required", file=sys.stderr)
        sys.exit(1)

    p = argparse.ArgumentParser()
    p.add_argument("--bucket", default=os.environ.get("MVP_GCS_BUCKET", ""))
    p.add_argument(
        "--have-index",
        default="usersim_sim/raw/ph_population/people_live/have_index.jsonl",
    )
    p.add_argument(
        "--events",
        default="usersim_sim/raw/population/store_v3/events.parquet",
    )
    p.add_argument("--tag", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ"))
    p.add_argument("--events-local", type=Path, help="skip GCS download if set")
    args = p.parse_args()
    if not args.bucket:
        print("MVP_GCS_BUCKET required", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    window_end = (today - timedelta(days=1)).replace(hour=23, minute=59, second=59)
    window_start = (today - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)

    with tempfile.TemporaryDirectory() as td:
        events_local = args.events_local or Path(td) / "events.parquet"
        if not events_local.exists():
            print("downloading events.parquet...", file=sys.stderr)
            _download(args.bucket, args.events, events_local)

        print("indexing launch dates...", file=sys.stderr)
        launch_day = _launch_dates(events_local)
        print("scoring upvotes in launch window...", file=sys.stderr)
        scores, n_launches_in_window = _score_upvotes(
            events_local, launch_day, window_start, window_end
        )
        n_vote_events = sum(scores.values())

        print("reading have_index...", file=sys.stderr)
        handle_to_pid, n_have = _stream_have_index(args.bucket, args.have_index)
        handles = list(handle_to_pid.keys())

        random.seed(42)
        jitter = {h: random.random() for h in handles}

        def key(h: str):
            pid = handle_to_pid[h]
            return (-scores.get(pid, 0), jitter[h], h)

        handles.sort(key=key)

        hdr = (
            f"# built {args.tag} fleet-cursor complete={len(handles)} "
            f"order=upvotes_on_launches_{window_start.date()}..{window_end.date()} "
            f"launches_in_window={n_launches_in_window} scored_vote_events={n_vote_events}\n"
        )
        lines = [f"{h}\t{scores.get(handle_to_pid[h], 0)}" for h in handles]
        body = "\n".join(lines) + ("\n" if lines else "")

        out_local = Path(f"/tmp/refresh_upvotes_{args.tag}.txt")
        out_local.write_text(hdr + body)

        dest = f"gs://{args.bucket}/usersim_sim/raw/_cursor/refresh_upvotes_{args.tag}_fleet.txt"
        subprocess.run(["gcloud", "storage", "cp", str(out_local), dest], check=True)

        print(
            json.dumps(
                {
                    "complete_handles": len(handles),
                    "have_index_complete": n_have,
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "gcs": dest,
                    "top_score": max(scores.values()) if scores else 0,
                }
            )
        )


if __name__ == "__main__":
    main()