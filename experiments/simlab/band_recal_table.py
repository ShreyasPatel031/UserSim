"""Recalibrated quantile table for the /try description band (orchestrator 19:34Z Nov 13). Same shape as results/web/launch_band.json
`bands` (one row per score decile), built from the deployed recipe's MONTH-FORWARD scores (band_2025.py arm A0: 2026 rows, ln votes,
the launch_band recipe) on every 2026 launch from March. Deciles are score PERCENTILES, so the site maps a new launch the same way it
does now (score -> percentile via score_percentile_cuts -> decile). Quantiles at nominal 82% (p09 / p50 / p91), the level that gave
80.5% [77.6, 83.1] coverage month-forward on the 856 (band_calib.json). Counts only.
    python band_recal_table.py <scratchpad> <out json>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); OUTJ = sys.argv[2]; sys.argv = sys.argv[:2] + [os.path.join(sys.argv[1], "b25")]
src = open(os.path.join(HERE, "band_2025.py")).read()
src = src.replace('ARMS = {"A0 2026 ln(votes) [current]": (False, "y_ln"), "A1 2026 pct": (False, "y_pct"), "A2 2025+2026 pct": (True, "y_pct"), "A3 2025+2026 z ln(votes)": (True, "y_zln"), "A4 2025+2026 ln(votes)": (True, "y_ln")}',
                  'ARMS = {"A0 2026 ln(votes) [current]": (False, "y_ln")}')
exec(src[src.index("import glob, json, os, subprocess, sys"):src.index("T6 = pd.read_parquet")])
G = A[(A.yr == 2026) & A["A0 2026 ln(votes) [current]"].notna()].copy(); s = G["A0 2026 ln(votes) [current]"]
G["dec"] = np.minimum(9, (s.rank(pct=True) * 10).astype(int))
bands = []
for d, g in G.groupby("dec"):
    q = lambda c: [round(float(np.quantile(g[c], x)), 3) for x in (0.09, 0.5, 0.91)]
    bands.append({"decile": int(d), "daily_rank_p09_p50_p91": [float(np.quantile(g["rank"], x)) for x in (0.09, 0.5, 0.91)],
                  "rank_percentile_p09_p50_p91": q("y_pct"), "votes_p09_p50_p91": [float(np.quantile(g.votes, x)) for x in (0.09, 0.5, 0.91)],
                  "share_top3": round(float((g["rank"] <= 3).mean()), 3), "share_top10": round(float((g["rank"] <= 10).mean()), 3), "n": int(len(g))})
out = {"version": "2026-11-13-recal82", "basis": "month-forward scores of the deployed product-only ridge recipe, 2026 launches Mar - Nov 10",
       "launches": int(len(G)), "decile_by": "score percentile (map with the existing score_percentile_cuts)", "nominal_level": 0.82,
       "measured": {"coverage_of_80pct_claim_on_856 (Sep 1 - Nov 10, month-forward)": [80.5, 77.6, 83.1], "coverage_on_130_fresh": [80.0, 72.3, 86.9],
                    "mean_width_share_of_day_rank_range": 77.2, "previous_table_same_test": {"coverage": 79.2, "width": 75.1}},
       "caveat": "Coarse: the 80% band spans about three quarters of a day's ranks. Product-only: no team, hunter, audience or line-up.",
       "bands": bands}
json.dump(out, open(OUTJ, "w"), indent=1); print(json.dumps(out)[:1500])
