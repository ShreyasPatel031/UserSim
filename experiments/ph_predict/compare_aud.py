"""Backtest Mar–Oct: current model vs + predicted audience (aud_), same folds, same scoring."""
import numpy as np, pandas as pd
import features as F, model as M, run as RN

df = RN.load_llm(F.build()); df = df[~df.known]
parts = []
import sys
MONTHS = sys.argv[1:] or ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
for m, tr, te in RN.folds(df, MONTHS):
    tr, te = M.add_fold_feats(tr, te); te = te.copy()
    te["base"] = M.fit_predict(tr, te, M.SOURCES)[0]
    te["aud"] = M.fit_predict(tr, te, M.SOURCES + ["aud"])[0]
    te["aud2"] = M.fit_predict(tr, te, M.SOURCES + ["aud2"])[0]
    te["base_wk"] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
    te["base_mo"] = M.fit_list_clf(tr, te, "mon", "monthlyRank", 20)
    src = M.SOURCES; M.SOURCES = src + ["aud"]
    te["aud_wk"] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
    te["aud_mo"] = M.fit_list_clf(tr, te, "mon", "monthlyRank", 20)
    M.SOURCES = src
    parts.append(te); print(m, flush=True)
te = pd.concat(parts)
rows = []
for name, d, w, mo in (("Current model", "base", "base_wk", "base_mo"), ("+ predicted audience (step 1)", "aud", "aud_wk", "aud_mo"),
                       ("+ audience with person snapshots (step 2)", "aud2", "aud_wk", "aud_mo")):
    rd, rw, rm = M.evaluate(te, d, with_ci=True), M.evaluate(te, w), M.evaluate(te, mo)
    rows.append({"model": name, "day@3": rd["day@3"], "day@5": rd["day@5"], "day@10": rd["day@10"],
                 "day@5 CI": f"{100*rd['day@5_ci'][0]:.0f}–{100*rd['day@5_ci'][1]:.0f}",
                 "week@3": rw["week@3"], "week@5": rw["week@5"], "week@10": rw["week@10"],
                 "month@3": rm["month@3"], "month@5": rm["month@5"], "month@10": rm["month@10"], "rho": rd["spearman_day"]})
out = pd.DataFrame(rows)
for c in out.columns:
    if out[c].dtype == float and c != "rho": out[c] = (100 * out[c]).round().astype(int)
out.to_csv("results/compare_aud_%s.csv" % ("_".join(MONTHS) if len(MONTHS) < 3 else "mar_oct"), index=False)
print(out.to_string(index=False))
