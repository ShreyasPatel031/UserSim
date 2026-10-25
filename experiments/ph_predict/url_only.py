"""Backtest for a brand-new launch where all we have is the product's URL/website and context about it and its
competitors: no hunter, makers, their Product Hunt history or followers, gallery or launch-day facts.
Same rolling monthly folds and recall@k as run.py, restricted to sources derivable from the URL."""
import sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

URL_SOURCES = ["txt", "web", "dom", "llm", "topic", "comp"]   # pitch text, homepage, domain, LLM, topic, similar launches
COMPANY_X = ["x_company_followers", "x_company_has_x"]       # company account only (no hunter/maker X)


def cols(df):
    c = [x for x in M.cols(df, URL_SOURCES) if not x.startswith(("dom_dayrank", "web_dayrank"))]
    return c + [x for x in COMPANY_X if x in df]


def main(months):
    df = RN.load_llm(F.build())
    df = df[~df.known]
    parts = []
    for m, tr, te in RN.folds(df, months):
        tr, te = M.add_fold_feats(tr, te)
        c = cols(tr)
        import lightgbm as lgb
        mdl = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                                subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
        te = te.copy()
        te["pred_url"] = mdl.fit(tr[c], tr.logv).predict(te[c])
        te["pred_full"] = M.fit_predict(tr, te, M.SOURCES)[0]
        te["pred_random"] = np.random.default_rng(0).random(len(te))
        parts.append(te)
        print(m, "features:", len(c), flush=True)
    te = pd.concat(parts)
    rows = []
    for s, name in (("pred_url", "URL + competitors only"), ("pred_full", "Full model (with hunter/makers)"), ("pred_random", "Random")):
        r = M.evaluate(te, s, with_ci=True)
        rows.append({"model": name, **{k: round(100 * r[k]) for k in ("day@3", "day@5", "day@10", "week@3", "week@5", "week@10",
                                                                    "month@3", "month@5", "month@10")},
                     "day@5 CI": f"{100 * r['day@5_ci'][0]:.0f}–{100 * r['day@5_ci'][1]:.0f}"})
    out = pd.DataFrame(rows)
    out.to_csv("results/url_only.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:] or ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"])
