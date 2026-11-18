"""A2: the makers' and hunter's own Product Hunt activity in the days before their launch (organised preparation), from
dated warehouse events only (store: upvotes dated to the launch day they were cast on; comments with their time).
Per launch, over the team (makers + hunter, from data/days/), counting events strictly before the launch's Pacific day:
  a2_act7 / a2_act14     events (upvotes + comments) on OTHER launches in the 7 / 14 days before (log1p)
  a2_launches14          distinct other launches the team touched in the 14 days before (log1p)
  a2_active_members14    team members with any event in the 14 days before
  a2_days_since          days since the team's most recent event (NaN if none in 60 days)
Then userbase_eval (gate first; boards vs the reference in HONEST_COL).
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... HONEST_COL="honest - live set" python a2_team_activity.py -> results/a2_team_activity.json"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import userbase_eval as UE
from a1_team_history import teams

CUT_DAYS = int(os.environ.get("CUT_DAYS", "0"))   # store comments carry a date only (likely UTC, ts_quality=day): 1 = safe bound,
# only comments dated at least 2 days before the launch day count (a UTC date can straddle 00:00 PT)
COLS = ["a2_act7", "a2_act14", "a2_launches14", "a2_active_members14", "a2_days_since"]


def main():
    P, I, E = store.load()
    UE.need(E, ["person", "item", "date"], "store events")
    E = E.assign(person=E.person.astype(str).str.lower(), item=E.item.astype(str), date=E.date.astype(str).str[:10])
    kinds = os.environ.get("A2_KINDS")   # "comment": comments only (exact times). Upvotes are dated to the upvoted launch's day, not
    if kinds:                            # when they were cast, so a team's upvotes on older launches cast ON its own launch day leak
        E = E[E.kind.isin(kinds.split(","))]
    print("event kinds used:", E.kind.value_counts().to_dict(), flush=True)
    by = {u: g for u, g in E.groupby("person")}
    rows = []
    for lid, (d, mk, hu) in teams("data").items():
        mem = [u for u in (mk | {hu}) - {""} if u in by]
        lo14 = str((pd.Timestamp(d) - pd.Timedelta(days=14)).date()); lo7 = str((pd.Timestamp(d) - pd.Timedelta(days=7)).date())
        lo60 = str((pd.Timestamp(d) - pd.Timedelta(days=60)).date())
        G = pd.concat([by[u] for u in mem]) if mem else E.iloc[:0]
        cut = str((pd.Timestamp(d) - pd.Timedelta(days=CUT_DAYS)).date())   # CUT_DAYS=1: dated <= launch day - 2
        G = G[(G.date < cut) & (G.date >= lo60) & (G.item != lid)]
        g14 = G[G.date >= lo14]; g7 = G[G.date >= lo7]
        rows.append({"id": lid, "a2_act7": np.log1p(len(g7)), "a2_act14": np.log1p(len(g14)), "a2_launches14": np.log1p(g14.item.nunique()),
                     "a2_active_members14": float(g14.person.nunique()),
                     "a2_days_since": float((pd.Timestamp(d) - pd.Timestamp(G.date.max())).days) if len(G) else np.nan})
    F = pd.DataFrame(rows)
    print(f"launches {len(F)}; with any team activity in 14 days {int((F.a2_act14 > 0).sum())}", flush=True)
    if os.environ.get("FEATS_OUT"):
        F.to_parquet(os.environ["FEATS_OUT"], index=False)
    return UE.evaluate(F, "a2", COLS, os.environ.get("OUT", "results/a2_team_activity.json"))


if __name__ == "__main__":
    main()
