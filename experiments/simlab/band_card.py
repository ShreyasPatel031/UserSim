"""Validate the /try launch card's numbers that the audit found unvalidated (orchestrator 08:56Z Nov 12), out of sample on the 856
(726 held Sep-Oct page reads + 130 fresh), with the best-constant and category-mean controls.
Band = the page band recipe (d_both, LLM read; band_facts.py B0) trained on launches <= Aug 31; deciles and their bands from 5-fold OOF
training scores, exactly as launch_band_page_v1 builds them. Also the PH-description band (PH rows only, served the PH description).
Card numbers checked: rank band p10-p90 (nominal 80%), votes band p10-p90 (80%), share_top3 / share_top10 (calibration), Spearman of
the score with final votes; coverage split by set (held / fresh), predicted quartile, launch-day size; a percentile-of-day band
(rank / line-up size, p10-p90 per decile) vs the rank band.
Controls: CONST = one band for all (training p10-p90 of rank / votes, overall top-3 / top-10 rate); CAT = deciles of the category mean
(read topics' shrunk base rate of rank-percentile, months strictly before).
    python band_card.py <scratchpad> <launch_band_page_v1.json> <out dir>
"""
import os, sys, json
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "band_facts.py")).read().split("# ---------- retrieval")[0]
exec(SRC)   # D (reads + facts), DT/DE, b0_oof, b0_te, helpers
OUT = sys.argv[3]
DSUM = L.groupby("day").y.apply(lambda s: float(np.expm1(s).sum()))
for Dx in (DT, DE):
    Dx["votes"] = [float(byid[i].votes) for i in Dx.id]; Dx["nday"] = [float(byid[i].nday) for i in Dx.id]; Dx["rq"] = Dx["rank"] / Dx.nday
    Dx["sv"] = Dx.votes / Dx.day.map(DSUM)   # share of the day's votes
# PH-description band (a_ph): PH rows only, OOF on train
ph_te = score(fit(rows(DT, 0)), rows(DE, 0)); ph_oof = np.zeros(len(DT))
for a, b in KFold(5, shuffle=True, random_state=0).split(DT): ph_oof[b] = score(fit(rows(DT.iloc[a], 0)), rows(DT.iloc[b], 0))
# category mean
g_all = {}
for mon in sorted(set(DT.day.str[:7]) | set(DE.day.str[:7])):
    E = L[(L.day < mon + "-01") & L.rp.notna()]; gm = E.rp.mean(); c, s_ = Counter(), Counter()
    for tp, r in zip(E.ptop, E.rp):
        for t in tp: c[t] += 1; s_[t] += r
    g_all[mon] = (gm, {t: (s_[t] + 20 * gm) / (c[t] + 20) for t in c})
cat = lambda Dx: np.array([np.mean([g_all[d[:7]][1].get(t, g_all[d[:7]][0]) for t in tp]) for d, tp in zip(Dx.day, Dx.topics)])
cat_oof, cat_te = cat(DT), cat(DE)
_gm = float(np.nanmean(cat_oof)); cat_oof = np.where(np.isnan(cat_oof), _gm, cat_oof); cat_te = np.where(np.isnan(cat_te), _gm, cat_te)   # first month has no earlier launches

RECENT = (pd.Timestamp(CUT) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
def card(oof, te):
    """deciles from OOF training scores -> per-decile p10/p50/p90 of rank, votes, rank/nday; top-3 / top-10 rates"""
    cuts = np.percentile(oof, np.arange(1, 100)); p_tr = np.searchsorted(cuts, oof, side="left"); p_te = np.searchsorted(cuts, te, side="left")
    dec = lambda p: np.minimum(9, p // 10); B = {}
    for q in range(10):
        g = DT[dec(p_tr) == q]; w = 1
        while len(g) < 20 and w < 10:   # tied scores (CAT) leave empty deciles: widen to neighbours
            g = DT[(dec(p_tr) >= q - w) & (dec(p_tr) <= q + w)]; w += 1
        gr = g[g.day > RECENT]
        B[q] = {"rank": np.percentile(g["rank"], [10, 90]), "votes": np.percentile(g.votes, [10, 90]), "rq": np.percentile(g.rq, [10, 90]),
                "sv": np.percentile(g.sv, [10, 90]), "sv1585": np.percentile(g.sv, [15, 85]), "sv2080": np.percentile(g.sv, [20, 80]), "votes595": np.percentile(g.votes, [5, 95]), "rq1585": np.percentile(g.rq, [15, 85]), "votes_recent": np.percentile(gr.votes if len(gr) >= 20 else g.votes, [10, 90]),
                "top3": float((g["rank"] <= 3).mean()), "top10": float((g["rank"] <= 10).mean()), "top10pct": float((g.rq <= 0.1).mean())}
    return p_te.astype(float), [B[q] for q in dec(p_te)]
def const_card():
    gr = DT[DT.day > RECENT]
    b = {"rank": np.percentile(DT["rank"], [10, 90]), "votes": np.percentile(DT.votes, [10, 90]), "rq": np.percentile(DT.rq, [10, 90]), "sv": np.percentile(DT.sv, [10, 90]), "sv1585": np.percentile(DT.sv, [15, 85]), "sv2080": np.percentile(DT.sv, [20, 80]), "votes595": np.percentile(DT.votes, [5, 95]), "rq1585": np.percentile(DT.rq, [15, 85]),
         "votes_recent": np.percentile(gr.votes, [10, 90]), "top3": float((DT["rank"] <= 3).mean()), "top10": float((DT["rank"] <= 10).mean()), "top10pct": float((DT.rq <= 0.1).mean())}
    return np.zeros(len(DE)), [b] * len(DE)
ARMS = {"page_band": card(b0_oof, b0_te), "ph_desc_band": card(ph_oof, ph_te), "CAT": card(cat_oof, cat_te), "CONST": const_card()}
rk, vt, rq, sv = DE["rank"].values, DE.votes.values, DE.rq.values, DE.sv.values
def inside(B, key, x): return np.array([b[key][0] <= v <= b[key][1] for b, v in zip(B, x)], float)
def boot_cov(v, B_=2000):
    n = len(v); bs = [v[rng.integers(0, n, n)].mean() for _ in range(B_)]; return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1)]
def calib(B, key, hit):
    p = np.array([b[key] for b in B]); return {"predicted": round(float(p.mean()) * 100, 1), "actual": round(float(hit.mean()) * 100, 1), "brier": round(float(((p - hit) ** 2).mean()), 4),
                                               "brier_const": round(float(((float({"top3": (DT["rank"] <= 3), "top10": (DT["rank"] <= 10), "top10pct": (DT.rq <= 0.1)}[key].mean()) - hit) ** 2).mean()), 4)}
pq = ARMS["page_band"][0]; ndays = DE.nday.values; ns = np.percentile(DT.nday, [33.3, 66.7])
SUBS = {"all_856": np.ones(len(DE), bool), "held_726": (DE.set != "fresh").values, "fresh_130": (DE.set == "fresh").values,
        "pred_top_quartile": pq >= 75, "pred_bottom_quartile": pq < 25, "pred_middle": (pq >= 25) & (pq < 75),
        f"small_days(<= {ns[0]:.0f})": ndays <= ns[0], "mid_days": (ndays > ns[0]) & (ndays <= ns[1]), f"large_days(> {ns[1]:.0f})": ndays > ns[1]}
res = {"design": __doc__.split("\n    python")[0], "n": len(DE), "train": len(DT), "day_size_cuts": [float(x) for x in ns], "arms": {}}
for a, (p, B) in ARMS.items():
    o = {"spearman_votes": round(float(spearmanr(p, vt).correlation), 3) if a != "CONST" else 0.0, "spearman_-rank": round(float(spearmanr(p, -rk).correlation), 3) if a != "CONST" else 0.0,
         "width_rank": round(float(np.mean([b["rank"][1] - b["rank"][0] for b in B])), 1), "width_votes_ratio_p90_p10": round(float(np.mean([b["votes"][1] / max(b["votes"][0], 1) for b in B])), 2),
         "width_rq": round(float(np.mean([b["rq"][1] - b["rq"][0] for b in B])), 3), "width_sv_ratio": round(float(np.mean([b["sv"][1] / max(b["sv"][0], 1e-6) for b in B])), 2), "width_sv1585_ratio": round(float(np.mean([b["sv1585"][1] / max(b["sv1585"][0], 1e-6) for b in B])), 2), "width_votes595_ratio": round(float(np.mean([b["votes595"][1] / max(b["votes595"][0], 1) for b in B])), 2), "by_subset": {}}
    ci, cv, cq, cs, cr = inside(B, "rank", rk), inside(B, "votes", vt), inside(B, "rq", rq), inside(B, "sv", sv), inside(B, "votes_recent", vt)
    for s, m in SUBS.items():
        o["by_subset"][s] = {"n": int(m.sum()), "rank_band_cov": boot_cov(ci[m]), "votes_band_cov": boot_cov(cv[m]), "pct_of_day_band_cov": boot_cov(cq[m]), "share_of_day_votes_cov": boot_cov(cs[m]), "votes_recent60_cov": boot_cov(cr[m]), "sv_p15_85_cov": boot_cov(inside(B, "sv1585", sv)[m]), "sv_p20_80_cov": boot_cov(inside(B, "sv2080", sv)[m]),
                             "votes_p5_95_cov": boot_cov(inside(B, "votes595", vt)[m]), "pct_p15_85_cov": boot_cov(inside(B, "rq1585", rq)[m]),
                             "top10pct": calib([b for b, k in zip(B, m) if k], "top10pct", (rq[m] <= 0.1).astype(float)),
                             "top3": calib([b for b, k in zip(B, m) if k], "top3", (rk[m] <= 3).astype(float)), "top10": calib([b for b, k in zip(B, m) if k], "top10", (rk[m] <= 10).astype(float))}
    # calibration of top-3 share by predicted quartile (does the card's share hold at the extremes?)
    res["arms"][a] = o
# paired: page band minus CAT on spearman with votes
idx = np.arange(len(DE)); bs = []
for _ in range(2000):
    j = rng.integers(0, len(DE), len(DE)); bs.append(spearmanr(ARMS["page_band"][0][j], vt[j]).correlation - spearmanr(ARMS["CAT"][0][j], vt[j]).correlation)
res["page_minus_CAT_spearman_votes"] = [round(float(x), 3) for x in np.percentile(bs, [2.5, 50, 97.5])]
json.dump(res, open(os.path.join(OUT, "band_card.json"), "w"), indent=1, default=float)
for a, o in res["arms"].items():
    print(a, {k: v for k, v in o.items() if k != "by_subset"})
    for s, v in o["by_subset"].items(): print("   ", s, v["n"], "rank", v["rank_band_cov"], "votes", v["votes_band_cov"], "pct", v["pct_of_day_band_cov"], "sv", v["share_of_day_votes_cov"], "votes60", v["votes_recent60_cov"], "sv1585", v["sv_p15_85_cov"], "sv2080", v["sv_p20_80_cov"], "v595", v["votes_p5_95_cov"], "top3", v["top3"]["predicted"], v["top3"]["actual"], "top10", v["top10"]["predicted"], v["top10"]["actual"], "top10%", v["top10pct"]["predicted"], v["top10pct"]["actual"])
print("page - CAT spearman votes", res["page_minus_CAT_spearman_votes"])
