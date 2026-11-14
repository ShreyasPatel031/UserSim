"""Score the orchestrator's Gemini Decisions API forward answers (tmp/orchestrator/decisions_pilot/forward_<day>.json) against final
daily ranks (warehouse launches, synced). Compared with the clean 00:05 order (clean_order in the file = forecast_<day>.parquet pred)
and, for probabilities, E5's published 00:05 probability file (tmp/e5/website/probabilities/<day>_0005.json).
Top-k: hits in the predicted top k among final top k (Wilson 95%). Pairwise: all lineup pairs, and the file's ranks 2-8 pairs
(p_a_beats_b_both_orders), launch-bootstrap 95%. Calibration: Brier and Brier skill vs the lineup base rate, paired launch bootstrap.
Counts only in the output (ids, no names).   python decisions_fwd_score.py <scratch dir with forward json + prob json> <out json> <day>"""
import json, os, sys, itertools
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
D, OUT, DAY = sys.argv[1:4]; rng = np.random.default_rng(0)
F = json.load(open(os.path.join(D, f"forward_{DAY}.json"))); P = json.load(open(os.path.join(D, f"prob_{DAY[5:7]}{DAY[8:]}.json")))
WL = warehouse.table("launches", do_sync=True); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
rk = dict(zip(WL[WL.day == DAY].id, WL[WL.day == DAY].daily_rank))
L = pd.DataFrame(F["launches"]); L["rank"] = L.id.map(rk); pe = pd.DataFrame(P["launches"]).set_index("id")
L["e5_p10"] = L.id.map(pe.p_top10); L["e5_p3"] = L.id.map(pe.p_top3)
missing = int(L["rank"].isna().sum()); L = L[L["rank"].notna()].copy()
def wilson(h, n):
    if n == 0: return [None, None]
    p = h / n; z = 1.96; c = (p + z*z/(2*n)) / (1 + z*z/n); w = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n); return [round(100*(c-w), 1), round(100*(c+w), 1)]
orders = {"clean": L.sort_values("clean_order").id.tolist(), "decisions_p_top10": L.sort_values("p_top10", ascending=False).id.tolist(),
          "decisions_p_top3": L.sort_values("p_top3", ascending=False).id.tolist()}
r = L.set_index("id")["rank"]; res = {"day": DAY, "model": F.get("model"), "lineup": len(F["launches"]), "scored": len(L), "missing_rank": missing}
res["topk"] = {}
for name, o in orders.items():
    res["topk"][name] = {}
    for k in (3, 5, 10):
        h = int((r[o[:k]] <= k).sum()); res["topk"][name][f"top{k}"] = [round(100*h/k, 1), *wilson(h, k), h]
# pairwise over all lineup pairs, launch bootstrap
ids = L.id.tolist(); score = {"clean": -L.set_index("id").clean_order, "decisions_p_top10": L.set_index("id").p_top10, "decisions_p_top3": L.set_index("id").p_top3}
def pw(sub, s):
    pr = [(a, b) for a, b in itertools.combinations(sub, 2) if r[a] != r[b] and a != b]
    return np.mean([(s[a] > s[b]) == (r[a] < r[b]) for a, b in pr]) if pr else np.nan
res["pairwise_all"] = {}
boots = [list(rng.choice(ids, len(ids))) for _ in range(1000)]
for n, s in score.items():
    bs = [pw(list(dict.fromkeys(b)), s) for b in boots]; res["pairwise_all"][n] = [round(100*pw(ids, s), 1), *np.round(100*np.nanpercentile(bs, [2.5, 97.5]), 1).tolist()]
d = np.array([pw(list(dict.fromkeys(b)), score["decisions_p_top10"]) - pw(list(dict.fromkeys(b)), score["clean"]) for b in boots])
res["pairwise_all"]["decisions_p_top10 - clean"] = [round(100*(pw(ids, score["decisions_p_top10"]) - pw(ids, score["clean"])), 1), *np.round(100*np.nanpercentile(d, [2.5, 97.5]), 1).tolist()]
# file's ranks 2-8 pairs
pp = [x for x in F["pairwise_clean_ranks_2_8"] if x["a"] in r and x["b"] in r and r[x["a"]] != r[x["b"]]]
co = L.set_index("id").clean_order
dec_ok = np.array([(x["p_a_beats_b_both_orders"] > .5) == (r[x["a"]] < r[x["b"]]) for x in pp]); cl_ok = np.array([(co[x["a"]] < co[x["b"]]) == (r[x["a"]] < r[x["b"]]) for x in pp])
bi = rng.integers(0, len(pp), (2000, len(pp)))
res["pairwise_ranks_2_8"] = {"n_pairs": len(pp), "decisions": [round(100*dec_ok.mean(), 1), *wilson(int(dec_ok.sum()), len(pp)), int(dec_ok.sum())],
    "clean": [round(100*cl_ok.mean(), 1), *wilson(int(cl_ok.sum()), len(pp)), int(cl_ok.sum())],
    "decisions - clean": [round(100*(dec_ok.mean()-cl_ok.mean()), 1), *np.round(100*np.percentile(dec_ok[bi].mean(1)-cl_ok[bi].mean(1), [2.5, 97.5]), 1).tolist()],
    "order_consistency (|p_ab - (1-p_ba)| mean)": round(float(np.mean([abs(x["p_a_order_ab"] - (1 - x["p_b_order_ba"])) for x in pp])), 3)}
# calibration
res["calibration"] = {}; n = len(L); bi = rng.integers(0, n, (2000, n))
for k, dc, ec in ((10, "p_top10", "e5_p10"), (3, "p_top3", "e5_p3")):
    y = (L["rank"] <= k).astype(float).values; pd_ = L[dc].values; pe_ = L[ec].values; base = np.full(n, y.mean())
    br = lambda p, i=slice(None): ((p[i] - y[i])**2).mean()
    bd = np.array([br(pd_, i) for i in bi]); be = np.array([br(pe_, i) for i in bi])
    res["calibration"][f"top{k}"] = {"actual_rate": round(float(y.mean()), 3), "mean_stated_decisions": round(float(pd_.mean()), 3), "mean_stated_e5": round(float(np.nanmean(pe_)), 3),
        "brier_decisions": [round(br(pd_), 4), *np.round(np.percentile(bd, [2.5, 97.5]), 4).tolist()], "brier_e5": [round(br(pe_), 4), *np.round(np.percentile(be, [2.5, 97.5]), 4).tolist()],
        "brier_base_rate (in-sample)": round(br(base), 4), "decisions - e5": [round(br(pd_) - br(pe_), 4), *np.round(np.percentile(bd - be, [2.5, 97.5]), 4).tolist()],
        "decisions by stated halves [stated, actual, n]": [[round(float(pd_[m].mean()), 2), round(float(y[m].mean()), 2), int(m.sum())] for m in (pd_ < np.median(pd_), pd_ >= np.median(pd_))]}
res["note"] = f"One day, n={n}; intervals are within-day only. E5 probabilities for {DAY} came from the rank-table fallback on the clean order (no scores were published that night), so they rank like clean."
os.makedirs(os.path.dirname(OUT), exist_ok=True); json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res))
