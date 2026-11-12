#!/usr/bin/env python3
"""Compute minimum daily IPs from soak.tsv + GCS daily workload bounds."""
import json
import os
import subprocess
import sys
from pathlib import Path

art = Path(sys.argv[1])
soak = art / "soak.tsv"
rows = []
if soak.exists():
    for ln in soak.read_text().splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        p = ln.split("\t")
        if len(p) < 7:
            continue
        rows.append(
            {
                "tag": p[0],
                "ip": p[1],
                "level": p[2],
                "complete_ppm": float(p[3] or 0),
                "attempt_ppm": float(p[4] or 0),
                "gql429": int(float(p[5] or 0)),
                "walls": int(float(p[6] or 0)),
                "browser_ok": int(float(p[7] or 0)),
                "browser_fail": int(float(p[8] or 0)),
            }
        )

# Typical daily people (measured 2026-11-03) vs cap (Data Feeder)
people_typical = 131
people_cap = 700
# Heavy page pass: Data Feeder 25–45 min; budget ~400 graphql-heavy pages (conservative)
heavy_pages = 400
# Light daily pull ~5 gql-equiv per person vs pdeep ~80 → scale factor
GQL_RATIO = 80 / 5

def ppm_to_light_people_per_min(ppm: float) -> float:
    return ppm * GQL_RATIO

steady = [r for r in rows if "daily_steady" in r["level"] or r["tag"].startswith("n2_")]
best = max((r["complete_ppm"] for r in steady), default=0)
if not best:
    best = max((r["complete_ppm"] for r in rows), default=0)
if best <= 0:
    best = 0.5  # Spain L2 fallback if Finland VM soak still warming

light_ppm = ppm_to_light_people_per_min(best)
typical_min = (people_typical + heavy_pages / 5) / max(light_ppm, 0.1)
cap_min = (people_cap + heavy_pages / 5) / max(light_ppm, 0.1)

parallel_n2 = [r for r in rows if r["tag"].startswith("n2_")]
n2_sum = sum(r["complete_ppm"] for r in parallel_n2)

blocked = [r["ip"] for r in rows if r["browser_fail"] > 0 and r["browser_ok"] == 0]

out = {
    "soak_rows": len(rows),
    "ips_cf_blocked_on_vm": blocked,
    "best_pdeep_complete_ppm": best,
    "estimated_light_people_per_min_per_ip": round(light_ppm, 2),
    "typical_daily_people": people_typical,
    "people_cap": people_cap,
    "heavy_page_budget": heavy_pages,
    "min_ips_typical_serial_hours": round(typical_min / 60, 2),
    "min_ips_cap_serial_hours": round(cap_min / 60, 2),
    "min_ips_typical_rounded": max(1, int(-(-typical_min // 60))),  # ceil hours → IPs if 1 job/IP
    "min_ips_parallel_overlap": 2 if parallel_n2 else None,
    "two_ip_parallel_pdeep_ppm_sum": round(n2_sum, 3),
    "recommendation": (
        "1 IP if heavy + people are scheduled sequentially (typical day fits in ~1–2h). "
        "2 IPs minimum for parallel morning windows without 429 bleed. "
        "3 IPs only if you want headroom on 700-person cap days while heavy pass runs."
    ),
}
(rep := art / "min_ips.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
