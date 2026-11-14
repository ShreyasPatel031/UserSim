"""LODO / L2O / permutation check of the 03:45 hybrid slots-6-10 ridge (orchestrator 15:42Z Nov 14), 12 days Nov 2-13; data build copied from
hybrid_vmonly.py. Original docstring: VM-only 03:45 hybrid (orchestrator 00:52Z Nov 14: two published predictions; the before-reveal one must depend ONLY on what the VM produces).
Inputs, all from usersim-pipeline itself:
  hidden rank   recorder rank_now (raw/vote_snapshots/<d>.jsonl, pipeline/hourly.py) at the latest read <= T (E5's rule: within 65 min, after 23:55 PT)
  move          log rank-position at 01:00 minus at T (same recorder)
  nc_rec        log1p commentsCount from the same recorder row (public before the reveal; replies included; no distinct-commenter count)
  clean         the 00:05 forecast parquet's `pred` (clean_nosite; raw/daily/<d>/forecast_<d>.parquet), month-fold clean_nosite as stand-in where absent
Line: hidden top 5 as is, slots 6+ by a ridge on z(lpos), z(move), z(nc_rec), z(clean). Weights: leave-one-day-out here (backtest); the live
version freezes the all-day fit. Compared with the plain hidden rank and the published hybrid (feed comments, frozen P345 weights).
usage: python hybrid_vmonly.py -> results/hybrid_vmonly.md (+ results/frozen/hybrid_vmonly_P345_20261114.json)"""
import json, os, subprocess, tempfile, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [os.path.dirname(HERE), HERE]
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; TMP = os.environ.get("TMPDIR", "/tmp")
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True)
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
PTS = {"P3": 3.0}   # 03:45 uses the 03:00 read in the backtest (no 03:45 recorder read existed); live adds one


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    TWn = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); TWn["id"] = TWn.id.astype(str); twc = dict(zip(TWn.id, TWn.clean_v3_nosite))
    rows = []; src = {}
    for d in pd.date_range("2026-11-02", "2026-11-13").strftime("%Y-%m-%d"):
        V = pd.DataFrame([json.loads(l) for l in gcat(f"{B}/raw/vote_snapshots/{d}.jsonl").stdout.splitlines() if l.strip()])
        V["launch_id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True); V = V.drop_duplicates(["launch_id", "at"]).dropna(subset=["rank_now"])
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC"); truth = R[R.day == d].sort_values("daily_rank")
        fc = tempfile.mkdtemp(dir=TMP) + "/f.parquet"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", fc], capture_output=True)
        cp = {}
        if os.path.exists(fc):
            F_ = pd.read_parquet(fc)
            if len(F_):
                cp = dict(zip(F_.id.astype(str), F_.pred))
        src[d] = "forecast parquet pred" if cp else "month-fold clean_nosite stand-in"
        def at(h):
            T = t0 + pd.Timedelta(hours=h); s = V[(V.a <= T) & (V.a >= T - pd.Timedelta(minutes=65)) & (V.a >= t0 - pd.Timedelta(minutes=5))]
            return s.sort_values("a").groupby("launch_id").last()
        s1 = at(1.0)
        for p, h in PTS.items():
            sT = at(h); ids = [i for i in truth.id if i in sT.index]
            if len(ids) < 10:
                continue
            posT = sT.rank_now.reindex(ids).rank(method="first"); pos1 = s1.rank_now.reindex(ids).fillna(999).rank(method="first")
            for i in ids:
                rows.append({"day": d, "point": p, "id": i, "final": int(truth.set_index("id").daily_rank[i]), "pos": posT[i], "lpos": np.log(posT[i]),
                             "move": np.log(pos1[i]) - np.log(posT[i]), "nc_rec": np.log1p(sT.comments.get(i, 0) or 0), "clean": cp.get(i, twc.get(i, np.nan))})
    X = pd.DataFrame(rows); X["clean"] = X.groupby("day").clean.transform(lambda s: s.fillna(s.min() - 0.1) if s.notna().any() else s.fillna(0))
    F = ["lpos", "move", "nc_rec", "clean"]; ZF = ["z_" + f for f in F]
    for c in F:
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").final.transform(lambda s: zf(-np.log(s)))
    dd = sorted(X.day.unique()); G = {d: X[X.day == d] for d in dd}; AL = [0.3, 1.0, 3.0, 10.0, 30.0]
    def hyb(te, sc):
        oh = te.sort_values(["pos", "id"]).id.tolist(); ol = te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
        return oh[:5] + [i for i in ol if i not in set(oh[:5])]
    def t10(te, order): t = te.sort_values("final").id.tolist(); return hits(order, t)[2]
    def fit(trd, ycol="y", alpha=None):
        tr = pd.concat([G[d] for d in trd])
        if alpha is None:   # regularisation chosen inside the fold: inner leave-one-day-out on the training days, best mean top 10
            best = None
            for a_ in AL:
                v = np.mean([t10(G[x], hyb(G[x], Ridge(alpha=a_).fit(pd.concat([G[z] for z in trd if z != x])[ZF], pd.concat([G[z] for z in trd if z != x])[ycol]).predict(G[x][ZF]))) for x in trd])
                best = (v, a_) if best is None or v > best[0] else best
            alpha = best[1]
        return Ridge(alpha=alpha).fit(tr[ZF], tr[ycol]), alpha
    H = {d: t10(G[d], G[d].sort_values(["pos", "id"]).id.tolist()) for d in dd}
    P6 = {d: t10(G[d], G[d].sort_values(["pos", "id"]).id.tolist()[:5] + [i for i in G[d].sort_values(["clean", "id"], ascending=[False, True]).id if i not in set(G[d].sort_values(["pos", "id"]).id.tolist()[:5])]) for d in dd}
    L1, alphas = {}, {}
    for d in dd:
        m, a_ = fit([x for x in dd if x != d]); alphas[d] = a_; L1[d] = t10(G[d], hyb(G[d], m.predict(G[d][ZF])))
    import itertools
    L2 = {d: [] for d in dd}
    for a, b in itertools.combinations(dd, 2):
        m, _ = fit([x for x in dd if x not in (a, b)], alpha=3.0)
        for d in (a, b): L2[d].append(t10(G[d], hyb(G[d], m.predict(G[d][ZF]))))
    L2 = {d: float(np.mean(v)) for d, v in L2.items()}
    rng = np.random.default_rng(0)
    def ci(A, Bm):
        x = np.array([A[d] - Bm[d] for d in dd]); b = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(10000)])
        return f"{x.mean():+.1f} [{np.percentile(b, 2.5):+.1f}, {np.percentile(b, 97.5):+.1f}]"
    obs = np.mean([L1[d] - H[d] for d in dd])
    # permutation: shuffle the slots-6+ labels within each day (launches outside the hidden top 5), refit LODO at alpha 3, gain vs hidden
    perm = []
    for r in range(200):
        Xs = {}
        for d in dd:
            g = G[d].copy(); top5 = set(g.sort_values(["pos", "id"]).id.tolist()[:5]); k = ~g.id.isin(top5)
            g.loc[k, "yp"] = rng.permutation(g.loc[k, "y"].values); g.loc[~k, "yp"] = g.loc[~k, "y"]; Xs[d] = g
        gains = []
        for d in dd:
            tr = pd.concat([Xs[x] for x in dd if x != d]); m = Ridge(alpha=3.0).fit(tr[ZF], tr.yp)
            gains.append(t10(G[d], hyb(G[d], m.predict(G[d][ZF]))) - H[d])
        perm.append(np.mean(gains))
    pval = float((np.sum(np.array(perm) >= obs) + 1) / (len(perm) + 1))
    md = ["# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)", "",
          f"Days: {len(dd)}. Hidden rank alone {np.mean(list(H.values())):.1f}; slots 6-10 by the 00:05 prior {np.mean(list(P6.values())):.1f}; "
          f"LODO hybrid (alpha chosen inside each fold from {AL}) {np.mean(list(L1.values())):.1f}; L2O hybrid (alpha 3, all 66 pairs) {np.mean(list(L2.values())):.1f}.",
          f"LODO hybrid - hidden: {ci(L1, H)}; L2O hybrid - hidden: {ci(L2, H)}; slots6-by-prior - hidden: {ci(P6, H)}; LODO hybrid - slots6-by-prior: {ci(L1, P6)}.",
          f"Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain {obs:+.2f}, permutation mean {np.mean(perm):+.2f}, "
          f"95th pct {np.percentile(perm, 95):+.2f}, one-sided p = {pval:.3f}.", f"Alphas chosen per fold: {sorted(set(alphas.values()))} ({list(alphas.values())}).",
          "Per day (hidden / LODO / L2O / prior): " + "; ".join(f"{d[5:]} {H[d]:.0f}/{L1[d]:.0f}/{L2[d]:.0f}/{P6[d]:.0f}" for d in dd)]
    open(f"{HERE}/results/hybrid_lodo.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
