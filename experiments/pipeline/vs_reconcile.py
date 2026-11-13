"""vote_snapshots reconcile (orchestrator 00:10Z Nov 14; bundle 12, NOT deployed). The hourly recorder (pipeline/hourly.py) appends the raw
copy (raw/vote_snapshots/<d>.jsonl) BEFORE writing the warehouse part; when the part write fails, the warehouse misses that hour (Nov 5-7
pre-reveal rows). Two recorders on Nov 5-6 also appended duplicate rows to the raw file.
  check <d> [<d> ...]   counts only: raw rows, raw deduped by (launch_id, at), warehouse rows, warehouse deduped, missing in warehouse,
                        warehouse duplicates; exit 1 if warehouse deduped != raw deduped for any day
  fix <d> [<d> ...]     writes the missing (deduped) rows as one extra warehouse part per day (vote_snapshots/reconcile_<d>_<utc>), then re-checks.
                        Never deletes or rewrites existing parts (duplicates are reported; readers dedup on (launch_id, at)).
usage: python -m pipeline.vs_reconcile check|fix <YYYY-MM-DD>...   (USERSIM_CACHE = a private cache; bucket reads, fix writes one part)"""
import json, os, subprocess, sys
import pandas as pd
from . import warehouse as W
K = ["launch_id", "at"]


def raw(d):
    r = subprocess.run(["gsutil", "cat", f"{W.BUCKET}/raw/vote_snapshots/{d}.jsonl"], capture_output=True, text=True)
    R = pd.DataFrame([json.loads(l) for l in r.stdout.splitlines() if l.strip()]) if r.returncode == 0 else pd.DataFrame(columns=["day"] + K)
    if len(R):
        R["launch_id"] = R.launch_id.astype(str)
    return R


def check(days, sync=None):
    sync = (os.environ.get("VS_NOSYNC") != "1") if sync is None else sync
    S = W.query("SELECT * FROM vote_snapshots", do_sync=sync); S["launch_id"] = S.launch_id.astype(str); S["at"] = S["at"].astype(str)
    out, bad = [], False
    for d in days:
        R = raw(d); Rd = R.drop_duplicates(K) if len(R) else R; Sd_all = S[S.day.astype(str) == d]; Sd = Sd_all.drop_duplicates(K)
        miss = Rd.merge(Sd[K], on=K, how="left", indicator=True).query("_merge == 'left_only'") if len(Rd) else Rd
        o = {"day": d, "raw_rows": len(R), "raw_dedup": len(Rd), "wh_rows": len(Sd_all), "wh_dedup": len(Sd), "missing_in_wh": len(miss),
             "wh_duplicates": len(Sd_all) - len(Sd), "ok": len(Sd) == len(Rd) and len(miss) == 0}
        bad |= not o["ok"]; out.append(o)
    return out, bad


def fix(days):
    S = W.query("SELECT * FROM vote_snapshots", do_sync=True); S["launch_id"] = S.launch_id.astype(str); S["at"] = S["at"].astype(str)
    for d in days:
        R = raw(d)
        if not len(R):
            continue
        Rd = R.drop_duplicates(K); Sd = S[S.day.astype(str) == d].drop_duplicates(K)
        miss = Rd.merge(Sd[K], on=K, how="left", indicator=True).query("_merge == 'left_only'").drop(columns="_merge")
        if len(miss):
            W.write("vote_snapshots", miss[[c for c in R.columns]], part=f"reconcile_{d}_{pd.Timestamp.now(tz='UTC'):%Y%m%dT%H%M%S}")
        print(json.dumps({"day": d, "rows_added": len(miss)}))
    return check(days, sync=True)


if __name__ == "__main__":
    mode, days = sys.argv[1], sys.argv[2:]
    res, bad = (check(days) if mode == "check" else fix(days))
    for o in res:
        print(json.dumps(o))
    sys.exit(1 if bad else 0)
