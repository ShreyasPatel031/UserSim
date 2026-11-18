"""Arm-2 re-fit choices (orchestrator 20:32Z Nov 13), scored paired vs deployed arm 2 on the same 214 days (Apr-Oct, walk-forward, 5 seeds).
Selection guard: each group's choice (capacity, row weighting, objective, blend weight) is picked on the FIRST 107 days by top 3 (ties:
top 5, then top 10), frozen, and reported on the last 107 and on all 214. Rule 5 here: last-107 and all-days top-3 intervals both > 0, or a
top 5/10 gain clearing 0 on both with top 3 not worse. Inputs: results/history_retrain_decomp_preds_rf_<tag>.parquet ('both');
blend partners from results/readable_preds_v2.parquet (a = ridge on the 10 readable inputs, b = readable v2 stumps).
usage: python refit_score.py -> results/arm2_refit.md"""
import glob, os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = f"{HERE}/results"
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
rng = np.random.default_rng(0)


def main():
    A = pd.read_parquet(f"{R}/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str)
    A = A.dropna(subset=["dailyRank", "both"])[["id", "day", "dailyRank", "both"]].rename(columns={"both": "arm2"})
    tags = sorted(os.path.basename(f)[len("history_retrain_decomp_preds_rf_"):-8] for f in glob.glob(f"{R}/history_retrain_decomp_preds_rf_*.parquet"))
    for t in tags:
        x = pd.read_parquet(f"{R}/history_retrain_decomp_preds_rf_{t}.parquet"); x["id"] = x.id.astype(str)
        A = A.merge(x[["id", "both"]].rename(columns={"both": t}), on="id", how="left")
    Rd = pd.read_parquet(f"{R}/readable_preds_v2.parquet"); Rd["id"] = Rd.id.astype(str)
    A = A.merge(Rd[["id", "a", "b"]].rename(columns={"a": "ridge10", "b": "stumps"}), on="id", how="left")
    for c in ["ridge10", "stumps"] + tags:
        A[c] = A.groupby("day")[c].transform(lambda s: s.fillna(s.min() - 1) if s.notna().any() else s.fillna(0))
    pr = lambda c: A.groupby("day")[c].rank(pct=True)
    for c in ("arm2", "ridge10", "stumps"):
        A["p_" + c] = pr(c)
    days = sorted(A.day.unique()); first, last = set(days[:107]), set(days[107:])
    G = {d: g for d, g in A.groupby("day")}
    def top(c):
        return np.array([hits(G[d].sort_values([c, "id"], ascending=[False, True]).id.tolist(), G[d].sort_values("dailyRank").id.tolist()) for d in days])
    base = top("arm2"); f_ix = np.array([d in first for d in days]); l_ix = ~f_ix
    def ci(P, ix):
        d = P[ix] - base[ix]; b = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(4000)])
        return d.mean(0), np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)
    S = {t: top(t) for t in tags}
    for nm in ("stumps", "ridge10"):
        for w in (0.1, 0.2, 0.3, 0.4, 0.5):
            c = f"blend_{nm}_{w}"; A[c] = (1 - w) * A.p_arm2 + w * A["p_" + nm]; G = {d: g for d, g in A.groupby("day")}; S[c] = top(c)
    groups = {"a) capacity": [t for t in tags if t.startswith("cap_")], "b) row weighting": [t for t in tags if t.startswith("w_")],
              "c) objective (LambdaRank)": [t for t in tags if t.startswith("obj_")],
              "d) rank blend with readable v2 stumps": [c for c in S if c.startswith("blend_stumps")], "d) rank blend with readable ridge": [c for c in S if c.startswith("blend_ridge10")]}
    key = lambda c: tuple(S[c][f_ix].mean(0))
    md = ["# Arm 2 re-fit choices with the doubled training set (orchestrator 20:32Z Nov 13)", "",
          f"{len(days)} days (Apr-Oct), walk-forward, 5 seeds, paired vs deployed arm 2 ({base.mean(0)[0]:.1f} / {base.mean(0)[1]:.1f} / {base.mean(0)[2]:.1f}; "
          f"first 107 {base[f_ix].mean(0)[0]:.1f} / last 107 {base[l_ix].mean(0)[0]:.1f} top 3). Each group's choice is picked on the first 107 days only, then frozen.", "",
          "| group | chosen (on first 107) | first-107 top 3 diff | last 107: top 3 / 5 / 10 diff [95%] | all 214: top 3 / 5 / 10 diff [95%] | rule 5 |", "|---|---|---|---|---|---|"]
    for g, cands in groups.items():
        if not cands:
            md.append(f"| {g} | (no runs) | | | | |"); continue
        ch = max(cands, key=key); fm = S[ch][f_ix].mean(0) - base[f_ix].mean(0)
        L, A_ = ci(S[ch], l_ix), ci(S[ch], np.ones(len(days), bool))
        q = lambda r: " / ".join(f"{r[0][k]:+.1f} [{r[1][k]:+.1f}, {r[2][k]:+.1f}]" for k in range(3))
        ok = (L[1][0] > 0 and A_[1][0] > 0) or (((L[1][1] > 0 and A_[1][1] > 0) or (L[1][2] > 0 and A_[1][2] > 0)) and L[0][0] >= 0 and A_[0][0] >= 0)
        md.append(f"| {g} | {ch} | {fm[0]:+.1f} | {q(L)} | {q(A_)} | {'QUALIFIES' if ok else 'no'} |")
    md += ["", "## Every candidate (top 3 / 5 / 10 diff vs arm 2; first 107 | last 107 | all)", "", "| candidate | first 107 | last 107 | all |", "|---|---|---|---|"]
    for c in S:
        f_ = lambda ix: " / ".join(f"{v:+.1f}" for v in (S[c][ix].mean(0) - base[ix].mean(0)))
        md.append(f"| {c} | {f_(f_ix)} | {f_(l_ix)} | {f_(np.ones(len(days), bool))} |")
    open(f"{R}/arm2_refit.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
