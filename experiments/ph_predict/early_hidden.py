"""Hidden rank in the first minutes (orchestrator 03:34Z Nov 13; replay on the 7 usable days; counts only).
Hidden rank at T = latest read fetched <= T: live posts_ts daily_rank_at_fetch (API v2), else warehouse vote_snapshots rank_now.
Points: first read (~00:06), 00:15, 00:30, 00:45, 01:00 PT. Per point: hidden rank alone; clean_nosite + th_n_pre (ridge, LODO);
hidden + clean_nosite + th_n_pre (ridge, LODO); mean within-day Spearman of hidden rank vs final rank.
If the combined line beats clean_nosite + th_n_pre at 00:15 or 00:30 with a positive top-3 interval, its weights (all days)
are frozen to results/frozen/early_hidden_20261113.json. usage: python early_hidden.py -> results/early_hidden.md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
import prior_blend as PB
from sklearn.linear_model import Ridge
PTS = {"first": None, "00:15": 15, "00:30": 30, "00:45": 45, "01:00": 60}
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]


def main():
    from pipeline import warehouse as W
    Q = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, CAST(rank_now AS DOUBLE) r FROM vote_snapshots WHERE rank_now IS NOT NULL', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str); cl = dict(zip(CL.id, CL.clean_v3_nosite))
    tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")); rows, src, firsts = [], {}, {}
    for d in DAYS:
        fin = Q[Q.day == d].set_index("id").daily_rank; ids = fin.index.tolist()
        p = f"{tmp}/{d}.jsonl"; H = []
        if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl", p], stderr=subprocess.DEVNULL).returncode == 0:
            for l in open(p):
                r = json.loads(l)
                if str(r.get("fetch_status")) == "200" and r.get("daily_rank_at_fetch") not in (None, "None") and str(r.get("source", "")).startswith("ph_api_v2"):
                    H.append((pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]), float(r["daily_rank_at_fetch"])))
        H = pd.DataFrame(H, columns=["a", "id", "r"]); t0 = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")
        if H.empty or H.a.min() > t0 + pd.Timedelta(minutes=20):
            H = V[V.d == d][["a", "id", "r"]]; src[d] = "vote_snapshots"
        else:
            src[d] = "posts_ts"
        H = H[H.a >= t0]; firsts[d] = H.a.min()
        E, _, _ = PB.thread(d, ids); npre = E.th_n_pre.to_dict()
        for pt, m in PTS.items():
            T = H.a.min() if m is None else t0 + pd.Timedelta(minutes=m)
            S = H[H.a <= T].sort_values("a").groupby("id").r.last()
            if S.empty:
                continue
            pos = pd.Series({i: S.get(i, 999) for i in ids}).rank(method="first")
            for i in ids:
                rows.append({"day": d, "pt": pt, "id": i, "final": fin[i], "lpos": -np.log(pos[i]), "clean": cl.get(i, np.nan), "npre": npre.get(i, 0.0)})
    X = pd.DataFrame(rows)
    X["clean"] = X.groupby("day").clean.transform(lambda s: s.fillna(s.mean()) if s.notna().any() else s.fillna(0))
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("lpos", "clean", "npre"):
        X["z_" + c] = X.groupby(["day", "pt"])[c].transform(zf)
    X["y"] = X.groupby(["day", "pt"]).final.transform(lambda s: zf(-np.log(s)))
    rng = np.random.default_rng(0)
    hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    md = [f"# Hidden rank in the first minutes ({len(DAYS)} days; replay)", "",
          "Source and first read (PT) per day: " + ", ".join(f"{d[5:]} {src[d]} {firsts[d].tz_convert('America/Los_Angeles').strftime('%H:%M')}" for d in DAYS), "",
          "| point | Spearman hidden vs final | hidden alone t3/t5/t10 | clean+th_n_pre t3/t5/t10 | hidden+clean+th_n_pre t3/t5/t10 | combined - clean+th (3 / 5 / 10, 95%) |",
          "|---|---|---|---|---|---|"]
    frozen = {}
    for pt in PTS:
        G = X[X.pt == pt]; days = sorted(G.day.unique()); Hh, Cc, Mm, rho = [], [], [], []
        for d in days:
            te, tr = G[G.day == d], G[G.day != d]; t = te.sort_values("final").id.tolist()
            rho.append(te.lpos.corr(-np.log(te.final), method="spearman"))
            Hh.append(hits(te.sort_values(["lpos", "id"], ascending=[False, True]).id.tolist(), t))
            for cols, acc in ((["z_clean", "z_npre"], Cc), (["z_lpos", "z_clean", "z_npre"], Mm)):
                acc.append(hits(te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), t))
        Hh, Cc, Mm = map(np.array, (Hh, Cc, Mm)); dP = Mm - Cc
        b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)]); lo = [np.percentile(b[:, k], 2.5) for k in range(3)]
        f3 = lambda A: " / ".join(f"{A[:, k].mean():.1f}" for k in range(3))
        md.append(f"| {pt} | {np.nanmean(rho):+.2f} | {f3(Hh)} | {f3(Cc)} | {f3(Mm)} | " +
                  " / ".join(f"{dP[:,k].mean():+.1f} [{lo[k]:+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + f" | ({len(days)} days)")
        if pt in ("00:15", "00:30") and ((dP[:, 0].mean() > 0 and lo[0] > 0) or (dP[:, 2].mean() > 0 and lo[2] > 0)):   # top 3 or top 10
            m = Ridge(alpha=3.0).fit(G[["z_lpos", "z_clean", "z_npre"]], G.y)
            frozen[pt] = {"coef": dict(zip(["z_lpos", "z_clean", "z_npre"], map(float, m.coef_))), "intercept": float(m.intercept_)}
    fp = os.path.join(HERE, "results", "frozen", "early_hidden_20261113.json")
    if frozen and not os.path.exists(fp):
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": DAYS, "features": "z within day: -log hidden position, clean_nosite, th_n_pre",
                   "points": frozen}, open(fp, "w"), indent=1)
        md += ["", f"Frozen: {', '.join(frozen)} -> {os.path.relpath(fp, HERE)}"]
    else:
        md += ["", "Nothing frozen (no positive top-3 or top-10 interval at 00:15 / 00:30)." if not frozen else "Frozen file exists; not overwritten."]
    open(os.path.join(HERE, "results", "early_hidden.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
