"""Why arm 2's #1 pick misses the final top 3, and a leak-free day-level "#1 is shaky" flag (orchestrator 23:09Z Nov 14).

PRE-REGISTERED (written before any 2026 test number was computed)
  Data   arm-2 orders: 2025 = pre-registered harness (arm3_vs_arm2_preds.parquet, arm2, 20 seeds, month-forward Mar-Dec 2025);
         2026 = published arm 2 (history_retrain_decomp_preds_arm2.parquet 'both', 5 seeds, Apr-Oct 2026, 184 days).
         Truth: 2026 truth_daily.json; 2025 the harness's stored dailyRank (truth_daily.json has no 2025). >= 10 ranked; unranked = miss.
         Features: pre-launch fields from history_retrain.build on the VM (shaky_feats.parquet), all dated before the launch day.
  Day features (pick #1 = p1, pick #2 = p2)
         margin    p1 score - p2 score;  margin_z = margin / sd of the day's scores
         ln        log number of launches that day
         hunter    p1 hunter's earlier launches (log1p hist_hunter_n), earlier top-5 share (hist_hunter_top5), p1 self-hunted
         first     p1 maker(s) have no earlier launches (hist_maker_n == 0)
         crowd     number of same-day launches sharing >= 1 topic with p1, and with p2
         weekday   weekend indicator
  Flag   logistic regression (standardised on 2025, C = 1) fitted on 2025 DISCORDANT days only (exactly one of p1, p2 finishes top 3),
         target = p2 finishes top 3 and p1 does not. Flag = predicted probability > 0.5. No threshold tuning.
  Action on flagged days: pick #2 becomes pick #1 (swap 1 <-> 2).
  Primary metric (one test on 2026): share of days the shown #1 finishes top 3, swap rule vs arm 2, paired, day bootstrap 95% (4000).
  Note: a 1 <-> 2 swap leaves the top-3/5/10 sets unchanged, so top-3 hits are identical by construction. Secondary (reported,
  not the decision): demote p1 to position 4 on flagged days (pick #4 enters the top 3), top-3 hits vs arm 2.
usage: python shaky1.py FEATS.parquet -> results/shaky1.{json,md}"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
F = pd.read_parquet(sys.argv[1]); F["id"] = F.id.astype(str); F = F.drop_duplicates("id", keep="last").set_index("id")
TOP = {i: set(t.split("|")) - {""} for i, t in F.topics_s.items()}
T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json"],
                              capture_output=True, text=True, check=True).stdout)["days"]
TR26 = {d: {str(i): r for i, r in v["ranks"].items()} for d, v in T.items() if len(v.get("ranks", {})) >= 10}
H = pd.read_parquet(R("arm3_vs_arm2_preds.parquet")); H["id"] = H.id.astype(str)
H25 = H[H.year == "2025"]
TR25 = {d: {i: r for i, r in zip(g.id, g.dailyRank) if pd.notna(r)} for d, g in H25.groupby("day")}
TR25 = {d: v for d, v in TR25.items() if len(v) >= 10}
A = pd.read_parquet(R("history_retrain_decomp_preds_arm2.parquet")); A["id"] = A.id.astype(str)
FEATS = ["margin", "margin_z", "ln", "h_n", "h_top5", "self_hunted", "first", "crowd1", "crowd2", "weekend"]
# correction (maker audit, Nov 14 23:40Z): "first" and "self_hunted" need named makers, which stored rows reveal after close; DROP removes them
FEATS = [c for c in FEATS if c not in os.environ.get("DROP", "").split(",")]
OUTN = os.environ.get("OUTN", "shaky1")


def f(i, c, default=0.0):
    try:
        v = F.at[i, c]; return float(v) if pd.notna(v) else default
    except KeyError:
        return default


def days(P, col, truth):
    rows = []
    for d, g in P.groupby("day"):
        t = truth.get(d)
        if t is None or len(g) < 4: continue
        g = g.sort_values([col, "id"], ascending=[False, True]); o = g.id.tolist(); s = g[col].values
        p1, p2 = o[0], o[1]
        crowd = lambda p: sum(1 for q in o if q != p and TOP.get(q, set()) & TOP.get(p, set()))
        rows.append({"day": d, "order": o, "hit1": int(t.get(p1, 999) <= 3), "hit2": int(t.get(p2, 999) <= 3),
                     "top3": len(set(o[:3]) & {i for i, r in t.items() if r <= 3}) / 3,
                     "top3_demote": len(set([o[1], o[2], o[3]]) & {i for i, r in t.items() if r <= 3}) / 3,
                     "margin": s[0] - s[1], "margin_z": (s[0] - s[1]) / (s.std() + 1e-9), "ln": np.log(len(o)),
                     "h_n": np.log1p(f(p1, "hist_hunter_n")), "h_top5": f(p1, "hist_hunter_top5"), "self_hunted": f(p1, "ph_self_hunted"),
                     "first": float(f(p1, "hist_maker_n", 0.0) == 0), "crowd1": crowd(p1), "crowd2": crowd(p2),
                     "weekend": float(pd.Timestamp(d).dayofweek >= 5)})
    return pd.DataFrame(rows)


def boot(x, B=4000, seed=0):
    rng = np.random.default_rng(seed); n = len(x); bs = [x[rng.integers(0, n, n)].mean() for _ in range(B)]
    return [round(100 * float(np.mean(x)), 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)]


D25 = days(H25, "arm2", TR25); D26 = days(A, "both", TR26)
desc = {}
for yr, D in (("2025", D25), ("2026", D26)):
    desc[yr] = {"n_days": len(D), "p1_top3_rate": round(100 * D.hit1.mean(), 1),
                "miss_vs_hit_means": {c: [round(float(D[D.hit1 == 0][c].mean()), 3), round(float(D[D.hit1 == 1][c].mean()), 3)] for c in FEATS}}
# flag fitted on 2025 discordant days only
disc = D25[D25.hit1 != D25.hit2]
mu, sd = D25[FEATS].mean(), D25[FEATS].std().replace(0, 1)
clf = LogisticRegression(C=1.0, max_iter=2000).fit((disc[FEATS] - mu) / sd, (disc.hit2 > disc.hit1).astype(int))
coef = dict(zip(FEATS, np.round(clf.coef_[0], 3)))
res = {"method": __doc__, "descriptive": desc, "flag": {"fit_days_2025_discordant": len(disc), "coef_standardised": coef,
                                                         "intercept": round(float(clf.intercept_[0]), 3)}}
for yr, D in (("2025 (in-sample, fitted here)", D25), ("2026 TEST", D26)):
    fl = clf.predict_proba((D[FEATS] - mu) / sd)[:, 1] > 0.5
    shown = np.where(fl, D.hit2, D.hit1).astype(float); base = D.hit1.values.astype(float)
    dem = np.where(fl, D.top3_demote, D.top3).astype(float)
    res[yr] = {"n_days": len(D), "flagged_days": int(fl.sum()),
               "flagged_p1_hit": round(100 * D.hit1[fl].mean(), 1) if fl.any() else None, "flagged_p2_hit": round(100 * D.hit2[fl].mean(), 1) if fl.any() else None,
               "p1_top3_arm2": boot(base), "p1_top3_swap": boot(shown), "swap_minus_arm2": boot(shown - base),
               "top3_hits_arm2": boot(D.top3.values), "top3_hits_demote_secondary": boot(dem), "demote_minus_arm2": boot(dem - D.top3.values)}
    print(yr, json.dumps(res[yr]))
print("coef", coef); print(json.dumps(desc))
json.dump(res, open(R(f"{OUTN}.json"), "w"), indent=1, default=str)
