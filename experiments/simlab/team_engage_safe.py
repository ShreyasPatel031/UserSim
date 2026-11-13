import sys, json, glob, hashlib, numpy as np, pandas as pd
SP = sys.argv[1]; rng = np.random.default_rng(0); PT = "America/Los_Angeles"
F = pd.read_parquet(f"{SP}/teng/team_engage_rows.parquet")
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
team = {i: list(dict.fromkeys(([pid(p)] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m))) for i, p, m in zip(L.id, L.poster, L.makers)}; lday = dict(zip(L.id, L.day))
P = pd.read_parquet(f"{SP}/store_merged/persons.parquet"); C = set(P[P.complete].person_id)
E = pd.read_parquet(f"{SP}/store_merged/events.parquet", columns=["person_id", "kind", "target_id", "ts_hi"]); U = E[(E.kind == "upvote") & E.person_id.isin(C)].copy(); U["target_id"] = U.target_id.astype(str)
U["d"] = pd.to_datetime(U.target_id.map(lday)); U = U[U.d.notna()]; U["hi"] = pd.to_datetime(U.ts_hi, utc=True).dt.tz_convert(PT).dt.tz_localize(None)
U = U.sort_values("hi").drop_duplicates(["person_id", "target_id"], keep="first"); G = {p: g for p, g in U.groupby("person_id")}
rk = lambda a: pd.Series(a).rank().to_numpy()
def partial(y, b, x):
    y, b, x = rk(y), rk(b), rk(x); return float(np.corrcoef(y - np.polyval(np.polyfit(b, y, 1), b), x - np.polyval(np.polyfit(b, x, 1), b))[0, 1])
rows = []
for r in F[F.T_cov == 1].itertuples():
    D = pd.Timestamp(r.day); safe = allv = 0; anyafter = False
    for m in team.get(r.id, []):
        g = G.get(m)
        if g is None: continue
        w = g[(g.d < D) & (g.d >= D - pd.Timedelta(days=30))]; allv += len(w); s = w[w.hi < D]; safe += len(s); anyafter |= bool((w.hi >= D).any())
    rows.append((r.day, r.id, r.rank, r.honest, allv, safe, anyafter))
X = pd.DataFrame(rows, columns=["day", "id", "rank", "honest", "all30", "safe30", "has_post_pull"])
print("covered launches", len(X), "| share of 30d upvotes provably before the day (ts_hi < day):", round(X.safe30.sum() / max(1, X.all30.sum()), 3), "| launches whose 30d upvotes are ALL provably before:", round(float((~X.has_post_pull & (X.all30 > 0)).mean()), 3))
X["mon"] = X.day.str[:7]; print(X.groupby("mon").apply(lambda g: round(g.safe30.sum() / max(1, g.all30.sum()), 3)).to_dict())
for nm, col in (("all upvotes", "all30"), ("provably before only", "safe30")):
    pc = [partial(-g["rank"].to_numpy(), g.honest.to_numpy(), g[col].to_numpy()) for _, g in X.groupby("day") if len(g) >= 5 and g[col].nunique() > 1]
    pc = np.array([p for p in pc if p == p]); bs = [pc[rng.integers(0, len(pc), len(pc))].mean() for _ in range(2000)] if len(pc) else [np.nan]
    print(nm, "partial beyond clean:", round(float(pc.mean()), 3) if len(pc) else None, np.percentile(bs, [2.5, 97.5]).round(3), "days", len(pc))
# same-day comparison restricted to launches where every 30d upvote is provably before
Y = X[~X.has_post_pull]
pc = [partial(-g["rank"].to_numpy(), g.honest.to_numpy(), g.all30.to_numpy()) for _, g in Y.groupby("day") if len(g) >= 5 and g.all30.nunique() > 1]
pc = np.array([p for p in pc if p == p]); print("launches with NO post-pull rows:", len(Y), "partial", round(float(pc.mean()), 3) if len(pc) else None, "days", len(pc))
