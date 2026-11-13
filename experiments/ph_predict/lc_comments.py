"""Learning curve of the comment-based 00:30 lines over 2026 history length + 2025-comments what-if (orchestrator 20:16Z Nov 13).
(1) Ridge lines on the clean_nosite OOF base (mrep = clean+th_n_pre+nu+nc+mrep_h; clean+th = clean+th_n_pre), weights fit month-forward on
    the most recent N 2026 days before the test month, N in 60/100/150/all.
(2) LightGBM arm-2 joint models with the 00:30 comment inputs inside (history_retrain.py JOINT=1 JOINT_COLS=th_n_pre,nu,nc,mrep_h):
    pure_th = 2026 rows only, HIST_N = 60/100/150/all; both_th = + 2025 rows with comment inputs missing (HIST_N keeps the most recent N
    days, so both_th at N < all has no 2025 rows: it differs from pure_th only by the build).
Test days: 2026-04-01..2026-10-24 (comment dumps end Oct 25). Paired bootstrap 4000 over days, 95%.
usage: python lc_comments.py -> results/lc_comments.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from sklearn.linear_model import Ridge
SCR = "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad"
NS = ["60", "100", "150", "all"]


def hits(o, t):
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]


def topk(A, col):
    return np.array([hits(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist())
                     for _, g in A.groupby("day")])


def ci(d, rng):
    b = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(4000)])
    return " / ".join(f"{d[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3))


def main():
    rng = np.random.default_rng(0)
    T = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); T["id"] = T.id.astype(str)
    C = pd.read_parquet(os.environ.get("CM_FILE", f"{SCR}/cm_p030_2026.parquet")); C["id"] = C.id.astype(str)
    A = T.dropna(subset=["clean_v3_nosite", "dailyRank"]).merge(C, on="id", how="inner")
    A = A[(A.day >= "2026-03-01") & (A.day <= "2026-10-24")].copy(); A["mon"] = A.day.str[:7]
    A["npre"] = A.th_n_pre
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean_v3_nosite", "npre", "nu", "nc", "mrep_h"):
        A["z_" + c] = A.groupby("day")[c].transform(zf)
    A["y"] = A.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    LINES = {"mrep": ["z_clean_v3_nosite", "z_npre", "z_nu", "z_nc", "z_mrep_h"], "clean+th": ["z_clean_v3_nosite", "z_npre"]}
    md = ["# Learning curve of the comment-based 00:30 lines over 2026 history, and the 2025-comments what-if", "",
          "Test days 2026-04-01..2026-10-24 (comment dumps end Oct 25). Paired 95% bootstrap over days. Diffs are vs the same line with all history.", ""]
    days = sorted(A[A.day >= "2026-04-01"].day.unique())
    R = {}
    for ln, cols in LINES.items():
        for N in NS:
            out = []
            for m in sorted(A[A.day >= "2026-04-01"].mon.unique()):
                tr = A[A.mon < m]; dd = sorted(tr.day.unique())
                if N != "all":
                    tr = tr[tr.day.isin(dd[-int(N):])]
                te = A[A.mon == m]; out.append(te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])))
            R[(ln, N)] = topk(pd.concat(out), "s")
    md += ["## (1) Ridge lines on the clean_nosite OOF base (only the blend weights see N days; the base model is unchanged)", "",
           "| line | N days | top 3 | top 5 | top 10 | diff vs all (t3 / t5 / t10) |", "|---|---|---|---|---|---|"]
    for ln in LINES:
        for N in NS:
            P = R[(ln, N)]; md.append(f"| {ln} | {N} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | {'-' if N == 'all' else ci(P - R[(ln, 'all')], rng)} |")
    # (2) GBM joint runs
    md += ["", "## (2) LightGBM arm-2 model with the 00:30 comment inputs inside (th_n_pre, distinct commenters, total comments, hunter replies)", ""]
    J = {}
    for N in NS:
        f = f"{HERE}/results/history_retrain_joint_arm2_cm{N}.parquet"
        if os.path.exists(f):
            x = pd.read_parquet(f); x["id"] = x.id.astype(str); J[N] = x.set_index("id")
    if J:
        B = A[A.day >= "2026-04-01"].copy()
        ok = np.ones(len(B), bool)
        for N, x in J.items():
            for v in ("pure_th", "both_th"):
                B[f"{v}_{N}"] = B.id.map(x[v]); ok &= B[f"{v}_{N}"].notna().values
        B = B[ok]; nd = B.day.nunique()
        # mrep ridge (LODO, as published) on these exact launches for the reference
        def lodo(cols):
            o = []
            for d in sorted(B.day.unique()):
                tr, te = B[B.day != d], B[B.day == d]
                o.append(te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])))
            return topk(pd.concat(o), "s")
        ref = lodo(LINES["mrep"]); cth = lodo(LINES["clean+th"])
        md += [f"{nd} days, {len(B)} launches with every run present. Reference = mrep (LODO ridge on the clean_nosite base, as published at 00:30): "
               f"{ref[:,0].mean():.1f} / {ref[:,1].mean():.1f} / {ref[:,2].mean():.1f}; clean+th_n_pre {cth[:,0].mean():.1f} / {cth[:,1].mean():.1f} / {cth[:,2].mean():.1f}.", "",
               "| model | N 2026 days | top 3 | top 5 | top 10 | diff vs same model, all days (t3 / t5 / t10) | diff vs mrep (t3 / t5 / t10) |", "|---|---|---|---|---|---|---|"]
        G = {}
        for v, lab in (("pure_th", "2026 rows only, comments inside"), ("both_th", "+ 2025 rows (comments missing)")):
            for N in NS:
                if N in J:
                    G[(v, N)] = topk(B, f"{v}_{N}")
            for N in NS:
                if (v, N) in G:
                    P = G[(v, N)]
                    md.append(f"| {lab} | {N} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | "
                              f"{'-' if N == 'all' or (v, 'all') not in G else ci(P - G[(v, 'all')], rng)} | {ci(P - ref, rng)} |")
        # log-days fit on pure_th (2026 only): slope per doubling of 2026 history, extrapolate to +365 days of comment-bearing rows
        if all(("pure_th", N) in G for N in NS):
            # effective N per test month: min(N, days available before the month)
            B["mon"] = B.day.str[:7]; avail = {m: (pd.Timestamp(m + "-01") - pd.Timestamp("2026-01-01")).days for m in B.mon.unique()}   # GBM trains on 2026 from Jan 1
            dmon = B.groupby("day").mon.first().sort_index()
            rows = []
            for N in NS:
                P = G[("pure_th", N)]
                for i, d in enumerate(sorted(B.day.unique())):
                    n_eff = avail[dmon[d]] if N == "all" else min(int(N), avail[dmon[d]])
                    rows.append((np.log2(n_eff), *P[i], d))
            Z = pd.DataFrame(rows, columns=["l", "t3", "t5", "t10", "day"])
            # within-day slope: demean per day so only history length varies
            for k in ("t3", "t5", "t10", "l"):
                Z[k + "_d"] = Z[k] - Z.groupby("day")[k].transform("mean")
            Zv = Z[Z.l_d.abs() > 1e-9]
            dlist = Zv.day.unique()
            def slope(Zs):
                return [float((Zs.l_d * Zs[k + "_d"]).sum() / (Zs.l_d ** 2).sum()) for k in ("t3", "t5", "t10")]
            s0 = slope(Zv); bs = []
            for _ in range(2000):
                pick = rng.choice(dlist, len(dlist)); bs.append(slope(Zv.set_index("day").loc[pick].reset_index()))
            bs = np.array(bs); n_all = np.mean([avail[m] for m in dmon.values])
            gain = np.log2((n_all + 365) / n_all)
            md += ["", f"Log-days fit (pure_th, within-day, days where N binds; mean history at 'all' = {n_all:.0f} days): per doubling of 2026 history "
                   + " / ".join(f"{s0[k]:+.1f} [{np.percentile(bs[:,k],2.5):+.1f}, {np.percentile(bs[:,k],97.5):+.1f}]" for k in range(3)) + " (top 3 / 5 / 10).",
                   f"Extrapolated gain from +365 days of comment-bearing rows ({gain:.2f} doublings): "
                   + " / ".join(f"{s0[k]*gain:+.1f} [{np.percentile(bs[:,k],2.5)*gain:+.1f}, {np.percentile(bs[:,k],97.5)*gain:+.1f}]" for k in range(3)) + "."]
    open(f"{HERE}/results/lc_comments.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
