"""Which per-person fields predict launch-day turnout? (population agent; counts/correlations only)
Label: person p turned up on PT day d = upvoted >= 1 launch featured on d (from the Nov 1 page-1 read; cast time unknown,
so this is "voted for a day-d launch", usually on day d). Days Oct 15-31. Features use only items before d:
upvotes on launches featured before d (launch-day proxy), comments with exact times before d; plus snapshot fields read
after d (profile totals, follow counts, following-page-1), marked LATE (leaky, for ranking signal size only).
Eligible on day d: page-1 list complete, or its oldest launch is >= 30 d before d (so the 30-d window is fully seen).
Per day: Spearman(feature, turned_up) across eligible people; report mean over days and the turnout rate.
Usage: python turnout_fields.py DATA_DIR
"""
import json, sys
import numpy as np, pandas as pd

D = sys.argv[1]
u = pd.read_json(f"{D}/up/upvotes_page1_full.jsonl", lines=True)
u = u[u.post_id.notna()].copy()
u["user"] = u.username.str.lower()
u["day"] = pd.to_datetime(u.launched_at, utc=True, format="mixed").dt.tz_convert("America/Los_Angeles").dt.tz_localize(None).dt.normalize()
meta = u.groupby("user").agg(hm=("has_more", "first"), oldest=("day", "min"))
e = pd.read_parquet(f"{D}/people_v3g/events.parquet")
c = e[(e.platform == "producthunt") & (e.kind == "comment")].copy()
c["user"] = c.person_id.str.replace("^ph:", "", regex=True).str.lower()
c["t"] = pd.to_datetime(c.ts, utc=True, format="mixed").dt.tz_convert("America/Los_Angeles").dt.tz_localize(None)
p = pd.read_parquet(f"{D}/people_v3g/profiles.parquet")
p = p[p.platform == "producthunt"].copy()
p["user"] = p.handle.str.lower()
x = pd.json_normalize(p.extra.map(json.loads)); x.index = p.index
for k in ["upvotes_total", "products_made", "hunted", "visit_streak_days", "reviews_count", "collections"]:
    p[k] = pd.to_numeric(x[k], errors="coerce")
prof = p.drop_duplicates("user").set_index("user")
fol = pd.read_json(f"{D}/daily/1102/following_page1.jsonl", lines=True)
fol["user"] = fol.username.str.lower()
fol_big = fol[fol.followee_followers >= 1000].groupby("user").size()

users = meta.index
res = []
for d in pd.date_range("2026-10-15", "2026-10-31"):
    elig = meta[(meta.hm == False) | (meta.oldest <= d - pd.Timedelta(days=30))].index
    uu = u[u.user.isin(elig)]
    y = uu[uu.day == d].groupby("user").size().reindex(elig, fill_value=0).gt(0).astype(int)
    before = uu[uu.day < d]
    f = pd.DataFrame(index=elig)
    for w in (1, 7, 30):
        win = before[before.day >= d - pd.Timedelta(days=w)]
        f[f"upv_{w}d"] = win.groupby("user").size()
        f[f"active_days_{w}d"] = win.groupby("user").day.nunique()
    last = before.groupby("user").day.max()
    f["days_since_last_upv"] = -((d - last).dt.days)
    wd = before[before.day >= d - pd.Timedelta(days=56)]
    f["same_weekday_8w"] = wd[wd.day.dt.weekday == d.weekday()].groupby("user").day.nunique()
    cb = c[c.user.isin(elig) & (c.t < d)]
    for w in (7, 30):
        f[f"comments_{w}d"] = cb[cb.t >= d - pd.Timedelta(days=w)].groupby("user").size()
    f["comments_ever"] = cb.groupby("user").size()
    for k in ["upvotes_total", "followers", "following", "products_made", "hunted", "visit_streak_days", "reviews_count"]:
        f[f"LATE_{k}"] = prof[k].reindex(elig)
    f["LATE_follows_1k+_accounts_p1"] = fol_big.reindex(elig)
    f = f.fillna(0)
    row = {"day": d.date(), "eligible": len(elig), "turnout": y.mean()}
    for col in f:
        row[col] = f[col].rank().corr(y.rank()) if f[col].std() > 0 else np.nan
    res.append(row)
r = pd.DataFrame(res)
print(r[["day", "eligible", "turnout"]].to_string(index=False))
feat = r.drop(columns=["day", "eligible", "turnout"])
s = pd.DataFrame({"mean_spearman": feat.mean(), "min": feat.min(), "max": feat.max()}).sort_values("mean_spearman", ascending=False)
print(s.round(3).to_string())
