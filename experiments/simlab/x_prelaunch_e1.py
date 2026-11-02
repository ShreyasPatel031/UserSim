"""Pre-launch X engagement over the day-calibrated control, paired by day (Grok Bot, Nov 2). Runs anywhere with gsutil and
numpy / pandas / scipy (no VM needed): every input is pulled from the bucket into a cache directory on each run.
Inputs (gs://usersim-bakeoff-347838016394/usersim_sim/):
  raw/x/prelaunch_posts.jsonl, raw/x/prelaunch_engagers.jsonl   Data Feeder's pre-launch X fetch (team handles' posts in
                                                                 the 30 days before launch day, replies / quotes / reposts)
  raw/x/prelaunch_wip/dm_gate.json                               day-matched coverage gate (open launches per day, full days)
  tmp/e5/honest/honest_preds.parquet                             the honest launch model (out of sample; column `honest`)
  tmp/e5/xtest/inputs.tgz                                        data/days/*.json (team X handles) + items.parquet (votes)
Honest X inputs only (dated before 00:00 PT on launch day): team posts in [day-30, day), and distinct engagers whose own
reply / quote is dated before the cutoff (engager_created_at, else the X snowflake of engager_post_id). Reposts carry no
time and are dropped; like / impression / reply counts were read at fetch time (after launch) and are not used.
Control: the honest launch model calibrated per day. Day terms are constant within a day, so the control's daily ranking
is the honest launch model's. Treatment: log mu = log mu_honest + a_day + b . x (Poisson, day fixed effects, small ridge on
b), fitted FORWARD ONLY: for each test day, on the covered launches of strictly earlier days (at least MIN_TRAIN_DAYS days
and MIN_TRAIN_LAUNCHES launches), then the test day is ranked by log mu_honest + b . x. Days without enough history are
not scored. Launches not covered by the gate keep x = 0 and do not enter any fit.
  (A) full days (every launch with X handles covered): daily top 3 / 5 / 10 vs the control, paired by day, also by month;
      weekly top 3 / 5 / 10 on weeks whose days are all full and scored (Monday-Sunday)
  (B) covered subsets: days with >= 3 covered launches, top 3 among the covered launches (real order by votes)
  plus a diagnostic: within-day Spearman of each x with the honest model's residual, covered launches.
Decision rule fixed before any run: X adds daily value iff (A) on >= 10 full days gives daily top 3 vs the control with a
95% interval above 0. Fewer full days: "insufficient data", (B) reported as an early read only.
usage: python -m simlab.x_prelaunch_e1 [cache_dir] -> simlab/reports/x_prelaunch_e1.json (and prints a summary)"""
import glob, json, os, subprocess, sys, tarfile
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
FILES = {"posts.jsonl": f"{B}/raw/x/prelaunch_posts.jsonl", "engagers.jsonl": f"{B}/raw/x/prelaunch_engagers.jsonl",
         "dm_gate.json": f"{B}/raw/x/prelaunch_wip/dm_gate.json", "honest_preds.parquet": f"{B}/tmp/e5/honest/honest_preds.parquet",
         "inputs.tgz": f"{B}/tmp/e5/xtest/inputs.tgz"}
MIN_FULL_DAYS = 10
MIN_TRAIN_DAYS, MIN_TRAIN_LAUNCHES = 5, 30
PT = ZoneInfo("America/Los_Angeles")


def fetch(cache):
    os.makedirs(cache, exist_ok=True)
    for name, url in FILES.items():
        subprocess.run(["gsutil", "-q", "cp", url, os.path.join(cache, name)], check=True)
    with tarfile.open(os.path.join(cache, "inputs.tgz")) as t:
        t.extractall(cache, filter="data")


def utc(ts):
    """Any timestamp string as naive UTC."""
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def snowflake_utc(i):
    return datetime.utcfromtimestamp(((int(i) >> 22) + 1288834974657) / 1000)


def cutoff_utc(day):
    """00:00 Pacific on the launch day, as naive UTC."""
    return datetime.fromisoformat(day).replace(tzinfo=PT).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def features(cache):
    team, lday = {}, {}
    for f in sorted(glob.glob(os.path.join(cache, "ph_predict", "data", "days", "*.json"))):
        for p in json.load(open(f)):
            hs = {(m.get("twitterUsername") or "").lower() for m in (p.get("makers") or []) if isinstance(m, dict)}
            hs |= {((p.get("user") or {}).get("twitterUsername") or "").lower()}
            team[str(p["id"])] = hs - {""}; lday[str(p["id"])] = os.path.basename(f)[:10]
    posts, eng = jl(os.path.join(cache, "posts.jsonl")), jl(os.path.join(cache, "engagers.jsonl"))
    by_hd = defaultdict(list)
    for r in posts:
        by_hd[((r.get("handle") or "").lower(), (r.get("launch_day") or "")[:10])].append(r)
    post_hd = {str(r["post_id"]): ((r.get("handle") or "").lower(), (r.get("launch_day") or "")[:10]) for r in posts}
    eng_hd = defaultdict(list)
    for r in eng:
        if r.get("kind") not in ("reply", "quote"):
            continue   # reposts: no time
        t = None
        if r.get("engager_created_at"):
            t = utc(r["engager_created_at"])
        elif r.get("engager_post_id"):
            t = pd.Timestamp(snowflake_utc(r["engager_post_id"]))
        hd = post_hd.get(str(r.get("post_id")))
        if t is not None and hd:
            eng_hd[hd].append((t, (r.get("user") or "").lower()))
    gate = json.load(open(os.path.join(cache, "dm_gate.json")))
    open_ids = {x for v in gate.get("open_by_day", {}).values() for x in v}
    gate_days = set(gate.get("open_by_day", {}))   # only days inside the fetch window can be covered
    rows = []
    for x, hs in team.items():
        d = lday[x]; cut = pd.Timestamp(cutoff_utc(d)); lo = cut - pd.Timedelta(days=30)
        n_posts, users = 0, set()
        for h in hs:
            for r in by_hd.get((h, d), []):
                t = utc(r["posted_at"])
                n_posts += int(lo <= t < cut)
            users |= {u for t, u in eng_hd.get((h, d), []) if t < cut}
        rows.append({"id": x, "day": d, "has_x": bool(hs), "covered": (d in gate_days and x not in open_ids), "x_posts": n_posts, "x_engagers": len(users)})
    F = pd.DataFrame(rows)
    F["lx_posts"], F["lx_engagers"] = np.log1p(F.x_posts), np.log1p(F.x_engagers)
    return F, set(gate.get("full_days", [])), gate


def fit_b(T, cols, ridge=0.1):
    """Poisson with offset log mu0 and day fixed effects; returns b (day effects profiled out in closed form)."""
    X = T[cols].values; y = T.votes.values; lm0 = np.log(T.mu0.values); g = pd.factorize(T.day)[0]

    def nll(b):
        eta = lm0 + X @ b
        a = np.log(np.bincount(g, y) + 1e-9) - np.log(np.bincount(g, np.exp(eta)) + 1e-9)   # MLE of each day's intercept
        e = eta + a[g]
        return float((np.exp(e) - y * e).sum() / len(y) + ridge * (b ** 2).sum())
    return minimize(nll, np.zeros(len(cols)), method="L-BFGS-B").x


def hit(g, col, k, real="votes"):
    return len(set(g.nlargest(k, col).id) & set(g.nlargest(k, real).id)) / k


def paired(d, rng):
    d = np.asarray(d, float)
    if not len(d):
        return None
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(cache):
    fetch(cache)
    F, full_days, gate = features(cache)
    H = pd.read_parquet(os.path.join(cache, "honest_preds.parquet")); H["id"] = H.id.astype(str); H = H.drop_duplicates("id")
    I = pd.read_parquet(os.path.join(cache, "simlab", "data_v2", "items.parquet")); I["id"] = I.id.astype(str)
    T = F.merge(H[["id", "honest", "dailyRank"]], on="id").merge(I[["id", "out_votes"]], on="id")
    T["votes"] = pd.to_numeric(T.out_votes, errors="coerce"); T = T[T.votes.notna()].copy()
    T["mu0"] = np.expm1(T.honest).clip(lower=0.5)
    cols = ["lx_posts", "lx_engagers"]
    C = T[T.covered & T.has_x]                      # launches whose X inputs are known
    eval_days = sorted(set(C.day))
    T["s_ctrl"] = T.honest; T["s_x"] = T.honest; coef = {}
    for d in eval_days:                              # forward only: fit on strictly earlier days
        tr = C[C.day < d]
        if tr.day.nunique() < MIN_TRAIN_DAYS or len(tr) < MIN_TRAIN_LAUNCHES:
            continue
        b = fit_b(tr, cols); coef[d] = [round(float(v), 4) for v in b]
        m = (T.day == d) & T.covered & T.has_x
        T.loc[m, "s_x"] = T.loc[m, "honest"] + T.loc[m, cols].values @ b
    rng = np.random.default_rng(0); res = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "gate": {k: v for k, v in gate.items() if k != "open_by_day"}}
    # (A) full days
    A = {}
    for k in (3, 5, 10):
        rows = [(hit(g, "s_x", k, "votes") - hit(g, "s_ctrl", k, "votes")) for d, g in T.groupby("day") if d in full_days and d in coef and len(g) >= k]
        A[f"daily_top{k}"] = paired(rows, rng)
    res["A_full_days"] = {"days": sorted(d for d in full_days if d in coef), **A}
    res["A_per_day"] = {d: {f"top{k}": [hit(g, "s_x", k), hit(g, "s_ctrl", k)] for k in (3, 5, 10) if len(g) >= k} | {"launches": int(len(g))}
                        for d, g in T.groupby("day") if d in full_days and d in coef}
    res["A_wins_ties_losses"] = {f"top{k}": [sum(v[f"top{k}"][0] > v[f"top{k}"][1] for v in res["A_per_day"].values() if f"top{k}" in v),
                                             sum(v[f"top{k}"][0] == v[f"top{k}"][1] for v in res["A_per_day"].values() if f"top{k}" in v),
                                             sum(v[f"top{k}"][0] < v[f"top{k}"][1] for v in res["A_per_day"].values() if f"top{k}" in v)] for k in (3, 5, 10)}
    scored_full = [d for d in sorted(full_days) if d in coef]
    T["week"] = pd.to_datetime(T.day).dt.strftime("%G-W%V"); T["mon"] = T.day.str[:7]
    res["A_by_month"] = {m: {f"daily_top{k}": [round(100 * float(np.mean([hit(g, "s_x", k) for d, g in T[T.mon == m].groupby("day") if d in scored_full and len(g) >= k])), 1),
                                                round(100 * float(np.mean([hit(g, "s_ctrl", k) for d, g in T[T.mon == m].groupby("day") if d in scored_full and len(g) >= k])), 1)]
                             for k in (3, 5, 10)} | {"days": sum(d[:7] == m for d in scored_full)}
                         for m in sorted({d[:7] for d in scored_full})}
    days_of_week = T.groupby("week").day.apply(lambda s: set(s))
    full_weeks = [w for w, ds in days_of_week.items() if ds and all(x in scored_full for x in ds)]
    W = {}
    for k in (3, 5, 10):
        rows = [(hit(g, "s_x", k) - hit(g, "s_ctrl", k)) for w, g in T.groupby("week") if w in full_weeks and len(g) >= k]
        W[f"weekly_top{k}"] = paired(rows, rng)
    res["A_full_weeks"] = {"weeks": full_weeks, **W}
    # (B) covered subsets
    Bk = {}
    for k in (3, 5):
        rows = [(hit(g, "s_x", k) - hit(g, "s_ctrl", k)) for d, g in C.assign(s_x=T.loc[C.index, "s_x"], s_ctrl=T.loc[C.index, "s_ctrl"]).groupby("day") if d in coef and len(g) >= max(3, k)]
        Bk[f"top{k}_among_covered"] = paired(rows, rng)
    res["B_covered_subsets"] = {"days": int(sum(1 for d, g in C.groupby("day") if d in coef and len(g) >= 3)), "launches": int(len(C)), **Bk}
    # diagnostic
    C2 = C.assign(resid=np.log1p(C.votes) - C.honest)
    res["diagnostic_spearman_with_residual"] = {c: round(float(np.nanmean([spearmanr(g[c], g.resid).correlation for _, g in C2.groupby("day") if len(g) >= 3 and g[c].nunique() > 1])), 3) for c in cols} if len(C2) else None
    res["coef_forward"] = coef
    n_full = len(res["A_full_days"]["days"])
    top3 = res["A_full_days"]["daily_top3"]
    res["verdict"] = (f"insufficient data: {n_full} full days (need {MIN_FULL_DAYS}); (B) is an early read only" if n_full < MIN_FULL_DAYS else
                      ("X adds daily value" if top3 and top3[1][0] > 0 else "X does not add daily value (daily top 3 interval not above 0)"))
    json.dump(res, open(os.path.join(HERE, "reports", "x_prelaunch_e1.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), ".cache", "x_prelaunch_e1"))
