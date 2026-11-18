"""Orchestrator diagnostic (uses test outcomes; diagnostic only): one appeal multiplier m_L per launch inside it8's share.
share'_pL = S_pL m_L / sum_j S_pj m_j, m fitted per day by MM (Luce) to the real picks of active people (label-filtered);
EV_m = sum_p A_p K_p share'_pL. Then: how much of log m is predictable from 00:05 features (within-day Spearman per
feature; LODO ridge on all of them, and EV with the predicted m)."""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, "/home/user/UserSim/experiments")
from pipeline import warehouse as W
S_ = "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad"
L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
votes = dict(zip(L.id, L.votes)); rnk = dict(zip(L.id, L.daily_rank))
H = pd.read_parquet(f"{S_}/e5h/honest_preds.parquet"); H["id"] = H.id.astype(str)
lm = {(str(r.day), r.id): float(r.honest) for r in H.itertuples()}
Fc = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
lm.update({(r.day, r.id): -float(np.log(r.predicted_rank)) for r in Fc.itertuples()})
df = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); df["id"] = df.id.astype(str)
FEATS = ["hist_maker_rel_max", "hist_hunter_rel", "hist_maker_top5", "hist_hunter_top5", "promo_posts", "promo_cov", "llm_pitch", "llm_brand",
         "ph_n_media", "ph_has_video", "ph_desc_len", "ph_tagline_len", "ph_n_topics", "ph_n_makers", "ph_self_hunted"]
F = df.set_index("id")[[c for c in FEATS if c in df]]

def topk(s, r, k):
    top = set(np.where(r <= k)[0])
    return len(set(np.argsort(-s)[:k]) & top) / k * 100 if len(top) >= k else np.nan

rows, per = [], []
for f in sorted(glob.glob(f"{S_}/simbt/diag_parts/*.parquet")):
    d = os.path.basename(f)[:10]; X = pd.read_parquet(f); X["id"] = X.id.astype(str)
    ids = sorted(X.id.unique()); ix = {i: k for k, i in enumerate(ids)}; X["j"] = X.id.map(ix).astype(int)
    act = X[X.groupby("person").y.transform("sum") > 0]
    m = np.ones(len(ids)); c = np.bincount(act.j, weights=act.y, minlength=len(ids))
    for _ in range(300):   # MM for the Luce model with person-specific base shares S
        den = act.S * m[act.j.values]; tot = den.groupby(act.person).transform("sum")
        npk = act.groupby("person").y.transform("sum")
        w = np.bincount(act.j, weights=(npk * act.S / tot).values, minlength=len(ids))
        m = np.where(w > 0, (c + 1e-3) / (w + 1e-3), 1.0); m = m / np.exp(np.log(m).mean())
    X["S2"] = X.S * m[X.j.values]; X["S2"] = X.S2 / X.groupby("person").S2.transform("sum")
    ev0 = (X.A * X.K * X.S).groupby(X.j).sum().reindex(range(len(ids))).values
    evm = (X.A * X.K * X.S2).groupby(X.j).sum().reindex(range(len(ids))).values
    kt = X.groupby("person").y.transform("sum"); st = np.where(kt > 0, X.y / kt.clip(lower=1), X.S)
    evs = (X.A * X.K * st).groupby(X.j).sum().reindex(range(len(ids))).values
    v = np.array([votes.get(i, np.nan) for i in ids], float); r = np.array([rnk.get(i, np.nan) for i in ids], float)
    ok = ~np.isnan(v)
    if ok.sum() < 5:
        continue
    row = {"day": d, "n": int(ok.sum())}
    for nm, ev in (("model", ev0), ("launch_mult", evm), ("S_true", evs)):
        row[f"sp_{nm}"] = spearmanr(ev[ok], v[ok]).correlation
        for k in (3, 5, 10):
            row[f"{nm}_top{k}"] = topk(np.where(ok, ev, -1), np.where(ok, r, 99), k)
    per.append(row)
    for i, idd in enumerate(ids):
        rows.append({"day": d, "id": idd, "logm": float(np.log(m[i])), "lm": lm.get((d, idd)), "A_K_S": ev0[i]})
P = pd.DataFrame(per); M = pd.DataFrame(rows).merge(F, left_on="id", right_index=True, how="left")
res = {"note": "DIAGNOSTIC ONLY: m fitted to test-day picks", "days": len(P),
       "spearman_ev_votes": {c: round(float(P[c].mean()), 3) for c in ("sp_model", "sp_launch_mult", "sp_S_true")},
       "topk": {nm: [round(float(P[f"{nm}_top{k}"].mean()), 1) for k in (3, 5, 10)] for nm in ("model", "launch_mult", "S_true")}}
fs = {}
for c in ["lm"] + [x for x in FEATS if x in M]:
    vals = [spearmanr(g[c], g.logm, nan_policy="omit").correlation for _, g in M.groupby("day") if g[c].notna().sum() >= 5 and g[c].nunique() > 1]
    vals = [x for x in vals if not np.isnan(x)]
    fs[c] = (round(float(np.mean(vals)), 3), len(vals)) if vals else None
res["within_day_spearman_logm_vs_feature"] = dict(sorted(fs.items(), key=lambda kv: -abs(kv[1][0]) if kv[1] else 0))
# LODO ridge: predict log m from the 00:05 features (z-scored within day, NaN -> 0), Spearman of predicted vs fitted m
from sklearn.linear_model import Ridge
cols = ["lm"] + [x for x in FEATS if x in M]
Z = M.copy()
for c in cols:
    g = Z.groupby("day")[c]; Z[c] = ((Z[c] - g.transform("mean")) / (g.transform("std") + 1e-9)).fillna(0)
pred = pd.Series(np.nan, index=Z.index)
for d in Z.day.unique():
    tr, te = Z.day != d, Z.day == d
    pred[te] = Ridge(alpha=1.0).fit(Z.loc[tr, cols], Z.loc[tr, "logm"]).predict(Z.loc[te, cols])
Z["pred"] = pred
res["lodo_ridge_spearman_pred_vs_fitted_logm"] = round(float(np.mean([spearmanr(g.pred, g.logm).correlation for _, g in Z.groupby("day")])), 3)
# orchestrator Nov 11: the same LODO ridge with the arrivals EV (no_dormant, honest monthly fits) and |C(L)| added
AE = f"{S_}/simbt/arrivals/ev_per_launch.parquet"
if os.path.exists(AE):
    A = pd.read_parquet(AE); A = A[A.variant == "no_dormant"][["day", "id", "arr", "cand_n"]].rename(columns={"arr": "arr_ev"})
    A["arr_ev"] = np.log1p(A.arr_ev); A["cand_n"] = np.log1p(A.cand_n)
    M2 = M.merge(A, on=["day", "id"], how="left")
    for extra, nm in ((["arr_ev", "cand_n"], "with_arrivals"), (["arr_ev", "cand_n"], "arrivals_only")):
        cols2 = (cols + extra) if nm == "with_arrivals" else extra
        Z2 = M2.copy()
        for c in cols2:
            g = Z2.groupby("day")[c]; Z2[c] = ((Z2[c] - g.transform("mean")) / (g.transform("std") + 1e-9)).fillna(0)
        pr = pd.Series(np.nan, index=Z2.index)
        for d in Z2.day.unique():
            tr, te = Z2.day != d, Z2.day == d
            pr[te] = Ridge(alpha=1.0).fit(Z2.loc[tr, cols2], Z2.loc[tr, "logm"]).predict(Z2.loc[te, cols2])
        Z2["pred"] = pr
        res[f"lodo_ridge_{nm}"] = round(float(np.mean([spearmanr(g.pred, g.logm).correlation for _, g in Z2.groupby("day")])), 3)
    res["arrivals_coverage"] = round(float(M2.arr_ev.notna().mean()), 3)
    # orchestrator 06:50Z Nov 11, team-audience pilot (TFOL=1): LEAKY upper bound (Nov follow lists, undated). Adds the
    # count of complete followers of the team (tcf), the team's summed follower counts (ttot) and the follower-edge
    # arrivals EV (arr_ev_fol) from team_fol_pilot.py; reported on all launches and pooled over held launches
    TF_ = f"{S_}/simbt/arrivals_fol/launch_feats.parquet"
    if os.environ.get("TFOL") == "1" and os.path.exists(TF_):
        G = pd.read_parquet(TF_)[["day", "id", "held", "tcf", "ttot", "arr_ev_fol"]]
        M3 = M2.merge(G, on=["day", "id"], how="left"); M3["held"] = M3.held.fillna(False).astype(bool)
        out = {"LEAK": "Nov follow lists, undated: upper bound", "held_launches": int(M3.held.sum()), "launches": int(len(M3))}
        for nm, cols3 in (("with_arrivals", cols + ["arr_ev", "cand_n"]), ("with_arrivals_fol", cols + ["arr_ev", "cand_n", "tcf", "ttot", "arr_ev_fol"]),
                          ("fol_only", ["tcf", "ttot", "arr_ev_fol"])):
            Z3 = M3.copy()
            for c in cols3:
                g = Z3.groupby("day")[c]; Z3[c] = ((Z3[c] - g.transform("mean")) / (g.transform("std") + 1e-9)).fillna(0)
            pr = pd.Series(np.nan, index=Z3.index)
            for d in Z3.day.unique():
                tr, te = Z3.day != d, Z3.day == d
                pr[te] = Ridge(alpha=1.0).fit(Z3.loc[tr, cols3], Z3.loc[tr, "logm"]).predict(Z3.loc[te, cols3])
            Z3["pred"] = pr
            Z3["pp"] = Z3.groupby("day").pred.rank(pct=True); Z3["mp"] = Z3.groupby("day").logm.rank(pct=True)
            h = Z3[Z3.held]
            out[nm] = {"lodo_spearman_all": round(float(np.mean([spearmanr(g.pred, g.logm).correlation for _, g in Z3.groupby("day")])), 3),
                       "held_pooled_within_day_pct": round(float(spearmanr(h.pp, h.mp).correlation), 3) if len(h) > 5 else None}
        fsp = {}
        for c in ("tcf", "ttot", "arr_ev_fol"):
            vals = [spearmanr(g[c], g.logm, nan_policy="omit").correlation for _, g in M3.groupby("day") if g[c].notna().sum() >= 5 and g[c].nunique() > 1]
            fsp[c] = round(float(np.nanmean(vals)), 3) if vals else None
        out["within_day_spearman_logm_vs_feature"] = fsp
        res["team_fol_pilot"] = out
    # orchestrator 07:00Z Nov 11 P1: audience SIZE. All follower counts in the LM cache were read AFTER launch (honest.py:
    # PH counts re-read from data/days/, X counts from later fetches; promo_reactions read at fetch time) -> LATE.
    # promo_posts is dated before launch -> honest at 00:05 (already in FEATS). Log1p, z-scored within day.
    AUD = {"ph_hunter_followers": "late", "ph_maker_sum_followers": "late", "ph_maker_max_followers": "late",
           "x_maker_sum_followers": "late", "x_company_followers": "late", "promo_reactions": "late", "promo_posts": "honest"}
    Fa = df.set_index("id")[[c for c in AUD if c in df]].apply(lambda x: np.log1p(x.clip(lower=0)))
    M4 = M2.drop(columns=[c for c in AUD if c in M2], errors="ignore").merge(Fa, left_on="id", right_index=True, how="left")
    if os.environ.get("TFOL") == "1" and os.path.exists(TF_):
        M4 = M4.merge(pd.read_parquet(TF_)[["day", "id", "ttot"]], on=["day", "id"], how="left")
    aud = [c for c in AUD if c in M4 and c not in cols] + (["ttot"] if "ttot" in M4 else [])   # promo_posts is already in cols
    out = {"flags": {**AUD, "ttot": "late (store_v3 followers header, Nov)"}}
    for nm, cols4 in (("with_arrivals", cols + ["arr_ev", "cand_n"]), ("with_arrivals_audience", cols + ["arr_ev", "cand_n"] + aud),
                      ("audience_only", aud), ("with_arrivals_audience_honest_only", cols + ["arr_ev", "cand_n"])):
        Z4 = M4.copy()
        for c in cols4:
            g = Z4.groupby("day")[c]; Z4[c] = ((Z4[c] - g.transform("mean")) / (g.transform("std") + 1e-9)).fillna(0)
        pr = pd.Series(np.nan, index=Z4.index); per_d = []
        for d in Z4.day.unique():
            tr, te = Z4.day != d, Z4.day == d
            pr[te] = Ridge(alpha=1.0).fit(Z4.loc[tr, cols4], Z4.loc[tr, "logm"]).predict(Z4.loc[te, cols4])
        Z4["pred"] = pr
        sp = np.array([spearmanr(g.pred, g.logm).correlation for _, g in Z4.groupby("day")])
        out[nm] = round(float(np.nanmean(sp)), 3); out[nm + "_per_day"] = sp.round(3).tolist()
    fsp = {}
    for c in aud:
        vals = [spearmanr(g[c], g.logm, nan_policy="omit").correlation for _, g in M4.groupby("day") if g[c].notna().sum() >= 5 and g[c].nunique() > 1]
        fsp[c] = round(float(np.nanmean(vals)), 3) if vals else None
    out["within_day_spearman_logm_vs_feature"] = fsp
    a, z = np.array(out["with_arrivals_audience_per_day"]), np.array(out["with_arrivals_per_day"])
    rr = np.random.default_rng(0); dd = a - z
    out["delta_audience"] = [round(float(np.nanmean(dd)), 3)] + [round(float(x), 3) for x in np.percentile([np.nanmean(dd[rr.integers(0, len(dd), len(dd))]) for _ in range(5000)], [2.5, 97.5])]
    res["audience_p1"] = out
res["lm_alone_spearman_vs_fitted_logm"] = fs.get("lm")
json.dump(res, open("/home/user/UserSim/experiments/ph_predict/results/launch_mult_diag.json", "w"), indent=1)
print(json.dumps(res, indent=1))
