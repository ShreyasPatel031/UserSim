"""Pool-share timing test (orchestrator, Nov 3): is the pool a cause of the shock, or does it follow board position?
Yesterday's test (shock_pool.py) found pool share rises with the shock (within-day rho +0.41), but upvotes are dated
only to the launch day, so pool members could simply vote for launches that already sit high on the board. Here pool
engagement is measured EARLY, before board position can matter much, and compared with the final shock.

Vote counts are hidden for ~4 h (hide_votes_count; latestScore masked), so early pool share of VOTES cannot be read
directly in hours 0-2. Early engagement is measured with what is visible:
  pool_c_T     comments by pool people created within T hours of the launch start (featured_at, else 00:01 PT)
  all_c_T      all comments within T hours (the launch team excluded: makers / hunter)
  pool_c_share_T = pool_c_T / all_c_T (NaN if none)
  pool_u_T     pool upvotes first seen in a read ending by start + T (upvote first-seen windows, 4-h resolution:
               only T >= 4 is usable; NaN when the file is absent)
for T in 1, 2, 4 h, and the same counts for the whole day (to reproduce the launch-day-dated result on these days).
Pool = people first seen in our data before the launch day (warehouse people.first_seen < day): honest by construction.
Shock = within-day (log final votes - the live forecast's honest prediction), from raw/daily/<d>/forecast_<d>.parquet
(pred, log votes) and final votes from the warehouse launches table (final once the day is closed).
Test: within-day Spearman of shock vs each early measure, and vs the whole-day measure, bootstrap over days. If early
pool engagement predicts the shock about as well as whole-day pool engagement, the pool leads (mobilised early);
if only the whole-day measure does, the pool follows exposure.
Power: reports per day the launches with >= 1 early comment and >= 1 early pool comment; with ~35 launches/day and
rho ~0.4, about 10 days give a CI half-width near 0.1.
Inputs (spec 20261103T1945): raw/ph_at_launch/<day>/api_comments/*.jsonl (API pulls, commenter_user_id) and
raw/ph_at_launch/<day>/live/comments_ts.jsonl (launch_id, comment_id, username or
commenter_user_id (API rows: user redacted; mapped with ID_MAP, the population agent's id -> username map),
created_at, is_maker, is_hunter), posts_ts.jsonl (launch_id, featured_at, makers, hunter), optional
raw/ph_people_daily/<day>/upvotes_4h/*.jsonl (username, launch_id | post_id, first_seen_lo, first_seen_hi).
No usernames are written: counts only.
usage: python pool_timing.py <day> [<day> ...] -> results/pool_timing.json"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUCKET = os.environ.get("USERSIM_BUCKET", "gs://usersim-bakeoff-347838016394/usersim_sim")
HOURS = [1, 2, 4]


def fetch(day):
    d = tempfile.mkdtemp(prefix=f"pt_{day}_")
    for f in ("comments_ts", "posts_ts"):
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/live/{f}.jsonl", d], capture_output=True)
    subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/daily/{day}/forecast_{day}.parquet", d], capture_output=True)
    os.makedirs(f"{d}/up", exist_ok=True)
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{BUCKET}/raw/ph_people_daily/{day}/upvotes_4h/*.jsonl", f"{d}/up/"], capture_output=True)
    rd = lambda p: pd.read_json(p, lines=True, dtype=False) if os.path.exists(p) and os.path.getsize(p) else None
    ups = [pd.read_json(f, lines=True, dtype=False) for f in glob.glob(f"{d}/up/*.jsonl")]
    F = f"{d}/forecast_{day}.parquet"
    return api_comments(day, rd(f"{d}/comments_ts.jsonl")), rd(f"{d}/posts_ts.jsonl"), pd.concat(ups) if ups else None, pd.read_parquet(F) if os.path.exists(F) else None


def api_comments(day, C=None):
    """API comment pulls (orchestrator, Nov 3 23:25 UTC): raw/ph_at_launch/<day>/api_comments/<tag>.jsonl, outside
    live/, one file per hourly pull with post_id, comment_id, commenter_user_id, createdAt, parentId. Normalised to the
    comments_ts shape (launch_id, comment_id, commenter_user_id, created_at) and appended to the page comments; the
    caller dedupes by (launch_id, comment_id)."""
    d = tempfile.mkdtemp(prefix=f"apic_{day}_")
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/api_comments/*.jsonl", d], capture_output=True)
    parts = [pd.read_json(f, lines=True, dtype=False) for f in sorted(glob.glob(f"{d}/*.jsonl")) if os.path.getsize(f)]
    if not parts:
        return C
    A = pd.concat(parts, ignore_index=True).rename(columns={"post_id": "launch_id", "createdAt": "created_at", "parentId": "parent_id"})
    A = A[[c for c in ("launch_id", "comment_id", "commenter_user_id", "created_at", "parent_id", "snapshot_at") if c in A]]
    A["username"] = ""   # filled from commenter_user_id by resolve_commenters (ID_MAP)
    A = A.sort_values("snapshot_at").drop_duplicates(["launch_id", "comment_id"]) if "snapshot_at" in A else A.drop_duplicates(["launch_id", "comment_id"])
    return A if C is None else pd.concat([C, A], ignore_index=True)


def ts(x):
    return pd.to_datetime(x, utc=True, errors="coerce", format="ISO8601")


def names(v):
    if isinstance(v, (list, tuple)):
        return {((m.get("username") or "") if isinstance(m, dict) else str(m)).lower() for m in v} - {"", "none", "[redacted]"}
    if isinstance(v, dict):
        return {(v.get("username") or "").lower()} - {""}
    return {str(v).lower()} - {"", "none", "nan"} if isinstance(v, str) else set()


def resolve_commenters(C, idmap=None):
    """API comments carry the real numeric commenter id (commenter_user_id) while the user object is redacted
    (orchestrator, Nov 3 20:45 UTC). Fill username from the population agent's id -> username map (ID_MAP: a jsonl or
    parquet with user_id, username) where it is missing or redacted. Rows that stay unresolved count as non-pool."""
    if "commenter_user_id" not in C:
        return C if "username" in C else C.assign(username="")
    if "username" not in C:
        C = C.assign(username="")
    bad = C.username.isna() | C.username.astype(str).str.lower().isin(["", "nan", "none", "[redacted]"])
    if not bad.any():
        return C
    if idmap is None:
        path = os.environ.get("ID_MAP", f"{BUCKET}/raw/population/user_id_map/user_id_map_20261103.jsonl")
        if path.startswith("gs://"):
            loc = os.path.join(tempfile.mkdtemp(prefix="idmap_"), os.path.basename(path))
            subprocess.run(["gsutil", "-q", "cp", path, loc], check=True); path = loc
        idmap = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_json(path, lines=True, dtype=False)
    if "last_seen" in idmap:   # renamed accounts: the current name is the one seen last
        idmap = idmap.sort_values("last_seen").groupby(idmap.user_id.astype(str)).tail(1)
    m = dict(zip(idmap.user_id.astype(str), idmap.username.astype(str)))
    C = C.copy()
    C.loc[bad, "username"] = C.loc[bad, "commenter_user_id"].astype(str).map(m).fillna("")
    return C


def day_rows(day, C, P, U, Fc, pool, final):
    """Pure. One row per launch of the day: shock and early / whole-day pool engagement."""
    for df, cols, w in ((C, ["launch_id", "username", "created_at"], "comments_ts"), (P, ["launch_id"], "posts_ts"), (Fc, ["id", "pred"], "forecast")):
        if df is None or any(c not in df.columns for c in cols):
            raise SystemExit(f"{day}: {w} missing or lacks {cols}")
    P = P.assign(launch_id=P.launch_id.astype(str))
    first = P.sort_values("fetched_at" if "fetched_at" in P else "launch_id").groupby("launch_id").first()
    day0 = pd.Timestamp(f"{day} 00:01", tz="America/Los_Angeles").tz_convert("UTC")
    start = {lid: (ts(r.featured_at) if "featured_at" in first and pd.notna(r.get("featured_at")) else day0) for lid, r in first.iterrows()}
    team = {lid: names(r.get("makers")) | names(r.get("hunter")) for lid, r in first.iterrows()}
    C = resolve_commenters(C)
    C = C.assign(launch_id=C.launch_id.astype(str), u=C.username.astype(str).str.lower(), t=ts(C.created_at))
    if "comment_id" in C:
        C = C.drop_duplicates(["launch_id", "comment_id"])
    if U is not None:
        if "launch_id" not in U and "post_id" in U:
            U = U.rename(columns={"post_id": "launch_id"})
        U = U.assign(launch_id=U.launch_id.astype(str), u=U.username.astype(str).str.lower(), hi=ts(U.first_seen_hi))
    Fc = Fc.assign(id=Fc.id.astype(str))
    rows = []
    for lid in Fc.id:
        if lid not in final or lid not in start:
            continue
        s0 = start[lid]; c = C[(C.launch_id == lid) & ~C.u.isin(team.get(lid, set()))]
        r = {"day": day, "id": lid, "logv": np.log1p(final[lid]), "pred": float(Fc.set_index("id").pred[lid])}
        for T in HOURS + ["day"]:
            cT = c if T == "day" else c[c.t <= s0 + pd.Timedelta(hours=T)]
            pc = int(cT.u.isin(pool).sum())
            r[f"all_c_{T}"] = len(cT); r[f"pool_c_{T}"] = pc; r[f"pool_c_share_{T}"] = pc / len(cT) if len(cT) else np.nan
            if U is not None:
                uT = U[(U.launch_id == lid) & U.u.isin(pool)]
                uT = uT if T == "day" else uT[uT.hi <= s0 + pd.Timedelta(hours=T)]
                r[f"pool_u_{T}"] = int(uT.u.nunique()) if (T == "day" or T >= 4) else np.nan
        rows.append(r)
    R = pd.DataFrame(rows)
    if len(R):
        R["shock"] = (R.logv - R.pred); R["shock"] -= R.groupby("day").shock.transform("mean")
    return R


def within(A, col, rng, n=5000):
    per = lambda S: [spearmanr(g[col], g.shock).correlation for _, g in S.groupby("day") if g[col].notna().sum() >= 5 and g[col].nunique() > 1]
    est = per(A)
    if not est:
        return {"rho": None, "days": 0}
    days = A.day.unique(); byd = {d: g for d, g in A.groupby("day")}
    bs = [np.nanmean(per(pd.concat([byd[d] for d in rng.choice(days, len(days))])) or [np.nan]) for _ in range(n)] if len(days) > 1 else []
    bs = [b for b in bs if not np.isnan(b)]
    return {"rho": round(float(np.nanmean(est)), 3), "ci95": [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])] if bs else None,
            "days": int(len(est)), "launches": int(A[col].notna().sum())}


def main(*days):
    from pipeline import warehouse as W
    con = W.connect()
    rng = np.random.default_rng(0); parts, power = [], {}
    for day in days:
        C, P, U, Fc = fetch(day)
        pool = {r[0].lower() for r in con.execute(f"SELECT person FROM people WHERE first_seen::VARCHAR < '{day}'").fetchall()}
        final = dict(con.execute(f"SELECT id::VARCHAR, votes FROM launches WHERE day::VARCHAR = '{day}' AND votes IS NOT NULL AND daily_rank IS NOT NULL").fetchall())
        R = day_rows(day, C, P, U, Fc, pool, final)
        parts.append(R)
        power[day] = {"launches": int(len(R)), **{f"with_comment_{T}h": int((R[f"all_c_{T}"] > 0).sum()) for T in HOURS},
                      **{f"with_pool_comment_{T}h": int((R[f"pool_c_{T}"] > 0).sum()) for T in HOURS},
                      "upvote_first_seen": U is not None, "pool_size": len(pool)}
    A = pd.concat(parts, ignore_index=True)
    res = {"days": list(days), "n_per_day": power, "tests": {}}
    for T in HOURS + ["day"]:
        for k in ("pool_c", "pool_c_share", "pool_u"):
            col = f"{k}_{T}"
            if col in A and A[col].notna().any():
                res["tests"][col] = within(A, col, rng)
    res["reading"] = ("pool leads if early (1-4 h) pool engagement predicts the shock about as well as the whole-day "
                      "measure; pool follows exposure if only the whole-day measure does")
    json.dump(res, open(os.environ.get("OUT", "results/pool_timing.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
