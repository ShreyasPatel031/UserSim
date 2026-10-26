"""Among close calls (pairs of a day's contenders whose model scores are near each other), what decides who wins?
For each input: how often 'the launch with more of it' wins the pair (AUC; 0.5 = no help), plus a model on all input
differences (5-fold by day). Uses the all-sources model scores (results/pred_all_sources.csv).
Output: results/tiebreak.csv"""
import pickle
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

df = pickle.load(open("data/build_cache.pkl", "rb"))
P = pd.read_csv("results/pred_all_sources.csv"); P["id"] = P.id.astype(str)
df = df.merge(P, on="id")
df["prank"] = df.groupby("day").pred.rank(ascending=False, method="first")
num = [c for c in df.columns if df[c].dtype.kind in "fi" and c.split("_")[0] in
       ("ph", "hist", "web", "dom", "x", "hn", "comp", "topic", "llm", "cm", "aud", "aud2", "rec", "fol", "busy", "seg", "promo", "txt")]
c = df[df.prank <= 10]
rows = []
for day, g in c.groupby("day"):
    g = g.sort_values("prank")
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            a, b = g.iloc[i], g.iloc[j]
            if min(a.dailyRank, b.dailyRank) <= 5 and abs(a.pred - b.pred) < 0.35:  # close call involving the top 5
                rows.append((day, a.name, b.name, int(b.dailyRank < a.dailyRank)))
pr = pd.DataFrame(rows, columns=["day", "a", "b", "b_wins"])
X = pd.DataFrame(df.loc[pr.b, num].values - df.loc[pr.a, num].values, columns=num)
y = pr.b_wins.values
print("close pairs", len(pr), "lower-ranked wins", y.mean().round(2))
res = []
for f in num:
    x = X[f]
    m = x.notna() & (x != 0)
    if m.sum() > 100:
        res.append({"input": f, "auc": roc_auc_score(y[m], x[m]), "pairs": int(m.sum())})
R = pd.DataFrame(res); R["strength"] = (R.auc - 0.5).abs(); R = R.sort_values("strength", ascending=False)
oof = np.zeros(len(y))
for trn, tst in GroupKFold(5).split(X, y, pr.day):
    oof[tst] = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=30, verbose=-1).fit(
        X.iloc[trn], y[trn]).predict_proba(X.iloc[tst])[:, 1]
print("all inputs together, AUC:", round(roc_auc_score(y, oof), 3))
R.to_csv("results/tiebreak.csv", index=False); print(R.head(20).round(3).to_string(index=False))
