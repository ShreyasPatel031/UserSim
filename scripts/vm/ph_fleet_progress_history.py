#!/usr/bin/env python3
"""Build fleet-dashboard/history.json from checkin.log + autoscale for the cppm line chart."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


MILESTONES = [
    ("2026-11-08T22:15:00Z", "fix", "Queue cache + 75s CF open timeout deployed"),
    ("2026-11-08T22:25:00Z", "recover", "Manual kick: 17 VMs stuck 20+ min after block"),
    ("2026-11-08T22:33:00Z", "fix", "Fast block exit, supervisor 5s poll, claim release"),
    ("2026-11-08T23:02:00Z", "scale", "Autoscale shed 4 VMs (42→19 planned)"),
    ("2026-11-08T23:15:00Z", "scale", "Shed 4 more VMs → 15"),
    ("2026-11-08T23:41:00Z", "fix", "Parallel requeue reads on queue-cache miss"),
    ("2026-11-08T23:45:00Z", "scale", "Under 20/min → +1 VM (slot 27)"),
]


def parse_measures(log: str) -> list[dict]:
    out = []
    for line in log.splitlines():
        if "measure=" not in line:
            continue
        try:
            j = json.loads(line.split("measure=", 1)[1])
        except Exception:
            continue
        out.append(
            {
                "utc": j.get("utc"),
                "complete_ppm": float(j.get("complete_ppm") or j.get("realized_ppm") or 0),
                "attempt_ppm": float(j.get("attempt_ppm") or 0),
                "rerun_ppm": float(j.get("rerun_ppm") or 0),
                "vms": int(j.get("vms") or 0),
                "active_vms": int(j.get("active_vms") or 0),
                "stale_vms": int(j.get("stale_vms") or 0),
                "cold_vms": int(j.get("cold_vms") or 0),
                "productive_vms": int(j.get("productive_vms") or 0),
                "avg_ppm_productive": float(j.get("avg_ppm_productive") or 0),
            }
        )
    # dedupe by utc
    seen = set()
    deduped = []
    for p in out:
        if p["utc"] in seen:
            continue
        seen.add(p["utc"])
        deduped.append(p)
    return deduped


def log_events_between(log: str, t0: str, t1: str) -> list[str]:
    ev = []
    for line in log.splitlines():
        m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", line)
        if not m:
            continue
        ts = m.group(1)
        if not (t0 < ts <= t1):
            continue
        if any(
            k in line
            for k in (
                "BATCH_KICKED",
                "==> delete",
                "==> create",
                "scale-to",
                "OVER ",
                "UNDER ",
                "IN BAND",
                "SHED idle",
                "FIXES_AUDIT",
                "bad_slots",
            )
        ):
            ev.append(line.strip()[:200])
    return ev


def explain_step(prev: dict, cur: dict, events: list[str]) -> dict:
    d_ppm = round(cur["complete_ppm"] - prev["complete_ppm"], 2)
    factors: list[dict] = []
    dv = cur["vms"] - prev["vms"]
    y = prev["avg_ppm_productive"] or (prev["complete_ppm"] / prev["vms"] if prev["vms"] else 0)
    if dv:
        factors.append(
            {
                "label": f"{dv:+d} VMs",
                "est_ppm": round(dv * y, 1),
                "detail": f"~{y:.2f} complete/min per VM at prior rate",
            }
        )
    da = cur["active_vms"] - prev["active_vms"]
    if abs(da) >= 2 and not dv:
        factors.append(
            {
                "label": f"{da:+d} active pullers",
                "est_ppm": round(da * y, 1),
                "detail": "more slots saving in the window",
            }
        )
    ds = cur["stale_vms"] - prev["stale_vms"]
    dc = cur["cold_vms"] - prev["cold_vms"]
    if ds or dc:
        factors.append(
            {
                "label": f"stale {ds:+d}, cf_wall {dc:+d}",
                "est_ppm": None,
                "detail": "idle or blocked slots",
            }
        )
    kicks = sum(1 for e in events if "BATCH_KICKED" in e)
    if kicks:
        factors.append(
            {
                "label": f"{kicks} hang kicks",
                "est_ppm": None,
                "detail": "released stuck collectors",
            }
        )
    dels = sum(1 for e in events if "==> delete" in e)
    creates = sum(1 for e in events if "==> create" in e)
    if dels and not dv:  # already counted via dv
        factors.append({"label": f"{dels} VM deletes", "est_ppm": None, "detail": "autoscale"})
    if creates:
        factors.append({"label": f"{creates} VM creates", "est_ppm": None, "detail": "autoscale"})
    bad = [e for e in events if "FIXES_AUDIT" in e and "bad=" in e and "bad=none" not in e]
    if bad:
        factors.append({"label": "fixes drift", "est_ppm": None, "detail": bad[0][:120]})

    direction = "up" if d_ppm > 0.5 else "down" if d_ppm < -0.5 else "flat"
    return {
        "from_utc": prev["utc"],
        "to_utc": cur["utc"],
        "delta_ppm": d_ppm,
        "direction": direction,
        "factors": factors,
        "events": events[:8],
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    run = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z")
    art = root / "results" / "ph_fleet_full" / run
    log_path = art / "checkin.log"
    if not log_path.exists():
        print("no checkin.log", file=sys.stderr)
        return 1
    log = log_path.read_text()
    series = parse_measures(log)
    if not series:
        return 1

    drivers = []
    for i in range(1, len(series)):
        ev = log_events_between(log, series[i - 1]["utc"], series[i]["utc"])
        drivers.append(explain_step(series[i - 1], series[i], ev))
    drivers.sort(key=lambda x: abs(x["delta_ppm"]), reverse=True)

    milestones = [
        {"utc": t, "kind": k, "label": lbl}
        for t, k, lbl in MILESTONES
        if series and t >= series[0]["utc"]
    ]

    out = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": str(run),
        "target_lo": 20,
        "target_hi": 30,
        "series": series,
        "milestones": milestones,
        "drivers": drivers[:12],
        "latest": series[-1],
        "peak": max(series, key=lambda p: p["complete_ppm"]),
        "trough": min(series, key=lambda p: p["complete_ppm"]),
    }
    web = root / "fleet-dashboard"
    web.mkdir(parents=True, exist_ok=True)
    (web / "history.json").write_text(json.dumps(out, indent=2))
    (art / "progress_history.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"points": len(series), "latest_ppm": series[-1]["complete_ppm"]}))
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main())
