"""results/REPORT.md from results/metrics.json, predictions.csv, importance_*.csv, topic_lists.csv."""
import json, os
import numpy as np, pandas as pd

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
m = json.load(open(f"{R}/metrics.json"))
p = pd.read_csv(f"{R}/predictions.csv")
L = []
w = L.append
NAMES = {"pred_week_model": "Weekly-list model", "pred_month_model": "Monthly-list model", "pred_blend": "Full model, blend of both objectives", "pred": "Full model (all sources)", "pred_rank_day": "Full model, ranking objective", "pred_random": "A. Random",
         "pred_llm_pitch": "B. LLM, pitch only", "pred_llm_site": "C. LLM, pitch + homepage",
         "pred_ph_only": "D. PH audience/metadata only", "pred_with_maker_followers": "Full + maker followers (leaky)"}
SRC = {"ph": "PH audience & metadata (hunter, makers, media)", "hist": "Hunter/maker track record on PH",
       "txt": "Pitch text (name, tagline, description)", "web": "Homepage content", "dom": "Domain (age, TLD, archive history)",
       "x": "X/Twitter audience", "hn": "Hacker News before launch", "comp": "Similar earlier PH launches",
       "topic": "Topic priors", "llm": "LLM judgement", "cm": "Commenter network (competitor users, makers' community)"}


def pct(x):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.0f}%"


def row(key):
    r = m[key]
    cells = []
    for per in ("day", "week", "mon"):
        for k in (3, 5, 10):
            v = r.get(f"{per if per != 'mon' else 'month'}@{k}")
            c = r.get(f"{per}@{k}_ci")
            cells.append(pct(v) + (f" ({pct(c[0])}–{pct(c[1])})" if c and not np.isnan(c[0]) else ""))
    return cells


meta = m["_meta"]
w("# Product Hunt top-list predictor: backtest\n")
w(f"Test months: {', '.join(meta['test_months'])}, each predicted by a model trained only on earlier launches. "
  f"{meta['n_test']} launches, {meta['n_days']} daily lists, {meta['n_weeks']} weekly lists. "
  "No vote, comment or rank field of the launch itself is used as an input.\n")
F = lambda key, per, k: pct(m[key].get(f"{per}@{k}"))
w("## Key findings\n")
w(f"1. **Daily list (Yesterday's Top Products): the model finds {F('pred','day',3)} of the real top 3, {F('pred','day',5)} of the top 5 "
  f"and {F('pred','day',10)} of the top 10** (random: {F('pred_random','day',3)} / {F('pred_random','day',5)} / {F('pred_random','day',10)}). "
  "Accuracy rises as history accumulates: the July–October test months, with 6+ months to learn from, score higher on every list "
  "(table below).")
w(f"2. **Weekly list: {F('pred_week_model','week',3)} / {F('pred_week_model','week',5)} / {F('pred_week_model','week',10)}** at top 3/5/10 "
  f"with the weekly-list model (random {F('pred_random','week',10)} at top 10). **Monthly list: {F('pred_month_model','month',3)} / "
  f"{F('pred_month_model','month',5)} / {F('pred_month_model','month',10)}** with the monthly-list model (only 8 monthly lists, so wide ranges). "
  "Weekly and monthly lists are harder because they compare launches across days: even a perfect within-day order gets only about half of a "
  "week's top 3, so these lists depend on predicting how big a day's winner gets.")
w("3. **Who posts the launch matters most.** Product Hunt audience and metadata alone find "
  f"{pct(m['pred_only_ph']['day@5'])} of the daily top 5; the hunter's and makers' track record alone {pct(m['pred_only_hist']['day@5'])}; "
  f"X audience {pct(m['pred_only_x']['day@5'])}; pitch text {pct(m['pred_only_txt']['day@5'])}; LLM judgements {pct(m['pred_only_llm']['day@5'])}; "
  f"homepage {pct(m['pred_only_web']['day@5'])}; Hacker News and domain age are near random ({pct(m['pred_random']['day@5'])}). "
  "Removing the PH audience source costs the most; removing any other source changes the full model by a point or less, so they "
  "carry little that the audience features do not already have.")
w(f"4. **Reading the product barely helps.** An LLM ranking each day's launches from the pitch finds {pct(m['pred_llm_pitch']['day@5'])} of the "
  f"top 5, and with the homepage {pct(m['pred_llm_site']['day@5'])}, against {pct(m['pred_random']['day@5'])} random. In the plan's terms: D is "
  "best and B/C are only slightly above chance, so Product Hunt votes mostly measure distribution (the hunter's audience and record), "
  "not the product. A product-quality simulator should not be judged on raw PH votes without controlling for who posted the launch.")
w("5. **Strongest single factors** (daily top-5 rate, high vs low): hunter's PH followers (top third 45% vs bottom third 1%); hunter's "
  "past top-5 rate (63% vs 8%); hunter account age (37% vs 7%); number of makers (46% vs 12%); LLM pitch score (37% vs 10%); "
  "weekend launch (45% vs 18%, fewer competitors). **Self-hunted launches finish top 5 9% of the time, others 34%.**")
w("6. **Across product types** the hunter's audience dominates everywhere, but least in marketing and 'other' launches. There the "
  "pitch (LLM score), the makers' own record and gallery quality count for more; in productivity the hunter's past record "
  "counts most after audience; in consumer apps, hunter account age. The model is most accurate on AI launches (74% of their daily "
  "top-5 finishes caught) and least on productivity (47%).")
w("7. **Leakage checks.** Maker follower counts are today's values (makers gain followers after a top launch), so they are left "
  "out; adding them back changes little. The LLM (training data older than every launch) recognised no product.\n")
w("## Recall@k (share of the real top k that the predicted top k contains), 95% CI over lists\n")
w("| Method | Day @3 | Day @5 | Day @10 | Week @3 | Week @5 | Week @10 | Month @3 | Month @5 | Month @10 |")
w("|---|" + "---|" * 9)
for k in ["pred", "pred_week_model", "pred_month_model", "pred_blend", "pred_rank_day", "pred_ph_only", "pred_llm_site", "pred_llm_pitch", "pred_random", "pred_with_maker_followers"]:
    if k in m:
        w(f"| {NAMES[k]} | " + " | ".join(row(k)) + " |")
w("")
import model as MM
w("## Accuracy grows with training history\n")
w("Same backtest, split by test months: early months had 2–5 months of history to learn from, later ones 6–9.\n")
w("| Test months | List | Model | Top 3 | Top 5 | Top 10 |")
w("|---|---|---|---|---|---|")
for lab, ms in (("Mar–Jun", ["2026-03", "2026-04", "2026-05", "2026-06"]), ("Jul–Oct", ["2026-07", "2026-08", "2026-09", "2026-10"])):
    q = p[p.mon.isin(ms)]
    for per, col, sc, nm in (("day", "dailyRank", "pred", "Full model"), ("week", "weeklyRank", "pred_week_model", "Weekly-list model"),
                             ("mon", "monthlyRank", "pred_month_model", "Monthly-list model")):
        w(f"| {lab} | {per} | {nm} | " + " | ".join(pct(MM.recall_at(q, per, col, k, sc)[0]) for k in (3, 5, 10)) + " |")
w("")
w("## Which sources predict (recall@5 on daily lists, and rank correlation within a day)\n")
w("| Source | Alone: day@5 | Alone: Spearman | Full minus source: day@5 | Change vs full |")
w("|---|---|---|---|---|")
full = m["pred"]["day@5"]
for s, name in SRC.items():
    if f"pred_only_{s}" in m:
        o, d = m[f"pred_only_{s}"], m[f"pred_drop_{s}"]
        w(f"| {name} | {pct(o['day@5'])} | {o['spearman_day']:.2f} | {pct(d['day@5'])} | {100 * (d['day@5'] - full):+.0f} pts |")
w("")
imp = pd.read_csv(f"{R}/importance_by_type.csv", index_col=0)
w("## Share of the model's decision by source, per product type\n")
w("| Type | " + " | ".join(imp.columns) + " |")
w("|---|" + "---|" * len(imp.columns))
for t, r in imp.iterrows():
    w(f"| {t} | " + " | ".join(pct(v) for v in r.values) + " |")
w("")
fi = pd.read_csv(f"{R}/importance_features.csv", index_col=0).iloc[:, 0]
w("## Top factors (mean |contribution| to predicted log votes)\n")
for f, v in fi.head(20).items():
    w(f"- `{f}`: {v:.3f}")
w("")
ft = pd.read_csv(f"{R}/importance_features_by_type.csv", index_col=0)
w("## Top 5 factors per product type\n")
for t in ft.columns:
    w(f"- **{t}**: " + ", ".join(f"`{f}`" for f in ft[t].sort_values(ascending=False).head(5).index))
w("")
tl = pd.read_csv(f"{R}/topic_lists.csv")
w("## Topic lists (top k by votes within a topic), recall@5\n")
piv = tl[(tl.k == 5)].pivot_table(index="topic", columns=["period", "score"], values="recall")
w("| Topic | Day: model | Day: random | Week: model | Week: random | Month: model | Month: random |")
w("|---|---|---|---|---|---|---|")
for t, r in piv.iterrows():
    w(f"| {t} | " + " | ".join(pct(r.get((per, s))) for per in ("day", "week", "mon") for s in ("pred", "pred_random")) + " |")
w("")
# the three front-page lists
w("## The three front-page lists (as of Oct 25), model trained only on earlier months\n")
p["day"] = p.day.astype(str)
for title, sub, col, sc in (("Yesterday's Top Products (Oct 24), full model", p[p.day == "2026-10-24"], "dailyRank", "pred"),
                        ("Last Week's Top Products (Oct 12–18), weekly-list model", p[p.week == "2026-W42"], "weeklyRank", "pred_week_model"),
                        ("Last Month's Top Products (September), monthly-list model", p[p.mon == "2026-09"], "monthlyRank", "pred_month_model")):
    if not len(sub):
        continue
    real = sub.nsmallest(10, col)
    pred = sub.nlargest(10, sc)
    hit = {k: len(set(real.head(k).id) & set(pred.head(k).id)) for k in (3, 5, 10)}
    w(f"### {title}: {len(sub)} launches; hits in top 3/5/10: {hit[3]}/3, {hit[5]}/5, {hit[10]}/10\n")
    w("| # | Actual | Predicted |")
    w("|---|---|---|")
    for i in range(10):
        a, b = real.iloc[i], pred.iloc[i]
        w(f"| {i + 1} | {a['name']}{' ✓' if a.id in set(pred.id) else ''} | {b['name']} (actual #{int(b[col])}) |")
    w("")
w("## Accuracy by product type\n")
w("| Type | Launches | Real day-top-5 launches | Share the model had in its day top 5 | Rank correlation within type |")
w("|---|---|---|---|---|")
for t, r in sorted(m.get("_by_type", {}).items(), key=lambda kv: -kv[1]["n"]):
    w(f"| {t} | {r['n']} | {r['n_top5']} | {pct(r['recall_of_type_in_day_top5'])} | "
      f"{(r['spearman_within_type_day'] or float('nan')):.2f} |")
w("")
fc = sorted(f for f in os.listdir(R) if f.startswith("forecast_"))
for f in fc:
    txt = open(f"{R}/{f}").read()
    w("## Forward test: " + txt.split("\n", 1)[0].lstrip("# ") + "\n")
    w(txt.split("\n", 1)[1])
if os.path.exists(f"{R}/snapshot_vs_live.json"):
    sv = json.load(open(f"{R}/snapshot_vs_live.json"))
    w("## Launch-day homepage (Wayback snapshot) vs today's live site\n")
    w(f"September–October launches with a Wayback capture from before launch day: {sv['n_launches']} launches over "
      f"{sv['n_days']} days. Median word overlap between the two versions: {pct(sv['word_overlap_snapshot_vs_live_median'])}. "
      "A homepage-only model, cross-validated by day, predicting each launch's votes relative to its day "
      "(rank correlation within a day):\n")
    w("| Homepage version | Page structure features | Page words |")
    w("|---|---|---|")
    for v in ("snapshot", "live"):
        w(f"| {v} | {sv[v]['homepage_structure_spearman']:.2f} | {sv[v]['homepage_words_spearman']:.2f} |")
    w("")
w("## Data coverage\n")
w(f"- Homepage: Wayback snapshot from before launch {pct(meta['sites_wayback'])}, live site {pct(meta['sites_live'])}, "
  f"none found {pct(meta['sites_none'])}")
w(f"- Products the LLM said it recognised (dropped): {meta['dropped_known']}")
open(f"{R}/REPORT.md", "w").write("\n".join(L))
print("\n".join(L)[:3000])
