"""Is the explain "who" launch-specific? (orchestrator 23:19Z Nov 14, website item 1). Strict Nov 8-12, frozen CF-only lists.
Per launch: actual = held backers (held before the freeze AND re-read after the day, upvote list contains the launch), n >= 10.
Distributions compared: role segments (keyword rule on own headline + bio, as on the site) and topic taste (share of each topic among the
person's upvotes on launches of the 90 days before D, from reads before 00:00 PT; averaged over the group).
  predicted = the CF-only list's top K (K = N_E = expected held backers, 200, 2000); base = all held active people that day.
Score = total-variation distance to the actual backers' distribution (0 = identical). Gain = TV(base) - TV(predicted) (> 0: our list is closer
than the base population). Pooled over launches, weighted by backers; launch bootstrap 95% intervals. Aggregates only.
    python who_lift_eval.py <store dir> <scratchpad> <day> ...   -> <SP>/backer/who_lift_eval.json"""
import json, os, re, sys
import numpy as np, pandas as pd
DOC = __doc__; HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "backer_arms.py")).read(); exec(SRC[:SRC.index("def day_cols(")])
import period_parts as PP  # noqa: E402
EW = open(os.path.join(HERE, "explain_writer.py")).read(); exec(EW[EW.index("SEG = ["):EW.index("WHO, COV = {}, {}")])
TOPN = list(g["TOP"])
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
seg = dict(zip(PJ.person_id, (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).map(seg_of))); SEGS = sorted(set(seg.values()) | {"no headline or bio"})
Ua = U.assign(ft=pd.to_datetime(U.fetched_at, utc=True)); held = set(PJ.person_id)
last_read = Ua.groupby("person_id").ft.max(); first_read = Ua.groupby("person_id").ft.min()
def sdist(people):
    s = pd.Series([seg.get(p, "no headline or bio") for p in people]).value_counts(normalize=True)
    return s.reindex(SEGS).fillna(0).values
tv = lambda a, b: 0.5 * float(np.abs(a - b).sum())
rows = []
for D in TDAYS:
    A_ = pd.read_parquet(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")); A_ = A_[A_.arm == "CF-only"]
    close = PP.close_utc(D); st = close - pd.Timedelta(days=1); H = U[U.fetched_at < start(D)]
    act, tvec, ix = feats(D, H); base_s = sdist(act.index); base_t = tvec.mean(0)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held
    obs = Ua[(Ua.lday == D) & Ua.person_id.isin(hf & reread)].groupby("target_id").person_id.agg(set).to_dict()
    for lid, gl in A_.groupby("launch_id"):
        o = obs.get(str(lid), set())
        if len(o) < 10: continue
        gl = gl.sort_values("rank"); NE = max(1, int(round(gl.p.sum())))
        oa = [p for p in o if p in ix.index]; act_s = sdist(o); act_t = tvec[ix[oa].values].mean(0) if oa else None
        r = {"day": D, "launch": str(lid), "n": len(o), "NE": NE, "tv_seg_base": tv(act_s, base_s), "tv_top_base": tv(act_t, base_t) if act_t is not None else np.nan}
        for K, nm in ((NE, "NE"), (200, "200"), (2000, "2000")):
            top = gl.person_id.iloc[:K].tolist(); r[f"tv_seg_{nm}"] = tv(act_s, sdist(top))
            ti = [p for p in top if p in ix.index]; r[f"tv_top_{nm}"] = tv(act_t, tvec[ix[ti].values].mean(0)) if (act_t is not None and ti) else np.nan
        rows.append(r)
P = pd.DataFrame(rows); rng = np.random.default_rng(0)
def wmean(df, c): w = df.n.values; return float(np.nansum(df[c].values * w) / w[~np.isnan(df[c].values)].sum())
def gain(kind, nm):
    f = lambda df: 100 * (wmean(df, f"tv_{kind}_base") - wmean(df, f"tv_{kind}_{nm}"))
    bs = [f(P.iloc[rng.integers(0, len(P), len(P))]) for _ in range(2000)]
    return [round(f(P), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
out = {"design": DOC.split("\n    python")[0], "launches": int(len(P)), "backers": int(P.n.sum()), "median N_E": float(P.NE.median()),
       "TV distance x100 to actual backers (weighted)": {k: round(100 * wmean(P, f"tv_{k}"), 2) for k in
            ["seg_base", "seg_NE", "seg_200", "seg_2000", "top_base", "top_NE", "top_200", "top_2000"]},
       "gain vs base (TV points x100, >0 = closer than base) [CI]": {f"{kind} top-{nm}": gain(kind, nm) for kind in ("seg", "top") for nm in ("NE", "200", "2000")}}
os.makedirs(f"{SP}/backer", exist_ok=True); json.dump(out, open(f"{SP}/backer/who_lift_eval.json", "w"), indent=1, default=float)
print(json.dumps(out, default=float)[-2500:])
