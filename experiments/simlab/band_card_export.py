"""Corrected launch-card banding for the page band (orchestrator 08:56Z Nov 12, task B), keyed to launch_band_page_v1's own deciles.
band_card.py (out of sample, 856) found the card off by > 5 points: rank band coverage 91 / 93 / 76% on small / mid / large days,
votes band 66% (nominal 80%), top-10 share predicted 43% vs 33% actual (61% small days vs 18% large). Fixes validated there:
  percentile-of-day band (rank / line-up size, p10-p50-p90): 79.8% overall, 81 / 81 / 79% by day size, 82% fresh, 79 / 85% top / bottom
  quartile; share-of-the-day's-votes band p15-p85: 77.6% overall, 84% fresh; P(top 10% of the day): 8.2% predicted vs 9.2% actual,
  holds by day size and quartile. top-3 / top-10 chances depend on the day's size, so they are given per day-size bucket.
Built from v1's exact 5-fold OOF page-row scores (band_page_export.py up to the final fit); cuts checked against the served v1 file.
    python band_card_export.py <ph-website worktree> <scratchpad> <band_page out dir> <out json>
"""
import os, sys
OUTJ = sys.argv[4]; sys.argv = sys.argv[:4]
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "band_page_export.py")).read().split("idf, mu, sd, m = fit(D)")[0]
exec(SRC)
V1 = json.load(open(os.path.join(BP, "launch_band_page_v1.json")))
same = np.allclose(np.round(cuts, 5), V1["score_percentile_cuts"], atol=1e-4); print("cuts identical to served v1:", same, flush=True)
L["nday"] = L.groupby("day").id.transform("count"); DSUM = L.groupby("day").votes.apply(lambda s: float(pd.to_numeric(s).sum()))
P = P.assign(day=[byid[i].day for i in P.id], nday=[float(L.nday[L.id == i].iat[0]) for i in P.id]); P["rq"] = P["rank"] / P.nday; P["sv"] = P.votes / P.day.map(DSUM)
P["size"] = np.where(P.nday <= 20, "small (<= 20)", np.where(P.nday <= 31, "mid (21-31)", "large (> 31)"))
recent = sorted(L.day.unique())[-56:]; typical = float(L[L.day.isin(recent)].groupby("day").size().median())
out = {"version": "launch_band_card_v2", "keyed_to": "site/launch_band_page_v1.json (same score, same score_percentile_cuts; decile = min(9, percentile // 10))",
       "cuts_identical_to_v1": bool(same), "typical_day_size_last_8_weeks": typical,
       "display": {"rank": "show the percentile-of-day band; in ranks for a day of N launches: rank = max(1, round(q * N)); N = typical_day_size unless the user gives one",
                   "votes": "replace the votes band with the share of the day's votes (p15-p85); in votes only with a stated day total",
                   "chances": "show P(top 10% of the day); top-3 / top-10 chances only per day-size bucket"},
       "validation_out_of_sample_856": {"pct_of_day_band_coverage": 79.8, "by_day_size": [81.4, 80.9, 78.7], "fresh_130": 82.3, "top_bottom_quartile": [79.3, 84.8],
                                        "share_of_day_votes_p15_p85": 77.6, "p_top10pct_pred_vs_actual": [8.2, 9.2],
                                        "old_card": {"rank_band_by_day_size": [91.0, 93.2, 76.3], "votes_band": 66.1, "top10_pred_vs_actual": [43.3, 33.2]}},
       "deciles": []}
for q in range(10):
    lo, hi = np.percentile(P.s, [q * 10, (q + 1) * 10]); g = P[(P.s >= lo) & ((P.s < hi) if q < 9 else (P.s <= hi))]
    out["deciles"].append({"decile": q, "n": int(len(g)), "pct_of_day_p10_p50_p90": [round(float(x), 3) for x in np.percentile(g.rq, [10, 50, 90])],
                           "share_of_day_votes_p15_p50_p85": [round(float(x), 4) for x in np.percentile(g.sv, [15, 50, 85])],
                           "p_top10pct_of_day": round(float((g.rq <= 0.1).mean()), 3),
                           "p_top3_by_day_size": {k: round(float((gg["rank"] <= 3).mean()), 3) for k, gg in g.groupby("size")},
                           "p_top10_by_day_size": {k: round(float((gg["rank"] <= 10).mean()), 3) for k, gg in g.groupby("size")},
                           "rank_band_typical_day": [max(1, round(float(x) * typical)) for x in np.percentile(g.rq, [10, 50, 90])]})
json.dump(out, open(OUTJ, "w"), indent=1); print(json.dumps(out["deciles"][0]), json.dumps(out["deciles"][9]))
