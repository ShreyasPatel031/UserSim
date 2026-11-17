#!/usr/bin/env python3
"""Keep only handles whose last saved upvotes paging did NOT end at PH hasNextPage=false."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

BKT = os.environ["MVP_GCS_BUCKET"]
ROOT = f"gs://{BKT}/usersim_sim/raw/ph_population/people_live"
INP = os.environ.get("SCROLL_REREAD_IN", f"gs://{BKT}/usersim_sim/raw/_cursor/upvotes_scroll_reread.txt")
OUT = os.environ.get("SCROLL_REREAD_OUT", INP)
MAX_W = int(os.environ.get("SCROLL_REREAD_WORKERS", "32"))


def _handles() -> list[str]:
    r = subprocess.run(["gsutil", "-q", "cat", INP], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"read {INP}: {r.stderr[:200]}")
    return [ln.split()[0].lower().lstrip("@") for ln in r.stdout.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _ph_ended(h: str) -> bool:
    r = subprocess.run(["gsutil", "-q", "cat", f"{ROOT}/{h}.json"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    try:
        j = json.loads(r.stdout)
    except json.JSONDecodeError:
        return False
    pg = (j.get("upvotes") or {}).get("paging") or {}
    if pg.get("ph_list_end") or pg.get("ended") == "hasNextPage_false":
        return True
    tt = pg.get("trail_tail") or []
    if tt and len(tt[-1]) >= 4 and tt[-1][3] is False:
        return True
    if tt and len(tt[-1]) >= 3 and tt[-1][2] is False:
        return True
    tpg = ((j.get("run") or {}).get("timing") or {}).get("upvotes", {}).get("paging") or {}
    if tpg.get("ended") in ("server_end", "hasNextPage_false"):
        return True
    return False


def main() -> None:
    handles = _handles()
    keep: list[str] = []
    drop = 0
    with ThreadPoolExecutor(max_workers=MAX_W) as ex:
        futs = {ex.submit(_ph_ended, h): h for h in handles}
        for fut in as_completed(futs):
            h = futs[fut]
            if fut.result():
                drop += 1
            else:
                keep.append(h)
    keep.sort()
    body = "\n".join(keep) + ("\n" if keep else "")
    p = subprocess.run(["gsutil", "-q", "cp", "-", OUT], input=body, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    print(json.dumps({"in": len(handles), "keep": len(keep), "drop_ph_end": drop, "out": OUT}))


if __name__ == "__main__":
    main()