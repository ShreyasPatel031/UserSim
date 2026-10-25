"""Do the new sources improve the lists? September–October, two folds (train Sep -> test Oct, train Oct -> test Sep).

  A  current model's prediction alone
  B  A + new pre-launch features (X posts/followers, LinkedIn company, competitor following, pre-launch commenters)
  C  B + launch-day audience features (who commented: count, reach, segments) — upper bound for a mid-day forecast
Each is a small LightGBM on top of the current model's prediction (so it can only add to it), target = log votes.
Scored with the same recall@k as the main backtest (daily/weekly lists; weekly only on full weeks)."""
import numpy as np, pandas as pd, lightgbm as lgb
import model as M
import signal_test as S

df, tags = S.features()
base = pd.read_csv("results/predictions.csv", usecols=["id", "votes", "weeklyRank", "monthlyRank", "week", "mon"])
base["id"] = base.id.astype(str)
df = df.merge(base, on="id", how="left")
df["logv"] = np.log1p(df.votes)
df["mon"] = df.day.str[:7]
pre = [f for f, t in tags.items() if t == "pre" and f in df]
post = [f for f, t in tags.items() if t == "post" and f in df]
sets = {"A: current model": ["pred"], "B: + new pre-launch data": ["pred"] + pre, "C: + launch-day audience (upper bound)": ["pred"] + pre + post}
out = {k: [] for k in sets}
for tr_m, te_m in (("2026-09", "2026-10"), ("2026-10", "2026-09")):
    tr, te = df[df.mon == tr_m], df[df.mon == te_m].copy()
    for name, cols in sets.items():
        if cols == ["pred"]:
            te["score"] = te.pred
        else:
            m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=7, min_child_samples=20,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.7, verbose=-1, random_state=0)
            te["score"] = m.fit(tr[cols], tr.logv).predict(te[cols])
        out[name].append(te[["id", "day", "week", "mon", "dailyRank", "weeklyRank", "monthlyRank", "votes", "score"]].copy())
rows = []
for name, parts in out.items():
    t = pd.concat(parts)
    r = M.evaluate(t, "score", with_ci=True)
    rows.append({"variant": name, **{k: round(100 * r[k]) for k in ("day@3", "day@5", "day@10", "week@3", "week@5", "week@10")},
                 "day@5 95% CI": f"{100 * r['day@5_ci'][0]:.0f}–{100 * r['day@5_ci'][1]:.0f}", "rho_day": round(r["spearman_day"], 3)})
res = pd.DataFrame(rows)
res.to_csv("results/batch_eval.csv", index=False)
print(res.to_string(index=False))
