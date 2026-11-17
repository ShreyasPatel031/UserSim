"""Rerun of experiments/launch_plan/counterfactual_arm2.py (orchestrator) with MEASURED Gemini pitch scores in place of the assumed 55 / 75.
Same logic (profile rows scored against each real day, bucketed calibration, trajectory feeding predictions forward). Differences, because the
pipeline VM was not reachable from this container: the arm-2 rebuild from the bucket backup is used (training_window.prep), trained on
2025-01-01..2026-09-17, test days 2026-09-18..2026-11-12 (56 days, 8 per weekday; the VM run used Sep 21..Nov 15). The assumed-score rows
are rerun too, so the two runs can be compared like for like."""
import json, sys, numpy as np, pandas as pd, lightgbm as lgb
import training_window as TW
SP = sys.argv[1]; T0 = "2026-09-18"
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).reset_index(drop=True)
tr, te, cols = TW.prep(X[(X.day < T0) & (X.day >= "2025-01-01")], X[X.day >= T0]); cc = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
mods = [lgb.LGBMRegressor(random_state=s, **dict(TW.P0, n_jobs=6)).fit(tr[cc], tr.logv) for s in range(5)]
pr = lambda d: np.mean([m.predict(d[cc]) for m in mods], axis=0)
te = te.copy(); te["pred"] = pr(te); te["prank"] = te.groupby("day").pred.rank(ascending=False, method="first"); te["arank"] = te.dailyRank
bkt = lambda r: int(r) if r <= 10 else (11 if r <= 15 else (16 if r <= 25 else 26))
te["b"] = te.prank.map(bkt); cal = {k: te.groupby("b").arank.apply(lambda s: (s <= k).mean()).to_dict() for k in (3, 5, 10)}
print("top3 hit", round(te[te.prank <= 3].arank.le(3).mean() * 100, 1), "days", te.day.nunique(), flush=True)
hh = te[te.hist_hunter_n > 0]; q = lambda c, p: float(hh[c].quantile(p)); AI = te[(te.topic_is_ai == 1) & (te.topic_is_dev == 0)]
BASE = dict(ph_n_makers=1, ph_hunter_age_d=60, ph_n_media=6, ph_has_video=1, ph_n_topics=3, ph_desc_len=350, ph_tagline_len=50, ph_name_len=12, x_company_has_x=0, busy_same_day=1, busy_7d=0,
            promo_posts=0, promo_posts_launch=0, promo_posts_li=0, promo_posts_x=0, promo_posts_founder=0, promo_cov=0, promo_cov_press=0, promo_cov_hn=0, promo_cov_reddit=0,
            hist_hunter_n=0, hist_hunter_rel=np.nan, hist_hunter_top5=np.nan, ph_hunter_n_same_day=1, llm_pitch=55, llm_brand=0, txt_ridge=float(te.txt_ridge.median()),
            comp_nn_mean=float(te.comp_nn_mean.median()), comp_nn_max=float(te.comp_nn_max.median()), comp_nn_sim=float(te.comp_nn_sim.median()),
            topic_prior_max=float(AI.topic_prior_max.median()), topic_prior_mean=float(AI.topic_prior_mean.median()), topic_is_ai=1.0, topic_is_dev=0.0)
assert set(cc) <= set(BASE) | {"ph_weekday", "ph_day_n_launches", "ph_dayrank_ph_hunter_age_d", "ph_dayrank_ph_n_makers", "ph_dayrank_ph_n_media", "hist_dayrank_hist_hunter_rel"}, set(cc) - set(BASE)
TOP10 = dict(hist_hunter_n=q("hist_hunter_n", .9), hist_hunter_rel=q("hist_hunter_rel", .9), hist_hunter_top5=q("hist_hunter_top5", .9), ph_hunter_age_d=q("ph_hunter_age_d", .9))
def drank(g, col, v):
    s = g[col].dropna(); return np.nan if (pd.isna(v) or len(s) == 0) else ((s < v).sum() + 0.5 * (s == v).sum() + 0.5) / (len(s) + 1)
def score(cfg):
    out = []
    for d, g in te.groupby("day"):
        r = {c: g[c].iloc[0] for c in ("ph_weekday", "ph_day_n_launches")}; r.update(BASE); r.update(cfg)
        for a, b in (("ph_dayrank_ph_hunter_age_d", "ph_hunter_age_d"), ("ph_dayrank_ph_n_makers", "ph_n_makers"), ("ph_dayrank_ph_n_media", "ph_n_media"), ("hist_dayrank_hist_hunter_rel", "hist_hunter_rel")): r[a] = drank(g, b, r[b])
        p = pr(pd.DataFrame([r])[cc].astype(float))[0]; rk = 1 + int((g.pred > p).sum()); b = bkt(rk)
        out.append(dict(day=d, wd=int(r["ph_weekday"]), n=len(g), rank=rk, pred=p, **{f"p{k}": cal[k].get(b, 0) for k in (3, 5, 10)}))
    return pd.DataFrame(out)
rng = np.random.default_rng(0); R = {}
def run(name, cfg):
    o = score(cfg); bs = [o.sample(len(o), replace=True, random_state=int(rng.integers(1e9))).p5.mean() for _ in range(1000)]
    R[name] = dict(med_rank=float(o["rank"].median()), p3=round(o.p3.mean() * 100, 1), p5=round(o.p5.mean() * 100, 1), p10=round(o.p10.mean() * 100, 1), p5_lo=round(np.percentile(bs, 2.5) * 100, 1), p5_hi=round(np.percentile(bs, 97.5) * 100, 1))
    print(name, json.dumps(R[name]), flush=True); return o
best = lambda pitch: dict(ph_n_makers=3, ph_hunter_age_d=1100, ph_n_media=9, ph_has_video=1, llm_pitch=pitch, x_company_has_x=1, promo_posts=3, promo_posts_launch=2, promo_posts_founder=3, promo_posts_x=2, promo_cov=3, promo_cov_press=1, promo_cov_hn=1, promo_cov_reddit=1)
MEAS = json.loads(sys.argv[2])  # product -> measured pitch score of its best version
for p in (40, 55, 75, 85): run(f"base case, pitch {p}", dict(llm_pitch=p))
for k, v in MEAS.items(): run(f"base case, {k} measured pitch {v}", dict(llm_pitch=v))
for k, v in MEAS.items(): run(f"first launch, everything you control, {k} measured pitch {v}", best(v))
for k, v in MEAS.items(): run(f"first launch, everything + top-10% hunter, {k} measured pitch {v}", dict(best(v), **TOP10))
def traj(tag, pitches):
    prev, prevr, o1 = [], [], None
    for i, pch in enumerate(pitches, 1):
        cfg = best(pch) if i == 1 else dict(best(pch), hist_hunter_n=i - 1, hist_hunter_rel=float(np.mean(prev)), hist_hunter_top5=float(np.mean([x <= 5 for x in prevr])))
        o = run(f"{tag} LAUNCH {i} (pitch {pch})", cfg); m = te.groupby("day").pred.mean(); prev.append(float((o.set_index("day").pred - m).median())); prevr += list(o["rank"]); o1 = o1 if o1 is not None else o
    return o1
traj("assumed 75:", [75, 75, 75, 75]); o1 = traj("measured:", list(MEAS.values()))
wd = o1.groupby("wd").agg(days=("day", "size"), med_rank=("rank", "median"), p5=("p5", "mean"), p10=("p10", "mean"), n=("n", "mean")).round(3).to_dict("index"); print("WEEKDAY step 1", json.dumps(wd))
json.dump({"window": [T0, str(te.day.max())], "measured": MEAS, "res": R, "weekday_step1": wd}, open(f"{SP}/selfplan/cf_arm2_measured.json", "w"), default=float, indent=1)
