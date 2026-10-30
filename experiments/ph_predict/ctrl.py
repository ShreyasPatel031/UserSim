"""What a maker can change, given what they can't. Rolling monthly (train on earlier months, test on the next), 5 seeds.
  fixed     what the maker can't change before launch: team and makers' reach, track record, network, brand, category
  page      the launch page: name, tagline, description, media, video, topics, Gemini's score of every page element,
            website, the maker's first comment
  day       which day they launch (weekday, how many launches that day, same-day competition)
  effort    who hunts it and pre-launch promotion
1. Ranking: fixed only vs fixed + each changeable group (daily top 3 / 5 / 10).
2. Over/under-performance: residual = real log votes minus the fixed-only prediction (out of sample). Does each
   changeable group's predicted lift, and each changeable input on its own, predict that residual? Rank correlation
   within day, with a 95% interval over days (bootstrap). This is the number that says whether advice on that
   input can be trusted.
usage: python ctrl.py -> results/ctrl.json"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import model as M, run as RN
from buildcache import build_cached

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
PAGE_PREFIX = ("ps_", "vs_", "pf_", "upw_", "txt_", "web_", "dom_", "llm_pitch", "llm_site", "llm_full", "topic_")
PAGE_COLS = {"ph_n_media", "ph_has_video", "ph_n_topics", "ph_desc_len", "ph_tagline_len", "ph_name_len", "ph_dayrank_ph_n_media",
             "web_dayrank_web_text_words", "dom_dayrank_dom_age_d"}
DAY_COLS = {"ph_weekday", "ph_day_n_launches", "ph_month", "busy_same_day", "busy_7d"}
EFFORT_PREFIX = ("promo_",)
EFFORT_COLS = {"ph_self_hunted", "ph_hunter_followers", "ph_hunter_age_d", "hist_hunter_n", "hist_hunter_rel", "hist_hunter_top5",
               "ph_hunter_n_same_day", "ph_dayrank_ph_hunter_followers", "ph_dayrank_ph_hunter_age_d", "x_hunter_followers",
               "x_dayrank_x_hunter_followers", "fol_hunter", "ctx_hunter_n_today", "ctx_hunter_rank_today", "ctx_pct_ph_hunter_followers",
               "ctx_gap_ph_hunter_followers", "ctx_pct_hist_hunter_rel", "ctx_gap_hist_hunter_rel", "ctx_pct_fol_hunter", "ctx_gap_fol_hunter",
               "hist_dayrank_hist_hunter_rel"}


def group(c):
    if c in DAY_COLS or c.startswith("ctx_") and "hunter" not in c:
        return "day"
    if c in EFFORT_COLS or c.startswith(EFFORT_PREFIX):
        return "effort"
    if c in PAGE_COLS or c.startswith(PAGE_PREFIX):
        return "page"
    return "fixed"


def fit(tr, te, cols, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.5, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=1)
    return m.fit(tr[cols], tr.logv).predict(te[cols])


def job(a):
    m, tr, te, seed, G = a
    tr, te = M.add_fold_feats(tr, te)
    cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    by = {g: [c for c in cols if group(c) == g] for g in ("fixed", "page", "day", "effort")}
    G.update({g: len(v) for g, v in by.items()})
    out = {"id": te.id.values, "seed": seed, "fixed": fit(tr, te, by["fixed"], seed)}
    for g in ("page", "day", "effort"):
        out[f"fixed+{g}"] = fit(tr, te, by["fixed"] + by[g], seed)
    out["all"] = fit(tr, te, cols, seed)
    out["txt_ridge"] = te["txt_ridge"].values if "txt_ridge" in te else np.nan   # made per fold
    return pd.DataFrame(out), by


def boot_corr(D, x, y, n=1000):
    days = [g for _, g in D.groupby("day") if g[x].nunique() > 1 and len(g) >= 8]
    per = np.array([spearmanr(g[x], g[y]).correlation for g in days])
    per = per[~np.isnan(per)]
    rng = np.random.default_rng(0)
    bs = [rng.choice(per, len(per)).mean() for _ in range(n)]
    return round(float(per.mean()), 3), [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)], len(per)


def main():
    df = build_cached(); df = df[~df.known].copy()
    G = {}
    jobs = [(m, tr, te, s, G) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        out = pool.map(job, jobs)
    P = pd.concat([o[0] for o in out]); by = out[0][1]
    V = [c for c in P.columns if c not in ("id", "seed", "txt_ridge")]
    A = P.groupby("id")[V + ["txt_ridge"]].mean().reset_index().merge(df, on="id")
    A = A[A.dailyRank.notna()]
    A[["id", "day", "dailyRank", "logv"] + V].to_parquet("results/ctrl_preds.parquet")
    res = {"inputs_per_group": {g: len(v) for g, v in by.items()}, "page_inputs": by["page"], "day_inputs": by["day"], "effort_inputs": by["effort"]}
    res["ranking_top3_5_10"] = {v: [round(100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)), 1) for k in (3, 5, 10)] for v in V}
    A["resid"] = A.logv - A.fixed
    res["predicted_lift_vs_real_over_performance"] = {}
    for g in ("page", "day", "effort"):
        A[f"lift_{g}"] = A[f"fixed+{g}"] - A.fixed
        res["predicted_lift_vs_real_over_performance"][g] = dict(zip(("corr", "ci95", "days"), boot_corr(A, f"lift_{g}", "resid")))
    single = {}
    for c in by["page"] + by["day"] + by["effort"]:
        if c in A and A[c].notna().mean() > 0.2:
            single[c] = dict(zip(("corr", "ci95", "days"), boot_corr(A, c, "resid")))
    res["each_input_vs_over_performance"] = dict(sorted(single.items(), key=lambda kv: -abs(kv[1]["corr"])))
    json.dump(res, open("results/ctrl.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("inputs_per_group", "ranking_top3_5_10", "predicted_lift_vs_real_over_performance")}, indent=1))
    print(pd.DataFrame(res["each_input_vs_over_performance"]).T.head(40).to_string())


if __name__ == "__main__":
    main()
