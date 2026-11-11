"""Queue item 7b (Nov 11): repeat makers' past share of one-vote / low-activity accounts as a pre-launch mobilisation feature.
Full voter lists per launch are not held, so the proxy uses complete pool people (store_v3, full upvote lists):
for launch L on day d with team T (real maker/poster handles; "[REDACTED]" dropped), the makers' EARLIER launches are
launches dated <= d-2 sharing a team member. Their pool voters (upvotes of complete people) are split by the voter's
activity = number of the voter's upvotes on launches dated <= d-2 (launch-day dating, no future reads):
  mob_low_n    number of distinct earlier-launch pool voters with activity <= 3 (low-activity, "one-vote-like")
  mob_low_sh   their share of the earlier-launch pool voters
  mob_n        distinct earlier-launch pool voters (warm audience size)
  prior_l      number of earlier launches; repeat = prior_l > 0
Target: per-launch multiplier r = logv - base (it8 LM out-of-sample). Month-forward LightGBM (months < m) on the features
+ base; daily top 3/5/10 of base + predicted r vs LM only, and within-day Spearman of predicted vs true r, paired by day,
day-bootstrap 95% CIs. Also the raw within-day Spearman of each feature with r among repeat-maker launches.
    python mobilisation.py <workdir: v3/ launches/ salt preds.parquet>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import lightgbm as lgb

W = sys.argv[1]; rng = np.random.default_rng(0)
_real = lambda h: bool(h) and not str(h).startswith("[") and str(h).strip().lower() not in ("redacted", "none", "null")
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(W, "launches", "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str)
SALT = open(os.path.join(W, "salt")).read().strip()
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
team = {i: {pid(m) for m in (json.loads(mk) if isinstance(mk, str) and mk.startswith("[") else []) if _real(m)} | ({pid(po)} if _real(po) else set())
        for i, mk, po in zip(L.id, L.makers, L.poster)}
by_member = {}
for i, d in zip(L.id, L.day):
    for m in team[i]: by_member.setdefault(m, []).append((d, i))
P = pd.read_parquet(os.path.join(W, "preds.parquet"))[["id", "base", "day", "dailyRank", "logv"]]; P["id"] = P.id.astype(str); P["r"] = P.logv - P.base
comp = set(pd.read_parquet(os.path.join(W, "v3", "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id", "extra"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; Lday = dict(zip(L.id, L.day)); ev["target_id"] = ev.target_id.astype(str)
ev["vday"] = ev.target_id.map(Lday).fillna(ev.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0])
ev = ev.dropna(subset=["vday"])[["person_id", "target_id", "vday"]].drop_duplicates()
voters = ev.groupby("target_id").person_id.apply(list).to_dict()
act = {p: np.sort(g.vday.to_numpy()) for p, g in ev.groupby("person_id")}
print("launches", len(P), "dated pool upvotes", len(ev), flush=True)
rows = []
for i, d in zip(P.id, P.day):
    d2 = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    prior = {j for m in team.get(i, ()) for (dd, j) in by_member.get(m, ()) if dd <= d2 and j != i}
    vs = {v for j in prior for v in voters.get(j, ())}
    a = np.array([np.searchsorted(act[v], d2, side="right") for v in vs]) if vs else np.array([])
    rows.append({"id": i, "prior_l": len(prior), "mob_n": len(vs), "mob_low_n": int((a <= 3).sum()), "mob_low_sh": float((a <= 3).mean()) if len(a) else 0.0})
X = P.merge(pd.DataFrame(rows), on="id"); X["repeat"] = (X.prior_l > 0).astype(int)
for c in ("prior_l", "mob_n", "mob_low_n"): X["l_" + c] = np.log1p(X[c])
print("repeat share", round(X.repeat.mean(), 3), flush=True)


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "repeat_share": round(float(X.repeat.mean()), 3), "raw_within_day_spearman_with_r (repeat launches)": {}}
R = X[X.repeat == 1]
for c in ("l_prior_l", "l_mob_n", "l_mob_low_n", "mob_low_sh"):
    s = R.groupby("day").apply(lambda g: spearmanr(g[c], g.r).correlation if len(g) >= 4 and g[c].std() > 0 else np.nan)
    res["raw_within_day_spearman_with_r (repeat launches)"][c] = boot(s.values)
VARS = {"warm (prior_l, mob_n)": ["base", "l_prior_l", "l_mob_n", "repeat"],
        "warm + mobilisation": ["base", "l_prior_l", "l_mob_n", "repeat", "l_mob_low_n", "mob_low_sh"]}
months = sorted(X.day.str[:7].unique()); SER = {}
for vn, cols in VARS.items():
    X["pred"] = np.nan
    for mo in months[1:]:
        tr, te = X.day.str[:7] < mo, X.day.str[:7] == mo
        m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, verbose=-1, random_state=0).fit(X.loc[tr, cols], X.loc[tr, "r"])
        X.loc[te, "pred"] = m.predict(X.loc[te, cols])
    T = X[X.pred.notna()].copy(); T["score"] = T.base + T.pred
    per = {}
    for d, g in T.groupby("day"):
        per[d] = [len(set(g.nlargest(k, "score").id) & set(g.nsmallest(k, "dailyRank").id)) / k * 100 for k in (3, 5, 10)] + \
                 [len(set(g.nlargest(k, "base").id) & set(g.nsmallest(k, "dailyRank").id)) / k * 100 for k in (3, 5, 10)] + \
                 [spearmanr(g.pred, g.r).correlation if g.pred.std() > 0 else np.nan]
    D = pd.DataFrame(per).T; SER[vn] = D
    res[vn] = {"within_day_spearman_pred_r": boot(D[6].values), **{f"top{k}": boot(D[j].values) for j, k in enumerate((3, 5, 10))},
               **{f"top{k} minus LM-only": boot((D[j] - D[j + 3]).values) for j, k in enumerate((3, 5, 10))}}
a, b = SER["warm (prior_l, mob_n)"], SER["warm + mobilisation"]
res["mobilisation minus warm (paired by day)"] = {"spearman": boot((b[6] - a[6]).values), **{f"top{k}": boot((b[j] - a[j]).values) for j, k in enumerate((3, 5, 10))}}
res["LM-only"] = {f"top{k}": boot(a[j + 3].values) for j, k in enumerate((3, 5, 10))}
os.makedirs(os.path.join(W, "out"), exist_ok=True)
json.dump(res, open(os.path.join(W, "out", "mobilisation.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
