"""Hidden-window early votes from REAL pulls (orchestrator 09:34Z Nov 13). Complete people of the merged store whose full pull
(upvotes tab, fetched_at = run finish) happened between 00:30 and 04:00 PT on a launch day: their upvote lists show that day's votes
cast before the pull. Early count E(L) = number of such people with an upvote on launch L. Days Nov 5-12 (only days with >= 100 such
people are scored). Base scores: clean_v3_nosite (clean_live_rows_nosite) and the hidden rank (warehouse vote_snapshots rank_now, the
last read at or before the median pull time, votes still hidden; held Nov 8-13). Truth: final daily rank (clean rows).
Per day: Spearman(E, -rank); partial beyond the hidden rank and beyond clean; top 3/5/10 of hidden alone vs hidden + w z(log1p E) and
clean vs clean + w z(log1p E) (w leave-day-out from {0, .25, .5, 1, 2}); people curve: E from a random 25% / 50% / 100% of the window people.
Counts only.
    python hidden_real.py <merged store dir> <clean_live_rows_nosite.parquet> <out dir>
"""
import os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
ST, CNS, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id)
T = pd.read_parquet(os.path.join(ST, "tabs.parquet")); T = T[(T.tab == "upvotes") & T.person_id.isin(C)].copy(); T["f"] = pd.to_datetime(T.fetched_at, utc=True).dt.tz_convert(PT)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U = U.drop_duplicates(["person_id", "target_id"])
CN = pd.read_parquet(CNS); CN["id"] = CN.id.astype(str)
V = warehouse.table("vote_snapshots", do_sync=True); V["at"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT); V["launch_id"] = V.launch_id.astype(str)
z = lambda s: (s - s.mean()) / (s.std() or 1); rk = lambda a: pd.Series(a).rank().to_numpy()
def partial(y, b, x):
    y, b, x = rk(y), rk(b), rk(x)
    return float(np.corrcoef(y - np.polyval(np.polyfit(b, y, 1), b), x - np.polyval(np.polyfit(b, x, 1), b))[0, 1])
def ov(order, g, k): t = g.sort_values("rank").id.tolist()[:k]; return len(set(order[:k]) & set(t)) / k * 100
rows, meta = [], {}
for d in pd.date_range("2026-11-05", "2026-11-12"):
    day = str(d.date()); lo = d.tz_localize(PT) + pd.Timedelta(minutes=30); hi = d.tz_localize(PT) + pd.Timedelta(hours=4)
    W = T[(T.f >= lo) & (T.f < hi)]; g = CN[(CN.day == day) & CN.clean_v3_nosite.notna() & CN["rank"].notna()][["id", "clean_v3_nosite", "rank"]].copy()
    meta[day] = {"people_in_window": len(W), "launches": len(g)}
    if len(W) < 100 or len(g) < 8: continue
    med = W.f.median(); vs = V[(V.day == day) & (V["at"] <= med)]
    if len(vs): last = vs["at"].max(); hr = dict(zip(vs[vs["at"] == last].launch_id, vs[vs["at"] == last].rank_now)); meta[day]["hidden_read_pt"] = last.strftime("%H:%M")
    else: hr = {}
    g["hidden"] = [-float(hr[i]) if i in hr and hr[i] == hr[i] else np.nan for i in g.id]
    ppl = W.person_id.to_numpy(); uw = U[U.person_id.isin(set(ppl)) & U.target_id.isin(set(g.id))]
    meta[day].update({"window_upvotes_on_day_launches": len(uw), "median_pull_pt": med.strftime("%H:%M"), "share_of_final_votes": None})
    for frac in (0.25, 0.5, 1.0):
        sub = set(rng.choice(ppl, max(1, int(len(ppl) * frac)), replace=False)); cnt = uw[uw.person_id.isin(sub)].groupby("target_id").size()
        g[f"E{int(frac*100)}"] = g.id.map(cnt).fillna(0).astype(float)
    g["day"] = day; rows.append(g)
res = {"design": __doc__.split("\n    python")[0], "days": meta}
if rows:
    A = pd.concat(rows); per = {}
    for day, g in A.groupby("day"):
        y = -g["rank"].to_numpy(); o = {}
        for e in ("E25", "E50", "E100"):
            o[e] = {"spearman": round(float(spearmanr(g[e], y).correlation), 3), "partial_beyond_clean": round(partial(y, g.clean_v3_nosite.to_numpy(), g[e].to_numpy()), 3),
                    "partial_beyond_hidden": round(partial(y, g.hidden.to_numpy(), g[e].to_numpy()), 3) if g.hidden.notna().all() else None}
        o["spearman_clean"] = round(float(spearmanr(g.clean_v3_nosite, y).correlation), 3); o["spearman_hidden"] = round(float(spearmanr(g.hidden, y).correlation), 3) if g.hidden.notna().all() else None
        tops = {"clean": g.sort_values("clean_v3_nosite", ascending=False).id.tolist()}
        if g.hidden.notna().all(): tops["hidden"] = g.sort_values("hidden", ascending=False).id.tolist()
        for w in (0.25, 0.5, 1, 2):
            tops[f"clean+E w{w}"] = g.assign(s=z(g.clean_v3_nosite) + w * z(np.log1p(g.E100))).sort_values("s", ascending=False).id.tolist()
            if g.hidden.notna().all(): tops[f"hidden+E w{w}"] = g.assign(s=z(g.hidden) + w * z(np.log1p(g.E100))).sort_values("s", ascending=False).id.tolist()
        o["top3/5/10"] = {k: [ov(v, g, kk) for kk in (3, 5, 10)] for k, v in tops.items()}; per[day] = o
    res["per_day"] = per
    def lodo(prefix, base):
        ds = [d for d in per if f"{prefix} w1" in per[d]["top3/5/10"]]; out = []
        for d in ds:
            oth = [x for x in ds if x != d] or [d]
            w = max((0.25, 0.5, 1, 2), key=lambda w: np.mean([sum(per[x]["top3/5/10"][f"{prefix} w{w}"][:2]) for x in oth]))
            out.append(np.array(per[d]["top3/5/10"][f"{prefix} w{w}"]) - np.array(per[d]["top3/5/10"][base]))
        return {"days": len(out), "mean gain top3/5/10": np.array(out).mean(0).round(1).tolist() if out else None}
    res["clean+E vs clean (lodo w)"] = lodo("clean+E", "clean"); res["hidden+E vs hidden (lodo w)"] = lodo("hidden+E", "hidden")
import json; json.dump(res, open(os.path.join(OUT, "hidden_real.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:3500])
