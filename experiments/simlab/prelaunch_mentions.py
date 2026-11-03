"""PH pre-launch campaign sweep, scored (orchestrator + Shreyas, Nov 3). Mentions from Data Feeder's free-route sweep
(raw/ph_prelaunch_mentions/: HN Algolia, Reddit via Arctic Shift (6 launch subreddits, posts), Bluesky public AppView,
dev.to tag listings; X first page per launch day for Oct only), each dated, kept only if posted in
[launch day 00:00 PT - 7 days, launch day 00:00 PT). LinkedIn / Indie Hackers / Medium / Substack: blocked on free routes.
Per launch (strong = domain, ph_link, or name + "product hunt"; any = also the distinctive name alone):
  pm_strong_n, pm_any_n, pm_strong_authors, pm_any_authors   counts and distinct authors (log1p)
  pm_reach_max, pm_reach_sum   author followers where public (Bluesky, X), log1p
  pm_ph_phrase                 a mention says "product hunt" / links the PH page
  pm_hn_n, pm_reddit_n, pm_bluesky_n, pm_devto_n, pm_x_n   channel mix (strong + any)
X is dropped from the main features (Oct only, first page) and kept as a sensitivity variant.
Months count only where the sweep finished every main channel (coverage.json channel_status); others are left out.
1. Gate: residual = log1p(votes) - honest (out-of-sample honest launch model); per day the Spearman of each feature
   with the residual over that day's launches, mean over days, 95% bootstrap over days. Passes if the interval is > 0.
2. Boards: honest + day terms (control) vs control + pm_*, Poisson LightGBM, 5 seeds, rolling monthly (test = covered
   months, train = all earlier months, features NaN where not covered), daily / weekly / monthly top 3/5/10 paired.
usage: SIMLAB_DATA=data_v2 python -m simlab.prelaunch_mentions <dir with mentions.jsonl, launches.json, coverage.json> <honest_preds.parquet>"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from . import vote_model2 as V, e1_honest as EH

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = ["hn", "reddit", "bluesky", "devto"]
STRONG = {"domain", "ph_link", "name+ph"}


def covered_months(cov):
    return sorted(m for m, v in cov["months"].items() if all(v["channel_status"].get(c) == "done" for c in MAIN))


def features(src, with_x=False):
    L = pd.DataFrame(json.load(open(os.path.join(src, "launches.json"))))
    M = pd.read_json(os.path.join(src, "mentions.jsonl"), lines=True, dtype={"launch_id": str}, convert_dates=False)
    M = M.merge(L[["launch_id", "window_start", "window_end"]].astype(str), on="launch_id")
    t = pd.to_datetime(M.posted_at, utc=True, format="ISO8601")
    M = M[(t >= pd.to_datetime(M.window_start, utc=True)) & (t < pd.to_datetime(M.window_end, utc=True))]
    if not with_x:
        M = M[M.channel != "x"]
    M = M.assign(strong=M.match.isin(STRONG), fol=pd.to_numeric(M.author_followers, errors="coerce"),
                 ph=M.match.isin({"ph_link", "name+ph"}) | M.text.fillna("").str.contains(r"product ?hunt", case=False))
    g, gs = M.groupby("launch_id"), M[M.strong].groupby("launch_id")
    F = pd.DataFrame(index=L.launch_id.astype(str))
    F["pm_any_n"] = np.log1p(g.size()); F["pm_strong_n"] = np.log1p(gs.size())
    F["pm_any_authors"] = np.log1p(g.author.nunique()); F["pm_strong_authors"] = np.log1p(gs.author.nunique())
    F["pm_reach_max"] = np.log1p(g.fol.max()); F["pm_reach_sum"] = np.log1p(g.fol.sum())
    F["pm_ph_phrase"] = g.ph.max().astype(float)
    for c in MAIN + (["x"] if with_x else []):
        F[f"pm_{c}_n"] = np.log1p(M[M.channel == c].groupby("launch_id").size())
    F = F.fillna(0.0)
    F["mon"] = L.set_index(L.launch_id.astype(str)).launch_day.str[:7]
    return F.reset_index(names="id"), int(len(M))


def gate(T, cols, rng):
    T = T.assign(resid=np.log1p(T.votes) - T["honest"])
    out = {}
    for c in cols:
        r = []
        for _, g in T.groupby("day"):
            if len(g) >= 5 and g[c].nunique() > 1:
                r.append(spearmanr(g[c], g.resid).correlation)
        r = np.array(r)
        bs = [r[rng.integers(0, len(r), len(r))].mean() for _ in range(10000)] if len(r) else [np.nan]
        out[c] = {"mean_spearman": round(float(np.mean(r)), 4) if len(r) else None, "ci": [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])],
                  "days": int(len(r)), "passes": bool(len(r) and np.percentile(bs, 2.5) > 0)}
    return out


def monthly(T, col, base):
    """monthly board: per month, overlap of the top k by col with the real monthly top k (out_monthlyRank)."""
    out = {}
    for k in (3, 5, 10):
        a, b = {}, {}
        for m, g in T.groupby("mon"):
            real = set(g[g.out_monthlyRank <= k].id)
            if len(real) == k:
                a[m] = len(set(g.nlargest(k, col).id) & real) / k; b[m] = len(set(g.nlargest(k, base).id) & real) / k
        out[f"monthly_top{k}"] = {m: [round(100 * a[m], 1), round(100 * b[m], 1)] for m in a}
    return out


def main(src, honest_path):
    cov = json.load(open(os.path.join(src, "coverage.json")))
    months = covered_months(cov)
    D, promo, hist, page = EH.load(honest_path)
    from . import store
    _, I, _ = store.load(); I = I.assign(id=I.id.astype(str))
    if "out_monthlyRank" in I:
        D = D.merge(I[["id", "out_monthlyRank"]], on="id", how="left")
    rng = np.random.default_rng(0); res = {"covered_months": months, "draft_status": "Data Feeder sweep (draft until verified)"}
    for variant, wx in (("main (hn, reddit, bluesky, devto)", False), ("+ x (Oct only, first page)", True)):
        Fm, nm = features(src, wx)
        cols = [c for c in Fm if c.startswith("pm_")]
        A = D.merge(Fm.drop(columns="mon"), on="id", how="left")
        A.loc[~A.mon.isin(months), cols] = np.nan
        C = A[A.mon.isin(months)]
        cvg = {m: {"launches_in_model": int((C.mon == m).sum()), "with_any_mention": round(float((C[C.mon == m].pm_any_n > 0).mean()), 3),
                   "with_strong_mention": round(float((C[C.mon == m].pm_strong_n > 0).mean()), 3),
                   "with_ph_phrase": round(float((C[C.mon == m].pm_ph_phrase > 0).mean()), 3)} for m in months}
        r = {"mentions_in_window": nm, "coverage": cvg, "gate_residual_spearman_vs_honest": gate(C, cols, rng)}
        # boards: control vs control + pm_*, rolling monthly over covered months
        parts = []
        for m in months:
            tr, te = A[A.mon < m], A[A.mon == m].copy()
            if not len(te) or (tr.mon.isin(months).sum() == 0 and m != months[0]):
                continue
            c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
            te["mu_control"] = np.mean([EH.fit_seed(tr, te, V.DAY, set(), s) for s in range(5)], 0)
            mono = {"pm_strong_n", "pm_strong_authors", "pm_any_n", "pm_any_authors"}
            te["mu_pm"] = np.mean([EH.fit_seed(tr, te, cols + V.DAY, mono, s) for s in range(5)], 0)
            parts.append(te); print(variant, "month", m, flush=True)
        if parts:
            T = pd.concat(parts)
            r["test_months"] = sorted(T.mon.unique()); r["launches"] = int(len(T)); r["days"] = int(T.day.nunique())
            r["honest launch model alone"] = V.boards(T, "mu_lm", rng); r["control"] = V.boards(T, "mu_control", rng)
            r["control + pm"] = V.boards(T, "mu_pm", rng)
            r["vs_control"] = {k.replace("_vs_lm", ""): v for k, v in V.boards(T, "mu_pm", rng, base="mu_control").items() if k.endswith("_vs_lm")}
            r["by_month"] = {m: {k: [V.boards(g, "mu_pm", rng)[k], V.boards(g, "mu_control", rng)[k]] for k in ("daily_top3", "daily_top5", "daily_top10")}
                             for m, g in T.groupby("mon")}
            if "out_monthlyRank" in T:
                r["monthly [control + pm, control]"] = monthly(T, "mu_pm", "mu_control")
            r["note"] = "first covered month is trained on months without pm_ features (NaN): the model cannot use them there"
        res[variant] = r
    json.dump(res, open(os.path.join(HERE, "reports", "prelaunch_mentions.json"), "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
