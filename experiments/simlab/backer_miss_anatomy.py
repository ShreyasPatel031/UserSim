"""Anatomy of CF-only's forward misses (orchestrator 22:54Z Nov 14). Strict, Nov 8-12, same frozen CF-only lists and the same scoring as
backer_arms_score.py: o = held-before-freeze AND re-read-after-close people whose upvote list contains the launch; N = |o|; CF-only list ranked
within the re-read people; a MISS = a person in o not in the top N. Each miss goes to the FIRST bucket that applies:
  (a) backed this team before: upvoted (reads before 00:00 PT of D) an earlier launch whose hunter or first maker is this launch's
  (b) follows the hunter or first maker in a follow read fetched before 00:00 PT of D (dated). Follows seen only in reads fetched later are
      reported separately as (b-undated) and NOT used for bucketing
  (c) taste-near: in the launch's CF-only list ranked within (N, 5N] (just below the cut). The literal "launch in their CF top 20" is true for
      every person on days with <= 20 launches, so the near-cut rank is used instead
  (d) not active: no upvote on launches of the 30 days before D (reads before 00:00 PT of D)
  (e) none of these
Per bucket: share of misses (launch bootstrap 95%), and the oracle recall at N if every miss in that bucket were named (pooled).
    python backer_miss_anatomy.py <store dir> <scratchpad> <day> ...   -> <SP>/backer/miss_anatomy.json (aggregates only)"""
import json, os, sys
import numpy as np, pandas as pd
DOC = __doc__
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "backer_arms.py")).read()
exec(SRC[:SRC.index("def day_cols(")])   # setup: U, L, FO via g, lhun, lmak, by_team, start, LINE, TDAYS ...
import period_parts as PP  # noqa: E402
FO = g["FO"]; FO = FO.assign(ft=pd.to_datetime(FO.fetched_at, utc=True))
Uall = U.assign(ft=pd.to_datetime(U.fetched_at, utc=True))
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
last_read = Uall.groupby("person_id").ft.max(); first_read = Uall.groupby("person_id").ft.min()
rows = []
for D in TDAYS:
    A_ = pd.read_parquet(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")); A_ = A_[A_.arm == "CF-only"]
    close = PP.close_utc(D); st = close - pd.Timedelta(days=1); cut = start(D)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held
    H = Uall[Uall.fetched_at < cut]
    obs = Uall[(Uall.lday == D) & Uall.person_id.isin(hf & reread)].groupby("target_id").person_id.agg(set).to_dict()
    d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); active30 = set(H[(H.lday < D) & (H.lday >= d30)].person_id)
    FOd = FO[FO.fetched_at < cut]
    FOu = FO[~FO.index.isin(FOd.index)]
    fd = FOd.groupby("target_id").person_id.agg(set).to_dict(); fu = FOu.groupby("target_id").person_id.agg(set).to_dict()
    Hb = H[H.lday < D]
    for lid, g_ in A_.groupby("launch_id"):
        o = obs.get(str(lid), set()); n = len(o)
        if not n: continue
        gl = g_[g_.person_id.isin(reread)].sort_values("rank"); ranked = gl.person_id.tolist()
        top = set(ranked[:n]); near = set(ranked[n:5 * n]); miss = o - top
        team = [x for x in (lhun.get(str(lid)), lmak.get(str(lid))) if x]
        ls = set().union(*[by_team.get(x, set()) for x in team]) - {str(lid)} if team else set()
        backed = set(Hb[Hb.target_id.isin(ls)].person_id) if ls else set()
        fol_d = set().union(*[fd.get(x, set()) for x in team]) if team else set(); fol_u = set().union(*[fu.get(x, set()) for x in team]) if team else set()
        b = {"a": 0, "b": 0, "c": 0, "d": 0, "e": 0}; b_und = 0
        for p in miss:
            if p in backed: b["a"] += 1
            elif p in fol_d: b["b"] += 1
            elif p in near: b["c"] += 1
            elif p not in active30: b["d"] += 1
            else: b["e"] += 1
            if p in fol_u and p not in fol_d: b_und += 1
        pool_b = backed & reread & hf
        rows.append({"day": D, "launch": str(lid), "N": n, "hits": n - len(miss), "miss": len(miss), **b, "b_undated": b_und,
                     "backed_pool": len(pool_b), "backed_pool_voted": len(pool_b & o)})
P = pd.DataFrame(rows); rng = np.random.default_rng(0)
def boot(f):
    v = [f(P.iloc[rng.integers(0, len(P), len(P))]) for _ in range(2000)]; return [round(float(np.percentile(v, 2.5)), 1), round(float(np.percentile(v, 97.5)), 1)]
NAMES = {"a": "(a) backed this team before", "b": "(b) follows hunter / first maker (dated)", "c": "(c) taste-near (CF rank in (N, 5N])",
         "d": "(d) not active in the 30 days before", "e": "(e) none of these"}
out = {"design": DOC.split("\n    python")[0], "launches": int(len(P)), "observed_backers": int(P.N.sum()), "misses": int(P.miss.sum()),
       "CF-only recall at N (pooled)": round(100 * P.hits.sum() / P.N.sum(), 1), "buckets": {}}
for k, nm in NAMES.items():
    out["buckets"][nm] = {"n": int(P[k].sum()), "share of misses %": [round(100 * P[k].sum() / P.miss.sum(), 1)] + boot(lambda x, k=k: 100 * x[k].sum() / max(x.miss.sum(), 1)),
                          "oracle recall at N if fixed %": round(100 * (P.hits.sum() + P[k].sum()) / P.N.sum(), 1)}
out["(b-undated) follows seen only in later reads, among misses"] = {"n": int(P.b_undated.sum()), "share of misses %": round(100 * P.b_undated.sum() / P.miss.sum(), 1)}
out["backed-before pool (re-read, held before freeze)"] = {"people per launch (median)": float(P.backed_pool.median()), "N per launch (median)": float(P.N.median()),
    "share of the pool who voted %": round(100 * P.backed_pool_voted.sum() / max(P.backed_pool.sum(), 1), 1), "pool / N (pooled)": round(P.backed_pool.sum() / P.N.sum(), 2)}
out["per day"] = {d: {"N": int(x.N.sum()), "misses": int(x.miss.sum()), **{k: int(x[k].sum()) for k in NAMES}} for d, x in P.groupby("day")}
os.makedirs(f"{SP}/backer", exist_ok=True); json.dump(out, open(f"{SP}/backer/miss_anatomy.json", "w"), indent=1, default=float)
print(json.dumps(out, default=float)[:3000])
