"""What adds the most rating accuracy on top of the plain review-context agent (router_eval's `agent_full` = C2)?

Model-free and spend-free: reuses the cached agent predictions in $CTX_ROOT/.../out/router/ratings_long.csv
(420 people: 25 DEV products, 10 held-out TEST products) and the Capterra corpus. Every corpus statistic for a person
excludes their own product (and, for the corpus models, every product in the split being evaluated).

Candidates, per rating output:
  bias      agent_full + constant (median of dev residuals)
  linear    L1 fit  a * agent_full + c
  stack     L1 fit  a * agent_full + b * averages + c          (averages = handoff's people-like-them estimate)
  factors   L1 fit  agent_full + each factor's deviation as its own weight (role/size/tenure/industry/category,
            plus within-category role/size/tenure deviations) + previous-product flag
  gbm       corpus model (gradient boosting, absolute-error loss) on the card fields, stacked with agent_full
  *+round   any of the above rounded to the rating grid
Calibrators are fit on DEV people and scored on TEST people; LOPO repeats that leaving one product out at a time over
all 35 products. Requires scikit-learn.

    python calibrate.py
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))

import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import QuantileRegressor, Ridge  # noqa: E402

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
OUT = HERE / "results/calibrate"
LONG = CTX / "experiments/staged_context/out/router/ratings_long.csv"
FACTORS = {"role": "role_family", "size": "reviewer_company_size", "tenure": "reviewer_time_used_product",
           "industry": "reviewer_industry"}
SCALE = {r: (hi - lo) / 4 for r, (lo, hi) in U.RATINGS.items()}  # recommend (0-10) errors count half
SHRINK = U.SHRINK


def corpus() -> pd.DataFrame:
    df = U.data().copy()
    df["category"] = df.product_category_group
    df["prev"] = (df.switched_from.notna() | df.alternatives_considered.notna()).astype(int)
    keep = df.role_family.ne("unknown") & df[list(FACTORS.values())[1:]].notna().all(axis=1)
    return df[keep]


def lpo_mean(df, keys, r, people, exclude_col="product_name"):
    """Shrunk mean of rating r per group `keys`, leaving out each person's own product. Returns (mean, n)."""
    d = df[df[r].notna()]
    tot = d.groupby(keys)[r].agg(["sum", "count"])
    own = d.groupby([exclude_col] + keys)[r].agg(["sum", "count"])
    idx_t = pd.MultiIndex.from_frame(people[keys]) if len(keys) > 1 else pd.Index(people[keys[0]])
    t = tot.reindex(idx_t).fillna(0).to_numpy()
    o = own.reindex(pd.MultiIndex.from_frame(people[[exclude_col] + keys])).fillna(0).to_numpy()
    s, n = t[:, 0] - o[:, 0], t[:, 1] - o[:, 1]
    return s, n


def features(df: pd.DataFrame, people: pd.DataFrame) -> pd.DataFrame:
    """Per person x output: leave-own-product-out deviations of each factor (overall and within category)."""
    rows = []
    for r in U.RATINGS:
        d = df[df[r].notna()]
        mu_all = d[r].sum()
        own_tot = d.groupby("product_name")[r].agg(["sum", "count"]).reindex(people.product_name).fillna(0).to_numpy()
        mu = (mu_all - own_tot[:, 0]) / (d[r].count() - own_tot[:, 1])
        f = pd.DataFrame({"rid": people.rid.values, "output": r, "mu": mu})
        cs, cn = lpo_mean(df, ["category"], r, people)
        cat = (cs + SHRINK * mu) / (cn + SHRINK)
        f["dev_category"] = cat - mu
        for k, col in FACTORS.items():
            s, n = lpo_mean(df, [col], r, people)
            f[f"dev_{k}"] = (s + SHRINK * mu) / (n + SHRINK) - mu
            if k != "industry":  # within-category (i.e. on same-category rivals) deviation from the category mean
                s, n = lpo_mean(df, ["category", col], r, people)
                f[f"devc_{k}"] = (s + SHRINK * cat) / (n + SHRINK) - cat
        f["prev"] = people.prev.values
        rows.append(f)
    return pd.concat(rows, ignore_index=True)


def gbm_preds(df: pd.DataFrame, people: pd.DataFrame, holdout: list[str]) -> pd.DataFrame:
    """Corpus model trained without any `holdout` product, predicting the people of those products."""
    cols = list(FACTORS.values()) + ["category"]
    top_ind = df.reviewer_industry.value_counts().index[:40]
    enc = lambda x: x.assign(reviewer_industry=x.reviewer_industry.where(x.reviewer_industry.isin(top_ind), "other"))  # noqa: E731
    tr, te = enc(df[~df.product_name.isin(holdout)]), enc(people[people.product_name.isin(holdout)])
    cats = {c: pd.Categorical(tr[c]).categories for c in cols}
    X = lambda x: np.column_stack([pd.Categorical(x[c], categories=cats[c]).codes for c in cols] + [x.prev.values])  # noqa: E731
    out = []
    for r in U.RATINGS:
        m = tr[r].notna()
        g = HistGradientBoostingRegressor(loss="absolute_error", max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                          min_samples_leaf=200, categorical_features=list(range(len(cols))), random_state=0)
        g.fit(X(tr[m]), tr[r][m])
        out.append(pd.DataFrame({"rid": te.rid.values, "output": r, "gbm": g.predict(X(te))}))
    return pd.concat(out, ignore_index=True)


FACTOR_COLS = ["dev_category", "dev_role", "dev_size", "dev_tenure", "dev_industry", "devc_role", "devc_size", "devc_tenure", "prev"]
MODELS = {
    "const": [],
    "bias": ["agent_full"],  # slope fixed at 1
    "linear": ["agent_full"],
    "stack": ["agent_full", "averages"],
    "stack_alone": ["agent_alone", "averages"],
    "averages_only": ["averages"],
    "factors_only": ["mu"] + FACTOR_COLS,
    "factors": ["agent_full", "mu"] + FACTOR_COLS,
    "gbm_only": ["gbm"],
    "gbm_stack": ["agent_full", "gbm"],
    "all": ["agent_full", "averages", "gbm"] + FACTOR_COLS,
}
RAW = ("agent_alone", "agent_full", "averages", "agent_averages", "gbm")


def fit_predict(name: str, loss: str, tr: pd.DataFrame, te: pd.DataFrame, lo: float, hi: float) -> np.ndarray:
    """loss 'l1' targets the median (what MAE rewards), 'l2' the mean (what RMSE and ranking reward)."""
    cols, agg = MODELS[name], (np.median if loss == "l1" else np.mean)
    if not cols:
        return np.full(len(te), agg(tr.y))
    if name == "bias":
        return np.clip(te.agent_full + agg(tr.y - tr.agent_full), lo, hi)
    if loss == "l1":
        m = QuantileRegressor(quantile=0.5, alpha=0.0005 if len(cols) > 3 else 0.0, solver="highs")
    else:
        m = Ridge(alpha=1.0 if len(cols) > 3 else 1e-6)
    m.fit(tr[cols], tr.y)
    return np.clip(m.predict(te[cols]), lo, hi)


def predict_all(W: pd.DataFrame, folds: list[tuple[list[str], list[str]]]) -> pd.DataFrame:
    rows = []
    for out, (lo, hi) in U.RATINGS.items():
        w = W[W.output == out]
        for train_p, test_p in folds:
            tr, te = w[w["product"].isin(train_p)], w[w["product"].isin(test_p)]
            preds = {s: te[s].values for s in RAW}
            preds["router"] = te[RE_ROUTER[out]].values
            for name in MODELS:
                for loss in ("l1", "l2"):
                    preds[f"{name}_{loss}"] = fit_predict(name, loss, tr, te, lo, hi)
            for name, p in preds.items():
                rows.append(pd.DataFrame({"rid": te.rid.values, "product": te["product"].values, "output": out,
                                          "y": te.y.values, "method": name, "pred": p}))
    P = pd.concat(rows, ignore_index=True)
    P["abs_err"] = (P.pred - P.y).abs() / P.output.map(SCALE)
    P["sq_err"] = ((P.pred - P.y) / P.output.map(SCALE)) ** 2
    return P


def spearman(a, b) -> float:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0


def auc(score, y) -> float:
    s, y = np.asarray(score), np.asarray(y)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float(((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean()))


def metrics(P: pd.DataFrame) -> pd.DataFrame:
    """Per method: normalized MAE / RMSE over all outputs, mean Spearman (pooled and within product), unhappy AUC."""
    res = []
    for m, g in P.groupby("method"):
        r = {"method": m, "mae": g.abs_err.mean(), "rmse": float(np.sqrt(g.sq_err.mean()))}
        r["spearman"] = np.mean([spearman(x.pred, x.y) for _, x in g.groupby("output")])
        r["spearman_within_product"] = np.mean([spearman(z.pred, z.y) for _, x in g.groupby("output")
                                                for _, z in x.groupby("product") if len(z) >= 5])
        wide = g.pivot_table(index="rid", columns="output", values=["pred", "y"])
        ok = wide[("y", "overall_rating")].notna() & wide[("pred", "overall_rating")].notna()
        wide = wide[ok]
        rec_y, rec_p = wide[("y", "recommendation_score")], wide[("pred", "recommendation_score")]
        label = ((wide[("y", "overall_rating")] <= 3) | (rec_y <= 6)).astype(int)
        r["unhappy_auc"] = auc(-(wide[("pred", "overall_rating")] + rec_p.fillna(rec_p.mean()) / 2), label)
        for out in U.RATINGS:
            r[out] = g[g.output == out].abs_err.mean() * SCALE[out]
        res.append(r)
    return pd.DataFrame(res).sort_values("mae")


RE_ROUTER = U.E.read_json(U.ROUTER_PATH)["strategy"]


def cluster_ci(P: pd.DataFrame, a: str, b: str, col: str = "abs_err", n: int = 2000) -> tuple[float, float, float]:
    """Mean per-row difference a - b in `col` over all outputs, with a product-cluster bootstrap 95% interval."""
    d = P[P.method.isin([a, b])].pivot_table(index=["rid", "output", "product"], columns="method", values=col).dropna()
    per = (d[a] - d[b]).groupby(level="product").agg(["sum", "count"])
    rng = np.random.default_rng(0)
    boots = [(s := per.iloc[rng.integers(0, len(per), len(per))])["sum"].sum() / s["count"].sum() for _ in range(n)]
    return per["sum"].sum() / per["count"].sum(), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide per person x output table with every candidate input; W for DEV->TEST, W2 with leave-one-product-out gbm."""
    cache = OUT / "inputs.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    df = corpus()
    ppl = pd.DataFrame(RE.sample(U.data()))
    ppl["rid"], ppl["category"] = ppl.review_id, ppl.product_category_group
    ppl["prev"] = (ppl.switched_from.notna() | ppl.alternatives_considered.notna()).astype(int)
    L = pd.read_csv(LONG)
    W = L.pivot_table(index=["rid", "product", "split", "output", "y"], columns="strategy", values="pred").reset_index()
    W = W.merge(features(df, ppl), on=["rid", "output"]).dropna(subset=["agent_full", "agent_alone", "averages", "agent_averages"])
    g = pd.concat([gbm_preds(df, ppl, RE.TEST), gbm_preds(df, ppl, RE.DEV)])
    lopo_g = pd.concat([gbm_preds(df, ppl, [p]) for p in RE.DEV + RE.TEST])
    out = (W.merge(g, on=["rid", "output"]), W.merge(lopo_g, on=["rid", "output"]))
    pd.to_pickle(out, cache)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    W, W2 = tables()
    products = RE.DEV + RE.TEST
    runs = {"test": predict_all(W, [(RE.DEV, RE.TEST)]),
            "lopo35": predict_all(W2, [([q for q in products if q != p], [p]) for p in products])}
    pd.set_option("display.width", 250)
    summ, ci = [], []
    for label, P in runs.items():
        P.to_csv(OUT / f"{label}_preds.csv.gz", index=False)
        m = metrics(P).assign(eval=label)
        summ.append(m)
        print(f"\n== {label}: normalized MAE / RMSE (recommend counted on a 1-5 scale), ranking, per-output MAE ==")
        print(m.round(3).to_string(index=False))
        for meth in sorted(set(P.method) - {"agent_full"}):
            for col in ("abs_err", "sq_err"):
                d, lo_, hi_ = cluster_ci(P, meth, "agent_full", col)
                ci.append({"eval": label, "method": meth, "metric": col, "minus_agent_full": d, "lo95": lo_, "hi95": hi_})
    pd.concat(summ).to_csv(OUT / "summary.csv", index=False)
    C = pd.DataFrame(ci).sort_values(["eval", "metric", "minus_agent_full"])
    C.to_csv(OUT / "vs_agent_full.csv", index=False)
    print("\nvs agent_full (negative = better), product-cluster bootstrap 95%:")
    print(C.round(3).to_string(index=False))

    # factor weights, standardized, from the mean (l2) fit on all 35 products: which inputs carry signal
    wts = []
    for out in U.RATINGS:
        w = W2[W2.output == out]
        cols = MODELS["all"]
        X = (w[cols] - w[cols].mean()) / w[cols].std().replace(0, 1)
        m = Ridge(alpha=1.0).fit(X, w.y)
        wts.append({"output": out, **dict(zip(cols, m.coef_.round(3)))})
    Wt = pd.DataFrame(wts)
    Wt.to_csv(OUT / "factor_weights.csv", index=False)
    print("\nstandardized weights (rating points per 1 SD; ridge on all 35 products):\n", Wt.to_string(index=False))


if __name__ == "__main__":
    main()
