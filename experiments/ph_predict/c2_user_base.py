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
Wayback profile rows (username, role, launch_id, launch_day, capture_ts, age_days, metric, count, parse_route,
capture_url) are read as is: as_of_date = the capture's Pacific day, source wayback_profile_<metric>, unparsed (null
count) rows dropped and counted. MAX_AGE_D (e.g. 30) keeps only recent values; ROLES=hunter / maker scores one role; MAKER_SOURCE=api / resolved keeps
makers from that source only (v2).
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... python c2_user_base.py <raw/ph_userbase dir or files...> -> results/c2_user_base.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
import userbase_eval as UE

MIN_COVERED = int(os.environ.get("MIN_COVERED", "50"))
MAX_AGE_D = int(os.environ.get("MAX_AGE_D", "0"))   # > 0: keep only values measured at most this many days before launch
ROLES = {r for r in os.environ.get("ROLES", "").split(",") if r}   # e.g. "hunter" or "maker": per-person rows of that role only
MAKER_SOURCE = os.environ.get("MAKER_SOURCE", "")   # "api" or "resolved": keep maker rows from that source only (v2 maker_source)


def capture_time(x):
    """capture_ts as UTC timestamps: Wayback's 14-digit YYYYMMDDhhmmss, or ISO 8601. Unparseable -> loud failure."""
    x = x.astype(str).str.strip()
    wb = x.str.fullmatch(r"\d{14}")
    t = pd.Series(pd.NaT, index=x.index, dtype="datetime64[ns, UTC]")
    t[wb] = pd.to_datetime(x[wb], format="%Y%m%d%H%M%S", utc=True)
    t[~wb] = pd.to_datetime(x[~wb], utc=True, errors="coerce", format="ISO8601")
    if t.isna().any():
        raise SystemExit(f"capture_ts: {int(t.isna().sum())} unparseable, e.g. {x[t.isna()].iloc[0]!r}")
    return t


def launch_days(days_dir="data"):
    day = {}
    for f in sorted(glob.glob(os.path.join(days_dir, "days", "*.json"))) + sorted(glob.glob(os.path.join(days_dir, "today", "*.json"))):
        for p in json.load(open(f)):
            day.setdefault(str(p["id"]), os.path.basename(f)[:10])
    # a line-up file can list a launch PH later moves to another day (1284558 specsight-2: in today/2026-10-25.json,
    # launched Oct 31); the warehouse launches table keeps the latest day, so it wins where reachable
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from pipeline import warehouse as W
        wh = dict(W.query('SELECT id::VARCHAR, "day"::VARCHAR FROM launches').values.tolist())
        fixed = {k: wh[k] for k in day if k in wh and wh[k] != day[k]}
        day.update(fixed)
        if fixed:
            print(json.dumps({"launch_days_corrected_from_warehouse": fixed}), flush=True)
    except Exception as e:  # noqa: BLE001  (no warehouse here: file days only)
        print(json.dumps({"launch_days": f"file days only ({type(e).__name__})"}), flush=True)
    return day


def read_rows(paths):
    files = []
    for p in paths:
        files += [p] if os.path.isfile(p) else sorted(glob.glob(os.path.join(p, "*.jsonl")))
    if not files:
        raise SystemExit(f"no *.jsonl in {paths}")
    U = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in files], ignore_index=True)
    if "source" not in U and "parse_route" in U:
        U["source"] = "wayback_profile"
    if "metric" in U:   # e.g. source=wayback_profile, metric=followers|followings|points -> wayback_profile_followers, ...
        U["source"] = U.source.astype(str) + U.metric.map(lambda m: f"_{m}" if isinstance(m, str) and m else "")
    if "count" not in U and "value" in U:
        U = U.rename(columns={"value": "count"})
    if "capture_ts" in U:   # Wayback profile rows: dated by the capture's Pacific day (replacing any as_of_date), so
        # "as_of_date < launch day" is "captured strictly before 00:00 PT of the launch day"
        U["capture_ts"] = capture_time(U.capture_ts)
        U["as_of_date"] = U.capture_ts.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    n0 = len(U)
    U = U[pd.to_numeric(U.get("count"), errors="coerce").notna()] if "count" in U else U
    if len(U) < n0:
        print(json.dumps({"unparsed_rows_dropped": n0 - len(U)}), flush=True)
    if MAKER_SOURCE:
        if "maker_source" not in U:
            raise SystemExit("MAKER_SOURCE set but the rows have no maker_source column")
        mk = U.role.astype(str).str.lower().str.startswith("make")
        U = U[~mk | (U.maker_source.astype(str) == MAKER_SOURCE)]
    if ROLES and "role" in U:   # maker-only / hunter-only variants
        U = U[U.role.astype(str).str.lower().map(lambda r: "hunter" if r.startswith("hunt") else "maker").isin(ROLES)]
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
    # age in days before launch: with capture_ts, (launch day 00:00 PT - capture_ts) in fractional days, as Data
    # Feeder's age_days; otherwise whole days from as_of_date to the launch day
    if "capture_ts" in U:
        l0 = pd.to_datetime(U.lday).dt.tz_localize("America/Los_Angeles")
        U["age"] = (l0 - U.capture_ts.dt.tz_convert("America/Los_Angeles")).dt.total_seconds() / 86400
    else:
        U["age"] = (pd.to_datetime(U.lday) - pd.to_datetime(U.as_of_date)).dt.days.astype(float)
    if MAX_AGE_D > 0:
        old = U.age > MAX_AGE_D
        dropped[f"older_than_{MAX_AGE_D}d"] = int(old.sum()); U = U[~old]
    who = next((c for c in ("username", "person", "user") if c in U), None)
    if who is None:   # one series per launch and source: the latest value before the day
        last = U.groupby(["launch_id", "source"]).tail(1)
        F = last.pivot_table(index="launch_id", columns="source", values="count", aggfunc="last")
        F = np.log1p(F.clip(lower=0)); F.columns = [f"c2_{c}" for c in F.columns]
        return F.reset_index().rename(columns={"launch_id": "id"}), dropped
    # per-person rows (e.g. Wayback profile captures of each maker / hunter): the latest capture before the day per
    # person, then per launch the max over makers and, separately, the hunter, plus the age in days of the capture behind
    # that value (an older capture is a lower bound on the at-launch count; the age lets the model discount it)
    if "role" in U:
        U["source"] = U.source + "_" + U.role.astype(str).str.lower().map(lambda r: "hunter" if r.startswith("hunt") else "maker")
    last = U.groupby(["launch_id", "source", who]).tail(1).copy()
    best = last.sort_values("count").groupby(["launch_id", "source"]).tail(1)
    V = np.log1p(best.pivot_table(index="launch_id", columns="source", values="count", aggfunc="last").clip(lower=0))
    Ag = best.pivot_table(index="launch_id", columns="source", values="age", aggfunc="last")
    V.columns = [f"c2_{c}" for c in V.columns]; Ag.columns = [f"c2_{c}_age_d" for c in Ag.columns]
    # one capture gives every metric of a person, so ages repeat across metrics: keep one age per role (from
    # followers, filled from another metric where followers is missing); Holm counts inputs
    import re
    grp = {}
    for c in Ag.columns:
        m = re.match(r"(c2_.+?)_(followers|followings|points)_(maker|hunter)_age_d$", c)
        grp.setdefault((m.group(1), m.group(3)) if m else (c, ""), []).append(c)
    out = {}
    for (src, role), cs in grp.items():
        cs = sorted(cs, key=lambda c: (0 if "_followers_" in c else 1, c))
        a = Ag[cs[0]].copy()
        for c in cs[1:]:
            a = a.fillna(Ag[c])
        out[f"{src}_followers_{role}_age_d" if role else src] = a
    dropped["age_inputs"] = f"{len(Ag.columns)} -> {len(out)}"
    Ag = pd.DataFrame(out)
    return V.join(Ag).reset_index().rename(columns={"launch_id": "id"}), dropped


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
