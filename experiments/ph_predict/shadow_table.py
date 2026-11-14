"""Score the rebuilt forward shadow lines, polluted vs fixed (orchestrator 17:34Z Nov 14). Counts only.
Input: <out>/{polluted,fixed}/shadow_{makerfix,h25,readable}/<d>.json from shadow_rebuild.py. Label: warehouse daily_rank, nights with
>= 10 ranked launches. 'published' = the model published that night (old full model = unfixed to Nov 12, clean_nosite Nov 13) from the same
rebuild; 'published (live)' = the scoreboard's published 00:05 row (what actually ran). Paired day bootstrap 10,000.
usage: python3 shadow_table.py <out dir> -> results/shadow_table_polluted_vs_fixed.md"""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
O = sys.argv[1]
LINES = {"old full model (unfixed)": ("shadow_makerfix", "pred_unfixed", 1), "makerfix": ("shadow_makerfix", "pred_makerfix", 1),
         "clean": ("shadow_makerfix", "pred_clean", 1), "clean_nosite": ("shadow_makerfix", "pred_clean_nosite", 1),
         "clean_avg": ("shadow_makerfix", "rank_clean_avg", -1), "h25": ("shadow_h25", "pred_clean_nosite_h25", 1),
         "arm 2 (h25llm)": ("shadow_h25", "pred_clean_nosite_h25llm", 1), "pure (2026 only)": ("shadow_h25", "pred_clean_nosite_pure", 1),
         "readable v2": ("shadow_readable", "pred_readable_v2", 1)}
Rk = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False); Rk["day"] = Rk.day.astype(str).str[:10]
truth = {d: g.sort_values("daily_rank").id.tolist() for d, g in Rk.groupby("day")}
def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
S = {}
for mode in ("polluted", "fixed"):
    for nm, (fd, col, sgn) in LINES.items():
        for f in glob.glob(f"{O}/{mode}/{fd}/*.json"):
            d = os.path.basename(f)[:10]; F = pd.DataFrame(json.load(open(f))["forecast"]); F["id"] = F.id.astype(str)
            if col not in F or d not in truth or len(truth[d]) < 10: continue
            o = F.assign(s=sgn * F[col].astype(float)).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            S[(mode, nm, d)] = hits(o, truth[d])
for mode in ("polluted", "fixed"):   # the published line, per night
    for d in sorted({k[2] for k in S if k[0] == mode}):
        k = (mode, "old full model (unfixed)" if d <= "2026-11-12" else "clean_nosite", d)
        if k in S: S[(mode, "published (that night's model)", d)] = S[k]
sb = json.load(open(f"{HERE}/results/web/scoreboard.json")); live = {r["day"]: [r["top3"], r["top5"], r["top10"]] for r in sb["rows"] if r["point"] == "0005" and r["method"] == "published"}
rng = np.random.default_rng(0)
def ci(x):
    b = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    return " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3))
names = list(LINES) + ["published (that night's model)"]
md = ["# Forward shadow lines rebuilt on fixed inputs (today-rows bug), Oct 26 - Nov 13", "",
      "As of each night (days <= d-2). polluted = all today/ files <= d plus features.py 981c5ded (what the shadows saw); fixed = today/<d> only plus 033d7bd7.",
      "Each script's own main(d) (shadow_rebuild.py). Nights with >= 10 ranked launches. Top 3 / 5 / 10; paired day bootstrap 10,000.", "",
      "| line | nights | polluted | fixed | fixed - polluted |", "|---|---|---|---|---|"]
for nm in names:
    dd = sorted(d for (m, n, d) in S if m == "fixed" and n == nm and ("polluted", nm, d) in S)
    if not dd: continue
    a = np.array([S[("polluted", nm, d)] for d in dd]); b = np.array([S[("fixed", nm, d)] for d in dd])
    md.append(f"| {nm} | {len(dd)} | {' / '.join(f'{v:.1f}' for v in a.mean(0))} | {' / '.join(f'{v:.1f}' for v in b.mean(0))} | {ci(b - a)} |")
md += ["", "## On the fixed table only, paired", "", "| comparison | nights | difference (top 3 / 5 / 10) |", "|---|---|---|"]
def pair(x, y, lab, ref=None):
    dd = sorted(d for (m, n, d) in S if m == "fixed" and n == x and (ref is not None and d in ref or ref is None and ("fixed", y, d) in S))
    if not dd: return
    a = np.array([S[("fixed", x, d)] for d in dd]); b = np.array([ref[d] for d in dd]) if ref is not None else np.array([S[("fixed", y, d)] for d in dd])
    md.append(f"| {lab} | {len(dd)} | {ci(a - b)} |")
pair("arm 2 (h25llm)", "clean_nosite", "arm 2 - clean_nosite"); pair("arm 2 (h25llm)", "old full model (unfixed)", "arm 2 - old full model")
pair("clean_nosite", "old full model (unfixed)", "clean_nosite - old full model")
for nm in LINES: pair(nm, "published (that night's model)", f"{nm} - published (fixed rebuild)")
for nm in LINES: pair(nm, None, f"{nm} (fixed) - published as it ran live", ref={d: v for d, v in live.items() if v[0] is not None})
open(f"{HERE}/results/shadow_table_polluted_vs_fixed.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))
