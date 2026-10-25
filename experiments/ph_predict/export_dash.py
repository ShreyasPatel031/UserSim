"""Write the dashboard's data files (results/dash/*.json) from the backtest outputs."""
import json, os
import numpy as np, pandas as pd

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
O = f"{R}/dash"; os.makedirs(O, exist_ok=True)
m = json.load(open(f"{R}/metrics.json"))
NAMES = {"pred": "Full model", "pred_week_model": "Weekly-list model", "pred_month_model": "Monthly-list model", "pred_blend": "Full model (blend)", "pred_rank_day": "Full model (ranking)",
         "pred_ph_only": "D · PH audience only", "pred_llm_site": "C · LLM reads homepage",
         "pred_llm_pitch": "B · LLM reads pitch", "pred_random": "A · Random",
         "pred_with_maker_followers": "Full + maker followers (leaky)"}
rows = []
for key, name in NAMES.items():
    if key not in m:
        continue
    r = m[key]
    for per, lab in (("day", "Daily"), ("week", "Weekly"), ("mon", "Monthly")):
        for k in (3, 5, 10):
            v = r.get(f"{'month' if per == 'mon' else per}@{k}")
            c = r.get(f"{per}@{k}_ci") or [None, None]
            P = lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else int(round(100 * x))
            rows.append({"id": f"{key}|{lab}|{k}", "method": name, "list": lab, "k": k, "recall": P(v),
                         "lo": P(c[0]), "hi": P(c[1]), "n_lists": r.get(f"{per}@{k}_n")})
json.dump(rows, open(f"{O}/recall.json", "w"))
SRC = {"ph": "PH audience & metadata", "hist": "Hunter & maker track record", "txt": "Pitch text",
       "web": "Homepage content", "dom": "Domain & archive history", "x": "X / Twitter audience",
       "hn": "Hacker News before launch", "comp": "Similar earlier launches", "topic": "Topic priors",
       "llm": "LLM judgements"}
full = m["pred"]
sp = lambda x: None if x is None or np.isnan(x) else round(float(x), 2)
src = [{"source": n, "alone_day5": int(round(100 * m[f"pred_only_{s}"]["day@5"])),
        "alone_spearman": sp(m[f"pred_only_{s}"]["spearman_day"]),
        "drop_day5_change": int(round(100 * (m[f"pred_drop_{s}"]["day@5"] - full["day@5"]))),
        "drop_spearman_change": sp(m[f"pred_drop_{s}"]["spearman_day"] - full["spearman_day"])}
       for s, n in SRC.items() if f"pred_only_{s}" in m]
src.sort(key=lambda r: -r["alone_day5"])
json.dump(src, open(f"{O}/sources.json", "w"))
imp = pd.read_csv(f"{R}/importance_by_type.csv", index_col=0)
json.dump([{"type": t, **{SRC.get(s, s): int(round(100 * float(v))) for s, v in r.items()}} for t, r in imp.iterrows()],
          open(f"{O}/importance_by_type.json", "w"))
fa = pd.read_csv(f"{R}/factors.csv")
types = [c for c in ("ai", "dev", "productivity", "design", "marketing", "consumer", "other") if c in fa]
json.dump([{"factor": r.factor, "high": int(round(100 * r.all_hi)), "low": int(round(100 * r.all_lo)),
            "n": int(r.all_n), **{t: (None if pd.isna(r[t]) or np.isinf(r[t]) else round(float(r[t]), 1)) for t in types}}
           for _, r in fa.iterrows() if not pd.isna(r.all_hi) and not pd.isna(r.all_lo)], open(f"{O}/factors.json", "w"))
bt = m.get("_by_type", {})
json.dump(sorted([{"type": t, "launches": r["n"], "real_top5": r["n_top5"],
                   "caught": None if r["recall_of_type_in_day_top5"] is None else int(round(100 * r["recall_of_type_in_day_top5"])),
                   "rank_corr": sp(r["spearman_within_type_day"] if r["spearman_within_type_day"] is not None else np.nan)}
                  for t, r in bt.items()], key=lambda r: -r["launches"]),
          open(f"{O}/by_type.json", "w"))
tl = pd.read_csv(f"{R}/topic_lists.csv")
tl = tl[tl.score.isin(["pred", "pred_random"])]
tl = tl[tl.k == 5]
pv = tl.pivot_table(index="topic", columns=["period", "score"], values="recall")
cnt = tl[tl.score == "pred"].pivot_table(index="topic", columns="period", values="n_lists")
P2 = lambda x: None if pd.isna(x) else int(round(100 * x))
json.dump(sorted([{"topic": t, "day_model": P2(r.get(("day", "pred"))), "day_random": P2(r.get(("day", "pred_random"))),
            "week_model": P2(r.get(("week", "pred"))), "week_random": P2(r.get(("week", "pred_random"))),
            "month_model": P2(r.get(("mon", "pred"))), "month_random": P2(r.get(("mon", "pred_random"))),
            "days": int(cnt.loc[t, "day"]) if "day" in cnt else None} for t, r in pv.iterrows()],
           key=lambda r: -(r["days"] or 0)), open(f"{O}/topic_lists.json", "w"))
p = pd.read_csv(f"{R}/predictions.csv")
p["day"] = p.day.astype(str)
named = []
for lab, sub, col in (("Yesterday (Oct 24)", p[p.day == "2026-10-24"], "dailyRank"),
                      ("Last week (Oct 12–18)", p[p.week == "2026-W42"], "weeklyRank"),
                      ("Last month (September)", p[p.mon == "2026-09"], "monthlyRank")):
    real, pred = sub.nsmallest(10, col), sub.nlargest(10, "pred")
    rset, pset = set(real.id), set(pred.id)
    for i in range(min(10, len(sub))):
        a, b = real.iloc[i], pred.iloc[i]
        named.append({"list": lab, "position": i + 1, "actual": a["name"], "actual_predicted": bool(a.id in pset),
                      "predicted": b["name"], "predicted_actual_rank": int(b[col]), "predicted_hit": bool(b.id in rset)})
json.dump(named, open(f"{O}/named_lists.json", "w"))
meta = m["_meta"]
json.dump([{"launches": meta["n_test"], "days": meta["n_days"], "weeks": meta["n_weeks"],
            "months": len(meta["test_months"]), "first_month": meta["test_months"][0], "last_month": meta["test_months"][-1],
            "site_found": int(round(100 * (1 - meta["sites_none"]))), "known_dropped": meta["dropped_known"]}],
          open(f"{O}/meta.json", "w"))
print(os.listdir(O))
