#!/usr/bin/env python3
"""Drop SB claims blocking fleet pdeep_list handles when the owning VM is dead/stale or not pulling."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACE = Path(os.environ.get("PACE_ENV_FILE", ROOT / "results/ph_fleet_full/20261108t082000z/pace.env"))
run_id = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z").lower()
art = ROOT / "results/ph_fleet_full" / run_id

for line in PACE.read_text().splitlines():
    if line.startswith("MVP_GCS_BUCKET="):
        bucket = line.split("=", 1)[1].strip()
        break
else:
    print("no bucket", file=sys.stderr)
    sys.exit(1)

vm_root = os.environ.get(
    "PACE_GCS_VM_ROOT",
    f"gs://{bucket}/usersim_sim/raw/ph_population/people_live/vm",
)
sb = os.environ.get(
    "PH_SAVE_B",
    f"gs://{bucket}/usersim_sim/raw/_pacetest/shared",
)


def gs(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gcloud", "storage", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(" ".join(args) + " " + (r.stderr or r.stdout))
    return (r.stdout or "").strip()


def gs_cat(url: str) -> str:
    r = subprocess.run(["gcloud", "storage", "cat", url], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


measure = json.loads((art / "fleet_measure.json").read_text())
stale_dead: dict[str, str] = {}
for s in measure.get("slots") or []:
    slot = int(s["slot"])
    st = s.get("state") or ""
    age = int(s.get("age") or 0)
    if st in ("dead", "cold") or (st == "stale" and age > 600):
        stale_dead[f"feeder-fleet-{run_id}-{slot}"] = st

handles: set[str] = set()
for url in gs("ls", f"{vm_root}/pdeep_list.feeder-fleet-{run_id}-*.txt", check=False).split():
    if not url.endswith(".txt"):
        continue
    for ln in gs_cat(url).splitlines():
        h = ln.strip().lower().lstrip("@")
        if h and not h.startswith("#"):
            handles.add(h)

claimed = [u.rsplit("/", 1)[-1] for u in gs("ls", f"{sb}/claims/", check=False).split() if u and "/" in u]
todo = sorted(handles.intersection(claimed))
released, kept, missing = 0, 0, len(handles) - len(todo)

from concurrent.futures import ThreadPoolExecutor, as_completed

def _release(h: str) -> str:
    curl = f"{sb}/claims/{h}"
    body = gs_cat(curl)
    if not body:
        return "missing"
    owner = body.split()[0].strip()
    m = re.search(rf"feeder-fleet-{run_id}-(\d+)", owner)
    if not m:
        return "kept"
    vm = f"feeder-fleet-{run_id}-{m.group(1)}"
    if vm not in stale_dead:
        return "kept"
    subprocess.run(
        ["gcloud", "storage", "rm", "-q", curl],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "released"

with ThreadPoolExecutor(max_workers=32) as ex:
    futs = {ex.submit(_release, h): h for h in todo}
    for fut in as_completed(futs):
        r = fut.result()
        if r == "released":
            released += 1
        elif r == "kept":
            kept += 1
        elif r == "missing":
            missing += 1

out = {
    "utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "handles_in_lists": len(handles),
    "released": released,
    "kept_active_owner": kept,
    "no_claim": missing,
}
print(json.dumps(out))
sys.exit(0 if released else 0)