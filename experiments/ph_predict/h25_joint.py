"""Joint fit score (orchestrator 11:33Z Nov 13): th_n_pre INSIDE the model (history_retrain.py JOINT=1) vs the stacked reference.
Reads results/history_retrain_joint_arm{N}.parquet (id, pure_th, both_th seed means) + the DECOMP file of the same arm (day, dailyRank,
pure, both). Same days as h25_stack (2026 Apr-Oct rows with all arms). Lines: model alone (pure_th, both_th, pure, both) and the
reference LODO ridge z(clean_nosite OOF) + z(th_n_pre). Paired 95% bootstrap over days vs the reference.
usage: python h25_joint.py _arm2 -> results/h25_joint_arm2.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import h25_stack as HS
from sklearn.linear_model import Ridge


def main():
    SUF = sys.argv[1]
    J = pd.read_parquet(f"{HERE}/results/history_retrain_joint{SUF}.parquet"); J["id"] = J.id.astype(str)
    A = pd.read_parquet(f"{HERE}/results/history_retrain_decomp_preds{SUF}.parquet"); A["id"] = A.id.astype(str)
    A = A.dropna(subset=["dailyRank", "pure", "both"]).merge(J, on="id", how="inner").dropna(subset=["pure_th", "both_th"])
    T = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); T["id"] = T.id.astype(str)
    A = A.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "ref"}), on="id", how="left")
    A["ref"] = A.groupby("day").ref.transform(lambda s: s.fillna(s.min()))
    th = pd.read_parquet(os.environ.get("TH_FILE", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/th_n_pre_2026.parquet"))
    A["npre"] = A.id.map(dict(zip(th.id.astype(str), th.th_n_pre))).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("ref", "npre", "pure", "both"):
        A["z_" + c] = A.groupby("day")[c].transform(zf)
    A["y"] = A.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    days = sorted(A.day.unique()); rng = np.random.default_rng(0)
    def alone(col):
        return np.array([HS.hits(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) for d, g in A.groupby("day")])
    def lodo(cols):
        o = []
        for d in days:
            te, tr = A[A.day == d], A[A.day != d]
            o.append(HS.hits(te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), te.sort_values("dailyRank").id.tolist()))
        return np.array(o)
    def ci(dP):
        b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        return " / ".join(f"{dP[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3))
    R0 = lodo(["z_ref", "z_npre"])
    md = [f"# Joint fit, th_n_pre inside the model ({SUF.strip('_')}; {len(days)} days 2026 Apr-Oct; {len(A)} launches; 5 seeds)", "",
          "| line | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (t3 / t5 / t10, 95%) |", "|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre (LODO ridge, reference) | {R0[:,0].mean():.1f} | {R0[:,1].mean():.1f} | {R0[:,2].mean():.1f} | - |"]
    rows = [("pure_th (joint, no 2025)", alone("pure_th")), ("both_th (joint, 2025 rows, th missing on them)", alone("both_th")),
            ("pure + th_n_pre (stacked)", lodo(["z_pure", "z_npre"])), ("both + th_n_pre (stacked)", lodo(["z_both", "z_npre"])),
            ("pure alone", alone("pure")), ("both alone", alone("both"))]
    for nm, X in rows:
        md.append(f"| {nm} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {ci(X - R0)} |")
    X = alone("both_th") - lodo(["z_both", "z_npre"]); md += ["", f"both_th (joint) minus both + th_n_pre (stacked): {ci(X)}"]
    open(f"{HERE}/results/h25_joint{SUF}.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
