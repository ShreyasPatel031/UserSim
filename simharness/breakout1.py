"""BREAKOUT-1: each day's breakout (the real #1 and its margin) - what it looks like, whether anything frozen before
results picks it, and how much the weekly top 10 would gain from flagging it. No model calls.

  python -m simharness.breakout1 --work WORK [--sync gs://.../tmp/breakout1]

WORK (local copies, private):
  bt/<day>.json                   STRUCT-BT26 structural backtest, every 2026 day (score, rank, pred_votes; truth)
  launches/*.parquet              warehouse launches (slug, makers, poster, topics, tagline, description; weekly/monthly rank)
  tax/launch_categories.parquet   simharness/taxonomy
  similar_products_all.jsonl      raw/ph_alternatives (launch -> product slug, launches to Nov 1)
  page_media.jsonl                raw/ph_api/page_media.jsonl (gallery; read after launch, assumed unchanged since 00:05)
  makers_header/<day>.jsonl       raw/ph_at_launch/<day>/makers_header.jsonl (maker / hunter follower counts, read ~00:18 PT)
  x_buzz/<day>.jsonl              raw/ph_at_launch/<day>/x_buzz_0010.jsonl (Grok X buzz, frozen ~00:20 PT; on-time days only)
  resid_backtest1/*.json          RESID-BACKTEST-1 day files (Stage B v1/v2, person panel; 60 days)
  explain/<day>.json              results/web/explain (persona panel interest; say.predicted_at before 03:30 PT)

Breakout of day D: the launch with final daily rank 1; margin = votes #1 / votes #2; share = votes #1 / the day's votes.
Every feature used for prediction is knowable at 00:05 PT on D.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

RNG = np.random.default_rng(0)
IV = {"high": 1.0, "medium": 0.5, "low": 0.0}


def boot(x, B=4000):
    x = np.array([v for v in x if v is not None and not (isinstance(v, float) and np.isnan(v))], float)
    if len(x) < 2:
        return {"mean": float(x.mean()) if len(x) else None, "lo": None, "hi": None, "n": int(len(x))}
    m = RNG.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 4), "lo": round(float(np.percentile(m, 2.5)), 4), "hi": round(float(np.percentile(m, 97.5)), 4), "n": int(len(x))}


def boot_stat(df, fn, B=2000):
    est = fn(df)
    vals = []
    for _ in range(B):
        s = fn(df.iloc[RNG.integers(0, len(df), len(df))])
        if s is not None and not np.isnan(s):
            vals.append(s)
    return {"est": None if est is None or np.isnan(est) else round(float(est), 4), "lo": round(float(np.percentile(vals, 2.5)), 4) if vals else None,
            "hi": round(float(np.percentile(vals, 97.5)), 4) if vals else None, "n": int(len(df))}


def sp(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    return spearmanr(a[ok], b[ok]).correlation if ok.sum() >= 5 else np.nan


def jl(s):
    try:
        v = json.loads(s) if isinstance(s, str) else s
        return v if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------ load
def load(W):
    rows = []
    for f in sorted(glob.glob(f"{W}/bt/*.json")):
        j = json.load(open(f))
        tr = j["truth"].get("by_id") or {}
        for x in j["launches"]:
            t = tr.get(str(x["id"])) or {}
            rows.append({"id": str(x["id"]), "day": j["day"], "score": x.get("structural_score"), "srank": x.get("structural_rank"),
                         "pred_votes": x.get("pred_votes"), "real_rank": t.get("final_rank"), "votes": t.get("votes")})
    S = pd.DataFrame(rows)
    L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{W}/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
    L["id"] = L.id.astype(str)
    L["d"] = L.day.astype(str).str[:10]
    cats = pd.read_parquet(f"{W}/tax/launch_categories.parquet")
    cats["item_id"] = cats.item_id.astype(str)
    sim = {}
    for l in open(f"{W}/similar_products_all.jsonl"):
        r = json.loads(l)
        if r.get("product_slug"):
            sim[str(r["launch_id"])] = r["product_slug"]
    media = {}
    for l in open(f"{W}/page_media.jsonl"):
        try:
            r = json.loads(l)
        except Exception:  # noqa: BLE001
            continue
        m = r.get("media") or []
        media[str(r.get("id"))] = {"media_count": len(m), "has_video": any((x or {}).get("type") == "video" or (x or {}).get("videoUrl") for x in m)}
    return S, L, cats, sim, media


def features(S, L, cats, sim, media):
    Lx = L.set_index("id")
    lday = dict(zip(L.id, L.d))
    by_prod = {}
    for i, p in sim.items():
        if i in lday:
            by_prod.setdefault(p, []).append(lday[i])
    cat = dict(zip(cats.item_id, cats.primary))
    F = S.copy()
    get = lambda i, c: Lx[c].get(i) if i in Lx.index else None
    F["category"] = F.id.map(cat)
    F["prior_launches_2026"] = [sum(e < d for e in by_prod.get(sim.get(i), [])) if sim.get(i) else np.nan for i, d in zip(F.id, F.day)]
    F["relaunch"] = F.prior_launches_2026.map(lambda x: np.nan if np.isnan(x) else float(x > 0))
    F["tagline_len"] = [len(str(get(i, "tagline") or "")) for i in F.id]
    F["description_len"] = [len(str(get(i, "description") or "")) for i in F.id]
    F["n_topics"] = [len(jl(get(i, "topics"))) for i in F.id]
    mk = [jl(get(i, "makers")) for i in F.id]
    F["n_makers"] = [len(m) for m in mk]
    F["self_hunted"] = [float(str(get(i, "poster") or "") in set(m)) if m else np.nan for i, m in zip(F.id, mk)]
    F["media_count"] = F.id.map(lambda i: media.get(i, {}).get("media_count", np.nan))
    F["has_video"] = F.id.map(lambda i: float(media[i]["has_video"]) if i in media else np.nan)
    return F


# ------------------------------------------------------------------ part 1
def part1(F):
    D = []
    for d, g in F.dropna(subset=["real_rank", "votes"]).groupby("day"):
        g = g.sort_values("real_rank")
        if len(g) < 2 or g.iloc[0].real_rank != 1:
            continue
        v1, v2 = float(g.iloc[0].votes), float(g.iloc[1].votes)
        D.append({"day": d, "id": g.iloc[0].id, "margin": v1 / max(v2, 1), "share": v1 / g.votes.astype(float).sum(), "votes1": v1,
                  "srank_of_1": g.iloc[0].srank, "pred_margin": (lambda p: p[0] / p[1] if len(p) > 1 else np.nan)(sorted(g.pred_votes.dropna(), reverse=True)),
                  "pred_share_top": float(g.pred_votes.max() / g.pred_votes.sum()) if g.pred_votes.notna().any() else np.nan})
    B = pd.DataFrame(D)
    q = lambda x: {f"p{p}": round(float(np.percentile(x, p)), 3) for p in (10, 25, 50, 75, 90)}
    out = {"n_days": len(B), "margin": q(B.margin), "share": q(B.share), "margin_ge_1_5_share": round(float((B.margin >= 1.5).mean()), 4),
           "structural_rank_of_real_1": {"1": round(float((B.srank_of_1 == 1).mean()), 4), "2-3": round(float(B.srank_of_1.between(2, 3).mean()), 4),
                                          "4-10": round(float(B.srank_of_1.between(4, 10).mean()), 4), ">10": round(float((B.srank_of_1 > 10).mean()), 4)},
           "structural_predicts_margin": {"spearman_pred_margin_vs_margin": boot_stat(B, lambda h: sp(h.pred_margin, h.margin)),
                                          "spearman_pred_top_share_vs_share": boot_stat(B, lambda h: sp(h.pred_share_top, h.share)),
                                          "median_pred_margin": round(float(B.pred_margin.median()), 3), "median_real_margin": round(float(B.margin.median()), 3)}}
    W1 = B.merge(F, on=["day", "id"], how="left")
    W1["big"] = W1.margin >= W1.margin.median()
    feats = ["score", "pred_votes", "prior_launches_2026", "relaunch", "tagline_len", "description_len", "n_topics", "n_makers", "self_hunted", "media_count", "has_video"]
    # (a) among real #1s: which 00:05 features go with a bigger margin
    out["margin_vs_feature_among_winners"] = {f: {"coverage": int(W1[f].notna().sum()), "spearman_with_margin": boot_stat(W1, lambda h: sp(h[f], h.margin))} for f in feats}
    cat_rows = []
    for c, g in W1.dropna(subset=["category"]).groupby("category"):
        if len(g) >= 8:
            cat_rows.append({"category": c, "n_wins": len(g), "median_margin": round(float(g.margin.median()), 3),
                             "big_margin_share_minus_rest": boot_stat(W1.dropna(subset=["category"]).assign(_c=lambda h: h.category == c),
                                                                       lambda h: h[h._c].big.mean() - h[~h._c].big.mean())})
    out["margin_by_category_among_winners"] = sorted(cat_rows, key=lambda r: -r["median_margin"])
    # (b) is the winner recognisable among the day's structural top 10? within-day AUC of each feature, beyond structural rank
    T = F[F.srank <= 10].dropna(subset=["real_rank"]).copy()
    T["is1"] = T.real_rank == 1

    def day_auc(col, sign=1):
        res = []
        for d, g in T.groupby("day"):
            if g.is1.sum() != 1 or g[col].isna().all():
                continue
            s = sign * g[col].astype(float)
            pos = s[g.is1].iloc[0]
            neg = s[~g.is1].dropna()
            if np.isnan(pos) or not len(neg):
                continue
            res.append(((neg < pos).sum() + 0.5 * (neg == pos).sum()) / len(neg))
        return res
    out["winner_auc_within_structural_top10"] = {"structural_rank": boot(day_auc("srank", -1))}
    for f in feats[2:]:
        out["winner_auc_within_structural_top10"][f] = boot(day_auc(f))
    cat_share = T.dropna(subset=["category"]).groupby("category").agg(n=("is1", "size"), win_rate=("is1", "mean"))
    out["win_rate_by_category_top10_launches"] = cat_share[cat_share.n >= 40].sort_values("win_rate", ascending=False).round(4).reset_index().to_dict("records")
    return out, B


# ------------------------------------------------------------------ part 2
def line_scores(W, F, L):
    """{line: {(day, id): score}} for lines frozen before results."""
    slug2id = dict(zip(L.slug.astype(str), L.id))
    lines = {}
    # X buzz (00:10 PT freeze; on-time files only)
    for f in sorted(glob.glob(f"{W}/x_buzz/*.jsonl")):
        d = os.path.basename(f)[:10]
        for l in open(f):
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            if r.get("window") not in (None, "pre_launch") or r.get("day") != d:
                continue
            i = slug2id.get(str(r.get("slug")))
            if not i:
                continue
            for k, nm in (("post_count", "x_buzz:posts"), ("distinct_account_count", "x_buzz:accounts"), ("total_likes_plus_reposts", "x_buzz:engagement"),
                          ("largest_poster_followers", "x_buzz:largest_poster_followers")):
                v = r.get(k)
                if isinstance(v, (int, float)):
                    lines.setdefault(nm, {})[(d, i)] = float(np.log1p(v))
            lines.setdefault("x_buzz:maker_preannounced", {})[(d, i)] = float(bool(r.get("maker_preannounced_ph_launch")))
    # maker / hunter followers at ~00:18 PT
    for f in sorted(glob.glob(f"{W}/makers_header/*.jsonl")):
        d = os.path.basename(f)[:10]
        agg = {}
        for l in open(f):
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            for p in r.get("posts") or []:
                i = slug2id.get(str(p))
                if i and isinstance(r.get("followers"), (int, float)):
                    agg.setdefault(i, []).append((r["followers"], set(r.get("roles") or [])))
        for i, v in agg.items():
            lines.setdefault("team:max_followers", {})[(d, i)] = float(np.log1p(max(x for x, _ in v)))
            lines.setdefault("team:sum_followers", {})[(d, i)] = float(np.log1p(sum(x for x, _ in v)))
            h = [x for x, r in v if "hunter" in r]
            if h:
                lines.setdefault("team:hunter_followers", {})[(d, i)] = float(np.log1p(max(h)))
    # RESID-BACKTEST-1 (60 days, frozen by construction: histories to D-1)
    for f in sorted(glob.glob(f"{W}/resid_backtest1/*.json")):
        j = json.load(open(f))
        for r in j["rows"]:
            for k, v in r.items():
                if ":" in k and v is not None and not k.endswith("_established"):
                    lines.setdefault("resid_bt1:" + k, {})[(j["day"], r["id"])] = float(v)
    # persona-panel interest in the explain files (say.predicted_at before 03:30 PT)
    for f in sorted(glob.glob(f"{W}/explain/*.json")):
        j = json.load(open(f))
        d = j["day"]
        cut = pd.Timestamp(f"{d} 03:30", tz="America/Los_Angeles").tz_convert("UTC")
        for i, Lr in j["launches"].items():
            say = Lr.get("say") or {}
            pa = say.get("predicted_at")
            if not pa or pd.Timestamp(pa) > cut:
                continue
            items = (say.get("persona_panel") or {}).get("items") or []
            w = [(it.get("n_people") or 0, IV[it["interest"]]) for it in items if it.get("interest") in IV]
            if w and sum(a for a, _ in w):
                lines.setdefault("persona_panel:interest", {})[(d, str(i))] = sum(a * b for a, b in w) / sum(a for a, _ in w)
    return lines


def part2(F, B, lines):
    T = F[F.srank <= 10].dropna(subset=["real_rank"]).copy()
    T["is1"] = T.real_rank == 1
    margin = dict(zip(B.day, B.margin))
    out = {}
    for nm, sc in sorted(lines.items()):
        T["s"] = [sc.get((d, i), np.nan) for d, i in zip(T.day, T.id)]
        aucs, aucs_struct, rows = [], [], []
        for d, g in T.groupby("day"):
            if g.is1.sum() != 1 or g.s.notna().sum() < 3 or np.isnan(g[g.is1].s.iloc[0]):
                continue
            pos, neg = g[g.is1].s.iloc[0], g[~g.is1].s.dropna()
            aucs.append(((neg < pos).sum() + 0.5 * (neg == pos).sum()) / len(neg))
            ps, ns = -g[g.is1].srank.iloc[0], -g[~g.is1].srank
            aucs_struct.append(((ns < ps).sum() + 0.5 * (ns == ps).sum()) / len(ns))
            z = (g.s - g.s.mean()) / (g.s.std() + 1e-9)
            rows.append({"day": d, "margin": margin.get(d), "top_z": float(z.max()), "winner_z": float(z[g.is1].iloc[0])})
        R = pd.DataFrame(rows)
        out[nm] = {"n_days": len(aucs), "n_launches": int(sum(1 for k in sc)),
                   "auc_real1_in_structural_top10": boot(aucs), "structural_rank_auc_same_days": boot(aucs_struct),
                   "auc_minus_structural": boot(np.array(aucs) - np.array(aucs_struct)) if aucs else None,
                   "spearman_top_z_with_margin": boot_stat(R, lambda h: sp(h.top_z, h.margin)) if len(R) >= 5 else None,
                   "spearman_winner_z_with_margin": boot_stat(R, lambda h: sp(h.winner_z, h.margin)) if len(R) >= 5 else None,
                   "note": "too few days to read" if len(aucs) < 20 else ""}
    return out


# ------------------------------------------------------------------ part 3
def part3(F, L, B):
    mean_margin = float(B.margin.mean())
    S = F.dropna(subset=["pred_votes"]).copy()
    win = dict(zip(B.day, B.id))
    cf = S.pred_votes.copy()
    for d, g in S.groupby("day"):
        i = win.get(d)
        if i is None or i not in set(g.id):
            continue
        others = g[g.id != i].pred_votes
        cf.loc[g[g.id == i].index] = (others.max() if len(others) else g.pred_votes.max()) * mean_margin
    S["cf"] = cf
    out = {"mean_real_margin_used": round(mean_margin, 3)}
    for per, rk, freq in (("week", "weekly_rank", "W-SUN"), ("month", "monthly_rank", "M")):
        Lr = L.dropna(subset=[rk]).copy()
        Lr["p"] = pd.to_datetime(Lr.d).dt.to_period(freq).astype(str)
        S["p"] = pd.to_datetime(S.day).dt.to_period(freq).astype(str)
        base_c, cf_c, missed, recovered = [], [], 0, 0
        for p, g in Lr.groupby("p"):
            pp = pd.Period(p, freq)
            truth = set(g[g[rk] <= 10].id)
            if len(truth) != 10 or pp.start_time < pd.Timestamp("2026-01-01") or pp.end_time > pd.Timestamp(S.day.max()) + pd.Timedelta(days=1):
                continue
            C = S[S.p == p]
            b = set(C.sort_values("pred_votes", ascending=False).id.head(10))
            c = set(C.sort_values("cf", ascending=False).id.head(10))
            base_c.append(len(b & truth) * 10)
            cf_c.append(len(c & truth) * 10)
            m = truth - b
            missed += len(m)
            recovered += len(m & c)
        out[per] = {"periods": len(base_c), "capture_structural": boot(base_c), "capture_if_day_1_flagged_with_mean_margin": boot(cf_c),
                    "weekly_misses": missed, "misses_recovered": recovered, "share_recovered": round(recovered / max(missed, 1), 4)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sync")
    a = ap.parse_args(argv)
    S, L, cats, sim, media = load(a.work)
    F = features(S, L, cats, sim, media)
    res = {"version": "breakout1_v1", "days": int(S.day.nunique()), "launches": int(len(S))}
    res["part1"], B = part1(F)
    lines = line_scores(a.work, F, L)
    res["part2"] = part2(F, B, lines)
    res["part3"] = part3(F, L, B)
    os.makedirs(f"{a.work}/out", exist_ok=True)
    json.dump(res, open(f"{a.work}/out/breakout1.json", "w"), indent=1, default=str)
    B.to_parquet(f"{a.work}/out/breakouts.parquet", index=False)
    if a.sync:
        subprocess.run(["gsutil", "-q", "-m", "cp", f"{a.work}/out/*", a.sync + "/"], check=False)
    print(json.dumps(res, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main()
