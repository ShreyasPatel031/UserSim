"""CATEGORY-1: launch categories, competitor sets, and the structural model's miss by category.

  python -m simharness.run_category STAGE --items-dir BUILD --similar similar_products_all.jsonl \\
      --taxonomy ph_categories_pasted.jsonl --structural STRUCT_DIR --out OUT [--sync gs://prefix] [--results-dir DIR]

Stages: labels (assign + validate the classifier), competitors, residual, agg. Private outputs go to OUT (and are
copied to --sync after each stage); `agg` writes aggregates only to --results-dir.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess

import numpy as np
import pandas as pd

from simharness import taxonomy as tx

NB = 2000
VAL_FROM, TEST_FROM, BACKTEST_FROM = "2026-07-01", "2026-09-01", "2026-04-01"


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def _items(a):
    it = pd.read_parquet(f"{a.items_dir}/items.parquet")
    k = pd.read_parquet(f"{a.items_dir}/item_keys.parquet")
    it["item_id"] = it["item_id"].astype(str)
    it["slug"] = it["item_id"].map(dict(zip(k["item_id"].astype(str), k["slug"]))).fillna("")
    return it.reset_index(drop=True)


def _wilson(k, n):
    if n == 0:
        return [None, None]
    z, p = 1.96, k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(float(c - h), 3), round(float(c + h), 3)]


# ------------------------------------------------------------------------------------------------ labels
def stage_labels(a):
    it = _items(a)
    launches, products = tx.load_similar(a.similar)
    tax = tx.load_taxonomy(a.taxonomy)
    vocab = sorted({c for cs in products["categories"] for c in cs})
    desc = dict(zip(tax["name"], tax["description"]))
    om = tx.own_and_majority(launches, products)
    lab = launches.merge(om, on="launch_id")
    # launches of the item table that have no similar-products row: (a) still possible via their slug
    cats = dict(zip(products["slug"], products["categories"]))
    ce = tx.CategoryEmbedder(vocab, desc)
    ef = f"{a.out}/launch_emb.npy"
    if os.path.exists(ef):
        E = np.load(ef)
    else:
        E = ce.encode([tx.launch_text(r) for r in it.itertuples()])
        np.save(ef, E)
    row = {i: k for k, i in enumerate(it["item_id"])}
    lab = lab[lab["launch_id"].isin(row)].copy()
    lab["day"] = lab["launch_id"].map(dict(zip(it["item_id"], it["day"])))
    counts = {r.launch_id: json.loads(r.majority_counts) for r in lab.itertuples()}
    prim = [tx.primary_category(r.own_categories, counts[r.launch_id], r.majority) for r in lab.itertuples()]
    lab["primary"], lab["primary_source"] = [p[0] for p in prim], [p[1] for p in prim]

    # validation of (c) against (b), split by time: fit on earlier launches, test on later ones
    hv = lab[lab["majority"].notna()].copy()
    Xh = E[[row[i] for i in hv["launch_id"]]]
    res = {"vocab_size": len(vocab), "pasted_with_description": int(len(desc)),
           "launches_with_similar_row": int(len(lab)), "validation": {}}

    def agree(model, m_test):
        Xt = Xh[m_test]
        top, _ = model.topk(Xt, 3)
        y = hv.loc[m_test, "majority"].tolist()
        allc = [set(json.loads(c)) for c in hv.loc[m_test, "majority_counts"]]
        d = hv.loc[m_test, "day"].to_numpy()
        t1 = np.array([t[0] == yy for t, yy in zip(top, y)], float)
        t3 = np.array([yy in t for t, yy in zip(top, y)], float)
        any1 = np.array([t[0] in s for t, s in zip(top, allc)], float)
        return t1, t3, any1, d, top, y

    days = hv["day"].to_numpy()
    m_fit_val, m_val = days < VAL_FROM, (days >= VAL_FROM) & (days < TEST_FROM)
    m_fit_test, m_test = days < TEST_FROM, days >= TEST_FROM
    choice = {}
    for name, alpha in (("zero-shot (name + description)", None), ("centroid alpha 0.0", 0.0),
                        ("centroid alpha 0.3", 0.3), ("centroid alpha 0.6", 0.6)):
        if alpha is not None:
            ce.fit_centroids(Xh[m_fit_val], hv.loc[m_fit_val, "majority"].tolist(), alpha)
        else:
            ce.C = ce.C0.copy()
        t1, t3, _, d, _, _ = agree(ce, m_val)
        choice[name] = {"alpha": alpha, "val_top1": round(float(t1.mean()), 4), "val_top3": round(float(t3.mean()), 4)}
    best = max(choice, key=lambda k: choice[k]["val_top1"])
    res["validation"]["model_choice_on_jul_aug"] = choice
    res["validation"]["chosen"] = best
    for name in ("zero-shot (name + description)", best):
        alpha = choice[name]["alpha"]
        if alpha is None:
            ce.C = ce.C0.copy()
        else:
            ce.fit_centroids(Xh[m_fit_test], hv.loc[m_fit_test, "majority"].tolist(), alpha)
        t1, t3, any1, d, top, y = agree(ce, m_test)
        e = {"fit_on": f"launches before {TEST_FROM}" if alpha is not None else "no launches",
             "test": f"launches {TEST_FROM} to Nov 1", "top1_vs_majority": tx.day_bootstrap_mean(t1, d, NB),
             "top3_contains_majority": tx.day_bootstrap_mean(t3, d, NB),
             "top1_is_any_similar_category": tx.day_bootstrap_mean(any1, d, NB)}
        # by majority share: is (b) itself confident?
        sh = hv.loc[m_test, "majority_share"].to_numpy()
        e["top1_by_majority_share"] = {f">= {q}": round(float(t1[sh >= q].mean()), 4) for q in (0.4, 0.6, 0.8)}
        if alpha is not None:
            per = {}
            n_all = hv["majority"].value_counts()
            for c in n_all[n_all >= 20].index:
                m = np.array([yy == c for yy in y])
                if m.sum() == 0:
                    continue
                k1, k3 = int(t1[m].sum()), int(t3[m].sum())
                predc = np.array([t[0] == c for t in top])
                per[c] = {"n_launches_all": int(n_all[c]), "n_test": int(m.sum()), "top1_recall": round(k1 / m.sum(), 3),
                          "top1_recall_ci95": _wilson(k1, int(m.sum())), "top3_recall": round(k3 / m.sum(), 3),
                          "top1_precision": round(float((predc & m).sum() / max(predc.sum(), 1)), 3)}
            e["per_category"] = per
            cm = pd.DataFrame({"true": y, "pred": [t[0] for t in top]})
            cm = cm[cm["true"] != cm["pred"]].value_counts().head(15)
            e["most_common_confusions"] = [{"true": t, "pred": p, "n": int(n)} for (t, p), n in cm.items()]
        res["validation"][name] = e
        print(name, json.dumps({k: e[k] for k in ("top1_vs_majority", "top3_contains_majority", "top1_is_any_similar_category")}), flush=True)

    # final labels for every launch of the item table
    alpha = choice[best]["alpha"]
    lab_all = hv  # (b)-labelled launches
    ce.fit_centroids(Xh, lab_all["majority"].tolist(), alpha if alpha is not None else 0.3)
    top_all, s_all = ce.topk(E, 3)
    # 00:05-knowable label for backtest days: centroids from launches before the first backtest day only
    ce2 = tx.CategoryEmbedder.__new__(tx.CategoryEmbedder)
    ce2.m, ce2.categories, ce2.C0 = ce.m, ce.categories, ce.C0
    early = hv["day"].to_numpy() < BACKTEST_FROM
    ce2.fit_centroids(Xh[early], hv.loc[early, "majority"].tolist(), alpha if alpha is not None else 0.3)
    top_pre, _ = ce2.topk(E, 1)
    ce.C = ce.C0.copy()
    top_zs, _ = ce.topk(E, 1)
    L = it[["item_id", "day", "slug", "title"]].copy()
    by_id = lab.set_index("launch_id")
    rows = []
    for k, r in enumerate(L.itertuples()):
        own = list(by_id.loc[r.item_id, "own_categories"]) if r.item_id in by_id.index else \
            list(cats.get(r.slug) or cats.get(tx.norm_slug(r.slug)) or [])
        if r.item_id in by_id.index:
            b = by_id.loc[r.item_id]
            maj, share, cnt, n_sim = b["majority"], b["majority_share"], json.loads(b["majority_counts"]), int(b["n_similar"])
            if not isinstance(maj, str):
                maj, share = None, None
        else:
            maj, share, cnt, n_sim = None, None, {}, 0
        p, src = tx.primary_category(own, cnt, maj)
        if p is None:
            p, src = top_all[k][0], "embedding"
        rows.append({"item_id": r.item_id, "day": r.day, "primary": p, "source": src,
                     "majority": maj, "majority_share": share, "n_similar": n_sim, "own_categories": own,
                     "similar_category_counts": json.dumps(cnt), "embedding_top3": top_all[k],
                     "embedding_top3_scores": [round(float(x), 4) for x in s_all[k]],
                     "embedding_0005_pre_april": top_pre[k][0], "embedding_zero_shot": top_zs[k][0]})
    out = pd.DataFrame(rows)
    out.to_parquet(f"{a.out}/launch_categories.parquet")
    res["assignment"] = {"launches": int(len(out)), "by_source": out["source"].value_counts().to_dict(),
                         "categories_used": int(out["primary"].nunique()),
                         "categories_with_20_plus_launches": int((out["primary"].value_counts() >= 20).sum())}
    json.dump(res, open(f"{a.out}/labels_results.json", "w"), indent=1, default=float)
    products.to_parquet(f"{a.out}/products.parquet")
    launches.to_parquet(f"{a.out}/similar_launches.parquet")
    print(json.dumps(res["assignment"]), flush=True)
    sync([f"{a.out}/launch_categories.parquet", f"{a.out}/labels_results.json", f"{a.out}/products.parquet",
          f"{a.out}/similar_launches.parquet"], a.sync)


# ------------------------------------------------------------------------------------------------ competitors
def _structural_days(a):
    out = {}
    for f in sorted(glob.glob(f"{a.structural}/backtest/*.json")) + sorted(glob.glob(f"{a.structural}/*/shortlist.json")):
        d = json.load(open(f))
        kind = "backtest" if "/backtest/" in f else "shortlist"
        out[(d["day"], kind)] = d
    return out


def stage_competitors(a):
    lc = pd.read_parquet(f"{a.out}/launch_categories.parquet").set_index("item_id")
    products = pd.read_parquet(f"{a.out}/products.parquet")
    products["categories"] = products["categories"].map(list)
    P = products.set_index("slug", drop=False)
    launches = pd.read_parquet(f"{a.out}/similar_launches.parquet").set_index("launch_id")
    top = tx.category_top_reviewed(products)
    it = _items(a).set_index("item_id")
    days = _structural_days(a)
    rows = []
    for (day, kind), d in days.items():
        for l in d["launches"]:
            i = str(l["id"])
            if i not in lc.index:
                continue
            c = lc.loc[i]
            sim = list(launches.loc[i, "similar"]) if i in launches.index else []
            own = {it.loc[i, "slug"], tx.norm_slug(it.loc[i, "slug"])} if i in it.index else set()
            if i in launches.index:
                own |= {launches.loc[i, "product_slug"], launches.loc[i, "launch_slug"]}
            cnt = json.loads(c["similar_category_counts"])
            lcats = {c["primary"]} | set(c["own_categories"]) | {k for k, v in cnt.items() if c["n_similar"] and v / c["n_similar"] >= 0.4}
            comp = tx.competitor_set(sorted(lcats), c["primary"], sim, own, P, top, k=5)
            rows.append({"day": day, "set": kind, "item_id": i, "name": l.get("name"), "primary": c["primary"],
                         "category_source": c["source"], "launch_categories": sorted(lcats),
                         "n_competitors": len(comp), "n_from_similar": sum(x["source"].startswith("ph_similar") for x in comp),
                         "competitors": json.dumps(comp),
                         "similar_fetched_at": launches.loc[i, "fetched_at"] if i in launches.index else None})
    out = pd.DataFrame(rows)
    out.to_parquet(f"{a.out}/competitors.parquet")
    res = {"launch_days": int(out[["day", "set"]].drop_duplicates().shape[0]), "launches": int(len(out)),
           "by_set": out["set"].value_counts().to_dict(),
           "with_5_competitors": round(float((out["n_competitors"] >= 5).mean()), 4),
           "mean_from_ph_similar": round(float(out["n_from_similar"].mean()), 2),
           "share_with_any_ph_similar": round(float((out["n_from_similar"] > 0).mean()), 4),
           "share_with_no_similar_row": round(float(out["similar_fetched_at"].isna().mean()), 4),
           "by_category_source": out["category_source"].value_counts().to_dict()}
    json.dump(res, open(f"{a.out}/competitors_results.json", "w"), indent=1)
    print(json.dumps(res), flush=True)
    sync([f"{a.out}/competitors.parquet", f"{a.out}/competitors_results.json"], a.sync)


# ------------------------------------------------------------------------------------------------ residual
def stage_residual(a):
    lc = pd.read_parquet(f"{a.out}/launch_categories.parquet").set_index("item_id")
    rows = []
    for (day, kind), d in _structural_days(a).items():
        if kind != "backtest":
            continue
        truth = d["truth"]["by_id"]
        n = len(d["launches"])
        for l in d["launches"]:
            i = str(l["id"])
            t = truth.get(i)
            if not t or t.get("final_rank") is None or i not in lc.index:
                continue
            c = lc.loc[i]
            rows.append({"day": day, "item_id": i, "n_launches": n, "structural_rank": int(l["structural_rank"]),
                         "real_rank": int(t["final_rank"]), "primary": c["primary"], "category_source": c["source"],
                         "cat_0005": c["embedding_0005_pre_april"], "cat_zero_shot": c["embedding_zero_shot"]})
    R = pd.DataFrame(rows)
    R["miss"] = R["real_rank"] - R["structural_rank"]
    R["miss_pct"] = R["miss"] / R["n_launches"]
    R["real_top3"], R["struct_top3"] = R["real_rank"] <= 3, R["structural_rank"] <= 3
    for col in ("primary", "cat_0005", "cat_zero_shot"):
        R["n_same_" + col] = R.groupby(["day", col])["item_id"].transform("size") - 1
    R.to_parquet(f"{a.out}/residual_rows.parquet")
    res = {"days": int(R["day"].nunique()), "launches": int(len(R)), "model": "frozen structural backtest (arm 3)",
           "miss": "real rank - structural rank (positive = finished below its structural rank)"}
    res["overall"] = {"mean_abs_miss": round(float(R["miss"].abs().mean()), 2),
                      "struct_top3_capture": tx.day_bootstrap_mean(R.loc[R.real_top3, "struct_top3"].to_numpy(float),
                                                                   R.loc[R.real_top3, "day"].to_numpy(), NB)}
    vc = R["primary"].value_counts()
    cats = vc[vc >= 20].index.tolist()
    per = {}
    for c in cats:
        g = R[R["primary"] == c]
        t3 = g[g.real_top3]
        e = {"launches": int(len(g)), "days": int(g["day"].nunique()),
             "mean_miss": tx.day_bootstrap_mean(g["miss"].to_numpy(float), g["day"].to_numpy(), NB),
             "mean_miss_pct_of_lineup": round(float(g["miss_pct"].mean()), 4),
             "sd_miss": round(float(g["miss"].std()), 2), "iqr_miss": [float(g["miss"].quantile(.25)), float(g["miss"].quantile(.75))],
             "mean_abs_miss": round(float(g["miss"].abs().mean()), 2),
             "real_top3_launches": int(len(t3)),
             "real_top3_missed_by_struct_top3": round(float((~t3.struct_top3).mean()), 4) if len(t3) else None,
             "struct_top3_capture": tx.day_bootstrap_mean(t3["struct_top3"].to_numpy(float), t3["day"].to_numpy(), NB) if len(t3) else None,
             "category_source_mix": g["category_source"].value_counts().to_dict()}
        over = g.sort_values("miss").head(3)
        under = g.sort_values("miss", ascending=False).head(3)
        e["over_performers"] = [{"day": r.day, "item_id": r.item_id, "structural_rank": r.structural_rank, "real_rank": r.real_rank} for r in over.itertuples()]
        e["under_performers"] = [{"day": r.day, "item_id": r.item_id, "structural_rank": r.structural_rank, "real_rank": r.real_rank} for r in under.itertuples()]
        per[c] = e
    res["per_category"] = per
    # is the category itself informative about the miss? (between-category share of variance, permutation test)
    g20 = R[R["primary"].isin(cats)]
    rng = np.random.default_rng(0)
    def r2(lbl):
        m = g20.groupby(lbl)["miss"].transform("mean")
        return float(((m - g20["miss"].mean()) ** 2).sum() / ((g20["miss"] - g20["miss"].mean()) ** 2).sum())
    obs = r2(g20["primary"].to_numpy())
    perm = [r2(rng.permutation(g20["primary"].to_numpy())) for _ in range(500)]
    res["category_explains_miss"] = {"between_category_share_of_variance": round(obs, 4),
                                     "permutation_p": round(float(np.mean(np.array(perm) >= obs)), 4),
                                     "permutation_mean": round(float(np.mean(perm)), 4), "launches": int(len(g20))}
    # same-day category competition vs the miss
    comp = {}
    for col, label in (("primary", "Similar-Products label (fetched Nov 1; not knowable at 00:05)"),
                       ("cat_0005", "classifier fit on launches before Apr 1 (knowable at 00:05)"),
                       ("cat_zero_shot", "zero-shot classifier (knowable at 00:05)")):
        x = R["n_same_" + col].to_numpy(float)
        comp[col] = {"label_source": label, **_competition_test(R, x)}
    res["same_day_competition"] = comp
    json.dump(res, open(f"{a.out}/residual_results.json", "w"), indent=1, default=float)
    print(json.dumps({k: res[k] for k in ("overall", "category_explains_miss")}, default=float), flush=True)
    for col, e in comp.items():
        print(col, json.dumps({k: v for k, v in e.items() if k != "label_source"}, default=float), flush=True)
    sync([f"{a.out}/residual_rows.parquet", f"{a.out}/residual_results.json"], a.sync)


def _competition_test(R: pd.DataFrame, x: np.ndarray) -> dict:
    """Within-day association of the miss with the number of same-category launches that day, controlling for
    structural rank and line-up size (OLS with day fixed effects via demeaning); day-cluster bootstrap."""
    from scipy.stats import spearmanr
    df = R.assign(x=x)
    def coef(d):
        cols = ["miss", "x", "structural_rank"]
        dm = d[cols] - d.groupby("day")[cols].transform("mean")
        X = dm[["x", "structural_rank"]].to_numpy(); y = dm["miss"].to_numpy()
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        return float(b[0])
    names = df["day"].unique()
    groups = {d: g for d, g in df.groupby("day")}
    rng = np.random.default_rng(1)
    point = coef(df)
    bs = []
    for _ in range(1000):
        pick = rng.choice(names, len(names), replace=True)
        bs.append(coef(pd.concat([groups[d].assign(day=f"{d}#{k}") for k, d in enumerate(pick)])))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    rho = spearmanr(df["x"], df["miss"]).correlation
    top = df[df["structural_rank"] <= 10]
    by = df.assign(b=np.minimum(df["x"], 3)).groupby("b")["miss_pct"].agg(["mean", "size"]).round(4)
    return {"coef_rank_places_per_same_category_launch": {"value": round(point, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)]},
            "spearman_raw": round(float(rho), 4),
            "spearman_struct_top10": round(float(spearmanr(top["x"], top["miss"]).correlation), 4),
            "mean_miss_pct_by_same_category_count(0,1,2,3+)": {int(k): {"mean": float(v["mean"]), "n": int(v["size"])} for k, v in by.iterrows()},
            "share_with_any_same_category_launch": round(float((df["x"] > 0).mean()), 4)}


# ------------------------------------------------------------------------------------------------ leak check
def stage_leak(a):
    """Similar Products were read on Nov 1. How much could that list reflect later popularity?
    (1) share of a launch's Similar Products that first launched AFTER the launch (by launch age);
    (2) reviews of the listed products by launch age; (3) does the competitors' popularity move with the structural
    miss more for older launches (read long after) than for the most recent 300 (read within 12 days)?
    (4) per-category miss with the Similar-Products label vs the label knowable at 00:05."""
    from scipy.stats import spearmanr
    launches = pd.read_parquet(f"{a.out}/similar_launches.parquet")
    products = pd.read_parquet(f"{a.out}/products.parquet").set_index("slug")
    post = {}
    for f in glob.glob(os.path.join(a.products_info, "*.json")):
        try:
            d = json.load(open(f))
        except ValueError:
            continue
        if d.get("post_created_at") and d.get("status") == "ok_post_slug_match":
            post[d.get("slug")] = str(d["post_created_at"])[:10]
    recent = set()
    if a.recent300 and os.path.exists(a.recent300):
        recent = {str(json.loads(l)["launch_id"]) for l in open(a.recent300) if l.strip()}
    rows = []
    for r in launches.itertuples():
        sims = [s for s in r.similar if s in products.index]
        dated = [s for s in sims if s in post]
        fut = [post[s] > r.launch_day for s in dated]
        rv = [np.log1p(products.loc[s, "reviews_count"]) for s in sims]
        rows.append({"launch_id": r.launch_id, "day": r.launch_day, "recent300": r.launch_id in recent,
                     "age_days_at_fetch": (pd.Timestamp("2026-11-01") - pd.Timestamp(r.launch_day)).days,
                     "n_similar": len(sims), "n_dated": len(dated), "n_future": int(sum(fut)),
                     "mean_log_reviews": float(np.mean(rv)) if rv else np.nan})
    L = pd.DataFrame(rows)
    L["age_bucket"] = pd.cut(L["age_days_at_fetch"], [-1, 12, 30, 90, 180, 400], labels=["0-12", "13-30", "31-90", "91-180", "181+"])
    g = L.groupby("age_bucket", observed=True)
    res = {"products_with_a_dated_first_post": int(len(post)),
           "similar_products_launched_after_the_launch": {
               str(k): {"launches": int(len(v)), "share_of_dated_similar_products": round(float(v["n_future"].sum() / max(v["n_dated"].sum(), 1)), 4),
                        "share_of_launches_with_any": round(float((v["n_future"] > 0).mean()), 4),
                        "dated_share": round(float(v["n_dated"].sum() / max(v["n_similar"].sum(), 1)), 3),
                        "mean_log1p_reviews_of_similar": round(float(v["mean_log_reviews"].mean()), 3)} for k, v in g},
           "recent300_vs_older": {
               "recent300": {"launches": int(L["recent300"].sum()),
                             "future_share": round(float(L.loc[L.recent300, "n_future"].sum() / max(L.loc[L.recent300, "n_dated"].sum(), 1)), 4)},
               "older": {"launches": int((~L["recent300"]).sum()),
                         "future_share": round(float(L.loc[~L.recent300, "n_future"].sum() / max(L.loc[~L.recent300, "n_dated"].sum(), 1)), 4)}}}
    R = pd.read_parquet(f"{a.out}/residual_rows.parquet").merge(L[["launch_id", "mean_log_reviews", "recent300", "age_bucket", "n_future"]],
                                                                 left_on="item_id", right_on="launch_id", how="inner")
    R["miss_w"] = R["miss"] - R.groupby("day")["miss"].transform("mean")
    pop = {}
    for name, m in (("recent 300 (read within 12 days)", R["recent300"]), ("older backtest launches", ~R["recent300"])):
        sub = R[m & R["mean_log_reviews"].notna()]
        pop[name] = {"launches": int(len(sub)),
                     "spearman_miss_vs_competitor_reviews": round(float(spearmanr(sub["miss_w"], sub["mean_log_reviews"]).correlation), 4),
                     "spearman_miss_vs_future_similar_count": round(float(spearmanr(sub["miss_w"], sub["n_future"]).correlation), 4)}
        rng = np.random.default_rng(2)
        bs = []
        for _ in range(500):
            k = rng.integers(0, len(sub), len(sub))
            bs.append(spearmanr(sub["miss_w"].to_numpy()[k], sub["mean_log_reviews"].to_numpy()[k]).correlation)
        pop[name]["ci95_reviews"] = [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])]
    res["competitor_popularity_vs_miss"] = pop
    # labels: per-category mean miss with the Similar-Products label vs the 00:05 label
    RR = pd.read_parquet(f"{a.out}/residual_rows.parquet")
    m1 = RR.groupby("primary")["miss"].agg(["mean", "size"]); m2 = RR.groupby("cat_0005")["miss"].agg(["mean", "size"])
    j = m1[m1["size"] >= 20].join(m2[m2["size"] >= 20], lsuffix="_ph", rsuffix="_0005", how="inner")
    res["per_category_miss_ph_label_vs_0005_label"] = {"categories": int(len(j)),
                                                       "spearman_of_category_means": round(float(spearmanr(j["mean_ph"], j["mean_0005"]).correlation), 4),
                                                       "launch_label_agreement": round(float((RR["primary"] == RR["cat_0005"]).mean()), 4)}
    json.dump(res, open(f"{a.out}/leak_results.json", "w"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float))
    sync([f"{a.out}/leak_results.json"], a.sync)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["labels", "competitors", "residual", "leak"])
    ap.add_argument("--items-dir", required=True)
    ap.add_argument("--similar", required=True)
    ap.add_argument("--taxonomy", required=True)
    ap.add_argument("--structural", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sync", default="")
    ap.add_argument("--products-info", default="")
    ap.add_argument("--recent300", default="")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
