"""Forecast the weekly list that the front page shows next Monday ("Last Week's Top Products" for ISO week W).
Models are trained only on launches before the week starts; the week's launches (including today's, whose
results are not in) are scored without their votes."""
import json, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

week = sys.argv[1]  # e.g. 2026-W43
df = RN.load_llm(F.build(include_today=True))
df = df[~df.known]
start = df[df.week == week].day.min()
tr, te = df[(df.day < start) & ~df.is_today], df[df.week == week]
tr, te = M.add_fold_feats(tr, te)
te = te.copy()
te["pred"] = M.fit_predict(tr, te, M.SOURCES)[0]
te["pred_week_model"] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
te = te.sort_values("pred_week_model", ascending=False)
done = te[~te.is_today]
L = [f"# Forecast: Last Week's Top Products for {week} (trained on launches before {start}; {len(te)} launches, "
     f"{int(te.is_today.sum())} of them today with results not in)\n",
     "| Predicted | Product | Day | Hunter PH followers | Real weekly rank so far |", "|---|---|---|---|---|"]
for i, (_, r) in enumerate(te.head(15).iterrows()):
    real = "–" if r.is_today or pd.isna(r.weeklyRank) else int(r.weeklyRank)
    L.append(f"| {i + 1} | {r['name']} | {r.day} | {int(np.expm1(r.ph_hunter_followers))} | {real} |")
hits = {k: len(set(done.nsmallest(k, "weeklyRank").id) & set(te.head(k).id)) for k in (3, 5, 10)}
L.append(f"\nAgainst the ranks so far (Oct 19–24 final, Oct 25 still open): top 3/5/10 hits {hits[3]}/3, {hits[5]}/5, {hits[10]}/10.")
open(f"{RN.OUT}/forecast_{week}.md", "w").write("\n".join(L) + "\n")
json.dump([{"rank": i + 1, "product": r["name"], "day": r.day, "hunter_followers": int(np.expm1(r.ph_hunter_followers)),
            "real_rank_so_far": None if r.is_today or pd.isna(r.weeklyRank) else int(r.weeklyRank), "id": r.id}
           for i, (_, r) in enumerate(te.head(15).iterrows())], open(f"{RN.OUT}/dash/forecast_week.json", "w"))
print("\n".join(L))
