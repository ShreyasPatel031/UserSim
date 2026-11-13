"""Page-threshold check for b20 concerns on /try (orchestrator 12:44Z Nov 13). Reuses retrieval_rep.py's 170 pooled launches, cached lists
and strict-judge labels (no new generation if the cache is complete). Page path, concerns:
(1) share of targets whose top-1 neighbour cosine is below the page threshold 0.886, by final-votes quartile and for top-10 final ranks
    ("well-known / large");
(2) policies: b20 if top-1 >= thr else fallback, thr in {none, 0.886, 0.87, 0.85, 0.83, always b20}, fallback = common list (d, constant)
    or deployed ranked list (c); p@3 / recall / top-1 with paired launch-bootstrap vs the deployed policy (thr 0.886 -> common);
(3) on the thin third (below 0.886): b20 vs c vs d head to head.
    python thin_check.py <ph-website worktree> <scratchpad> <page_path out dir> <rr dir (cache)> <out dir>
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = sys.argv[5]; sys.argv = sys.argv[:5]
RP = open(os.path.join(HERE, "retrieval_rep.py")).read(); exec(RP[:RP.index("def mb(v):")])
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(HERE, "..")); from pipeline import warehouse  # noqa: E402
WL = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last")
vk = {(s, d): (v, r) for s, d, v, r in zip(WL.slug, WL.day, pd.to_numeric(WL.votes, errors="coerce").astype(float).values, pd.to_numeric(WL.daily_rank, errors="coerce").astype(float).values)}
met = {"p@3": lambda o: float(np.mean(o["lab"][:3])), "recall": lambda o: o["rec"] if o["rec"] is not None else np.nan, "top1": lambda o: float(o["lab"][0])}
g = lambda o, nm, m: met[m](o[nm]) if o and o.get(nm) and o[nm]["lab"] else np.nan
rows = [(x, r, mt) for x, r, mt in R if r.get("RC") and mt.get("sim1|page") is not None]
T = pd.DataFrame([{"sim": mt["sim1|page"], "votes": vk.get((x["stem"], x["day"]), (np.nan, np.nan))[0], "rank": vk.get((x["stem"], x["day"]), (np.nan, np.nan))[1],
                   **{f"{a}|{m}": g(r["RC"], f"page|{a}", m) for a in ("b20", "c", "d") for m in met}} for x, r, mt in rows])
T["thin"] = T.sim < 0.886; res = {"n": len(T), "with votes": int(T.votes.notna().sum()), "thin share @0.886": round(float(T.thin.mean()), 3)}
T["vq"] = pd.qcut(T.votes, 4, labels=["Q1", "Q2", "Q3", "Q4 largest"])
res["thin share by final-votes quartile"] = {str(k): [round(float(g_.thin.mean()), 3), len(g_), round(float(g_.votes.median()), 0)] for k, g_ in T.groupby("vq", observed=True)}
res["thin share, final rank <= 10 vs > 10"] = [[round(float(T[T["rank"] <= 10].thin.mean()), 3), int((T["rank"] <= 10).sum())], [round(float(T[T["rank"] > 10].thin.mean()), 3), int((T["rank"] > 10).sum())]]
res["spearman(top-1 cos, ln votes)"] = round(float(T[["sim", "votes"]].dropna().assign(v=lambda d: np.log1p(d.votes)).corr("spearman").loc["sim", "v"]), 3)
def pol(thr, fb, m): return np.where(T.sim >= thr, T[f"b20|{m}"], T[f"{fb}|{m}"])
def mbx(v):
    v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
for m in met:
    ref = pol(0.886, "d", m); o = {}
    for thr in (0.886, 0.87, 0.85, 0.83, -1):
        for fb in ("d", "c"):
            p = pol(thr, fb, m); nm = f"thr {thr if thr > 0 else 'none (always b20)'} -> {'common' if fb == 'd' else 'deployed ranked'}"
            o[nm] = {"level": mbx(p.astype(float))}
            if not (thr == 0.886 and fb == "d"): o[nm]["vs deployed policy (0.886 -> common)"] = mbx((p - ref).astype(float))
    res[f"policies|{m}"] = o
TT = T[T.thin]
res["thin third head to head (page, concerns)"] = {m: {"b20": mbx(TT[f"b20|{m}"].values), "deployed ranked (c)": mbx(TT[f"c|{m}"].values), "common (d)": mbx(TT[f"d|{m}"].values),
    "b20 - common": mbx((TT[f"b20|{m}"] - TT[f"d|{m}"]).values), "c - common": mbx((TT[f"c|{m}"] - TT[f"d|{m}"]).values)} for m in met}
res["est_usd_this_run"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "result.json"), "w"), indent=1, default=float); print(json.dumps(res, default=float))
