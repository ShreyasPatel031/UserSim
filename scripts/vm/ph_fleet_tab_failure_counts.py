#!/usr/bin/env python3
"""Aggregate per-tab failure counts from Population audit TSVs for status.json."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = (os.environ.get("PACE_FLEET_RUN_ID") or "20261108t082000z").lower()
ART = Path(os.environ.get("FLEET_ART") or ROOT / f"results/ph_fleet_full/{RUN_ID}")
BKT = os.environ["MVP_GCS_BUCKET"]
OUT = ART / "tab_failure_counts.json"
G = f"gs://{BKT}/usersim_sim/raw/_cursor"


def gs_ls_audits() -> list[str]:
    r = subprocess.run(
        ["gcloud", "storage", "ls", f"{G}/audit_20261121T*.tsv"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return []
    return sorted(x.strip().split("/")[-1] for x in r.stdout.splitlines() if x.strip())[-6:]


def parse_reasons(reasons: str, tab: Counter, people: Counter):
    if not reasons:
        return
    for m in re.finditer(r"not_filled:(\w+)", reasons):
        k = f"not_filled:{m.group(1)}"
        tab[k] += 1
        people[k] += 1
    for m in re.finditer(r"(\w+):FAIL_partial", reasons):
        k = f"fail_partial:{m.group(1)}"
        tab[k] += 1
        people[k] += 1
    for m in re.finditer(r"header_missing:([^\t]+)", reasons):
        chunk = m.group(1)
        for part in re.split(r"[,;]", chunk):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                tab_name = part.split(":", 1)[0]
                tab[f"header_missing:{tab_name}"] += 1
                people[f"header_missing:{tab_name}"] += 1
            elif part in ("hunted", "collections", "stacks", "reviews"):
                tab[f"header_missing:{part}"] += 1
                people[f"header_missing:{part}"] += 1


def main() -> int:
    inc = 0
    rp = ART / "refill_state.json"
    if rp.is_file():
        try:
            inc = int(json.loads(rp.read_text()).get("pdeep_incomplete") or 0)
        except Exception:
            pass
    tab_people: Counter = Counter()
    held_no_pkg = 0
    held_build = 0
    audits_used: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        for name in gs_ls_audits():
            local = Path(td) / name
            if subprocess.run(["gcloud", "storage", "cp", f"{G}/{name}", str(local)], capture_output=True).returncode != 0:
                continue
            audits_used.append(name)
            for ln in local.read_text().splitlines():
                if ln.startswith("#") or not ln.strip():
                    continue
                parts = ln.split("\t")
                if len(parts) < 3:
                    continue
                res = parts[2]
                pkg = parts[3] if len(parts) > 3 else ""
                reasons = parts[5] if len(parts) > 5 else (parts[4] if len(parts) > 4 and "not_filled" in parts[4] else "")
                if res == "fail":
                    parse_reasons(reasons, tab_people, tab_people)
                if res == "held_gate" and (pkg in ("", "None") or "build_not_audited" in reasons):
                    held_build += 1
                    if pkg in ("", "None"):
                        held_no_pkg += 1
    tab_people["pdeep_stacks_PersistedQueryNotFound_blocks_whole_est"] = inc
    need_list_tab_counts = {k: v for k, v in sorted(tab_people.items(), key=lambda x: -x[1])}
    report = {
        "utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audits_scanned": audits_used,
        "need_list_incomplete_store": inc,
        "need_list_tab_failure_people_counts": need_list_tab_counts,
        "refresh_held_legacy_no_pkg_md5_approx": held_no_pkg,
        "refresh_held_build_not_audited_in_audits": held_build,
        "orchestrator_deadline_22z_tab_counts_utc": "2026-11-21T22:00:00Z",
        "forecast_deadline_00_05_pt_utc": "2026-11-22T08:05:00Z",
        "note": "Counts are people rows in recent Population audits (fail/held), plus store-scale stacks blocker for need_list.",
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())