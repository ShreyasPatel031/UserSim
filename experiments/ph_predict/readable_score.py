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
    Bt = lodo(["z_b", "z_npre"])
    md += [row("(a) + th_n_pre", lodo(["z_a", "z_npre"]), P2), row("(b) + th_n_pre", Bt, P2), ""]
    # orchestrator 18:46Z guard: input set chosen on the first half only; report last half and all days separately
    half = len(days) // 2
    md += [f"## Split (input set chosen on the first {half} days only; days {days[0]}..{days[half - 1]} | {days[half]}..{days[-1]})", "",
           "| line | days | diff t3 / t5 / t10 / rho vs reference (95%) | call |", "|---|---|---|---|"]
    for nm, X, ref in (("(b) alone vs clean_nosite", alone("b"), P), ("(b) + th_n_pre vs clean_nosite + th_n_pre", Bt, P2)):
        for lab, sl in (("first half", slice(0, half)), ("last half", slice(half, None)), ("all", slice(None))):
            c = ci((X - ref)[sl]); nw = c[0][1] <= 0 <= c[0][2] and abs(c[0][0]) <= 1.5
            md.append(f"| {nm} | {lab} | " + " / ".join(f"{m:+.{3 if k == 3 else 1}f} [{l:+.{3 if k == 3 else 1}f}, {h:+.{3 if k == 3 else 1}f}]" for k, (m, l, h) in enumerate(c)) + f" | {'not worse' if nw else 'worse'} |")
    # agreement: how often (b)+th and clean+th pick the same top 3 per day (LODO scores)
    ag = []
    for d in days:
        te, tr = A[A.day == d], A[A.day != d]
        sb = Ridge(alpha=3.0).fit(tr[["z_b", "z_npre"]], tr.y).predict(te[["z_b", "z_npre"]]); sc = Ridge(alpha=3.0).fit(tr[["z_pure", "z_npre"]], tr.y).predict(te[["z_pure", "z_npre"]])
        tb = set(te.assign(s=sb).sort_values(["s", "id"], ascending=[False, True]).id[:3]); tc = set(te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id[:3])
        ag.append(len(tb & tc))
    ag = np.array(ag)
    md += ["", f"Top-3 agreement, (b) + th_n_pre vs clean_nosite + th_n_pre, per day: all 3 same {np.mean(ag == 3):.1%}, >= 2 same {np.mean(ag >= 2):.1%}, mean overlap {ag.mean():.2f} of 3 ({len(days)} days).", "",
           "Rule (orchestrator): not worse = interval of the top-3 difference includes 0 and the mean is within 1.5 points."]
    fp = f"{HERE}/results/frozen/readable_v2_th_20261113.json"
    if SUF == "_v2" and not os.path.exists(fp):   # orchestrator 18:46Z: v2 input set fixed on the first half; weights fit on all 214 days
        import json
        m = Ridge(alpha=3.0).fit(A[["z_b", "z_npre"]], A.y)
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": len(days), "coef": {"z_readable": float(m.coef_[0]), "z_npre": float(m.coef_[1])},
                   "inputs": "z within day: shadow_readable pred_readable_v2 (00:05 rows), th_n_pre (night's first comment read)",
                   "backtest": "readable_model_v2.md: (b)+th vs clean+th top 3 -1.2 [-3.4, +0.9] all 214 days, -1.2 [-4.4, +1.6] last 107"}, open(fp, "w"), indent=1)
    open(f"{HERE}/results/readable_model{SUF}.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
