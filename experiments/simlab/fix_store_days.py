"""One-off: in the simlab store (SIMLAB_DATA), move the 204 launches stored on the day before their featuredAt Pacific
day to the right day, and re-date their upvote events (dated by launch day) with them. Comments keep their own
timestamps. Backups: <store>/items.parquet.bak_days, events.parquet.bak_days.
usage: SIMLAB_DATA=data_v2 python -m simlab.fix_store_days"""
import json, os, shutil
import pandas as pd
from . import store
from .shock_model import canonical_days

canon = canonical_days()
I = pd.read_parquet(f"{store.OUT}/items.parquet"); E = pd.read_parquet(f"{store.OUT}/events.parquet")
wrong = I[I.id.map(canon).notna() & (I.day != I.id.map(canon))]
fix = dict(zip(wrong.id, wrong.id.map(canon)))
m = E.item.isin(fix) & (E.kind == "upvote") & (E.date == E.item.map(dict(zip(wrong.id, wrong.day))))
for f in ("items", "events"):
    shutil.copy(f"{store.OUT}/{f}.parquet", f"{store.OUT}/{f}.parquet.bak_days")
I.loc[I.id.isin(fix), "day"] = I.loc[I.id.isin(fix), "id"].map(fix)
E.loc[m, "date"] = E.loc[m, "item"].map(fix)
E = E.drop_duplicates()
I.to_parquet(f"{store.OUT}/items.parquet"); E.to_parquet(f"{store.OUT}/events.parquet")
print(json.dumps({"items_moved": len(fix), "upvote_events_redated": int(m.sum()), "events_after": len(E)}))
