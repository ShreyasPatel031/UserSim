"""Score the three backer-prediction arms (CF-only, A7, raw most-active) under one metric (orchestrator 22:34Z Nov 14).
Per launch: o = observed backers = people held before the freeze (a read before 00:00 PT of D) AND re-read after the day closed whose own upvote
list contains the launch; N = |o|; each arm's list is ranked within the re-read people; hits = |top N ∩ o|.
Pooled recall per arm = sum(hits) / sum(N) over all scored launches; 95% interval and the paired difference vs raw = launch bootstrap (2000).
The raw arm = held people ranked by upvotes on launches of the 30 days before D, from reads fetched before 00:00 PT of D.
  python backer_arms_score.py <store dir> <scratchpad> <day> [<day> ...] [--no-upload]
Writes results/web/backer_prediction_arms.json (accumulating rows per (day, store read)) and results/web/north_star_rows_e5.json (best arm)."""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import period_parts as PP
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, SP, DAYS = args[0], args[1], args[2:]; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min(); store_time = U.ft.max()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
ARMS = ["CF-only", "A7", "CF+back", "raw most-active"]; FIT = ["CF-only", "A7", "CF+back"]
rows, per_launch = [], []
for D in DAYS:
    raw = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/backer_arms/{D}.parquet"], capture_output=True).stdout
    lp = os.path.join(SP, "bp", f"_arms_{D}.parquet")
    if raw: open(lp, "wb").write(raw)
    elif os.path.exists(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")): lp = os.path.join(SP, "bp", f"backer_arms_{D}.parquet")
    else: rows.append({"day": D, "status": "no frozen arms"}); continue
    FR = pd.read_parquet(lp); close = PP.close_utc(D); start = close - pd.Timedelta(days=1)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < start].index) & held
    obs = U[(U.lday == D) & U.person_id.isin(hf & reread)].groupby("target_id").person_id.agg(set).to_dict()
    hist = U[(U.lday < D) & (U.lday >= (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")) & (U.ft < start)]
    raw_list = [p for p in hist.groupby("person_id").size().sort_values(ascending=False).index if p in reread]
    n_day = 0
    for lid in FR.launch_id.unique():
        o = obs.get(str(lid), set()); n = len(o)
        if not n: continue
        r = {"day": D, "launch_id": str(lid), "N": n}
        for arm in FIT:
            g = FR[(FR.launch_id == lid) & (FR.arm == arm)]
            g = g[g.person_id.isin(reread)].sort_values("rank"); r[arm] = len(set(g.person_id.iloc[:n]) & o) if len(g) else np.nan
        r["raw most-active"] = len(set(raw_list[:n]) & o); per_launch.append(r); n_day += 1
    rows.append({"day": D, "status": "scored" if n_day else "no observed held backers", "store_read_until": str(store_time)[:16],
                 "days_after_close": round((store_time - close).total_seconds() / 86400, 2), "launches_scored": n_day,
                 "held_people_reread_after_close": len(reread), "frozen_at": str(FR.frozen_at.iloc[0])[:16],
                 "leak_checks": {"svd_max_launch_day": str(FR.svd_max_lday.iloc[0]), "reads_before": str(FR.reads_before.iloc[0])[:16], "follows_used": False}})
P = pd.DataFrame(per_launch)
def pooled(df, a): return 100 * df[a].sum() / df.N.sum()
def boot(df, f):
    v = [f(df.iloc[rng.integers(0, len(df), len(df))]) for _ in range(2000)]; return [round(float(np.percentile(v, 2.5)), 1), round(float(np.percentile(v, 97.5)), 1)]
summary = {}
if len(P):
    for D in sorted(P.day.unique()) + ["ALL"]:
        df = P if D == "ALL" else P[P.day == D]; df = df.dropna(subset=[a for a in FIT if a in df])
        if not len(df): continue
        s = {"launches": int(len(df)), "observed_backers": int(df.N.sum())}
        for a in [a for a in ARMS if a in df]: s[a] = [round(pooled(df, a), 1)] + boot(df, lambda x, a=a: pooled(x, a))
        if "CF+back" in df: s["CF+back minus CF-only (paired)"] = [round(pooled(df, "CF+back") - pooled(df, "CF-only"), 1)] + boot(df, lambda x: pooled(x, "CF+back") - pooled(x, "CF-only"))
        for a in [a for a in FIT if a in df]: s[f"{a} minus raw (paired)"] = [round(pooled(df, a) - pooled(df, "raw most-active"), 1)] + boot(df, lambda x, a=a: pooled(x, a) - pooled(x, "raw most-active"))
        summary[D] = s
out = {"metric": "BACKER PREDICTION, 3 arms, strict: recall at N (N = observed backers), pooled; launch-bootstrap 95% intervals",
       "how": __doc__.split("\n    python")[0], "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "rows": rows, "summary": summary}
os.makedirs(f"{SP}/backer", exist_ok=True); p = f"{SP}/backer/backer_arms_score.json"; json.dump(out, open(p, "w"), indent=1, default=float)
ns = []
if "ALL" in summary:
    s = summary["ALL"]; best = max([a for a in ARMS if a in s], key=lambda a: s[a][0])
    ns = [{"point": "0005", "model": f"backer prediction: {best}", "method": "forward-style strict replay/nightly freeze (reads before 00:00 PT; SVD on upvotes dated before the day; no follows)",
           "metric": "recall at N (N = observed held backers per launch), pooled", "value": s[best][0], "interval": s[best][1:],
           "arms": {a: s[a] for a in ARMS if a in s}, "paired_vs_raw": {a: s[f"{a} minus raw (paired)"] for a in FIT if f"{a} minus raw (paired)" in s},
           "n_launches": s["launches"], "n_backers": s["observed_backers"], "first_day": min(P.day), "last_day": max(P.day),
           "rule": "observed backers = people held before the freeze AND re-read after the day closed whose own upvote list contains the launch; every arm ranked within those re-read people",
           "source": "results/web/backer_prediction_arms.json", "top3": None, "top5": None, "top10": None}]
json.dump({"computed_at": out["written_at"], "rows": ns}, open(f"{SP}/backer/north_star_rows_e5.json", "w"), indent=1)
if UP:
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/backer_prediction_arms.json"], check=True)
    subprocess.run(["gsutil", "-q", "cp", f"{SP}/backer/north_star_rows_e5.json", f"{B}/results/web/north_star_rows_e5.json"], check=True)
print(json.dumps(summary, default=float))
