"""Which review data, mixed how, predicts a held-out reviewer's ratings best, on as many held-out eval sets as possible?

Model-free, no spend. Two eval sets today (one per review platform in the FreshCrawl snapshots): Capterra and G2
reviewers, up to PER_PRODUCT per product, products split DEV/TEST by hash. A third (TrustRadius / Gartner, via the
all-in-one Apify scraper) plugs in as another `source` once its reviews are in the same frame.

Every estimator for a person uses only data that would exist for a live study of that product:
  global     all reviews of OTHER products on the same platform
  category   same-category OTHER products (the product's rivals), same platform
  segment    people-like-them average (role / size / tenure / industry) on OTHER products (the handoff's averages)
  rivals_x   same-category OTHER products on the OTHER platform, shifted to this platform's scale
  own_x      the SAME product on the OTHER platform (overall rating only; shifted to this platform's scale)
  own_past   the SAME product on the same platform, reviews dated strictly before this person's review
Mixtures shrink the product's own evidence toward a prior: (n_own * mean_own + k * prior) / (n_own + k), with k and
the prior chosen on DEV. Point predictions: the mean (scored with RMSE) and the median of the mixed rating
distribution (scored with MAE; ratings skew to 5, so the median is what MAE rewards).

    python heldout_bench.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))

import corpus as C  # noqa: E402
import experiment as E  # noqa: E402
import ux_mcp as U  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/heldout_bench"
PER_PRODUCT = 40
MIN_REVIEWS = 100
SHRINK = U.SHRINK
KS = [0, 2, 5, 10, 20, 50, 100, 200]
RECENT = [10, 20, 50, 100, 200]
SCALE = {r: (hi - lo) / 4 for r, (lo, hi) in U.RATINGS.items()}
# same product, different names on the two platforms (exact case/space-insensitive matches are found automatically)
ALIASES = {"Agentforce Sales (formerly Salesforce Sales Cloud)": "Salesforce Sales Cloud",
           "Zendesk for Customer Service": "Zendesk Suite", "monday AI Work Platform": "monday.com AI Work Platform"}


def frame() -> pd.DataFrame:
    d = C.corpus().copy()
    cap_names = {p.lower().replace(" ", ""): p for p in d[d.source == "capterra"]["product"].unique()}
    g2 = d.source == "g2"
    d.loc[g2, "product"] = d.loc[g2, "product"].map(lambda p: ALIASES.get(p) or cap_names.get(p.lower().replace(" ", ""), p))
    cap_raw, g2_raw = U.data(), pd.read_csv(C.G2_FILE, low_memory=False, usecols=["review_id", "review_date"])
    dates = pd.concat([pd.Series(cap_raw.review_date.values, index="C:" + cap_raw.review_id.astype(str)),
                       pd.Series(g2_raw.review_date.values, index="G:" + g2_raw.review_id.astype(str))])
    d["date"] = pd.to_datetime(d.rid.map(dates), errors="coerce")
    # one category per product: Capterra's label wins when both platforms carry it
    cat = d[d.source == "capterra"].groupby("product").category.first()
    d["category"] = d["product"].map(cat).fillna(d.category)
    return d


def people(d: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (src, p), g in d[d.overall_rating.notna() & d.date.notna()].groupby(["source", "product"]):
        if len(g) < MIN_REVIEWS:
            continue
        g = g[g.role_family.ne("unknown")]
        g = g.assign(_h=g.rid.map(lambda i: E.sha(f"42|hob|{i}"))).sort_values("_h").head(PER_PRODUCT)
        split = "dev" if int(E.sha(f"42|hob-split|{p}")[:8], 16) % 2 == 0 else "test"
        out.append(g.assign(split=split))
    return pd.concat(out, ignore_index=True)


def _stats(v: np.ndarray) -> tuple[float, float, int]:
    v = v[~np.isnan(v)]
    return (float(v.mean()), float(np.median(v)), len(v)) if len(v) else (np.nan, np.nan, 0)


def estimates(d: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    rows = []
    src_mean = {(s, r): d.loc[d.source == s, r].mean() for s in ("capterra", "g2") for r in U.RATINGS}
    groups = {k: g for k, g in d.groupby(["source", "product"])}
    for (s, p), pp in P.groupby(["source", "product"]):
        cat = pp.category.iloc[0]
        other = "g2" if s == "capterra" else "capterra"
        rest = d[(d.source == s) & (d["product"] != p)]  # this platform, other products
        rest_cat = rest[rest.category == cat]
        xr_all = d[(d.source == other) & (d["product"] != p) & (d.category == cat)]
        own, ownx = groups[(s, p)], groups.get((other, p))
        seg = {(a, r): rest.groupby(a)[r].agg(["sum", "count"]) for a in ("role_family", "size_fine", "size3", "time_used", "industry")
               for r in U.RATINGS}
        for r in U.RATINGS:
            gm, gmed, _ = _stats(rest[r].to_numpy(float))
            cm, cmed, cn = _stats(rest_cat[r].to_numpy(float))
            shift = src_mean[(s, r)] - src_mean[(other, r)] if not np.isnan(src_mean[(other, r)]) else np.nan
            xm, _, xn = _stats(xr_all[r].to_numpy(float))
            om, _, on = _stats(ownx[r].to_numpy(float)) if ownx is not None else (np.nan, np.nan, 0)
            od = own[["rid", "date", r]].dropna().sort_values("date")
            for person in pp.to_dict("records"):
                y = person.get(r)
                if y is None or (isinstance(y, float) and np.isnan(y)):
                    continue
                e = {"rid": person["rid"], "source": s, "product": p, "split": person["split"], "output": r, "y": y,
                     "global_mean": gm, "global_median": gmed, "category_mean": cm, "category_median": cmed, "category_n": cn}
                dev = 0.0
                for a in C._attrs(s, person):
                    v = person.get(a)
                    if v is None or (isinstance(v, float) and np.isnan(v)):
                        continue
                    t = seg[(a, r)]
                    if v in t.index and t.loc[v, "count"]:
                        dev += (t.loc[v, "sum"] + SHRINK * gm) / (t.loc[v, "count"] + SHRINK) - gm
                e["segment_mean"] = gm + dev
                e["rivals_x_mean"], e["rivals_x_n"] = (xm + shift if xn else np.nan), xn
                e["own_x_mean"], e["own_x_n"] = (om + shift if on else np.nan), on
                pv = od.loc[(od.date < person["date"]) & (od.rid != person["rid"]), r].to_numpy(float)
                e["own_past_mean"], e["own_past_median"], e["own_past_n"] = _stats(pv)
                for w in RECENT:
                    e[f"own_last{w}_mean"], _, e[f"own_last{w}_n"] = _stats(pv[-w:])
                rows.append(e)
    return pd.DataFrame(rows)


def mix(X: pd.DataFrame, own: str, prior: str, k: float) -> pd.Series:
    n = X[f"{own}_n"].fillna(0)
    m = X[f"{own}_mean"].fillna(0)
    return (n * m + k * X[prior]) / (n + k).replace(0, np.nan)


PRIORS = ["global_mean", "category_mean", "segment_mean"]


def candidates(X: pd.DataFrame) -> dict[str, pd.Series]:
    c = {p: X[p] for p in PRIORS + ["rivals_x_mean"]}
    c["category+rivals_x"] = (X.category_mean * X.category_n + X.rivals_x_mean.fillna(0) * X.rivals_x_n.fillna(0)) / (
        X.category_n + X.rivals_x_n.fillna(0))
    for own in ["own_x", "own_past"] + [f"own_last{w}" for w in RECENT]:
        for prior in PRIORS:
            for k in KS[1:]:
                c[f"{own}|{prior}|k{k}"] = mix(X, own, prior, k).fillna(X[prior])
    for prior in PRIORS:  # both own-product sources, pooled before shrinking
        for k in KS[1:]:
            n = X.own_past_n.fillna(0) + X.own_x_n.fillna(0)
            m = (X.own_past_mean.fillna(0) * X.own_past_n.fillna(0) + X.own_x_mean.fillna(0) * X.own_x_n.fillna(0))
            c[f"own_past+own_x|{prior}|k{k}"] = ((m + k * X[prior]) / (n + k)).fillna(X[prior])
    # an estimator that has nothing for this person/output falls back to the people-like-them prior, so every
    # candidate is scored on the same rows
    return {k: v.fillna(X.segment_mean) for k, v in c.items()}


def score(X: pd.DataFrame) -> pd.DataFrame:
    """Per candidate x eval set (source x split): RMSE of the mean prediction and MAE of the rounded-up median proxy."""
    rows = []
    sc = X.output.map(SCALE)
    lo = X.output.map(lambda r: U.RATINGS[r][0])
    hi = X.output.map(lambda r: U.RATINGS[r][1])
    for name, pred in candidates(X).items():
        pred = pred.clip(lo, hi)
        # median proxy: ratings are integer-valued and left-skewed, so the median of a distribution with mean m sits at
        # ceil(m - t); t is fit on DEV per platform below
        err2 = ((pred - X.y) / sc) ** 2
        for (s, sp, o), g in X.assign(e2=err2, pred=pred).groupby(["source", "split", "output"]):
            rows.append({"candidate": name, "source": s, "split": sp, "output": o, "sse": g.e2.sum(), "n": len(g)})
    return pd.DataFrame(rows)


def median_scores(X: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """MAE of ceil(pred - t) with the threshold t chosen on DEV per platform (a median rule for skewed ratings)."""
    rows = []
    cands = candidates(X)
    lo = X.output.map(lambda r: U.RATINGS[r][0])
    hi = X.output.map(lambda r: U.RATINGS[r][1])
    sc = X.output.map(SCALE)
    for name in names:
        pred = cands[name].clip(lo, hi)
        for s in X.source.unique():
            best = None
            for t in np.arange(0.0, 1.01, 0.05):
                q = np.clip(np.ceil(pred - t), lo, hi)
                m = (X.source == s) & (X.split == "dev")
                mae = float((abs(q - X.y) / sc)[m].mean())
                if best is None or mae < best[1]:
                    best = (t, mae)
            q = np.clip(np.ceil(pred - best[0]), lo, hi)
            for sp in ("dev", "test"):
                m = (X.source == s) & (X.split == sp)
                rows.append({"candidate": name, "source": s, "split": sp, "t": round(best[0], 2),
                             "mae": float((abs(q - X.y) / sc)[m].mean())})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "estimates.pkl"
    if cache.exists():
        X = pd.read_pickle(cache)
    else:
        d = frame()
        P = people(d)
        print(P.groupby(["source", "split"])["product"].agg(["nunique", "size"]), flush=True)
        X = estimates(d, P)
        X.to_pickle(cache)
    S = score(X)
    S.to_csv(OUT / "sse_by_output.csv", index=False)
    agg = S.groupby(["candidate", "source", "split"])[["sse", "n"]].sum()
    piv = np.sqrt(agg.sse / agg.n).unstack(["source", "split"])
    ov = S[S.output == "overall_rating"].set_index(["candidate", "source", "split"])
    ov = np.sqrt(ov.sse / ov.n).unstack(["source", "split"])
    base = piv.loc["segment_mean"]
    wins = (piv.xs("test", axis=1, level=1) < base.xs("test", level=1) - 1e-9).sum(axis=1)
    # choose ONE mixture on DEV (mean rank across platforms), report TEST
    dev_rank = piv.xs("dev", axis=1, level=1).rank().mean(axis=1)
    pick = dev_rank.idxmin()
    pd.set_option("display.width", 250)
    families = {}
    for name in piv.index:
        fam = name.split("|k")[0]
        if fam not in families or dev_rank[name] < dev_rank[families[fam]]:
            families[fam] = name
    T = piv.loc[list(families.values())].assign(dev_rank=dev_rank, test_wins_vs_segment=wins).sort_values("dev_rank")
    T.to_csv(OUT / "rmse_by_family.csv")
    print("RMSE (normalized) per eval set; best k per family chosen on DEV:\n", T.round(4).to_string())
    print(f"\nchosen on DEV: {pick}")
    print("\noverall_rating only (the one rating both platforms carry):\n",
          ov.loc[list(families.values())].round(4).sort_values(("capterra", "dev")).to_string())
    M = median_scores(X, list(families.values()))
    M.to_csv(OUT / "mae_median_rule.csv", index=False)
    print("\nMAE with the median rule:\n", M.pivot_table(index="candidate", columns=["source", "split"], values="mae")
          .round(4).sort_values(("capterra", "dev")).to_string())
    cov = X.groupby(["source", "split"]).agg(own_x=("own_x_n", lambda v: (v > 0).mean()),
                                             own_past=("own_past_n", lambda v: (v > 0).mean()))
    print("\nshare of people with own-product evidence:\n", cov.round(3).to_string())


if __name__ == "__main__":
    main()
