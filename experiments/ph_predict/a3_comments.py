"""A3, reciprocity, comment half: on whom the team spent its pre-launch comments. Exact-time comments only (store events
kind=comment; upvotes are dated to the upvoted launch's day, not when cast, so they are left out), strictly before the
launch's Pacific day, on OTHER launches, over the team (makers + hunter, from data/days/ and data/today/).
Per launch:
  a3_c7, a3_c30              the team's comments on other launches in the 7 / 30 days before (log1p)
  a3_launches30              distinct other launches commented on in the 30 days before (log1p)
  a3_makers30                distinct makers of those launches (log1p)
  a3_makers_active30         of those makers, how many had themselves commented anywhere on PH (in our data) before
                             the launch day: makers who are active commenters, i.e. who could reciprocate (log1p)
  a3_makers_active_share30   a3_makers_active30 / a3_makers30 (NaN if none)
Then userbase_eval: gate first (within-day + pooled residual Spearman, Holm), boards vs the reference in HONEST_COL
(default "honest - live set") with the day-calibrated control.
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... python a3_comments.py -> results/a3_comments.json"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import userbase_eval as UE
from a1_team_history import teams

COLS = ["a3_c7", "a3_c30", "a3_launches30", "a3_makers30", "a3_makers_active30", "a3_makers_active_share30"]


def features(E, T):
    """E: comment events (person, item, date); T: {launch_id: (day, makers, hunter)}. Pure."""
    UE.need(E, ["person", "item", "date"], "store events")
    E = E.assign(person=E.person.astype(str).str.lower(), item=E.item.astype(str), date=E.date.astype(str).str[:10])
    by = {u: g for u, g in E.groupby("person")}
    first = E.groupby("person").date.min()            # each person's first comment in our data
    makers_of = {lid: mk - {"[redacted]"} for lid, (_, mk, _) in T.items()}
    rows = []
    for lid, (d, mk, hu) in T.items():
        lo30 = str((pd.Timestamp(d) - pd.Timedelta(days=30)).date()); lo7 = str((pd.Timestamp(d) - pd.Timedelta(days=7)).date())
        team = (mk | {hu}) - {"", "[redacted]"}
        mem = [u for u in team if u in by]
        G = pd.concat([by[u] for u in mem]) if mem else E.iloc[:0]
        G = G[(G.date < d) & (G.date >= lo30) & (G.item != lid)]
        g7 = G[G.date >= lo7]
        targets = set().union(*[makers_of.get(i, set()) for i in G.item.unique()]) - team if len(G) else set()
        active = {m for m in targets if m in first.index and first[m] < d}
        rows.append({"id": lid, "a3_c7": np.log1p(len(g7)), "a3_c30": np.log1p(len(G)), "a3_launches30": np.log1p(G.item.nunique()),
                     "a3_makers30": np.log1p(len(targets)), "a3_makers_active30": np.log1p(len(active)),
                     "a3_makers_active_share30": len(active) / len(targets) if targets else np.nan})
    return pd.DataFrame(rows)


def main():
    P, I, E = store.load()
    UE.need(E, ["kind"], "store events")
    E = E[E.kind == "comment"]
    print("comment events:", len(E), flush=True)
    F = features(E, teams("data"))
    print(f"launches {len(F)}; with team comments in 30 d {int((F.a3_c30 > 0).sum())}; with commented-on makers {int((F.a3_makers30 > 0).sum())}", flush=True)
    if os.environ.get("FEATS_OUT"):
        F.to_parquet(os.environ["FEATS_OUT"], index=False)
    os.environ.setdefault("HONEST_COL", "honest - live set")
    return UE.evaluate(F, "a3", COLS, os.environ.get("OUT", "results/a3_comments.json"))


if __name__ == "__main__":
    main()
