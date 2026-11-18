"""Displayed votesCount drift (orchestrator 11:54Z Nov 13): for launches captured live (vote_snapshots, Oct 31 on), displayed votes at
day end (last snapshot <= 23:59:59 PT of the launch day) vs the latest displayed count (launches.votes, its updated_at), by final rank band.
Did the displayed count go DOWN after the day (removals), or not? Counts only. usage: python votes_drift.py -> results/votes_drift.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W

V = W.query('SELECT "day", "at", CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots WHERE votes IS NOT NULL', do_sync=False)
V["at"] = pd.to_datetime(V["at"], utc=True)
V["end"] = [pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(days=1) for d in V.day]
E = V[V["at"] < V.end.dt.tz_convert("UTC")].sort_values("at").groupby("id").last()[["day", "at", "votes"]].rename(columns={"votes": "v_end", "at": "at_end"})
P = V.sort_values("at").groupby("id").agg(v_max=("votes", "max"), v_last=("votes", "last"), at_last=("at", "last"))
L = W.query("SELECT CAST(id AS VARCHAR) id, votes v_now, daily_rank, updated_at FROM launches", do_sync=False).set_index("id")
X = E.join(P).join(L, how="inner").dropna(subset=["v_end", "v_now"])
X = X[X.day < pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")]
X["d"] = X.v_now - X.v_end; X["peak_drop"] = X.v_max - X.v_now
X["band"] = pd.cut(X.daily_rank, [0, 3, 10, 30, 1e9], labels=["1-3", "4-10", "11-30", "31+"])
md = [f"# Displayed votesCount: day end vs now ({len(X)} launches, {X.day.nunique()} days {X.day.min()}..{X.day.max()}; snapshots end <= 23:59 PT)", "",
      "| final rank band | n | share now < day end | share now == day end | share now > day end | median change | min change | share now < peak seen |", "|---|---|---|---|---|---|---|---|"]
for b, g in list(X.groupby("band", observed=True)) + [("all", X)]:
    md.append(f"| {b} | {len(g)} | {(g.d < 0).mean():.1%} | {(g.d == 0).mean():.1%} | {(g.d > 0).mean():.1%} | {g.d.median():+.0f} | {g.d.min():+.0f} | {(g.peak_drop > 0).mean():.1%} |")
dn = X[X.d < 0]
md += ["", f"Launches whose displayed count fell after the day: {len(dn)}; total votes removed {int(-dn.d.sum())} of {int(X.v_end.sum())} displayed at day end "
       f"({-dn.d.sum() / X.v_end.sum():.2%}); largest drop {int(-X.d.min()) if len(X) else 0}.",
       f"Launches whose count fell below a value seen earlier in any snapshot: {(X.peak_drop > 0).sum()} (largest {int(X.peak_drop.max())})."]
open(os.path.join(HERE, "results", "votes_drift.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))
