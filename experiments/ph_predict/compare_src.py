"""Backtest: current model vs current model + one or more new sources (by feature prefix), same folds and scoring.
usage: python compare_src.py rec [aud ...] [--months 2026-09 2026-10]"""
import sys
import pandas as pd
import features as F, model as M, run as RN

args = sys.argv[1:]
months = args[args.index("--months") + 1:] if "--months" in args else ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
new = [a for a in (args[:args.index("--months")] if "--months" in args else args)]
df = RN.load_llm(F.build()); df = df[~df.known]
variants = {"Current model": M.SOURCES, **{f"+ {s}": M.SOURCES + [s] for s in new}}
if len(new) > 1:
    variants["+ " + " + ".join(new)] = M.SOURCES + new
parts = []
for m, tr, te in RN.folds(df, months):
    tr, te = M.add_fold_feats(tr, te); te = te.copy()
    for name, src in variants.items():
        te["d|" + name] = M.fit_predict(tr, te, src)[0]
        keep = M.SOURCES; M.SOURCES = src
        te["w|" + name] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
        te["m|" + name] = M.fit_list_clf(tr, te, "mon", "monthlyRank", 20)
        M.SOURCES = keep
    parts.append(te); print(m, flush=True)
te = pd.concat(parts)
rows = []
for name in variants:
    d, w, mo = M.evaluate(te, "d|" + name, with_ci=True), M.evaluate(te, "w|" + name), M.evaluate(te, "m|" + name)
    rows.append({"model": name, **{k: round(100 * d[k]) for k in ("day@3", "day@5", "day@10")},
                 "day@5 CI": f"{100*d['day@5_ci'][0]:.0f}–{100*d['day@5_ci'][1]:.0f}",
                 **{k: round(100 * w[k]) for k in ("week@3", "week@5", "week@10")},
                 **{k: round(100 * mo[k]) for k in ("month@3", "month@5", "month@10")}, "rho": round(d["spearman_day"], 3)})
out = pd.DataFrame(rows)
out.to_csv(f"results/compare_{'_'.join(new)}.csv", index=False)
print(out.to_string(index=False))
