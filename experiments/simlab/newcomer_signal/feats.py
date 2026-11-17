import sys, numpy as np, pandas as pd
SP = sys.argv[1]
P = pd.read_parquet(f"{SP}/store_live/persons.parquet", columns=["person_id", "ph_user_id"]); pid = dict(zip(P.ph_user_id.astype(str), P.person_id))
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id", "ts_lo"]); E = E[E.kind.isin(["hunted", "launched"]) & E.ts_lo.notna()]
E = E.drop_duplicates(["person_id", "kind", "target_id"]); E["d"] = E.ts_lo.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
G = {p: g for p, g in E.groupby("person_id")}
X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "day", "hunter_id"]); X["id"] = X.id.astype(str); X = X.drop_duplicates("id")
rows = []
for r in X.itertuples(index=False):
    p = pid.get(str(r.hunter_id)); out = {"id": r.id, "H4_in_store": float(p is not None)}
    if p is None: out.update(H1_hunts=np.nan, H2_launches=np.nan, H3_days_since=np.nan)
    else:
        g = G.get(p); g = g[g.d < r.day] if g is not None else None
        if g is None or not len(g): out.update(H1_hunts=0.0, H2_launches=0.0, H3_days_since=np.nan)
        else:
            out.update(H1_hunts=np.log1p((g.kind == "hunted").sum()), H2_launches=np.log1p((g.kind == "launched").sum()),
                       H3_days_since=np.log1p((pd.Timestamp(r.day) - pd.to_datetime(g.d.max())).days))
    rows.append(out)
F = pd.DataFrame(rows); F.to_parquet(f"{SP}/nc/hfeats.parquet"); print(F.describe().T)
