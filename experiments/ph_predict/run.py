"""Backtest everything and write results/metrics.json + results/*.csv.
Folds: test month M in TEST_MONTHS, train on all launches before M (rolling origin). Weekly lists are scored
on ISO weeks fully inside the test month; monthly list = the test month itself."""
import json, os, sys
import numpy as np, pandas as pd
import features as F, model as M

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"); os.makedirs(OUT, exist_ok=True)
GROUPS = {"ai": ["Artificial Intelligence"], "dev": ["Developer Tools", "GitHub", "Open Source", "API"],
          "productivity": ["Productivity", "Task Management", "Notes", "Calendar"],
          "design": ["Design Tools", "Art", "Photography", "Video"], "marketing": ["Marketing", "SEO", "Sales", "Social Media"],
          "consumer": ["iOS", "Android", "Health & Fitness", "Lifestyle", "Games", "Education"]}


def load_llm(df):
    for mode in ("pitch", "site", "brand"):
        d = F.D + f"/llm_{mode}" + ("_gemini" if os.environ.get("LLM_PROVIDER") == "gemini" else "")
        sc, kn = {}, {}
        if os.path.isdir(d):
            for fn in os.listdir(d):
                for k, v in json.load(open(f"{d}/{fn}")).items():
                    if isinstance(v, dict):
                        sc[k], kn[k] = v.get("score"), v.get("known")
        df[f"llm_{mode}"] = df.id.map(sc).astype(float)
        if mode == "pitch":
            df["known"] = df.id.map(kn).fillna(False).astype(bool)
    return df


def ptype(ts):
    for g, names in GROUPS.items():
        if any(t in names for t in ts):
            return g
    return "other"


def folds(df, test_months):
    for m in test_months:
        tr, te = df[df.mon < m], df[df.mon == m]
        if len(tr) > 200 and len(te):
            yield m, tr, te


def run(test_months):
    df = load_llm(F.build())
    df = df[~df.known]  # memorisation check: drop products the LLM says it knows
    df["ptype"] = df.topics.apply(ptype)
    allte, ablate, single, imps = [], [], [], []
    for m, tr, te in folds(df, test_months):
        tr, te = M.add_fold_feats(tr, te)
        te = te.copy()
        te["pred"], mdl, c = M.fit_predict(tr, te, M.SOURCES)
        te["pred_random"] = np.random.default_rng(0).random(len(te))
        te["pred_rank_day"] = M.fit_rank(tr, te, M.SOURCES)
        te["pred_week_model"] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
        te["pred_month_model"] = M.fit_list_clf(tr, te, "mon", "monthlyRank", 20)
        te["pred_ph_only"] = M.fit_predict(tr, te, ["ph"])[0]
        z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
        te["pred_blend"] = z(te.pred) + z(te.groupby("day").pred_rank_day.transform(lambda v: v - v.mean()))
        M.INCLUDE_LEAKY = True
        te["pred_with_maker_followers"] = M.fit_predict(tr, te, M.SOURCES)[0]
        M.INCLUDE_LEAKY = False
        te["pred_llm_pitch"] = te.llm_pitch  # baseline B: LLM reads the pitch only
        te["pred_llm_site"] = te.llm_site    # baseline C: LLM reads pitch + homepage
        for s in M.SOURCES:  # drop one source / only one source
            te[f"pred_drop_{s}"] = M.fit_predict(tr, te, [x for x in M.SOURCES if x != s])[0]
            te[f"pred_only_{s}"] = M.fit_predict(tr, te, [s])[0]
        # SHAP-style contributions on the test month, summed per source
        contrib = mdl.predict(te[c], pred_contrib=True)[:, :-1]
        cdf = pd.DataFrame(np.abs(contrib), columns=c)
        cdf["ptype"] = te.ptype.values
        imps.append(cdf)
        allte.append(te)
        print(m, len(tr), len(te), M.evaluate(te), flush=True)
    te = pd.concat(allte)
    scores = [c for c in te.columns if c.startswith("pred")]
    res = {s: M.evaluate(te, s, with_ci=s in ("pred", "pred_random", "pred_ph_only", "pred_llm_pitch",
                                              "pred_llm_site", "pred_rank_day", "pred_week_model", "pred_month_model",
                                              "pred_blend")) for s in scores}
    # memorised share
    res["_meta"] = {"n_test": int(len(te)), "test_months": sorted(te.mon.unique().tolist()),
                    "n_days": int(te.day.nunique()), "n_weeks": int(te.week.nunique()),
                    "dropped_known": int(load_llm(F.build()).known.sum()),
                    "sites_wayback": float(te.web_src_wayback.mean()), "sites_live": float(te.web_src_live.mean()),
                    "sites_none": float(te.web_dead.mean())}
    # per-topic lists: within each (topic, period), top-k by votes
    topic_res = []
    top_topics = te.explode("topics").topics.value_counts().head(15).index
    ex = te.explode("topics")
    for t in top_topics:
        g = ex[ex.topics == t]
        for per in ("day", "week", "mon"):
            for k in (3, 5, 10):
                for s in ("pred", "pred_random", "pred_llm_pitch", "pred_ph_only"):
                    r, n = M.recall_at(g, per, None, k, s)
                    topic_res.append({"topic": t, "period": per, "k": k, "score": s, "recall": r, "n_lists": n})
    pd.DataFrame(topic_res).to_csv(f"{OUT}/topic_lists.csv", index=False)
    # importance by source and by product type
    imp = pd.concat(imps)
    srcmap = {c: c.split("_")[0] for c in imp.columns if c != "ptype"}
    by_src = imp.drop(columns="ptype").T.groupby(srcmap).sum().T
    by_src["ptype"] = imp.ptype.values
    share = by_src.groupby("ptype").mean()
    share = share.div(share.sum(axis=1), axis=0)
    share.to_csv(f"{OUT}/importance_by_type.csv")
    feat = imp.drop(columns="ptype").mean().sort_values(ascending=False)
    feat.to_csv(f"{OUT}/importance_features.csv")
    feat_t = imp.groupby("ptype").mean().T
    feat_t.to_csv(f"{OUT}/importance_features_by_type.csv")
    # by snapshot vs live
    for src in ("web_src_wayback", "web_src_live", "web_dead"):
        sub = te[te[src] == 1]
        res["_meta"][f"spearman_day_{src}"] = float(np.nanmean([M.spearmanr(g.pred, -g.dailyRank)[0]
                                                                for _, g in sub.groupby("day") if len(g) > 4]))
    # accuracy by product type: within-day rank correlation among that type's launches, and how often a type's
    # real top-5 launches were in the predicted top 5 of the whole day
    bt = {}
    for t in te.ptype.unique():
        sp = [M.spearmanr(g.pred, -g.dailyRank)[0] for _, g in te[te.ptype == t].groupby("day") if len(g) >= 4]
        hits = []
        for _, g in te.groupby("day"):
            top = g.nsmallest(5, "dailyRank"); pt = set(g.nlargest(5, "pred").id)
            hits += [i in pt for i in top[top.ptype == t].id]
        bt[t] = {"spearman_within_type_day": float(np.nanmean(sp)) if sp else None,
                 "recall_of_type_in_day_top5": float(np.mean(hits)) if hits else None, "n_top5": len(hits),
                 "n": int((te.ptype == t).sum())}
    res["_by_type"] = bt
    te.drop(columns=["web_text", "description"]).to_csv(f"{OUT}/predictions.csv", index=False)
    json.dump(res, open(f"{OUT}/metrics.json", "w"), indent=1, default=float)
    return res


if __name__ == "__main__":
    r = run(sys.argv[1:] or ["2026-07", "2026-08", "2026-09", "2026-10"])
    keys = ["day@3", "day@5", "day@10", "week@3", "week@5", "week@10", "month@3", "month@5", "month@10", "spearman_day"]
    print(pd.DataFrame({k: v for k, v in r.items() if not k.startswith("_")}).T[keys].round(3).to_string())
    print({k: v for k, v in r["pred"].items() if k.endswith("_ci")})
    print(r["_meta"])
