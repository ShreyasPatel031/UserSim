"""Same launches, two versions of the homepage: the Wayback snapshot from before launch vs today's live site.
A homepage-only model (cross-validated by day) predicts how each launch did relative to its day; compare."""
import json
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
import features as F

snap = {r["id"]: r for r in map(json.loads, open(F.D + "/wb_snap.jsonl")) if r.get("html")}
live = F._jl("sites.jsonl", "id")
df = F.build()
df = df[df.id.isin(snap) & df.mon.isin(["2026-09", "2026-10"])].copy()
df["rel"] = df.logv - df.groupby("day").logv.transform("mean")
out = {"n_launches": int(len(df)), "n_days": int(df.day.nunique())}
for version, src in (("snapshot", snap), ("live", live)):
    feats, texts = [], []
    for i in df.id:
        f, t = F.web_feats({"html": src[i].get("html", ""), "src": "x"})
        feats.append(f); texts.append(t[:6000])
    X = pd.DataFrame(feats).drop(columns=["web_src_wayback", "web_src_live"])
    folds = pd.factorize(df.day)[0] % 5
    pred_f, pred_t = np.zeros(len(df)), np.zeros(len(df))
    for k in range(5):
        trn, tst = folds != k, folds == k
        m = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=20, verbose=-1)
        pred_f[tst] = m.fit(X[trn], df.rel[trn]).predict(X[tst])
        v = TfidfVectorizer(min_df=3, max_features=20000, sublinear_tf=True)
        Tt = v.fit_transform([texts[j] for j in np.where(trn)[0]])
        pred_t[tst] = Ridge(alpha=5.0).fit(Tt, df.rel[trn]).predict(v.transform([texts[j] for j in np.where(tst)[0]]))
    sp = lambda p: float(np.nanmean([spearmanr(g, df.rel.values[idx])[0] for idx in df.groupby("day").indices.values()
                                     if len(idx) > 4 for g in [p[idx]]]))
    out[version] = {"homepage_structure_spearman": round(sp(pred_f), 3), "homepage_words_spearman": round(sp(pred_t), 3)}
    # how different are the two pages?
same = [len(set(F.site_text(snap[i]["html"]).split()) & set(F.site_text(live[i].get("html", "")).split())) /
        max(1, len(set(F.site_text(snap[i]["html"]).split()) | set(F.site_text(live[i].get("html", "")).split()))) for i in df.id]
out["word_overlap_snapshot_vs_live_median"] = round(float(np.median(same)), 3)
json.dump(out, open(F.D + "/../results/snapshot_vs_live.json", "w"), indent=1)
print(out)
