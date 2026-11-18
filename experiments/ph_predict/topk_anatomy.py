"""Top 5 / top 10 anatomy for arm 2 (orchestrator 20:00Z Nov 13; the top-3 misses are done elsewhere). 214 days Apr-Oct 2026.
Groups: (A) real rank 4-10 the model placed outside its top 10 (misses); (B) model top-10 picks that finished outside the top 10 (false
picks); (H) real rank 4-10 the model placed in its top 10 (hits). Compared on the readable v2 per-input points (walk-forward, same days),
th_n_pre (pre-launch commenters) and final votes. Oracle headroom: per day, give the model's ranks 11-15 their true order against its
6-10 (swap any true top-10 launch from 11-15 in for a false pick at 6-10), and similarly 4-8 for top 5.
usage: python topk_anatomy.py -> results/topk_anatomy.md"""
import os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = f"{HERE}/results"
A = pd.read_parquet(f"{R}/history_retrain_decomp_preds_arm2.parquet")[["id", "day", "dailyRank", "both"]].dropna(); A["id"] = A.id.astype(str)
A["mrank"] = A.groupby("day").both.rank(ascending=False, method="first")
C = pd.read_parquet(f"{R}/readable_contrib_v2.parquet"); C["id"] = C.id.astype(str); P = C.pivot_table(index="id", columns="input", values="points")
th = pd.read_parquet(os.environ.get("TH_FILE", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/th_n_pre_2026.parquet")); A["th_n_pre"] = A.id.map(dict(zip(th.id.astype(str), th.th_n_pre)))
A = A.join(P, on="id")
A["grp"] = np.where((A.dailyRank.between(4, 10)) & (A.mrank > 10), "A miss (real 4-10, model >10)",
           np.where((A.mrank <= 10) & (A.dailyRank > 10), "B false pick (model top 10, real >10)",
           np.where((A.dailyRank.between(4, 10)) & (A.mrank <= 10), "H hit (real 4-10, model top 10)", None)))
cols = list(P.columns) + ["th_n_pre"]
md = ["# Top 5 / top 10 anatomy, arm 2 (214 days Apr-Oct 2026)", "", f"Launches: misses {int((A.grp.str.startswith('A')).sum())}, false picks {int((A.grp.str.startswith('B')).sum())}, hits {int((A.grp.str.startswith('H')).sum())}.", "",
      "Mean per-input points (readable v2, log-vote scale) and th_n_pre by group; last columns: miss - hit and false pick - hit.", "",
      "| input | A miss | B false pick | H hit | A - H | B - H |", "|---|---|---|---|---|---|"]
G = A.dropna(subset=["grp"]).groupby("grp")[cols].mean()
ga, gb, gh = [g for g in G.index if g.startswith("A")][0], [g for g in G.index if g.startswith("B")][0], [g for g in G.index if g.startswith("H")][0]
for c in sorted(cols, key=lambda c: -abs(G.loc[ga, c] - G.loc[gh, c])):
    md.append(f"| {c} | {G.loc[ga, c]:.3f} | {G.loc[gb, c]:.3f} | {G.loc[gh, c]:.3f} | {G.loc[ga, c] - G.loc[gh, c]:+.3f} | {G.loc[gb, c] - G.loc[gh, c]:+.3f} |")
# where do misses sit in the model ranking
mr = A[A.grp.str.startswith("A", na=False)].mrank
md += ["", f"Model rank of misses: 11-15 {np.mean(mr <= 15):.0%}, 16-20 {np.mean((mr > 15) & (mr <= 20)):.0%}, >20 {np.mean(mr > 20):.0%} (median {mr.median():.0f})."]
# oracle headroom
def hits(o, t, k): return len(set(o[:k]) & set(t[:k])) / k * 100
base10, or10, base5, or5 = [], [], [], []
for d, g in A.groupby("day"):
    t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values("mrank").id.tolist()
    base10.append(hits(o, t, 10)); base5.append(hits(o, t, 5))
    top10, nxt = o[:10], o[10:15]; true10 = set(t[:10])
    ins = [x for x in nxt if x in true10]; outs = [x for x in top10[5:] if x not in true10][::-1]
    o2 = list(top10)
    for i_, x in zip(ins, outs): o2[o2.index(x)] = i_
    or10.append(hits(o2, t, 10))
    top5, nxt5 = o[:5], o[5:8]; true5 = set(t[:5]); ins5 = [x for x in nxt5 if x in true5]; outs5 = [x for x in top5[3:] if x not in true5][::-1]
    o3 = list(top5)
    for i_, x in zip(ins5, outs5): o3[o3.index(x)] = i_
    or5.append(hits(o3 + o[5:], t, 5))
md += ["", "## Oracle headroom", "", f"- Top 10: model {np.mean(base10):.1f}; if every true top-10 launch the model had at 11-15 swapped in for a false pick at 6-10: {np.mean(or10):.1f} (+{np.mean(or10) - np.mean(base10):.1f}).",
       f"- Top 5: model {np.mean(base5):.1f}; swapping true top-5 launches at model 6-8 in for false picks at 4-5: {np.mean(or5):.1f} (+{np.mean(or5) - np.mean(base5):.1f})."]
open(f"{R}/topk_anatomy.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))
