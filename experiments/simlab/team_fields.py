"""(team_fields) Team person fields on top of the stack base; adapted from team_stack.py. Team engagement on top of the stack base (orchestrator 10:38Z Nov 13). Base = clean 00:05 (honest_preds_v2) + th_n_pre (distinct
non-hunter commenters by 00:05 PT, launch thread dumps, as early_stack.py), month-forward ridge (alpha 10) on within-day z, target z of
-log(rank). Added block: team (hunter + named makers, complete in the merged store) upvotes given 7 d / 30 d, distinct makers supported
30 d (log1p) + coverage flag; variant LAG2 = only launches dated >= 2 days before. Days = those with thread data and >= 10 launches.
Paired day bootstrap top 3 / 5 / 10, overall and on days with >= 40% covered launches. Counts only.
    python team_stack.py <scratchpad> <merged store> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP, ST, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()].reset_index(drop=True)
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["h"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["m"] = [mk(m) for m in L.makers]
bys = {s: i for i, s in enumerate(L.slug)}; npre = {}
for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]; t5 = pd.Timestamp(L.day.iat[i]).tz_localize(PT, ambiguous=True).tz_convert("UTC") + pd.Timedelta(minutes=5); us = set()
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t and pd.Timestamp(t) <= t5 and pid(u) != L.h.iat[i]: us.add(pid(u))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
        npre[i] = max(npre.get(i, 0), len(us))
L["th_n_pre"] = [npre.get(i, np.nan) for i in range(len(L))]

# --- team person fields from the lossless store (14:35Z): dated safely ---
P = pd.read_parquet(f"{ST}/persons.parquet"); P = P.set_index("person_id"); comp = set(P.index[P.complete])
mh = {p: [pd.Timestamp(e["date"]).tz_convert("UTC") for e in json.loads(j) if e.get("date")] for p, j in P.maker_history_json.dropna().items() if j and j.startswith("[")}
pull = pd.to_datetime(P.pull_finished_utc, utc=True, errors="coerce")
EV = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "ts_lo", "ts_hi", "fetched_at"]); RV = EV[EV.kind == "review"].copy()
RV["t"] = RV.ts_hi.fillna(RV.fetched_at); RVg = {p: g.t.values for p, g in RV.groupby("person_id")}
H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str); B = L.merge(H, on="id"); B["rank"] = B.daily_rank.astype(float); feats = []
for r in B.itertuples():
    d0 = pd.Timestamp(r.day).tz_localize(PT, ambiguous=True).tz_convert("UTC"); team = [m for m in dict.fromkeys(([r.h] if r.h else []) + r.m) if m in comp]
    o = {"covr": float(bool(team)), "n_team_held": float(len(team))}
    prior = [sum(t < d0 - pd.Timedelta(hours=12) for t in mh.get(m, [])) for m in team]
    o["mh_prior"] = float(max(prior)) if prior else 0.0
    last = [max([t for t in mh.get(m, []) if t < d0 - pd.Timedelta(hours=12)], default=None) for m in team]; last = [x for x in last if x is not None]
    o["mh_days_since"] = float(min((d0 - x).days for x in last)) if last else 999.0
    o["rev_written"] = float(sum(int((RVg.get(m, np.array([], "datetime64[ns]")) < d0.to_datetime64()).sum()) for m in team)) if team else 0.0
    o["has_headline"] = float(any(isinstance(P.headline.get(m), str) and P.headline.get(m).strip() for m in team)); o["has_bio"] = float(any(isinstance(P.bio.get(m), str) and P.bio.get(m).strip() for m in team))
    pre = [m for m in team if pull.get(m) is not pd.NaT and pull.get(m) < d0]   # snapshot fields only when pulled before the day
    o["pre_pulled"] = float(bool(pre)); o["badges"] = float(max([P.badges_count.get(m) or 0 for m in pre], default=0))
    feats.append(o)
B = pd.concat([B.reset_index(drop=True), pd.DataFrame(feats)], axis=1); B = B[B.th_n_pre.notna()]
B = B[B.groupby("day").id.transform("count") >= 10]
z = lambda s: (s - s.mean()) / (s.std() or 1)
FC = ["mh_prior", "mh_days_since", "rev_written", "has_headline", "has_bio"]
for c in ["honest", "th_n_pre", "covr"] + FC:
    B["z_" + c] = B.groupby("day")[c].transform(lambda s: z(np.log1p(s) if c not in ("honest", "covr", "has_headline", "has_bio") else s)).fillna(0)
B["y"] = B.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); B["mon"] = B.day.str[:7]; B["covday"] = B.groupby("day").covr.transform("mean")
BASE = ["z_honest", "z_th_n_pre", "z_covr"]
ARMS = {"base (clean + th_n_pre)": BASE, "+ maker history": BASE + ["z_mh_prior", "z_mh_days_since"], "+ reviews written": BASE + ["z_rev_written"],
        "+ headline/bio present": BASE + ["z_has_headline", "z_has_bio"], "+ all": BASE + ["z_" + c for c in FC]}
mons = sorted(B.mon.unique())
for a, X in ARMS.items():
    B[a] = np.nan
    for m in mons[1:]:
        tr, te = B[B.mon < m], B[B.mon == m]; B.loc[te.index, a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
def ov(g, col): o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
T = B[B["+ all"].notna()]; res = {"design": __doc__.split("\n    python")[0], "days": int(T.day.nunique()), "launches": len(T), "coverage": round(float(T.covr.mean()), 3)}
for sub, m in (("all days", T.day.notna()), ("days with >= 40% covered", T.covday >= 0.4)):
    S = T[m]; o = {"days": int(S.day.nunique()), "levels top3/5/10": {a: np.array([ov(g, a) for _, g in S.groupby("day")]).mean(0).round(1).tolist() for a in ARMS}}
    for a in ARMS:
        if a == "base (clean + th_n_pre)": continue
        b = "base (clean + th_n_pre)"
        d = np.array([np.array(ov(g, a)) - np.array(ov(g, b)) for _, g in S.groupby("day")]); bs = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(2000)])
        o[f"{a} - base"] = [[round(float(d[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
    def resid(v, Zm): Z1 = np.c_[np.ones(len(v)), Zm]; return v - Z1 @ np.linalg.lstsq(Z1, v, rcond=None)[0]
    for c in FC:
        dd = S.day.unique(); f_ = lambda D: np.corrcoef(resid(D.y.values, D[BASE].values), resid(D["z_" + c].values, D[BASE].values))[0, 1]
        bsv = [f_(pd.concat([S[S.day == x] for x in rng.choice(dd, len(dd))])) for _ in range(300)]
        o[f"partial r {c}"] = [round(float(f_(S)), 4), round(float(np.nanpercentile(bsv, 2.5)), 4), round(float(np.nanpercentile(bsv, 97.5)), 4)]
    o["coverage: launches with a held team member / with maker history before / pulled before the day"] = [round(float(S.covr.mean()), 3), round(float((S.mh_prior > 0).mean()), 3), round(float(S.pre_pulled.mean()), 3)]
    res[sub] = o
json.dump(res, open(f"{OUT}/team_fields.json", "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
