"""X audience pilot scorer (orchestrator 01:56Z Nov 13). Inputs (bucket only): tmp/orchestrator/x_audience/handles_20261113.jsonl
(launch_id, day, role, handle, identity_source) and the follower reads Grok Bot writes there (any *.jsonl other than
handles_* / launches_* / product_accounts_*, rows {handle, followers, fetched_at}) and product_accounts_*.jsonl
(launch_id, handle, followers, posts_7d = posts in the 7 days before launch; product accounts are not people, no leak set). PILOT PROXY: follower counts read now, not at launch (X counts move slowly).
Leak rule: the 00:05-safe set = hunters (never redacted) + makers named in the 00:05 read; makers known only from later reads
carry the positional leak and are reported separately, never used in the honest variant.
Features per launch: log1p(max followers), log1p(sum followers) over the safe set (0 if none) and has_handle.
Leave-one-day-out ridge on days with a clean 00:05 score: z(clean_nosite) + z(th_n_pre) [+ X features], top 3/5/10 paired.
Climber check on hidden-window days: launches at hidden rank 11-19 at 03:00 PT that end top 10 vs those that do not.
usage: python x_audience_score.py -> results/x_audience.md (counts only)"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
import prior_blend as PB
from sklearn.linear_model import Ridge
D = f"{B}/tmp/orchestrator/x_audience"


def main():
    from pipeline import warehouse as W
    tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp"))
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{D}/*.jsonl", tmp + "/"], check=True)
    H = pd.read_json(os.path.join(tmp, "handles_20261113.jsonl"), lines=True); H["launch_id"] = H.launch_id.astype(str)
    fol = {}
    for f in glob.glob(tmp + "/*.jsonl"):
        if os.path.basename(f).startswith(("handles_", "launches_", "product_accounts_")):
            continue
        for l in open(f):
            r = json.loads(l)
            if r.get("handle") and r.get("followers") is not None:
                fol[str(r["handle"]).lower().lstrip("@")] = float(r["followers"])
    PA = {}   # product accounts (Grok Bot): launch_id -> (followers, posts in the 7 days before launch); max over rows
    for f in glob.glob(tmp + "/product_accounts_*.jsonl"):
        for l in open(f):
            r = json.loads(l)
            if r.get("launch_id") is not None and r.get("followers") is not None:
                k = str(r["launch_id"]); a = PA.get(k, (0.0, 0.0))
                PA[k] = (max(a[0], float(r["followers"])), max(a[1], float(r.get("posts_7d") or r.get("posts") or 0)))
    if not fol and not PA:
        print(json.dumps({"status": "no follower reads yet"})); return
    H["f"] = H.handle.str.lower().map(fol); H["safe"] = (H.role == "hunter") | (H.identity_source == "0005")
    S = H[H.safe & H.f.notna()].groupby("launch_id").f.agg(["max", "sum"])
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-26' AND day <= '2026-11-12'", do_sync=False)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    X = L.merge(CL[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X["xmax"] = np.log1p(X.id.map(S["max"]).fillna(0)); X["xsum"] = np.log1p(X.id.map(S["sum"]).fillna(0)); X["xhas"] = X.id.isin(S.index).astype(float)
    X["pfol"] = np.log1p(X.id.map({k: v[0] for k, v in PA.items()}).fillna(0)); X["ppost"] = np.log1p(X.id.map({k: v[1] for k, v in PA.items()}).fillna(0))
    X["phas"] = X.id.isin(PA.keys()).astype(float)
    npre = {}
    for d in X.day.unique():
        E, _, _ = PB.thread(d, X[X.day == d].id.tolist()); npre.update(E.th_n_pre.to_dict())
    X["npre"] = X.id.map(npre).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean", "npre", "xmax", "xsum", "xhas", "pfol", "ppost", "phas"):
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    def lodo(cols):
        o_ = []
        for d in days:
            te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(o_)
    base = lodo(["z_clean", "z_npre"])
    md = [f"# X audience pilot (PROXY: followers read now; {len(days)} days, {len(X)} launches; safe-set coverage {X.xhas.mean():.1%})", "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for nm, cols in (("+ X max", ["z_xmax"]), ("+ X sum", ["z_xsum"]), ("+ X max + has", ["z_xmax", "z_xhas"]),
                     ("+ product followers", ["z_pfol", "z_phas"]), ("+ product posts 7d", ["z_ppost", "z_phas"]),
                     ("+ X max + product followers + posts", ["z_xmax", "z_pfol", "z_ppost", "z_phas"])):
        P = lodo(["z_clean", "z_npre"] + cols); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    # climber check (hidden rank at 03:00 PT from vote_snapshots / posts_ts via prereveal_top5_10's output is not per-launch; use vote_snapshots)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots WHERE rank_now IS NOT NULL', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True); cl = []
    for d, g in V.groupby("d"):
        t3 = pd.Timestamp(d + " 03:00", tz="America/Los_Angeles").tz_convert("UTC")
        S3 = g[g.a <= t3].sort_values("a").groupby("id").rank_now.last()
        for i, r in S3.items():
            if 11 <= r <= 19 and i in set(X.id):
                cl.append({"id": i, "climbed": int(X.set_index("id").daily_rank[i] <= 10), "xmax": float(X.set_index("id").xmax[i]),
                           "xhas": float(X.set_index("id").xhas[i])})
    C = pd.DataFrame(cl)
    if len(C):
        md += ["", f"Climber check (hidden rank 11-19 at 03:00 PT, {len(C)} launches): mean log1p X max followers, ended top 10 "
               f"{C[C.climbed == 1].xmax.mean():.2f} (n {int(C.climbed.sum())}) vs not {C[C.climbed == 0].xmax.mean():.2f} (n {int((C.climbed == 0).sum())}); "
               f"share with a safe-set handle {C[C.climbed == 1].xhas.mean():.2f} vs {C[C.climbed == 0].xhas.mean():.2f}; "
               f"among launches with a handle, mean log1p X max {C[(C.climbed == 1) & (C.xhas == 1)].xmax.mean():.2f} "
               f"(n {int(((C.climbed == 1) & (C.xhas == 1)).sum())}) vs {C[(C.climbed == 0) & (C.xhas == 1)].xmax.mean():.2f} "
               f"(n {int(((C.climbed == 0) & (C.xhas == 1)).sum())})"]
        from sklearn.metrics import roc_auc_score
        if C.climbed.nunique() == 2:
            md.append(f"Climber AUC of X max followers alone: {roc_auc_score(C.climbed, C.xmax):.2f}")
    open(os.path.join(HERE, "results", "x_audience.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
