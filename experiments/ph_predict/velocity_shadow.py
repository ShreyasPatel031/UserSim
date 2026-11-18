"""Velocity shadow lines (orchestrator 19:30Z Nov 13; velocity_forecast.md (ii), provisional on 5-9 days): at V05 / V08 / V10 / V12
(05:00 / 08:00 / 10:00 / 12:00 PT) rank today's launches by votes_h x M(h) x (1 + b(h) x relative 1 h velocity), from the warehouse hourly
vote_snapshots stamped <= h (launch-day reads). M(h), b(h) frozen in results/frozen/velocity_20261113.json (fit on Oct 31-Nov 12).
  freeze            -> writes the frozen file (once)
  live <day> <V05|V08|V10|V12> -> results/velocity_shadow/<day>_<V>.json + bucket copy (label: dailyRank)"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
FZ = os.path.join(HERE, "results", "frozen", "velocity_20261113.json"); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
HOURS = {"V05": 5, "V08": 8, "V10": 10, "V12": 12}


def snaps(day=None, sync=False):
    q = 'SELECT "day", "at", CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots WHERE votes IS NOT NULL' + (f" AND \"day\" = '{day}'" if day else "")
    V = W.query(q, do_sync=sync); V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert("America/Los_Angeles"); return V


def frame(g, d, h):
    t0 = pd.Timestamp(d, tz="America/Los_Angeles"); th = t0 + pd.Timedelta(hours=h); s = g[g.pt <= th]
    if s.empty or (th - s.pt.max()) > pd.Timedelta(hours=1, minutes=5): return None, None
    last = s.sort_values("pt").groupby("id").votes.last(); m1 = g[g.pt <= th - pd.Timedelta(hours=1)].sort_values("pt").groupby("id").votes.last()
    X = pd.DataFrame({"votes": last}); X["g1"] = (X.votes - m1.reindex(X.index).fillna(0)).clip(lower=0)
    X["relv"] = (X.g1 / (X.g1.mean() or np.nan)).fillna(1.0); return X, s.pt.max()


def freeze():
    if os.path.exists(FZ): print("exists", FZ); return
    V = snaps(); L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, votes final FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    hits = lambda o, t: np.mean([len(set(o[:k]) & set(t[:k])) / k for k in (3, 5, 10)])
    out = {"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": sorted(V.day.unique()), "points": {}}
    for nm, h in HOURS.items():
        F = []
        for d, g in V.groupby("day"):
            X, _ = frame(g, d, h)
            if X is None: continue
            X = X.join(L[L.day == d].set_index("id")[["daily_rank", "final"]], how="inner"); X["day"] = d; F.append(X)
        if not F: continue
        F = pd.concat(F); M = float((F.final / F.votes.replace(0, np.nan)).median())
        sc = {b: np.mean([hits(x.assign(s=x.votes * (1 + b * (x.relv - 1))).sort_values("s", ascending=False).index.tolist(), x.sort_values("daily_rank").index.tolist()) for _, x in F.groupby("day")]) for b in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5)}
        b = max(sc, key=sc.get); out["points"][nm] = {"hour_pt": h, "M": round(M, 4), "b": b, "fit_days": int(F.day.nunique())}
    json.dump(out, open(FZ, "w"), indent=1); print(json.dumps(out["points"]))


def live(d, pt):
    P = json.load(open(FZ))["points"][pt]; g = snaps(d, sync=True); X, last = frame(g, d, P["hour_pt"])
    if X is None:
        print(json.dumps({"day": d, "point": pt, "status": "no hourly snapshot within 65 min of the point"})); return
    X["score"] = X.votes * P["M"] * (1 + P["b"] * (X.relv - 1)); X["pred_rank"] = X.score.rank(ascending=False, method="first").astype(int)
    res = {"day": d, "point": pt, "method": "velocity (ii): votes_h x M(h) x (1 + b x relative 1 h velocity)", "frozen": os.path.basename(FZ), "params": P,
           "data_up_to": last.isoformat(), "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "label": "dailyRank", "provisional": "5-9 backtest days",
           "forecast": X.reset_index().rename(columns={"index": "id"}).sort_values("pred_rank").round(4).to_dict("records")}
    os.makedirs(os.path.join(HERE, "results", "velocity_shadow"), exist_ok=True); p = os.path.join(HERE, "results", "velocity_shadow", f"{d}_{pt}.json")
    json.dump(res, open(p, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/velocity_shadow/{d}_{pt}.json"], check=True); print(p)


if __name__ == "__main__":
    freeze() if sys.argv[1] == "freeze" else live(sys.argv[2], sys.argv[3])
