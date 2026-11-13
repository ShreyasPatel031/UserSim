"""Size the post-launch "vote back" leak for team upvote features (orchestrator 10:38Z Nov 13). Upvote rows with cast-time bounds
(ts_quality bounded: lo from list order + launch times, hi = earliest read showing it) let us classify a team member's upvote on an
OLDER launch as cast before the member's own launch day (hi < D 00:00 PT), after it (lo >= D), or undetermined. Reported by lag (target
launch dated 1 / 2-7 / 8-30 days before D) and the share cast in the 24 h after D.
    python team_leak_size.py <scratchpad> <merged store>
"""
import glob, hashlib, json, sys
import numpy as np, pandas as pd
SP, ST = sys.argv[1:3]; PT = "America/Los_Angeles"
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
lday = dict(zip(L.id, pd.to_datetime(L.day)))
P = pd.read_parquet(f"{ST}/persons.parquet"); C = set(P[P.complete].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "ts_lo", "ts_hi", "ts_quality"]); U = E[(E.kind == "upvote") & (E.ts_quality == "bounded") & E.person_id.isin(C)].copy()
U["target_id"] = U.target_id.astype(str); U["d"] = U.target_id.map(lday); U = U[U.d.notna()]
for c in ("ts_lo", "ts_hi"): U[c] = pd.to_datetime(U[c], utc=True).dt.tz_convert(PT).dt.tz_localize(None)
G = {p: g for p, g in U.groupby("person_id")}; rows = []
for r in L.itertuples():
    D = pd.Timestamp(r.day)
    for m in set(([pid(r.poster)] if isinstance(r.poster, str) and r.poster and not r.poster.startswith("[") else []) + mk(r.makers)):
        g = G.get(m)
        if g is None: continue
        w = g[(g.d < D) & (g.d >= D - pd.Timedelta(days=30))]
        for x in w.itertuples():
            lag = (D - x.d).days; st = "before" if x.ts_hi < D else ("after" if x.ts_lo >= D else "undetermined")
            rows.append((lag, st, bool(x.ts_lo >= D and x.ts_lo < D + pd.Timedelta(hours=24)), r.daily_rank <= 10))
X = pd.DataFrame(rows, columns=["lag", "status", "after_24h", "top10"]); print("team-member bounded upvotes on older launches:", len(X))
X["lagb"] = pd.cut(X.lag, [0, 1, 7, 30], labels=["1 day", "2-7 days", "8-30 days"])
t = X.groupby("lagb", observed=True).status.value_counts().unstack(fill_value=0); t["after share of determined"] = (t.get("after", 0) / (t.get("after", 0) + t.get("before", 0))).round(3); print(t.to_string())
print("after-launch votes within 24 h of own launch, share of all after:", round(float(X[X.status == 'after'].after_24h.mean()), 3) if (X.status == 'after').any() else None)
print("after share of determined, own launch top-10 vs not:", X[X.status != "undetermined"].groupby("top10").status.apply(lambda s: round(float((s == "after").mean()), 3)).to_dict())
