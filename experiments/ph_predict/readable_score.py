"""Score readable_model.py (orchestrator 17:40Z Nov 13). Lines vs clean_nosite on the same launches and days (Apr-Oct 2026):
reference = clean_nosite month walk-forward retrain ("pure" of history_retrain DECOMP, 5 seeds, same months); also the OOF tw_nosite line.
Paired day bootstrap on top 3/5/10 and daily Spearman; "not worse" = interval of the top-3 difference includes 0 and |mean| <= 1.5.
Also + th_n_pre (LODO ridge on z(model) + z(th_n_pre)) for both. Output results/readable_model.md"""
import os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
HERE = os.path.dirname(os.path.abspath(__file__))
TH = os.environ.get("TH_FILE", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/th_n_pre_2026.parquet")


def main():
    SUF = os.environ.get("READABLE_SUF", ""); R = pd.read_parquet(f"{HERE}/results/readable_preds{SUF}.parquet"); R["id"] = R.id.astype(str)
    D = pd.read_parquet(f"{HERE}/results/history_retrain_decomp_preds_arm1.parquet")[["id", "day", "dailyRank", "pure"]]; D["id"] = D.id.astype(str)
    A = D.merge(R[["id", "a", "b"]], on="id").dropna(subset=["dailyRank", "pure", "a", "b"])
    T = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); T["id"] = T.id.astype(str)
    A = A.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "oof"}), on="id", how="left"); A["oof"] = A.groupby("day").oof.transform(lambda s: s.fillna(s.min()))
    th = pd.read_parquet(TH); A["npre"] = A.id.map(dict(zip(th.id.astype(str), th.th_n_pre))).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("pure", "a", "b", "oof", "npre"): A["z_" + c] = A.groupby("day")[c].transform(zf)
    A["y"] = A.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    days = sorted(A.day.unique()); rng = np.random.default_rng(0)
    def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    def alone(col):
        return np.array([hits(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) + [g[col].corr(-g.dailyRank, method="spearman")] for _, g in A.groupby("day")])
    def lodo(cols):
        o = []
        for d in days:
            te, tr = A[A.day == d], A[A.day != d]; s = Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols]); te = te.assign(s=s)
            o.append(hits(te.sort_values(["s", "id"], ascending=[False, True]).id.tolist(), te.sort_values("dailyRank").id.tolist()) + [te.s.corr(-te.dailyRank, method="spearman")])
        return np.array(o)
    def ci(dP):
        b = np.array([np.nanmean(dP[rng.integers(0, len(dP), len(dP))], 0) for _ in range(3000)])
        return [(np.nanmean(dP[:, k]), np.nanpercentile(b[:, k], 2.5), np.nanpercentile(b[:, k], 97.5)) for k in range(4)]
    def row(nm, X, ref):
        c = ci(X - ref); nw = c[0][1] <= 0 <= c[0][2] and abs(c[0][0]) <= 1.5
        return f"| {nm} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {np.nanmean(X[:,3]):.3f} | " + " / ".join(f"{m:+.{3 if k == 3 else 1}f} [{l:+.{3 if k == 3 else 1}f}, {h:+.{3 if k == 3 else 1}f}]" for k, (m, l, h) in enumerate(c)) + f" | {'not worse' if nw else ('better' if c[0][1] > 0 else 'worse')} |"
    P = alone("pure"); md = [f"# Readable 00:05 model vs clean_nosite ({len(days)} days Apr-Oct 2026, {len(A)} launches; walk-forward by month)", "",
          "Inputs (10, all in the deployed clean_nosite set, known at 00:05): hunter track record (hist_hunter_rel, hist_hunter_n), Gemini pitch and brand (llm_pitch, llm_brand), topic prior (topic_prior_mean), closest same-day competitor (comp_nn_max), media (ph_n_media, ph_has_video), team size (ph_n_makers), pre-launch promotion (promo_cov).", "",
          "| line | top 3 | top 5 | top 10 | daily rho | diff vs clean_nosite (t3 / t5 / t10 / rho, 95%) | call (top 3) |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite (walk-forward retrain, 40 inputs, reference) | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | {np.nanmean(P[:,3]):.3f} | - | - |",
          row("(a) readable ridge on within-day z, 10 inputs", alone("a"), P), row("(b) readable additive monotone stumps, 10 inputs", alone("b"), P),
          row("clean_nosite OOF line (tw_nosite)", alone("oof"), P), "", "## + th_n_pre (LODO ridge), vs clean_nosite + th_n_pre", "",
          "| line | top 3 | top 5 | top 10 | daily rho | diff (95%) | call |", "|---|---|---|---|---|---|---|"]
    P2 = lodo(["z_pure", "z_npre"]); md.append(f"| clean_nosite + th_n_pre (reference) | {P2[:,0].mean():.1f} | {P2[:,1].mean():.1f} | {P2[:,2].mean():.1f} | {np.nanmean(P2[:,3]):.3f} | - | - |")
    md += [row("(a) + th_n_pre", lodo(["z_a", "z_npre"]), P2), row("(b) + th_n_pre", lodo(["z_b", "z_npre"]), P2), "",
           "Rule (orchestrator): not worse = interval of the top-3 difference includes 0 and the mean is within 1.5 points."]
    open(f"{HERE}/results/readable_model{SUF}.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
