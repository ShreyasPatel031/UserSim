import pandas as pd, numpy as np, json, glob, hashlib, sys
from scipy.stats import spearmanr
SP = sys.argv[1]; SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def mk(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    return {pid(x) for x in ms if x and not str(x).startswith("[")}
team = {i: ({pid(p)} if isinstance(p, str) and p and not p.startswith("[") else set()) | mk(m) for i, p, m in zip(L.id, L.poster, L.makers)}; lday = dict(zip(L.id, L.day))
P = pd.read_parquet(f"{SP}/tl/v3/persons.parquet"); COV = set(P[P.complete].person_id)
E = pd.read_parquet(f"{SP}/tl/v3/events.parquet", columns=["person_id", "kind", "target_id", "first_seen_at", "source"]); E = E[E.person_id.isin(COV)]
U = E[E.kind == "upvote"]; anc = {}
for p, t in zip(U.person_id, U.target_id.astype(str)):
    d = lday.get(t)
    if d:
        for m in team.get(t, ()): k = (p, m); anc[k] = min(anc.get(k, d), d)
f = E[(E.kind == "follows") & (E.source == "people_live:vm:reused_browser")].copy()
f["page"] = f.groupby("person_id").cumcount(); f["anc"] = [anc.get((p, t)) for p, t in zip(f.person_id, f.target_id)]
a = f[f.anc.notna()].copy(); a["ad"] = pd.to_datetime(a.anc).astype("int64") // 86400_000_000_000
print("follow edges with a dated anchor", len(a), "people", a.person_id.nunique())
rs = [spearmanr(g.page, g.ad).correlation for _, g in a.groupby("person_id") if len(g) >= 5 and g.page.nunique() > 1 and g.ad.nunique() > 1]
rs = np.array([r for r in rs if r == r]); print("people with >=5 anchored follows on >1 page", len(rs), "median spearman(page, anchor date)", round(float(np.median(rs)), 3), "share negative", round(float((rs < 0).mean()), 3))
# relative position of anchored follows by anchor month
a["rel"] = a.page / a.groupby("person_id").page.transform("max").clip(lower=1); a["n"] = f.groupby("person_id").page.transform("max").reindex(a.index)
print(a.assign(m=a.anc.str[:7]).groupby("m").rel.agg(["mean", "size"]).round(3).to_string())
