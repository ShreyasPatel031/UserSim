"""Team track record from the people store (orchestrator 02:07Z Nov 13). The clean 00:05 model already holds the hunter's record
(hist_hunter_n / _rel / _top5, warehouse launches) and drops every maker-history input (hist_maker_*), so this adds:
  maker (first named maker, safe at 00:05 in most reads), from the person's complete "launched" + "hunted" tabs in the store, launches dated
  strictly before the target day: n past launches, best and median ln(1+final votes), n that finished daily top 5, days since the last;
  relaunch: an earlier ranked launch of the same product (same slug stem / name), its ln votes;
  hunter: median final daily rank of past hunts from the store's hunted tab (OVERLAPS clean's hist_hunter_rel; reported separately).
Past launches' final votes / ranks are frozen, so values read after the target day cannot have changed; tab MEMBERSHIP was read in Nov
(a launch made after the target day is excluded by date). Coverage per launch first; < 15% -> stop.
Leave-day-out over Mar 1 - Nov 10 (honest_preds_v2 = clean 00:05 as-of score; th_n_pre is not held over the window): ridge on within-day z of
[clean, feature block], weight chosen on other days; top 3/5/10, paired day bootstrap.
    python team_record.py <store dir> <launches dir> <salt dir> <honest_preds_v2.parquet> <out dir>
"""
import glob, hashlib, json, os, re, sys
import numpy as np, pandas as pd
V3, LDIR, SALTD, HP, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float); L["lv"] = np.log1p(pd.to_numeric(L.votes, errors="coerce"))
def fmk(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    ms = [x for x in ms if x and not str(x).startswith("[")]; return pid(ms[0]) if ms else None
L["hun"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["mak"] = [fmk(m) for m in L.makers]
L["stem"] = L.slug.astype(str).str.replace(r"-\d+$", "", regex=True).str.replace(r"-[0-9a-f]{6,}$", "", regex=True); L["nm"] = L.name.astype(str).str.lower().str.strip()
info = L.set_index("id")[["day", "rank", "lv"]].to_dict("index")
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[E.kind.isin(["launched", "hunted"]) & E.person_id.isin(COV)]
E["target_id"] = E.target_id.astype(str); E = E[E.target_id.isin(info)]
made = E[E.kind == "launched"].groupby("person_id").target_id.agg(list).to_dict(); hunted = E[E.kind == "hunted"].groupby("person_id").target_id.agg(list).to_dict()
rows = []
for r in L.itertuples():
    o = {"id": r.id}
    past = [info[t] for t in (made.get(r.mak, []) + hunted.get(r.mak, [])) if info[t]["day"] < r.day] if r.mak in COV else None
    o["mk_known"] = float(past is not None)
    if past:
        v = [p["lv"] for p in past if p["lv"] == p["lv"]]
        o.update({"mk_n": np.log1p(len(past)), "mk_best": max(v) if v else 0, "mk_med": float(np.median(v)) if v else 0,
                  "mk_top5": float(sum(p["rank"] <= 5 for p in past)), "mk_since": np.log1p((pd.Timestamp(r.day) - pd.Timestamp(max(p["day"] for p in past))).days)})
    else: o.update({"mk_n": 0, "mk_best": 0, "mk_med": 0, "mk_top5": 0, "mk_since": np.log1p(400)})
    hp = [info[t] for t in hunted.get(r.hun, []) if info[t]["day"] < r.day] if r.hun in COV else []
    o["hu_med_rank"] = -np.log(np.median([p["rank"] for p in hp])) if hp else 0.0; o["hu_known"] = float(bool(hp))
    rows.append(o)
F = L[["id", "day", "rank", "stem", "nm", "lv"]].merge(pd.DataFrame(rows), on="id")
# relaunch: earlier ranked launch with the same slug stem or name
F = F.sort_values("day"); prev = {}; rl, rlv = [], []
for r in F.itertuples():
    k1, k2 = ("s", r.stem), ("n", r.nm); p = [x for x in prev.get(k1, []) + prev.get(k2, []) if x[0] < r.day]
    rl.append(float(bool(p))); rlv.append(max(x[1] for x in p) if p else 0.0)
    for k in (k1, k2): prev.setdefault(k, []).append((r.day, r.lv))
F["relaunch"], F["relaunch_lv"] = rl, rlv
H = pd.read_parquet(HP)[["id", "honest"]]; H["id"] = H.id.astype(str); F = F.merge(H, on="id")
cov = {"launches": len(F), "maker_identified_and_complete": round(float(F.mk_known.mean()), 3), "maker_with_past_launches": round(float((F.mk_n > 0).mean()), 3),
       "relaunch": round(float(F.relaunch.mean()), 3), "hunter_with_past_hunts_in_store": round(float(F.hu_known.mean()), 3),
       "any_new_feature": round(float(((F.mk_n > 0) | (F.relaunch > 0)).mean()), 3)}
res = {"design": __doc__.split("\n    python")[0], "coverage": cov}; print(cov, flush=True)
if cov["any_new_feature"] >= 0.15:
    z = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0
    BL = {"maker_record": ["mk_n", "mk_best", "mk_med", "mk_top5", "mk_since"], "relaunch": ["relaunch", "relaunch_lv"], "hunter_median_rank (overlaps clean)": ["hu_med_rank"]}
    BL["all"] = sum(BL.values(), [])
    for c in BL["all"] + ["honest"]: F["z_" + c] = F.groupby("day")[c].transform(z)
    F["zy"] = F.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); F["mon"] = F.day.str[:7]
    from sklearn.linear_model import Ridge
    def dm(g, col):
        o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    mons = sorted(F.mon.unique())
    for name, cols in BL.items():
        X = ["z_honest"] + ["z_" + c for c in cols]; F["p"] = np.nan
        for m in mons[1:]:   # month-forward ridge (alpha 10)
            tr, te = F[F.mon < m], F[F.mon == m]; F.loc[te.index, "p"] = Ridge(alpha=10).fit(tr[X], tr.zy).predict(te[X])
        G = F[F.p.notna()]; per = np.array([np.array(dm(g, "p")) - np.array(dm(g, "z_honest")) for _, g in G.groupby("day") if len(g) >= 8])
        base = np.array([dm(g, "z_honest") for _, g in G.groupby("day") if len(g) >= 8]).mean(0)
        bs = np.array([per[rng.integers(0, len(per), len(per))].mean(0) for _ in range(2000)])
        res[name] = {"days": len(per), "clean": base.round(1).tolist(), "gain top3/5/10": [[round(float(per[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]}
        print(name, res[name], flush=True)
json.dump(res, open(os.path.join(OUT, "team_record.json"), "w"), indent=1, default=float)
