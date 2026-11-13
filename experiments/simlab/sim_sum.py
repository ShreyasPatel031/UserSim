"""Is the summed per-person LLM upvote probability a real launch signal beyond the clean 00:05 score? (orchestrator 04:41Z Nov 13)
Days Oct 26 - Nov 11 with a clean_v3_nosite score (line-up = those launches). Per day, up to 1,000 complete people of the Nov 10 store
sampled WITHOUT replacement with probability proportional to their upvotes dated in the 30 days before the day (people with none are
not eligible) - no conditioning on voting that day. Card = pilot/prompts.json person_upvote (30 most recent upvotes dated strictly before
the day: product - tagline; line-up in a fixed hashed order: name - tagline + [follows team] flag). gemini-2.5-flash-lite, temperature 0,
thinking off. Launch scores: SUM (sum of p), SUM_NOFOLLOW (sum over people who follow nobody on the team), RANKMEAN (mean over people of
the launch's within-person rank percentile). Learning curve: first 100 / 300 / 1,000 sampled people. Test: leave-day-out ridge on
within-day z of [clean, score] vs clean; top 3/5/10 overlap, paired day bootstrap; within-day Spearman; partial correlation beyond clean
(within-day rank residuals). th_n_pre is not held on these days. Leak checks in the output.
    python sim_sum.py <store dir> <launches dir> <salt dir> <clean_nosite.parquet> <ph-website worktree> <out dir>
"""
import glob, hashlib, json, os, sys, asyncio, time
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
V3, LDIR, SALTD, CNS, WT, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; sys.path[:0] = [WT, os.path.join(WT, "src")]
from capability import gemini_config as GC  # noqa: E402
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def mk(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    return {pid(x) for x in ms if x and not str(x).startswith("[")}
team = {i: ({pid(p)} if isinstance(p, str) and p and not p.startswith("[") else set()) | mk(m) for i, p, m in zip(L.id, L.poster, L.makers)}
lday = dict(zip(L.id, L.day)); info = L.set_index("id")[["name", "tagline"]].to_dict("index")
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[E.person_id.isin(COV)]
U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()].drop_duplicates(["person_id", "target_id"])
fol = E[E.kind == "follows"].groupby("person_id").target_id.agg(set).to_dict(); hist = U.sort_values("lday").groupby("person_id").apply(lambda g: list(zip(g.lday, g.target_id))).to_dict()
CN = pd.read_parquet(CNS)[["id", "day", "rank", "clean_v3_nosite"]].dropna(); CN["id"] = CN.id.astype(str); CN = CN[(CN.day >= "2026-10-26") & (CN.day <= "2026-11-11") & CN.id.isin(info)]
TPL = json.load(open(os.path.join(HERE, "pilot", "prompts.json")))["person_upvote"]["template"]
CF = os.path.join(OUT, "cache_simsum.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}; USD = {"usd": 0.0}; LAT = []
async def call(key, prompt, n):
    if key in C: return C[key]
    if USD["usd"] > 8.0: return None
    t0 = time.time()
    try: r = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": prompt}], model="gemini-2.5-flash-lite", temperature=0.0, thinking_budget=0, max_retries=3, max_output_tokens=12 * n + 60)) or {}
    except Exception: r = {}
    LAT.append(time.time() - t0); USD["usd"] += len(prompt) / 4 * 0.10e-6 + (8 * n + 20) * 0.40e-6; C[key] = r; return r
leak = {"card_upvotes_on_or_after_day": 0, "cards": 0}; PD = []
for d in sorted(CN.day.unique()):
    order = sorted(CN[CN.day == d].id, key=lambda i: hashlib.sha1(i.encode()).hexdigest())
    lo = str(pd.Timestamp(d) - pd.Timedelta(days=30))[:10]; w = U[(U.lday < d) & (U.lday >= lo)].groupby("person_id").size()
    ps = rng.choice(w.index.to_numpy(), size=min(1000, len(w)), replace=False, p=(w / w.sum()).to_numpy()).tolist()
    for k, p in enumerate(ps):
        h = [(dd, t) for dd, t in hist.get(p, []) if dd < d][-30:][::-1]; leak["cards"] += 1; leak["card_upvotes_on_or_after_day"] += sum(dd >= d for dd, _ in h)
        fs = fol.get(p, set()); fl = [bool(team.get(i, set()) & fs) for i in order]
        hl = "\n".join(f"- {info.get(t, {}).get('name', '?')} - {str(info.get(t, {}).get('tagline', ''))[:80]}" for _, t in h)
        ln = "\n".join(f"{j+1}. {info[i]['name']} - {str(info[i]['tagline'])[:90]}{' [follows team]' if f else ''}" for j, (i, f) in enumerate(zip(order, fl)))
        PD.append({"p": p, "day": d, "k": k, "order": order, "fl": fl, "prompt": TPL.format(history=hl or "- (none)", lineup=ln)})
print("person-days", len(PD), "days", CN.day.nunique(), flush=True)
async def run():
    sem = asyncio.Semaphore(32)
    async def one(x):
        async with sem: return await call(f"S|{x['p']}|{x['day']}", x["prompt"], len(x["order"]))
    out = []
    for s in range(0, len(PD), 2000):
        out += await asyncio.gather(*[one(x) for x in PD[s:s + 2000]]); json.dump(C, open(CF, "w")); print("done", s + 2000, round(USD["usd"], 2), flush=True)
    return out
RS = asyncio.run(run())
rows = []
for x, r in zip(PD, RS):
    pv = (r or {}).get("p")
    if not isinstance(pv, list) or len(pv) != len(x["order"]): continue
    pv = np.array([float(z) if isinstance(z, (int, float)) else 0.0 for z in pv]); rp = pd.Series(pv).rank(pct=True).to_numpy()
    for i, a, b, f in zip(x["order"], pv, rp, x["fl"]): rows.append((x["day"], x["k"], i, a, b, f))
R = pd.DataFrame(rows, columns=["day", "k", "id", "p", "rp", "fl"]); print("valid answers", R.groupby(["day", "k"]).ngroups, flush=True)
def scores(n):
    r = R[R.k < n]; g = r.groupby("id")
    return pd.DataFrame({"SUM": g.p.sum(), "SUM_NOFOLLOW": r[~r.fl].groupby("id").p.sum(), "RANKMEAN": g.rp.mean()}).fillna(0)
z = lambda s: (s - s.mean()) / (s.std() or 1)
def ov(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def bt(a):
    bs = np.array([a[rng.integers(0, len(a), len(a))].mean(0) for _ in range(2000)]); return np.round(a.mean(0), 3), np.round(np.percentile(bs, 2.5, axis=0), 3), np.round(np.percentile(bs, 97.5, axis=0), 3)
res = {"design": __doc__.split("\n    python")[0], "days": int(CN.day.nunique()), "launches": len(CN), "person_days": len(PD),
       "leak_checks": {**leak, "launch_text": "name and tagline only (fixed at submission, visible at 00:05); history = earlier launches' name / tagline",
                       "caveat": "upvote dates are the upvoted launch's day; a late vote on an older launch cast on or after the target day cannot be excluded (store has no vote timestamps); follows are undated snapshots"}}
for n in (100, 300, 1000):
    S = scores(n); D = CN.merge(S, left_on="id", right_index=True, how="left").fillna(0)
    for c in ("clean_v3_nosite", "SUM", "SUM_NOFOLLOW", "RANKMEAN"): D["z_" + c] = D.groupby("day")[c].transform(z)
    D["y"] = D.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); o_ = {}
    for v in ("SUM", "SUM_NOFOLLOW", "RANKMEAN"):
        pr_ = pd.Series(np.nan, index=D.index)
        for d in D.day.unique():
            tr, te = D[D.day != d], D[D.day == d]; X = ["z_clean_v3_nosite", "z_" + v]; pr_[te.index] = Ridge(alpha=1.0).fit(tr[X], tr.y).predict(te[X])
        D["p_"] = pr_; per = np.array([np.array(ov(g, "p_")) - np.array(ov(g, "z_clean_v3_nosite")) for _, g in D.groupby("day")])
        sp = np.array([[spearmanr(g[v], -g["rank"]).correlation, spearmanr(g.clean_v3_nosite, -g["rank"]).correlation] for _, g in D.groupby("day")])
        pc = []
        for _, g in D.groupby("day"):
            rr, cc, ll = (pd.Series(a).rank().to_numpy() for a in (-g["rank"].to_numpy(), g.clean_v3_nosite.to_numpy(), g[v].to_numpy()))
            pc.append(np.corrcoef(rr - np.polyval(np.polyfit(cc, rr, 1), cc), ll - np.polyval(np.polyfit(cc, ll, 1), cc))[0, 1])
        m, lo, hi = bt(per); mp, lp, hp = bt(np.array(pc)[:, None]); ms, ls_, hs = bt(sp)
        o_[v] = {"gain top3/5/10 [lo, hi]": [[float(m[j]), float(lo[j]), float(hi[j])] for j in range(3)], "within_day_spearman score / clean": [float(ms[0]), float(ms[1])],
                 "spearman score [lo, hi]": [float(ms[0]), float(ls_[0]), float(hs[0])], "partial beyond clean [lo, hi]": [float(mp[0]), float(lp[0]), float(hp[0])]}
    o_["clean top3/5/10"] = np.array([ov(g, "z_clean_v3_nosite") for _, g in D.groupby("day")]).mean(0).round(1).tolist(); res[f"people_{n}"] = o_
res["est_usd"] = round(USD["usd"], 2); res["latency_s_median"] = round(float(np.median(LAT)), 2) if LAT else None
json.dump(res, open(os.path.join(OUT, "sim_sum.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
