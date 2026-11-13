"""Which launch types the standalone who-backs-it model gets right (orchestrator 17:40Z Nov 13, part 3). Input: who_backs.py per-launch
dump (DUMP=..., follows on): E, clean_v3_nosite, final rank, displayed votes, held voters per launch. Per launch: |within-day rank of E -
final rank| vs the same for clean; and, for real top-3 launches, whether E / clean put them in their day's top 3. Segments: team held
(hunter or a named maker complete in the store), held-voter share (held voters / displayed votes, terciles), final-votes tercile.
Launch-bootstrap intervals. Counts only.
    python who_backs_segments.py <dump.parquet> <store dir> <launches dir> <salt dir> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
DP, ST, LD, SD, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
salt = open(os.path.join(SD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
D = pd.read_parquet(DP); comp = set(pd.read_parquet(os.path.join(ST, "persons.parquet")).query("complete").person_id)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LD, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def team(p, m):
    hs = [p] if isinstance(p, str) and p and not p.startswith("[") else []
    try: hs += [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: pass
    return sum(pid(h) in comp for h in dict.fromkeys(hs))
th = {i: team(p, m) for i, p, m in zip(L.id, L.poster, L.makers)}
D["n_team_held"] = D.id.map(th).fillna(0).astype(float); D["team_held"] = D.n_team_held > 0; D["votes"] = D.votes.astype(float); D["share"] = D.n_held / D.votes
D["rk_E"] = D.groupby("day").E.rank(ascending=False); D["rk_C"] = D.groupby("day").clean_v3_nosite.rank(ascending=False)
D["errE"] = (D.rk_E - D["rank"]).abs(); D["errC"] = (D.rk_C - D["rank"]).abs(); D["top3"] = D["rank"] <= 3
D["E_hit"] = D.rk_E <= 3; D["C_hit"] = D.rk_C <= 3
D["share_t"] = pd.qcut(D.share.rank(method="first"), 3, labels=["low", "mid", "high"]); D["votes_t"] = pd.qcut(D.votes.rank(method="first"), 3, labels=["small", "mid", "large"])
def bt(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; return [round(float(v.mean()), 2), round(float(np.percentile(b, 2.5)), 2), round(float(np.percentile(b, 97.5)), 2), len(v)]
res = {"launches": len(D), "days": int(D.day.nunique())}
for seg in ("team_held", "share_t", "votes_t"):
    o = {}
    for k, g in D.groupby(seg, observed=True):
        t3 = g[g.top3]
        o[str(k)] = {"rank error E - clean (mean, lower = E better)": bt(g.errE - g.errC),
                     "real top-3 launches: share E puts in its top 3 / clean": [bt(t3.E_hit.astype(float)), bt(t3.C_hit.astype(float))]}
    res[seg] = o
# placebo (orchestrator 17:47Z): rank by number of held team members alone (ties broken by a fixed random draw)
D["plac"] = D.n_team_held + rng.random(len(D)) * 1e-3
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
days = sorted(D.day.unique()); A = {c: np.array([dm(D[D.day == d], c) for d in days]) for c in ("E", "plac", "clean_v3_nosite")}
def pd_(a, b):
    df = A[a] - A[b]; bs = np.array([df[rng.integers(0, len(days), len(days))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
res["placebo"] = {"days": len(days), "levels top3/5/10": {k: v.mean(0).round(1).tolist() for k, v in A.items()},
                  "E - placebo": pd_("E", "plac"), "placebo - clean": pd_("plac", "clean_v3_nosite"), "E - clean": pd_("E", "clean_v3_nosite")}
json.dump(res, open(os.path.join(OUT, "who_backs_segments.json"), "w"), indent=1); print(json.dumps(res))
