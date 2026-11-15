"""Backer prediction with likely-discounted (ring) votes removed (orchestrator 00:51Z Nov 15, item 2). Strict, same rules as backer_arms_score.py:
o = held-before-freeze AND re-read-after-close people whose upvote list contains the launch, MINUS people flagged by ringlib.dated_flags
(reads fetched before 00:00 PT of D, over-count launches dated before D-1). N = |o|; each list ranked within the re-read people (flagged removed).
Lists: CF-only (trained with ring votes) and CF-only/ring (ring votes removed from CF training); raw most-active and raw/ring (activity
counted without flagged people, flagged people excluded). Pooled recall; paired differences; DAY bootstrap 2000.
Also: share of observed backers removed as flagged.
    python ring_score.py <store dir> <scratchpad> <day> ...   -> <SP>/ring/ring_score.json"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import period_parts as PP, ringlib
from pipeline import warehouse  # noqa: E402
ST, SP, DAYS = sys.argv[1], sys.argv[2], sys.argv[3:]; rng = np.random.default_rng(0)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["votes"] = pd.to_numeric(W.votes, errors="coerce"); U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
per, meta = [], {}
for D in DAYS:
    FR = pd.read_parquet(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")); FR = FR[FR.arm.isin(["CF-only", "CF-only/ring"])]
    if FR.arm.nunique() < 2: meta[D] = "missing an arm"; continue
    close = PP.close_utc(D); st = close - pd.Timedelta(days=1)
    Hs = U[U.ft < st]; RF, n_oc = ringlib.dated_flags(Hs[["person_id", "target_id", "lday"]], W, (pd.Timestamp(D) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held
    obs_all = U[(U.lday == D) & U.person_id.isin(hf & reread)].groupby("target_id").person_id.agg(set).to_dict()
    hist = Hs[(Hs.lday < D) & (Hs.lday >= (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"))]
    rank_all = hist.groupby("person_id").size().sort_values(ascending=False).index
    raw = [p for p in rank_all if p in reread and p not in RF]                      # raw list, flagged people excluded
    raw_ring = [p for p in hist[~hist.person_id.isin(RF)].groupby("person_id").size().sort_values(ascending=False).index if p in reread]
    n_before = sum(len(v) for v in obs_all.values()); n_after = 0
    for lid in FR.launch_id.unique():
        o = obs_all.get(str(lid), set()) - RF; n = len(o); n_after += n
        if not n: continue
        r = {"day": D, "N": n}
        for arm in ("CF-only", "CF-only/ring"):
            g = FR[(FR.launch_id == lid) & (FR.arm == arm)]; g = g[g.person_id.isin(reread - RF)].sort_values("rank"); r[arm] = len(set(g.person_id.iloc[:n]) & o)
        r["raw"] = len(set(raw[:n]) & o); r["raw/ring"] = len(set(raw_ring[:n]) & o); per.append(r)
    meta[D] = {"flagged people (dated)": len(RF), "over-count launches used": n_oc, "observed backers before / after removing flagged": [n_before, n_after]}
P = pd.DataFrame(per)
pooled = lambda df, a: 100 * df[a].sum() / df.N.sum()
def boot(f):
    days = P.day.unique(); g = {d: P[P.day == d] for d in days}
    v = [f(pd.concat([g[d] for d in rng.choice(days, len(days))])) for _ in range(2000)]
    return [round(float(np.percentile(v, 2.5)), 1), round(float(np.percentile(v, 97.5)), 1)]
out = {"design": __doc__.split("\n    python")[0], "per_day": meta, "launches": int(len(P)), "observed_backers (ring removed)": int(P.N.sum())}
for a in ("CF-only", "CF-only/ring", "raw", "raw/ring"): out[a] = [round(pooled(P, a), 1)] + boot(lambda x, a=a: pooled(x, a))
for a, b in (("CF-only/ring", "CF-only"), ("raw/ring", "raw"), ("CF-only/ring", "raw/ring"), ("CF-only", "raw")):
    out[f"{a} minus {b} (paired)"] = [round(pooled(P, a) - pooled(P, b), 1)] + boot(lambda x, a=a, b=b: pooled(x, a) - pooled(x, b))
out["per-day differences CF-only/ring minus CF-only"] = {d: round(pooled(g, "CF-only/ring") - pooled(g, "CF-only"), 1) for d, g in P.groupby("day")}
os.makedirs(f"{SP}/ring", exist_ok=True); json.dump(out, open(f"{SP}/ring/ring_score.json", "w"), indent=1, default=float); print(json.dumps(out, default=float, indent=1))
