"""Keep the hidden API rank's top-3 win without losing depth (orchestrator 02:00Z Nov 12). Days: the 6 with hourly
pre-reveal API ranks (vote_snapshots: Nov 2, 3, 4, 8, 9, 10); reads at 01:00, 02:00, 03:00 PT. Candidates:
  api, lm                 the two orders alone
  slots_k (k = 1..5)      top k slots from the API rank, the rest from the LM order (k = 3 is (a))
  wmean_w (w = .25/.5/.75) weighted mean of rank positions, w on the API rank
  floor5                  API rank, but the LM's top 5 are never placed below 10
  vote3_eq / vote3_w      + the comment ridge as a third voter (5 days with replay P files): equal weights, or w_api = .5,
                          .25 LM, .25 ridge
Settings chosen by leave-one-day-out: for each held-out day, the candidate (or the parameter within a family) with the best
mean of top 3/5/10 on the other days is scored on the held-out day. n = 6 days, no intervals.
usage: python api_depth.py -> results/api_depth.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import lm_scores


def tk(order, truth, k):
    return len(set(order[:k]) & set(truth[:k])) / k * 100


def orders(api, lm, ridge):
    ids = list(api)
    ra = {i: n for n, i in enumerate(api)}; rl = {i: n for n, i in enumerate(lm)}
    O = {"api": api, "lm": lm}
    for k in range(1, 6):
        top = api[:k]; O[f"slots_{k}"] = top + [i for i in lm if i not in top]
    for w in (0.25, 0.5, 0.75):
        O[f"wmean_{w}"] = sorted(ids, key=lambda i: (w * ra[i] + (1 - w) * rl[i], rl[i]))
    lm5 = set(lm[:5]); o = list(api)
    for i in lm5:   # move LM-top-5 launches up to position 10 if below
        if o.index(i) > 9:
            o.remove(i); o.insert(9, i)
    O["floor5"] = o
    if ridge is not None:
        rr = {i: n for n, i in enumerate(ridge)}
        O["vote3_eq"] = sorted(ids, key=lambda i: ((ra[i] + rl[i] + rr[i]) / 3, rl[i]))
        O["vote3_w"] = sorted(ids, key=lambda i: (0.5 * ra[i] + 0.25 * rl[i] + 0.25 * rr[i], rl[i]))
    return O


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, hours_since_start h, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10"]
    rows = []
    for d in days:
        truth = R[R.day == d].sort_values("daily_rank").id.tolist(); lm = lm_scores(d)
        base = sorted(truth)   # ties (launches missing from a prior) broken by id, never by final rank (orchestrator 10:35Z Nov 12)
        lmo = sorted(base, key=lambda i: -lm.get(i, -99))
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        for h in (1, 2, 3):
            T = t0 + pd.Timedelta(hours=h); g = V[(V.d == d) & (V.a <= T)]
            S = g.sort_values("a").groupby("id").rank_now.last()
            api = sorted(base, key=lambda i: (S.get(i, 999), -lm.get(i, -99)))
            ridge = None
            for pf in (os.path.join(HERE, "results", "early_forecast", f"{d}_P{h}.json"), os.path.join(HERE, "results", "early_forecast_replay_P", f"{d}_P{h}.json")):
                if os.path.exists(pf):
                    F = pd.DataFrame(json.load(open(pf))["forecast"]); F["id"] = F.id.astype(str); cr = dict(zip(F.id, F.pred_rank))
                    ridge = sorted(base, key=lambda i: cr.get(i, 999)); break
            for nm, o in orders(api, lmo, ridge).items():
                rows.append({"day": d, "h": h, "cand": nm, **{f"t{k}": tk(o, truth, k) for k in (3, 5, 10)}})
    X = pd.DataFrame(rows); X["avg"] = X[["t3", "t5", "t10"]].mean(axis=1)
    res, md = {}, ["# Pre-reveal API rank: keeping depth (6 days, hourly reads; n = 6, no intervals)", ""]
    for h in (1, 2, 3):
        Y = X[X.h == h]
        tab = Y.groupby("cand")[["t3", "t5", "t10"]].mean().round(1)
        fams = {"slots": [f"slots_{k}" for k in range(1, 6)], "wmean": ["wmean_0.25", "wmean_0.5", "wmean_0.75"],
                "any (no ridge)": [c for c in tab.index if not c.startswith("vote3")], "any (with ridge, 5 days)": list(tab.index)}
        lodo = {}
        for fam, cands in fams.items():
            sc, picks = [], []
            Z = Y[Y.cand.isin(cands)]
            dd = sorted(Y[Y.cand == "vote3_eq"].day.unique()) if "ridge" in fam else days
            for dh in dd:
                tr = Z[(Z.day != dh) & Z.day.isin(dd)].groupby("cand").avg.mean()
                c = tr.idxmax(); picks.append(c)
                sc.append(Z[(Z.day == dh) & (Z.cand == c)][["t3", "t5", "t10"]].values[0])
            lodo[fam] = {"lodo": [round(float(x), 1) for x in np.mean(sc, axis=0)], "picks": picks, "days": len(dd)}
        res[f"{h}:00"] = {"table": tab.to_dict(orient="index"), "lodo": lodo}
        md += [f"## {h}:00 PT read", "", "| candidate | top 3 | top 5 | top 10 |", "|---|---|---|---|"]
        for c, r in tab.iterrows():
            md.append(f"| {c} | {r.t3} | {r.t5} | {r.t10} |")
        md += ["", "Leave-one-day-out choice (choose on 5 days, score the 6th):", "", "| family | top 3 / 5 / 10 | picks per held-out day |", "|---|---|---|"]
        for fam, v in lodo.items():
            md.append(f"| {fam} ({v['days']} days) | {' / '.join(str(x) for x in v['lodo'])} | {', '.join(v['picks'])} |")
        md.append("")
    md += ["Per-day rows: results/api_depth.json (rows)."]
    res["rows"] = rows
    json.dump(res, open(os.path.join(HERE, "results", "api_depth.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "api_depth.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
