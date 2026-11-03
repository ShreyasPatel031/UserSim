"""C2: dated pre-launch user-base measures for any number of sources (Data Feeder's raw/ph_userbase/<source>.jsonl), scored
with the same gate and boards as C1 (userbase_eval), with no new code per source.
Expected rows (JSON lines; fails loudly on a missing column): launch_id, source, as_of_date (YYYY-MM-DD), count
  (url and capture_url optional). A source may give one row per launch (already measured as of a date before launch,
  e.g. Wayback captures in the 90 days before) or a dated series (several rows per launch).
Per launch and source: c2_<source> = log1p(count) at the latest as_of_date strictly before the launch's Pacific day
(rows dated on or after the launch day are dropped and counted in the output). Sources with fewer than MIN_COVERED
launches are reported but not scored. Optional C1 inputs (stars / downloads) can be added with C1_JSON (c1_user_base
features are recomputed if its inputs are given).
Reference: HONEST_COL (default "honest - live set" with HONEST_PREDS, the live forecast's honest set; state it in reports).
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... python c2_user_base.py <raw/ph_userbase dir or files...> -> results/c2_user_base.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
import userbase_eval as UE

MIN_COVERED = int(os.environ.get("MIN_COVERED", "50"))


def launch_days(days_dir="data"):
    day = {}
    for f in sorted(glob.glob(os.path.join(days_dir, "days", "*.json"))) + sorted(glob.glob(os.path.join(days_dir, "today", "*.json"))):
        for p in json.load(open(f)):
            day.setdefault(str(p["id"]), os.path.basename(f)[:10])
    return day


def read_rows(paths):
    files = []
    for p in paths:
        files += [p] if os.path.isfile(p) else sorted(glob.glob(os.path.join(p, "*.jsonl")))
    if not files:
        raise SystemExit(f"no *.jsonl in {paths}")
    U = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in files], ignore_index=True)
    if "metric" in U:   # e.g. source=wayback_profile, metric=followers|followings|points -> wayback_profile_followers, ...
        U["source"] = U.source.astype(str) + U.metric.map(lambda m: f"_{m}" if isinstance(m, str) and m else "")
    if "count" not in U and "value" in U:
        U = U.rename(columns={"value": "count"})
    UE.need(U, ["launch_id", "source", "as_of_date", "count"], "ph_userbase")
    return U


def features(U, day):
    U = U.assign(launch_id=U.launch_id.astype(str), as_of_date=U.as_of_date.astype(str).str[:10],
                 count=pd.to_numeric(U["count"], errors="coerce"), source=U.source.astype(str).str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True))
    U["lday"] = U.launch_id.map(day)
    dropped = {"unknown_launch": int(U.lday.isna().sum())}
    U = U[U.lday.notna() & U["count"].notna()]
    late = U.as_of_date >= U.lday
    dropped["on_or_after_launch_day"] = int(late.sum())
    U = U[~late].sort_values("as_of_date")
    last = U.groupby(["launch_id", "source"]).tail(1)
    F = last.pivot_table(index="launch_id", columns="source", values="count", aggfunc="last")
    F = np.log1p(F.clip(lower=0)); F.columns = [f"c2_{c}" for c in F.columns]
    return F.reset_index().rename(columns={"launch_id": "id"}), dropped


def main(*paths):
    day = launch_days(os.environ.get("DAYS_DIR", "data"))
    F, dropped = features(read_rows(paths), day)
    os.environ.setdefault("HONEST_COL", "honest - live set")
    cov = {c: int(F[c].notna().sum()) for c in F.columns if c != "id"}
    cols = [c for c, n in cov.items() if n >= MIN_COVERED]
    print(json.dumps({"rows_dropped": dropped, "covered_launches_by_source": cov, "scored": cols}), flush=True)
    if not cols:
        raise SystemExit(f"no source has {MIN_COVERED}+ covered launches")
    res = UE.evaluate(F[["id"] + cols], "c2", cols, os.environ.get("OUT", "results/c2_user_base.json"))
    res["rows_dropped"] = dropped; res["covered_launches_by_source"] = cov; res["reference"] = os.environ["HONEST_COL"]
    json.dump(res, open(os.environ.get("OUT", "results/c2_user_base.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    main(*sys.argv[1:])
