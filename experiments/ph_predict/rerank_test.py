"""Re-rank test (orchestrator 20:04Z Nov 13). At 00:30 (P030) and 01:00 (P1): keep the published line's positions 1-3 (or 1)
fixed and re-order positions 4-15 (or 2-15) by a frozen readable early-activity score = non-negative ridge on z(th_n_pre),
z(distinct commenters), z(total comments), z(hunter-only replies) at T, fit month-forward (earlier months only; April has no
earlier month, so April days keep the published order). Published line = mrep LODO score (P030: clean+npre+nu+nc+mrep_h;
P1: clean+npre+nu+nc+mrep_f full team, as maker_replies.py). Paired bootstrap, all days and last 107. Counts only.
usage: python rerank_test.py -> results/rerank_test.md (+ results/frozen/rerank_<pt>_20261113.json if it qualifies)"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
CUTS = {"P030": (30, "z_mrep_h"), "P1": (60, "z_mrep_f")}
RS = ["z_npre", "z_nu", "z_nc", "z_mrep_h"]


def hits(o, t):
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]


def boot(dP, rng, n=4000):
    b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(n)])
    return dP.mean(0), np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster, makers FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X0 = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X0 = X0[(X0.day >= "2026-04-01") & (X0.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster", "makers"]], on="slug")
    K["d0"] = [pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    mk = {i: {str(m).lower() for m in (json.loads(v) if isinstance(v, str) and v.startswith("[") else [])} for i, v in zip(L.id, L.makers)}
    K["is_h"] = K.user == K.poster; K["is_team"] = K.is_h | np.array([u in mk.get(i, set()) for u, i in zip(K.user, K.id)], dtype=bool)
    K["rep"] = K.depth > 0
    pre = K[K.ts <= K.d0 + pd.Timedelta(minutes=5)]
    X0["npre"] = X0.id.map(pre[~pre.is_h].groupby("id").user.nunique()).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    rng = np.random.default_rng(0)
    md = [f"# Re-rank test: keep published top positions, re-order the rest by a readable early-activity score", "",
          "Published line = mrep LODO (P030 hunter-only replies; P1 full-team replies). Re-rank score = non-negative ridge on z(th_n_pre), "
          "z(distinct non-hunter commenters <= T), z(total comments <= T), z(hunter-only replies <= T); weights fit month-forward on earlier months "
          "only (April keeps the published order, diff 0). Paired bootstrap 4000; 95% intervals.", ""]
    out = {}
    for pt, (mins, mcol) in CUTS.items():
        C = K[K.ts <= K.d0 + pd.Timedelta(minutes=mins)]; X = X0.copy()
        X["nc"] = np.log1p(X.id.map(C.groupby("id").size()).fillna(0))
        X["nu"] = np.log1p(X.id.map(C[~C.is_h].groupby("id").user.nunique()).fillna(0))
        X["mrep_f"] = np.log1p(X.id.map(C[C.is_team & C.rep].groupby("id").size()).fillna(0))
        X["mrep_h"] = np.log1p(X.id.map(C[C.is_h & C.rep].groupby("id").size()).fillna(0))
        for c in ("clean", "npre", "nc", "nu", "mrep_f", "mrep_h"):
            X["z_" + c] = X.groupby("day")[c].transform(zf)
        X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
        X["mon"] = X.day.str[:7]
        PUB = ["z_clean", "z_npre", "z_nu", "z_nc", mcol]
        days = sorted(X.day.unique()); rows = []; wts = {}
        for d in days:
            te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            te = te.assign(s=Ridge(alpha=3.0).fit(tr[PUB], tr.y).predict(te[PUB])).sort_values(["s", "id"], ascending=[False, True])
            pub = te.id.tolist(); m = te.mon.iloc[0]
            if m not in wts:
                trm = X[X.mon < m]
                wts[m] = Ridge(alpha=3.0, positive=True).fit(trm[RS], trm.y) if len(trm) else None
            r = dict(day=d, pub=hits(pub, t))
            for keep in (3, 1):
                if wts[m] is None:
                    o = pub
                else:
                    seg = te.iloc[keep:15].assign(r=wts[m].predict(te.iloc[keep:15][RS])).sort_values(["r", "id"], ascending=[False, True]).id.tolist()
                    o = pub[:keep] + seg + pub[15:]
                r[f"k{keep}"] = hits(o, t)
            rows.append(r)
        Pp = np.array([r["pub"] for r in rows])
        md += [f"## {pt} ({mins // 60:02d}:{mins % 60:02d} PT), {len(days)} days; published (mrep) top 3/5/10 = {Pp[:,0].mean():.1f} / {Pp[:,1].mean():.1f} / {Pp[:,2].mean():.1f}", "",
               "| variant | days | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|---|"]
        for keep, nm in ((3, "keep 1-3, re-order 4-15"), (1, "keep 1, re-order 2-15")):
            Pk = np.array([r[f"k{keep}"] for r in rows])
            for lab, sl in (("all", slice(None)), ("last 107", slice(-107, None))):
                mu, lo, hi = boot(Pk[sl] - Pp[sl], rng)
                md.append(f"| {nm} | {lab} | {Pk[sl][:,0].mean():.1f} | {Pk[sl][:,1].mean():.1f} | {Pk[sl][:,2].mean():.1f} | " +
                          " | ".join(f"{mu[k]:+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3)) + " |")
                out[(pt, keep, lab)] = (mu, lo, hi)
        last = wts[max(wts)]
        md += ["", f"Month-forward weights for the last month ({max(wts)}): " + ", ".join(f"{c} {w:.3f}" for c, w in zip(RS, last.coef_)), ""]
        # rule 5: top 5 or top 10 lower bound > 0 (all days) and top 3 not worse (upper >= 0 i.e. mean >= 0 / not significantly worse)
        for keep in (3, 1):
            mu, lo, hi = out[(pt, keep, "all")]
            ok = (lo[1] > 0 or lo[2] > 0) and hi[0] >= 0 and mu[0] >= -0.05
            md.append(f"Rule 5 check {pt} keep {keep}: {'QUALIFIES' if ok else 'does not qualify'} (top 5 lo {lo[1]:+.1f}, top 10 lo {lo[2]:+.1f}, top 3 {mu[0]:+.1f} [{lo[0]:+.1f}, {hi[0]:+.1f}])")
            if ok:
                full = Ridge(alpha=3.0, positive=True).fit(X[RS], X.y)
                fp = os.path.join(HERE, "results", "frozen", f"rerank_{pt}_k{keep}_20261113.json")
                if not os.path.exists(fp):
                    json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "point": pt, "keep_top": keep, "reorder_to": 15,
                               "coef": dict(zip(RS, map(float, full.coef_))), "intercept": float(full.intercept_)}, open(fp, "w"), indent=1)
                    md.append(f"  frozen -> {os.path.relpath(fp, HERE)}")
        md.append("")
    open(os.path.join(HERE, "results", "rerank_test.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
