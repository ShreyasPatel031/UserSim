"""2025 decomposition + stacking (orchestrator 05:05Z Nov 13). Reads the VM output of history_retrain.py DECOMP=1
(results/history_retrain_decomp_preds.parquet: seed-mean predictions; results/history_retrain_decomp_seeds.parquet: per seed).
Arms: pure (no 2025), histonly (2025 only through hunter history), rowsonly (2025 only as training rows), both.
(a) model alone, top 3/5/10 + daily rho, seed sd, paired diff vs pure; (b) split of both - pure by whether the launch's hunter has
2025 history; (c) stacking: LODO ridge z(arm) + z(th_n_pre) vs the reference z(clean_nosite OOF, tw_nosite) + z(th_n_pre)
(60.1 / 68.7 / 75.3), and the clean_nosite_tb-style tie-break (positions 2-6 by z(arm) + z(th_n_pre)).
usage: python h25_stack.py -> results/h25_stack.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
ARMS = ["pure", "histonly", "rowsonly", "both"]


def hits(o, t):
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]


def main():
    from pipeline import warehouse as W
    A = pd.read_parquet(os.path.join(HERE, "results", "history_retrain_decomp_preds.parquet")); A["id"] = A.id.astype(str)
    S = pd.read_parquet(os.path.join(HERE, "results", "history_retrain_decomp_seeds.parquet")); S["id"] = S.id.astype(str)
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, poster FROM launches", do_sync=False); L["poster"] = L.poster.fillna("").str.lower()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [(pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(minutes=5)).tz_convert("UTC") for d in K.day]
    A["npre"] = A.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    A = A.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "ref"}), on="id", how="left")
    A["ref"] = A.groupby("day").ref.transform(lambda s: s.fillna(s.min()))
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ARMS + ["npre", "ref"]:
        A["z_" + c] = A.groupby("day")[c].transform(zf)
    A["y"] = A.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    days = sorted(A.day.unique()); rng = np.random.default_rng(0)
    def alone(col, sub=None):
        o_ = []
        for d, g in (A if sub is None else A[sub]).groupby("day"):
            t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
            o_.append(hits(o, t) + [g[col].corr(-g.dailyRank, method="spearman")])
        return np.array(o_)
    def ci(dP):
        b = np.array([np.nanmean(dP[rng.integers(0, len(dP), len(dP))], 0) for _ in range(3000)])
        return " / ".join(f"{np.nanmean(dP[:, k]):+.{3 if k == 3 else 1}f} [{np.nanpercentile(b[:, k], 2.5):+.{3 if k == 3 else 1}f}, {np.nanpercentile(b[:, k], 97.5):+.{3 if k == 3 else 1}f}]" for k in range(dP.shape[1]))
    md = [f"# 2025 decomposition and stacking ({len(days)} days Apr-Oct; 5 seeds; share of launches whose hunter has 2025 history {A.h_has_2025.mean():.1%})", "",
          "## (a) model alone", "", "| arm | top 3 | top 5 | top 10 | daily rho | seed sd t3 | diff vs pure (t3 / t5 / t10 / rho, 95%) |", "|---|---|---|---|---|---|---|"]
    base = alone("pure")
    for a in ARMS:
        X = alone(a); sd = []
        for s, g in S[S.variant == a].groupby("seed"):
            G = g.merge(A[["id", "day", "dailyRank"]], on="id"); sd.append(np.mean([hits(x.sort_values(["pred", "id"], ascending=[False, True]).id.tolist(), x.sort_values("dailyRank").id.tolist())[0] for _, x in G.groupby("day")]))
        md.append(f"| {a} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {np.nanmean(X[:,3]):.3f} | {np.std(sd):.1f} | {'-' if a == 'pure' else ci(X - base)} |")
    md += ["", "## (b) both - pure, by whether the hunter has 2025 history (top 3 / 5 / 10 hits counted on launches of that group only is not defined per day; "
           "reported: mean rank-percentile gain of the true top-3 launches)", ""]
    A["pct_pure"] = A.groupby("day").pure.rank(pct=True); A["pct_both"] = A.groupby("day").both.rank(pct=True)
    T3 = A[A.dailyRank <= 3]
    for flag, g in T3.groupby("h_has_2025"):
        dd = (g.pct_both - g.pct_pure).values; b = [np.mean(dd[rng.integers(0, len(dd), len(dd))]) for _ in range(3000)]
        md.append(f"- hunter has 2025 history = {bool(flag)}: final top-3 launches n {len(g)}, mean within-day percentile gain {dd.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]")
    md += ["", "## (c) stacking with th_n_pre (LODO ridge)", "", "| model | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (95%) |", "|---|---|---|---|---|"]
    def lodo(cols):
        o_ = []
        for d in days:
            te, tr = A[A.day == d], A[A.day != d]; t = te.sort_values("dailyRank").id.tolist()
            o_.append(hits(te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), t))
        return np.array(o_)
    def tb(arm):
        o_ = []
        for d in days:
            te, tr = A[A.day == d], A[A.day != d]; t = te.sort_values("dailyRank").id.tolist()
            tr = tr.assign(cp=tr.groupby("day")[arm].rank(ascending=False, method="first")); w = tr[(tr.cp >= 2) & (tr.cp <= 6)]
            m = Ridge(alpha=3.0).fit(w[["z_" + arm, "z_npre"]], w.y)
            o0 = te.sort_values([arm, "id"], ascending=[False, True]).id.tolist(); mid = te[te.id.isin(o0[1:6])]
            mid = mid.assign(s=m.predict(mid[["z_" + arm, "z_npre"]])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append(hits(o0[:1] + mid + o0[6:], t))
        return np.array(o_)
    R0 = lodo(["z_ref", "z_npre"]); md.append(f"| clean_nosite (tw_nosite) + th_n_pre | {R0[:,0].mean():.1f} | {R0[:,1].mean():.1f} | {R0[:,2].mean():.1f} | - |")
    for a in ARMS:
        X = lodo(["z_" + a, "z_npre"]); md.append(f"| {a} + th_n_pre | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {ci(X - R0)} |")
    for a in ("pure", "both"):
        X = tb(a); md.append(f"| {a} tie-break (pos 2-6 by z({a}) + z(th_n_pre)) | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {ci(X - R0)} |")
    open(os.path.join(HERE, "results", "h25_stack.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
