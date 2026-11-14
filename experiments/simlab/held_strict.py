"""Held-team count: stricter backtest + forward power (orchestrator 00:42Z Nov 14). Counts only. Base: arm 2 (PH ops 'both', Apr-Oct).
Features per launch (team = hunter + named makers; held = complete in the provenance store):
  asof_any   held team members with >= 1 dated activity before the launch day (team_inc2; the stack's L2)
  recent30   held team members whose LAST dated event before the launch day (upvote on an earlier-dated launch, or an earlier team role)
             is within 30 days of it; nothing after the launch is used
  placebo    each recent30 member replaced by a random held NON-team person matched on entry route, pull week (pull_finished_utc) and
             prior-activity bin (log2(1 + dated upvotes before the day)); counted if that person is recent30 too. Same selection mechanics,
             no tie to the launch: its gain is what store selection alone buys.
Month-forward ridge on within-day z (target z(-ln rank)): arm2 vs arm2 + z(log1p f); paired top 3/5/10, day bootstrap; by launch-age tercile.
Power: per-day paired top-3 differences of arm2 + asof_any (frozen full-fit weight) vs arm2, with the feature thinned to a forward coverage
(share of launches with f > 0) of c; days needed for 80% power at alpha 0.05: n = ((1.96 + 0.84) sd / mean)^2, mean scaled to +3 at full
backtest coverage. Coverages: Nov 13 live (2 established / 20 launches = 0.10), 0.25, 0.5, backtest, and a full-team pull (share of
launches with any team member holding an earlier team role in the 2025 lists / 2026 warehouse = upper bound).
    python held_strict.py <store dir> <scratchpad> <arm2 parquet> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); A2P, OUT2 = sys.argv[3], sys.argv[4]; sys.argv = sys.argv[:3] + [OUT2]
src = open(os.path.join(HERE, "team_inc.py")).read(); exec(src[src.index("import glob, hashlib, json, os, sys"):src.index("L = pd.concat([L.reset_index(drop=True), pd.DataFrame([feats(r) for r in L.itertuples()])], axis=1)")])
os.makedirs(OUT2, exist_ok=True)
PP = P.set_index("person_id"); pw = pd.to_datetime(PP.pull_finished_utc, utc=True, errors="coerce").dt.strftime("%G-%V"); route = PP.entry_route.fillna("unknown")
nup = {p: len(u) for p, u in UD.items()}
def last_before(p, day):
    u = UD.get(p, np.array([])); b = u[u < day] if len(u) else u; r = [x for x in roles.get(p, []) if x < day]
    c = ([b.max()] if len(b) else []) + ([max(r)] if r else []); return max(c) if c else None
cand = list(comp); key = {p: (route.get(p, "unknown"), pw.get(p, "na"), int(np.log2(1 + nup.get(p, 0)))) for p in cand}
pool = {}
for p, k in key.items(): pool.setdefault(k, []).append(p)
def feats3(r):
    held = [p for p in r.team if p in comp]; d30 = (pd.Timestamp(r.day) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); team = set(r.team)
    a = sum(1 for p in held if last_before(p, r.day) is not None); rec = [p for p in held if (lambda lb: lb is not None and lb >= d30)(last_before(p, r.day))]
    pl = 0
    for p in rec:
        c = [q for q in pool.get(key[p], []) if q not in team]
        if c:
            q = c[rng.integers(len(c))]; lb = last_before(q, r.day); pl += int(lb is not None and lb >= d30)
    return {"asof_any": a, "recent30": len(rec), "placebo": pl}
A2 = pd.read_parquet(A2P)[["id", "both"]]; A2["id"] = A2.id.astype(str)
L = L.merge(A2, on="id"); L = L[L.groupby("day").id.transform("count") >= 10].reset_index(drop=True)
L = pd.concat([L, pd.DataFrame([feats3(r) for r in L.itertuples()])], axis=1); L["mon"] = L.day.str[:7]
z = lambda s: (s - s.mean()) / (s.std() or 1)
L["y"] = L.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); L["zb"] = L.groupby("day").both.transform(z)
FE = ["asof_any", "recent30", "placebo"]
for f in FE: L["z_" + f] = L.groupby("day")[f].transform(lambda s: z(np.log1p(s)))
mons = sorted(L.mon.unique()); ARMS = {"arm2": ["zb"], **{f"arm2 + {f}": ["zb", "z_" + f] for f in FE}}
for a, X in ARMS.items():
    L["p_" + a] = np.nan
    for m in mons[1:]:
        tr, te = L[L.mon < m], L[L.mon == m]; L.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
T = L[L.p_arm2.notna()]; days = sorted(T.day.unique()); terc = np.array_split(np.arange(len(days)), 3)
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def ci(D):
    D = np.asarray(D, float); bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(4000)])
    return [[round(float(D[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(D.shape[1])]
R = {a: np.array([dm(T[T.day == d], "p_" + a) for d in days]) for a in ARMS}
res = {"design": __doc__.split("\n    python")[0], "scored days": len(days), "launches": len(T), "arm2 top3/5/10": R["arm2"].mean(0).round(1).tolist(),
       "coverage (share of launches with f > 0)": {f: round(float((T[f] > 0).mean()), 3) for f in FE}}
for f in FE:
    D = R[f"arm2 + {f}"] - R["arm2"]; res[f"arm2 + {f}"] = {"top3/5/10": R[f"arm2 + {f}"].mean(0).round(1).tolist(), "vs arm2": ci(D), "by age tercile (0 = oldest), top 3/5/10": {k: ci(D[ix]) for k, ix in enumerate(terc)}}
res["recent30 - placebo (paired)"] = ci(R["arm2 + recent30"] - R["arm2 + placebo"])
# power
w = Ridge(alpha=10).fit(T[["zb", "z_asof_any"]], T.y).coef_
fulld = {}
for d0, x in L.groupby("day"):
    for r_ in x[["id"]].itertuples(): pass
first_role = {}
for d, t in zip(L.day, L.team):
    for p in t: first_role.setdefault(p, []).append(d)
import glob as _g
H25 = []
for f in sorted(_g.glob(f"{SP}/ph2025/*.json")):
    for p_ in json.load(open(f)):
        u = str((p_.get("user") or {}).get("username") or "").lower()
        if u: first_role.setdefault(pid(u), []).append(os.path.basename(f)[:10])
fullcov = float(np.mean([any(min(first_role.get(p, ["9999"])) < d for p in t) for d, t in zip(T.day, T.team)]))
c0 = float((T.asof_any > 0).mean()); pw_ = {}
for nm, c in (("Nov 13 live (0.10)", 0.10), ("0.25", 0.25), ("0.50", 0.50), (f"backtest ({c0:.2f})", c0), (f"full-team pull upper bound ({fullcov:.2f})", fullcov)):
    keep = min(c / c0, 1.0); diffs = []
    for _ in range(20):
        g = T.copy(); m = (g.asof_any > 0) & (rng.random(len(g)) > keep); g.loc[m, "asof_any"] = 0
        g["zf"] = g.groupby("day").asof_any.transform(lambda s: z(np.log1p(s))); g["s"] = w[0] * g.zb + w[1] * g.zf
        diffs.append(np.array([dm(g[g.day == d], "s")[0] - dm(g[g.day == d], "zb")[0] for d in days]))
    dd = np.concatenate(diffs); full_mean = 3.0 * (np.mean(dd) / max(np.mean(R["arm2 + asof_any"][:, 0] - R["arm2"][:, 0]), 1e-9)) if c < c0 else 3.0 * min(c / c0, 1.0)
    sd = float(np.std(dd)); mu = max(abs(full_mean) if c < c0 else 3.0, 1e-9)
    pw_[nm] = {"per-day top-3 diff sd": round(sd, 1), "share of days with any top-3 change": round(float(np.mean(dd != 0)), 3), "assumed effect (top 3)": round(mu, 2),
               "days for 80% power": int(np.ceil(((1.96 + 0.84) * sd / mu) ** 2))}
res["power (frozen full-fit weight, asof_any)"] = {"weight (zb, z_asof_any)": np.round(w, 3).tolist(), **pw_}
json.dump(res, open(os.path.join(OUT2, "held_strict.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
