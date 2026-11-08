#!/usr/bin/env python3
"""Durable agent-msgs consume: persist JSONL, then ack Pub/Sub."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def pull(project: str, sub: str, limit: int) -> list[dict]:
    r = subprocess.run(
        [
            "gcloud",
            "pubsub",
            "subscriptions",
            "pull",
            sub,
            f"--project={project}",
            f"--limit={limit}",
            "--format=json",
            "--no-auto-ack",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return []
    raw = (r.stdout or "").strip()
    if not raw:
        return []
    return json.loads(raw) if raw.startswith("[") else [json.loads(raw)]


def ack(project: str, sub: str, ack_ids: list[str]) -> None:
    if not ack_ids:
        return
    subprocess.run(
        [
            "gcloud",
            "pubsub",
            "subscriptions",
            "ack",
            sub,
            f"--project={project}",
            f"--ack-ids={','.join(a for a in ack_ids if a)}",
        ],
        check=False,
        timeout=60,
    )


def decode_data(msg: dict) -> str:
    data = (msg.get("message") or {}).get("data") or ""
    if not data:
        return ""
    try:
        return base64.b64decode(data).decode("utf-8", "replace")
    except Exception:
        return data


def attrs(msg: dict) -> dict[str, str]:
    raw = (msg.get("message") or {}).get("attributes") or {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    out: dict[str, str] = {}
    for a in raw:
        if isinstance(a, dict):
            out[a.get("key", "")] = a.get("value", "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--subscription", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--ack", action="store_true", help="Ack after durable append")
    ap.add_argument("--once-tag", default="", help="dedupe tag stored per line")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if args.out.exists():
        for ln in args.out.read_text().splitlines():
            try:
                seen.add(json.loads(ln).get("messageId", ""))
            except Exception:
                pass
    rows = pull(args.project, args.subscription, args.limit)
    ack_ids: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with args.out.open("a") as f:
        for row in rows:
            mid = (row.get("message") or {}).get("messageId") or ""
            if mid and mid in seen:
                ack_ids.append(row.get("ackId", ""))
                continue
            body = decode_data(row)
            at = attrs(row)
            rec = {
                "utc": now,
                "subscription": args.subscription,
                "messageId": mid,
                "ackId": row.get("ackId"),
                "from": at.get("from"),
                "to": at.get("to"),
                "ts": at.get("ts"),
                "onceTag": args.once_tag or None,
                "data": body,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if mid:
                seen.add(mid)
            if args.ack and row.get("ackId"):
                ack_ids.append(row["ackId"])
    if args.ack:
        ack(args.project, args.subscription, [a for a in ack_ids if a])
    print(json.dumps({"subscription": args.subscription, "new": len(rows), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
