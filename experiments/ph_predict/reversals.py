"""Where the model's order flips. For each day, pairs among the model's top 10 where the model ranked A above B but B
finished above A, with at least one of them in the real top 5 ("reversals"), versus pairs the model got right.
1) Which inputs favour the surprise winner (B) in reversals, compared with correct pairs: mean of (winner - loser)
   standardised, reversal vs correct.  2) Where reversals happen: error rate by context bucket.
Output: results/reversal_feats.csv, results/reversal_context.csv, results/reversal_pairs.csv"""
import os, pickle
import numpy as np, pandas as pd

R = "results"
df = pickle.load(open("data/build_cache.pkl", "rb"))
P = pd.read_csv(os.environ.get("PRED", f"{R}/predictions.csv"), usecols=["id", "pred"]); P["id"] = P.id.astype(str)
df = df.merge(P, on="id", how="inner")
df["prank"] = df.groupby("day").pred.rank(ascending=False, method="first")
num = [c for c in df.columns if df[c].dtype.kind in "fi" and c.split("_")[0] in
       ("ph", "hist", "web", "dom", "x", "hn", "comp", "topic", "llm", "cm", "aud", "aud2", "rec", "fol", "busy", "seg", "promo")]
Z = (df[num] - df[num].mean()) / df[num].std().replace(0, np.nan)
pairs = []
for day, g in df[df.prank <= 10].groupby("day"):
    idx = g.index.values
    for i in idx:
        for j in idx:
            if df.prank[i] < df.prank[j] and min(df.dailyRank[i], df.dailyRank[j]) <= 5:
                pairs.append((day, i, j, df.dailyRank[j] < df.dailyRank[i]))  # True: lower-predicted j finished higher
pr = pd.DataFrame(pairs, columns=["day", "a", "b", "reversed"])
# winner - loser differences
win = np.where(pr.reversed, pr.b, pr.a); lose = np.where(pr.reversed, pr.a, pr.b)
D = pd.DataFrame(Z.loc[win].values - Z.loc[lose].values, columns=num)
# the question: in reversals, what did the (lower-predicted) winner have more of than in correct calls?
pd_ = pd.DataFrame(Z.loc[pr.b].values - Z.loc[pr.a].values, columns=num)  # lower-predicted minus higher-predicted
rev, ok = pd_[pr.reversed.values], pd_[~pr.reversed.values]
out = pd.DataFrame({"reversal_mean": rev.mean(), "correct_mean": ok.mean()})
out["gap"] = out.reversal_mean - out.correct_mean
out["n_nonnull"] = rev.notna().sum()
out = out[out.n_nonnull > 50].sort_values("gap", key=abs, ascending=False)
out.round(3).to_csv(f"{R}/reversal_feats.csv")
print("pairs", len(pr), "reversed", int(pr.reversed.sum()), f"({pr.reversed.mean():.0%})")
print("\nInputs where the surprise winner (ranked lower by the model) differs most, vs correct pairs (sd units):")
print(out.head(25).round(3).to_string())
# context: miss rate of model's top-5 picks by bucket
t = df[df.prank <= 5].copy(); t["miss"] = (t.dailyRank > 5).astype(int)
ctx = {"hunter followers (log) quartile": pd.qcut(t.ph_hunter_followers.rank(method="first"), 4, labels=False),
       "self-posted": t.ph_self_hunted, "weekday (0=Mon)": t.ph_weekday,
       "launches that day": pd.qcut(t.ph_day_n_launches.rank(method="first"), 4, labels=False),
       "model's rank": t.prank, "poster's launches same day": t.get("busy_same_day", pd.Series(0, index=t.index)).clip(upper=5),
       "month": t.mon}
rows = []
for name, b in ctx.items():
    for v, g in t.groupby(b):
        rows.append({"context": name, "bucket": v, "n": len(g), "miss_rate": round(g.miss.mean(), 2)})
C = pd.DataFrame(rows); C.to_csv(f"{R}/reversal_context.csv", index=False)
print("\nHow often the model's top-5 picks miss the real top 5, by context:"); print(C.to_string(index=False))
pr.to_csv(f"{R}/reversal_pairs.csv", index=False)
