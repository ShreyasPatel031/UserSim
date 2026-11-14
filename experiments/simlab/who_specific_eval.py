"""Launch-SPECIFICITY of the explain "who" (follow-up to who_lift_eval.py: being closer than the base population only shows the list is made
of active people, which every launch's list is). Strict Nov 8-12, frozen CF-only lists (top 2000 per launch).
Per launch i with >= 10 actual held backers (held before freeze AND re-read after the day):
  list "p"     = top 200 by CF-only probability for i
  list "ratio" = top 200 by p_i / mean over the day's launches of p_j (a person missing from launch j's top 2000 gets that list's minimum p)
Specificity = mean over other same-day launches j of TV(actual_i, list_j) - TV(actual_i, list_i)   (> 0: i's own list matches i's backers
better than other launches' lists do). Role segments and topic taste as on the site. Weighted by backers; launch bootstrap 95%.
    python who_specific_eval.py <store dir> <scratchpad> <day> ...   -> <SP>/backer/who_specific_eval.json"""
import json, os, re, sys
import numpy as np, pandas as pd
DOC = __doc__; HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "backer_arms.py")).read(); exec(SRC[:SRC.index("def day_cols(")])
import period_parts as PP  # noqa: E402
EW = open(os.path.join(HERE, "explain_writer.py")).read(); exec(EW[EW.index("SEG = ["):EW.index("WHO, COV = {}, {}")])
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
seg = dict(zip(PJ.person_id, (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).map(seg_of))); SEGS = sorted(set(seg.values()) | {"no headline or bio"})
Ua = U.assign(ft=pd.to_datetime(U.fetched_at, utc=True)); held = set(PJ.person_id)
last_read = Ua.groupby("person_id").ft.max(); first_read = Ua.groupby("person_id").ft.min()
sdist = lambda ps: pd.Series([seg.get(p, "no headline or bio") for p in ps]).value_counts(normalize=True).reindex(SEGS).fillna(0).values
tvd = lambda a, b: 0.5 * float(np.abs(a - b).sum())
rows = []
for D in TDAYS:
    A_ = pd.read_parquet(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")); A_ = A_[A_.arm == "CF-only"]
    close = PP.close_utc(D); st = close - pd.Timedelta(days=1); H = U[U.fetched_at < start(D)]
    act, tvec, ix = feats(D, H)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held
    obs = Ua[(Ua.lday == D) & Ua.person_id.isin(hf & reread)].groupby("target_id").person_id.agg(set).to_dict()
    PM = A_.pivot_table(index="person_id", columns="launch_id", values="p")
    PM = PM.fillna(A_.groupby("launch_id").p.min())          # missing from a launch's top 2000 -> that list's minimum p
    ratio = PM.div(PM.mean(1), axis=0)
    lists = {"p": {l: PM[l].sort_values(ascending=False).index[:200].tolist() for l in PM.columns},
             "ratio": {l: ratio[l].sort_values(ascending=False).index[:200].tolist() for l in PM.columns}}
    # team pool: held people who upvoted an earlier launch of this launch's hunter / first maker (reads before 00:00 PT of D)
    Hb = H[H.lday < D]; pool = {}
    for l in PM.columns:
        team = [x for x in (lhun.get(str(l)), lmak.get(str(l))) if x]
        ls_ = set().union(*[by_team.get(x, set()) for x in team]) - {str(l)} if team else set()
        pool[l] = Hb[Hb.target_id.isin(ls_)].person_id.unique().tolist() if ls_ else []
    lists["team_pool"] = {l: v for l, v in pool.items() if len(v) >= 20}
    def tdist(ps):
        q = [p for p in ps if p in ix.index]; return tvec[ix[q].values].mean(0) if q else None
    for l in PM.columns:
        o = obs.get(str(l), set())
        if len(o) < 10: continue
        a_s = sdist(o); a_t = tdist(o); r = {"day": D, "launch": str(l), "n": len(o)}
        r["in_team_pool"] = len(o & set(pool.get(l, [])))
        for kind, L_ in lists.items():
            if l not in L_ or len(L_) < 2: continue
            own_s = tvd(a_s, sdist(L_[l])); oth_s = np.mean([tvd(a_s, sdist(L_[j])) for j in L_ if j != l])
            r[f"seg_{kind}"] = oth_s - own_s
            if a_t is not None:
                own_t = tvd(a_t, tdist(L_[l])); oth_t = np.mean([tvd(a_t, tdist(L_[j])) for j in L_ if j != l]); r[f"top_{kind}"] = oth_t - own_t
            r[f"overlap_{kind}"] = np.mean([len(set(L_[l]) & set(L_[j])) / 200 for j in L_ if j != l])
        rows.append(r)
P = pd.DataFrame(rows); rng = np.random.default_rng(0)
def wm(df, c): w = df.n.values; v = df[c].values; m = ~np.isnan(v); return float((v[m] * w[m]).sum() / w[m].sum())
def ci(c):
    bs = [wm(P.iloc[rng.integers(0, len(P), len(P))], c) for _ in range(2000)]
    return [round(100 * wm(P, c), 2), round(100 * float(np.percentile(bs, 2.5)), 2), round(100 * float(np.percentile(bs, 97.5)), 2)]
out = {"design": DOC.split("\n    python")[0], "launches": int(len(P)), "backers": int(P.n.sum()),
       "specificity (TV points x100; > 0 = own list fits own backers better than other launches' lists) [CI]": {f"{k} {kind}": ci(f"{k}_{kind}") for k in ("seg", "top") for kind in ("p", "ratio", "team_pool") if f"{k}_{kind}" in P},
       "share of actual held backers inside the launch's team pool": round(float(P.in_team_pool.sum() / P.n.sum()), 3),
       "mean overlap of a launch's top 200 with other same-day launches' top 200": {kind: round(float(P[f"overlap_{kind}"].mean()), 3) for kind in ("p", "ratio", "team_pool") if f"overlap_{kind}" in P}}
os.makedirs(f"{SP}/backer", exist_ok=True); json.dump(out, open(f"{SP}/backer/who_specific_eval.json", "w"), indent=1, default=float)
print(json.dumps(out, default=float)[-1500:])
