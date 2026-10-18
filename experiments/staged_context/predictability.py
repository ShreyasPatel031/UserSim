"""What can be predicted at all? A no-model scan over every outcome in the Capterra file.

Two questions, both leave-one-product-out (the product being predicted is never in the training data):
  product level  - can a NEW product's outcome (mean rating, share of switchers, share complaining about pricing...)
                   be predicted from the other products in its category?  Baseline: mean of all other products.
  person level   - within a product, do a reviewer's role family, company size, tenure and industry predict their
                   outcome?  Averages are fitted on the other 65 products; scored within each product, then averaged.

    python experiments/staged_context/predictability.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402

OUT = E.OUT / "predictability"
MIN_REVIEWS = 100
TOPICS = {  # keyword topics in the cons text; a review "mentions" a topic if any pattern matches
    "complaint_pricing": r"\b(price|pricing|pricey|expensive|cost(ly|s)?|subscription|afford\w*|paid plan|upgrade)\b",
    "complaint_learning_curve": r"\b(learning curve|complicated|complex|overwhelm\w*|confus\w*|not intuitive|hard to (learn|use|navigate)|takes time to learn)\b",
    "complaint_mobile": r"\b(mobile|app on (my )?phone|ios|android|iphone)\b",
    "complaint_integrations": r"\b(integrat\w*|sync\w*|api)\b",
    "complaint_performance": r"\b(slow\w*|lag\w*|crash\w*|load(ing)? time|freez\w*|glitch\w*|bug\w*)\b",
    "complaint_support": r"\b(customer (service|support)|support team|support (is|was)|response time|tickets?)\b",
    "complaint_notifications": r"\b(notification\w*|emails? (are|too)|spam\w*)\b",
    "complaint_reporting": r"\b(report\w*|dashboard\w*|analytics)\b",
    "complaint_customization": r"\b(customi[sz]\w*|flexib\w*|limited|limitation\w*)\b",
}


warnings.filterwarnings("ignore", message="This pattern is interpreted")


def build_targets(df: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame(index=df.index)
    for c in ("overall_rating", "ease_of_use_rating", "customer_support_rating", "functionality_rating",
              "value_for_money_rating", "recommendation_score"):
        t[c] = df[c]
    t["unhappy_overall_le3"] = (df.overall_rating <= 3).astype(float)
    t["detractor_rec_le6"] = np.where(df.recommendation_score.notna(), (df.recommendation_score <= 6).astype(float), np.nan)
    t["switched_from_another_tool"] = df.switched_from.notna().astype(float)
    t["considered_alternatives"] = df.alternatives_considered.notna().astype(float)
    cons = df.cons.fillna("").str.lower()
    for k, pat in TOPICS.items():
        t[k] = cons.str.contains(pat, regex=True).astype(float)
    return t


def product_level(df: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    prod = df.groupby("product_name").agg(category=("product_category_group", "first"), n=("review_id", "size"))
    prod = prod[prod.n >= MIN_REVIEWS]
    vals = t.join(df.product_name).groupby("product_name").mean().loc[prod.index]
    rows = []
    for col in t.columns:
        y = vals[col]
        cat_pred, glob_pred = [], []
        for p in prod.index:
            peers = prod.index[(prod.category == prod.loc[p, "category"]) & (prod.index != p)]
            others = prod.index[prod.index != p]
            cat_pred.append(y[peers].mean() if len(peers) else y[others].mean())
            glob_pred.append(y[others].mean())
        cat_pred, glob_pred = np.array(cat_pred), np.array(glob_pred)
        mae_cat, mae_glob = np.abs(cat_pred - y).mean(), np.abs(glob_pred - y).mean()
        rows.append({"target": col, "products": len(y), "spread_across_products_sd": y.std(),
                     "corr_category_peers_vs_actual": np.corrcoef(cat_pred, y)[0, 1],
                     "error_reduction_vs_global_mean": 1 - mae_cat / mae_glob})
    return pd.DataFrame(rows)


def auc(score: np.ndarray, label: np.ndarray) -> float | None:
    pos, neg = score[label == 1], score[label == 0]
    if len(pos) < 5 or len(neg) < 5:
        return None
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return (ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def person_level(df: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    feats = pd.DataFrame({"role_family": df.reviewer_job_title.fillna("").map(E.role_family),
                          "size": df.reviewer_company_size.fillna("unknown"),
                          "tenure": df.reviewer_time_used_product.fillna("unknown"),
                          "industry": df.reviewer_industry.fillna("unknown")}, index=df.index)
    counts = df.product_name.value_counts()
    keep = df.product_name.isin(counts[counts >= MIN_REVIEWS].index)
    rows = []
    k = 20.0
    for col in t.columns:
        y = t[col]
        ok = y.notna() & keep
        binary = set(y[ok].unique()) <= {0.0, 1.0}
        # leave-one-product-out sums: total minus the product's own contribution
        frame = pd.DataFrame({"y": y[ok], "p": df.product_name[ok]}).join(feats[ok])
        tot_s, tot_n = frame.y.sum(), len(frame)
        pred = pd.Series(0.0, index=frame.index)
        mu_lopo = (tot_s - frame.groupby("p").y.transform("sum")) / (tot_n - frame.groupby("p").y.transform("size"))
        for f in feats.columns:
            g_all = frame.groupby(f).y.agg(["sum", "size"])
            g_prod = frame.groupby([f, "p"]).y.agg(["sum", "size"])
            idx = pd.MultiIndex.from_arrays([frame[f], frame.p])
            s = g_all["sum"].reindex(frame[f]).to_numpy() - g_prod["sum"].reindex(idx).to_numpy()
            n = g_all["size"].reindex(frame[f]).to_numpy() - g_prod["size"].reindex(idx).to_numpy()
            pred += ((s + k * mu_lopo.to_numpy()) / (n + k)) - mu_lopo.to_numpy()
        frame["pred"] = pred
        per_prod = []
        for p, g in frame.groupby("p"):
            if binary:
                a = auc(g.pred.to_numpy(), g.y.to_numpy())
                if a is not None:
                    per_prod.append(a)
            elif g.y.nunique() > 1 and g.pred.nunique() > 1:
                per_prod.append(g.pred.rank().corr(g.y.rank()))
        rows.append({"target": col, "metric": "AUC (0.5 = chance)" if binary else "Spearman (0 = chance)",
                     "within_product_mean": float(np.mean(per_prod)), "products_scored": len(per_prod),
                     "share_of_products_better_than_chance": float(np.mean([(v > 0.5) if binary else (v > 0) for v in per_prod])),
                     "base_rate_or_mean": float(y[ok].mean())})
    return pd.DataFrame(rows)


def main() -> None:
    df, _ = E.load_capterra()
    t = build_targets(df)
    pl, ps = product_level(df, t), person_level(df, t)
    OUT.mkdir(parents=True, exist_ok=True)
    pl.to_csv(OUT / "product_level.csv", index=False)
    ps.to_csv(OUT / "person_level.csv", index=False)
    pd.set_option("display.width", 220)
    print(pl.sort_values("error_reduction_vs_global_mean", ascending=False).round(3).to_string(index=False))
    print()
    print(ps.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
