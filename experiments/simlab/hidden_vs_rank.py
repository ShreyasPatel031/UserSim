"""Hidden-window held votes vs the HIDDEN RANK baseline (orchestrator 01:43Z Nov 13). Days Nov 2, 3, 4, 8, 9, 10, 11; hidden rank = latest
official API dailyRank read <= 01:00 / 02:00 / 03:00 PT (warehouse vote_snapshots). Held votes = complete people's upvotes of each launch
(store), binomially thinned by an assumed pre-03:00 share (30 / 50 / 70%; no per-launch vote order is held), 20 draws.
Arms: hidden rank alone; hidden rank + thinned held votes (z(-ln rank) + w z(ln(1+votes)), w leave-one-day-out); identity weighting:
each held voter weighted by their rate of voting for CLIMBERS on the other test days (launches whose final rank beat their 03:00 hidden
rank by >= 3 places), leave-one-day-out. Truth: final daily rank. Paired day bootstrap over the 7 days (draws averaged within day).
    python hidden_vs_rank.py <store dir> <warehouse cache dir> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
V3, WH, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
rd = lambda t: pd.concat([pd.read_parquet(f) for f in glob.glob(f"{WH}/{t}/*.parquet")])
L = rd("launches").sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["rank"] = pd.to_numeric(L.daily_rank, errors="coerce")
L = L[L.day.isin(DAYS) & L["rank"].notna()][["id", "day", "rank"]]
V = rd("vote_snapshots"); V["at"] = pd.to_datetime(V["at"], utc=True); V["id"] = V.launch_id.astype(str); V["rank_now"] = pd.to_numeric(V.rank_now, errors="coerce"); V = V[V.rank_now.notna()]
def hidden(d, hh):
    T = pd.Timestamp(f"{d} {hh}").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
    return V[(V.day == d) & (V["at"] <= T)].sort_values("at").groupby("id").rank_now.last()
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[(E.kind == "upvote") & E.person_id.isin(COV)]
E["target_id"] = E.target_id.astype(str); E = E[E.target_id.isin(set(L.id))]
held = E.groupby("target_id").person_id.agg(list).to_dict()
h03 = {d: hidden(d, "03:00") for d in DAYS}
L["h03"] = [h03[d].get(i, np.nan) for i, d in zip(L.id, L.day)]; L["climber"] = (L.h03 - L["rank"]) >= 3
z = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist()
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
res = {"design": __doc__.split("\n    python")[0], "held_votes_by_day": {d: int(sum(len(held.get(i, [])) for i in L[L.day == d].id)) for d in DAYS},
       "climbers_by_day": L.groupby("day").climber.sum().astype(int).to_dict()}
for hh in ("01:00", "02:00", "03:00"):
    Hr = {d: hidden(d, hh) for d in DAYS}; base = L.copy(); base["hr"] = [Hr[d].get(i, 999) for i, d in zip(base.id, base.day)]
    base["zh"] = base.groupby("day").hr.transform(lambda s: z(-np.log(s)))
    out = {}
    for f in (0.3, 0.5, 0.7):
        rows = {"alone": [], "plus_held": [], "plus_identity": []}
        for r_ in range(20):
            g_ = np.random.default_rng(r_); D = base.copy()
            thin = {i: [p for p in held.get(i, []) if g_.random() < f] for i in D.id}
            D["obs"] = D.id.map(lambda i: len(thin[i])).astype(float)
            for d in DAYS:   # identity weights from the OTHER days' climbers
                oth = L[(L.day != d)]; cl = set(oth[oth.climber].id); per = E[E.target_id.isin(set(oth.id))]
                rate = per.assign(c=per.target_id.isin(cl)).groupby("person_id").c.mean()
                m = D.day == d; D.loc[m, "wobs"] = D.loc[m, "id"].map(lambda i: sum(rate.get(p, 0.0) for p in thin[i])).astype(float)
            for col, key in (("obs", "plus_held"), ("wobs", "plus_identity")):
                D["zx"] = D.groupby("day")[col].transform(lambda s: z(np.log1p(s)))
                for d in DAYS:
                    tr = D[D.day != d]; w = max((0, .25, .5, 1, 2), key=lambda w: np.mean([dm(g.assign(s=g.zh + w * g.zx), "s")[0] for _, g in tr.groupby("day")]))
                    g = D[D.day == d]; rows[key].append(np.array(dm(g.assign(s=g.zh + w * g.zx), "s")) - np.array(dm(g, "zh")))
            if r_ == 0: rows["alone"] = [dm(D[D.day == d], "zh") for d in DAYS]
        def ci(a):
            a = np.array(a).reshape(20, len(DAYS), 3).mean(0)   # average draws within each day; bootstrap the 7 days
            bs = np.array([a[rng.integers(0, len(a), len(a))].mean(0) for _ in range(2000)])
            return [[round(float(a[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
        out[f"pre-03:00 share {int(f * 100)}%"] = {"hidden_rank_alone top3/5/10": np.array(rows["alone"]).mean(0).round(1).tolist(),
                                                    "plus_held - alone": ci(rows["plus_held"]), "plus_identity - alone": ci(rows["plus_identity"])}
    res[f"hidden rank at {hh}"] = out; print(hh, json.dumps(out), flush=True)
json.dump(res, open(os.path.join(OUT, "hidden_vs_rank.json"), "w"), indent=1, default=float)
print(res["held_votes_by_day"], res["climbers_by_day"])
