#!/usr/bin/env python3
"""Append IPRoyal sticky-IP rotations to Population audit log (GCS jsonl)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _bucket() -> str:
    return os.environ.get("MVP_GCS_BUCKET", "").strip()


def audit_gcs_uri() -> str | None:
    b = _bucket()
    if not b:
        return None
    prefix = os.environ.get(
        "IPROYAL_ROTATE_AUDIT_OBJ",
        "usersim_sim/raw/_cursor/iproyal_rotate/rotate.jsonl",
    ).lstrip("/")
    return f"gs://{b}/{prefix}"


def art_dir() -> Path:
    root = Path(os.environ.get("PACE_REPO_ROOT", Path(__file__).resolve().parents[2]))
    run = os.environ.get("PACE_FLEET_RUN_ID", "").lower()
    if not run:
        p = root / "results/ph_fleet_full/latest_run.txt"
        if p.is_file():
            run = p.read_text().strip().lower()
    return Path(os.environ.get("FLEET_ART", root / f"results/ph_fleet_full/{run}"))


def local_mirror_path() -> Path:
    return art_dir() / "iproyal_rotate_audit.jsonl"


def _run_id() -> str:
    rid = os.environ.get("PACE_FLEET_RUN_ID", "").lower()
    if rid:
        return rid
    p = Path(os.environ.get("PACE_REPO_ROOT", Path(__file__).resolve().parents[2])) / "results/ph_fleet_full/latest_run.txt"
    if p.is_file():
        return p.read_text().strip().lower()
    return ""


def vm_name(slot: str | int, run_id: str | None = None) -> str:
    rid = (run_id or _run_id()).lower()
    return f"feeder-fleet-{rid}-{slot}"


def row_from_rotate_result(res: dict, utc: str | None = None) -> dict | None:
    if not res.get("ok"):
        return None
    slot = str(res.get("slot") or "")
    if not slot:
        return None
    ts = utc or res.get("utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "slot": int(slot) if slot.isdigit() else slot,
        "vm": vm_name(slot),
        "utc": ts,
        "old_ip": res.get("from_host") or res.get("old_ip"),
        "new_ip": res.get("to_host") or res.get("new_ip"),
        "reason": res.get("reason") or "unknown",
        "gen": int(res.get("gen") or 0),
    }


def row_from_rebalance_move(moved: dict, run_id: str | None = None) -> dict:
    slot = str(moved.get("slot") or "")
    return {
        "slot": int(slot) if slot.isdigit() else slot,
        "vm": vm_name(slot, run_id),
        "utc": moved.get("utc")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "old_ip": moved.get("from_host"),
        "new_ip": moved.get("to_host"),
        "reason": moved.get("reason") or "rebalance_unique",
        "gen": int(moved.get("gen") or 0),
    }


def _dedupe_key(row: dict) -> tuple:
    return (
        str(row.get("utc")),
        str(row.get("slot")),
        str(row.get("old_ip")),
        str(row.get("new_ip")),
        int(row.get("gen") or 0),
    )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def append_row(row: dict, flush_gcs: bool = True) -> None:
    mirror = local_mirror_path()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    seen = {_dedupe_key(r) for r in _read_jsonl(mirror)}
    key = _dedupe_key(row)
    if key in seen:
        return
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with mirror.open("a") as f:
        f.write(line)
    if flush_gcs:
        flush_mirror_to_gcs()


def flush_mirror_to_gcs() -> bool:
    uri = audit_gcs_uri()
    if not uri:
        return False
    mirror = local_mirror_path()
    if not mirror.is_file():
        return False
    subprocess.run(["gsutil", "-q", "cp", str(mirror), uri], check=False)
    return True


def record_rotate_result(res: dict, utc: str | None = None) -> None:
    row = row_from_rotate_result(res, utc=utc)
    if row:
        append_row(row)


def backfill_from_run_log(log_path: Path | None = None) -> int:
    log_path = log_path or (art_dir() / "iproyal_rotate.log")
    if not log_path.is_file():
        return 0
    n = 0
    for ln in log_path.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(" ", 1)
        if len(parts) != 2:
            continue
        ts, payload = parts[0], parts[1]
        try:
            res = json.loads(payload)
        except json.JSONDecodeError:
            continue
        row = row_from_rotate_result(res, utc=ts)
        if not row:
            continue
        append_row(row, flush_gcs=False)
        n += 1
    flush_mirror_to_gcs()
    return n


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: ph_iproyal_rotate_audit.py flush|backfill|append-json",
            file=sys.stderr,
        )
        return 2
    cmd = sys.argv[1]
    if cmd == "flush":
        print(json.dumps({"flushed": flush_mirror_to_gcs(), "uri": audit_gcs_uri()}))
        return 0
    if cmd == "backfill":
        n = backfill_from_run_log()
        print(json.dumps({"backfilled": n, "uri": audit_gcs_uri()}))
        return 0
    if cmd == "append-json" and len(sys.argv) > 2:
        res = json.loads(sys.argv[2])
        utc = sys.argv[3] if len(sys.argv) > 3 else None
        record_rotate_result(res, utc=utc)
        print(json.dumps({"appended": True}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())