"""Orchestrator 07:00Z Nov 11 P1: arrivals EV scaled by audience SIZE. rate_L = arrivals EV / |C(L)| (mean activation over
complete candidates, no_dormant honest monthly fits, ev_per_launch.parquet); EV_L = rate_L x audience_L, with audience =
hunter PH followers + real makers' PH followers (LATE: re-read after launch), X maker + company followers (LATE), or
both. Launches without candidates get the day's median rate. Daily top 3/5/10 vs real rank and Spearman vs votes, on
the same days and line-ups as arrivals.json (registered arrivals-only 53.3 / 64.0 / 70.0); paired bootstrap vs arr.
usage: SIMBT=<dir> python p1_audience_ev.py -> results/p1_audience_ev.json"""
import json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
WORK = os.environ["SIMBT"]; S_ = os.path.dirname(WORK)
L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
rk = dict(zip(L.id, L.daily_rank)); vt = dict(zip(L.id, L.votes))
df = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); df["id"] = df.id.astype(str); df = df.set_index("id")
G = pd.read_parquet(f"{WORK}/arrivals/ev_per_launch.parquet"); G = G[G.variant == "no_dormant"].copy(); G["id"] = G.id.astype(str)
G["rate"] = G.arr / G.cand_n.where(G.cand_n > 0)
G["rate"] = G.rate.fillna(G.groupby("day").rate.transform("median"))
f = lambda c: G.id.map(df[c]).fillna(0).clip(lower=0)
G["aud_ph"] = f("ph_hunter_followers") + f("ph_maker_sum_followers"); G["aud_x"] = f("x_maker_sum_followers") + f("x_company_followers")
G["aud_all"] = G.aud_ph + G.aud_x
S = {"arr": G.arr, "rate_x_aud_ph": G.rate * G.aud_ph, "rate_x_aud_x": G.rate * G.aud_x, "rate_x_aud_all": G.rate * G.aud_all,
     "aud_ph_only": G.aud_ph, "arr_plus_rate_x_aud_ph": G.arr + G.rate * G.aud_ph}
for k, v in S.items():
    G[k] = v.values
G["rank"] = G.id.map(rk); G["votes"] = G.id.map(vt); G = G.dropna(subset=["rank"])
per = []
for d, g in G.groupby("day"):
    row = {"day": d}
    for m in S:
        for k in (3, 5, 10):
            top = set(g[g["rank"] <= k].id)
            row[f"{m}_top{k}"] = len(set(g.nlargest(k, m).id) & top) / k * 100 if len(top) >= k and len(g) >= k else np.nan
        row[f"{m}_sp"] = spearmanr(g[m], g.votes).correlation
    per.append(row)
P = pd.DataFrame(per); rng = np.random.default_rng(0)
def b(x, r=1):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return [round(float(x.mean()), r)] + [round(float(v), r) for v in np.percentile([x[rng.integers(0, len(x), len(x))].mean() for _ in range(5000)], [2.5, 97.5])] + [int(len(x))]
res = {"note": "audience counts are LATE (read after launch); rate is honest", "days": int(len(P))}
for m in S:
    res[m] = {**{f"top{k}": b(P[f"{m}_top{k}"]) for k in (3, 5, 10)}, "spearman": b(P[f"{m}_sp"], 3)}
    if m != "arr":
        res[m]["delta_vs_arr"] = {**{f"top{k}": b(P[f"{m}_top{k}"] - P[f"arr_top{k}"]) for k in (3, 5, 10)}, "spearman": b(P[f"{m}_sp"] - P["arr_sp"], 3)}
json.dump(res, open(os.path.join(HERE, "results", "p1_audience_ev.json"), "w"), indent=1)
for m in S:
    print(m, [res[m][f"top{k}"][0] for k in (3, 5, 10)], res[m]["spearman"][0], res[m].get("delta_vs_arr"))
