"""Vertex Gemini baselines for the Decisions API pilot (orchestrator 04:34Z Nov 13). Prompts fixed in pilot/prompts.json; samples written
to <out>/pilot_sample.json (hashed person ids + launch ids only) so the Decisions API run reuses them exactly.
(A) PERSON LEVEL. People / days as person_choice.py (complete people, >= 20 dated upvotes; upvote date = launch day). 5 test days drawn
    (seed 0) from Oct 20 - Nov 10; per day 300 person-days sampled among people who upvoted >= 1 of that day's launches (line-up = launches
    with a clean 00:05 score). Card: the person's 30 most recent upvotes dated before the day (product - tagline; no names / handles),
    and the line-up in a fixed shuffled order with a [follows team] flag (follows are undated snapshots: possible leak, as in person_choice).
    No headline: the store holds no profile text. Models gemini-2.5-flash-lite and gemini-2.5-flash, temperature 0, thinking off, one call
    per person-day, JSON probabilities. Scores vs popularity (within-day z of the clean 00:05 score) and popularity + follows (logistic
    fit on 20 earlier days, person_choice features a+b); blend = mean of within-person-day rank percentiles of LLM p and popularity.
    Metrics per voted launch: top-3 hit, ranking accuracy (share of the other line-up launches ranked below); paired bootstrap over
    person-days. Launch score = sum of p over the sampled person-days (conditions on the person being active that day: indicative only);
    within-day Spearman with final rank and partial Spearman beyond the clean score.
(B) LAUNCH LEVEL. gemini-2.5-flash, P(top 10) and P(top 3) from name / tagline / topics / description, launches Oct 26 - Nov 11 with a
    clean_v3_nosite score. Leave-day-out: logistic-free ridge on within-day z of [clean, p] vs clean alone; top 3/5/10 overlap, paired day
    bootstrap; calibration bins. th_n_pre is not held across these days, so the base is clean_v3_nosite alone.
    python pilot_base.py <store dir> <launches dir> <salt dir> <honest_preds_v2.parquet> <clean_nosite.parquet> <ph-website worktree> <out dir>
"""
import os, sys, json, asyncio, time
HERE = os.path.dirname(os.path.abspath(__file__)); CNS, WT, OUTP = sys.argv[5], sys.argv[6], sys.argv[7]
PC = open(os.path.join(HERE, "person_choice.py")).read(); sys.argv = sys.argv[:5] + [OUTP]
exec(PC[:PC.index("days = sorted(LU.day.unique())")])
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; sys.path[:0] = [WT, os.path.join(WT, "src")]
from capability import gemini_config as GC  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402
PR = json.load(open(os.path.join(HERE, "pilot", "prompts.json"))); CF = os.path.join(OUTP, "cache_pilot.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}
PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}; USD = {"usd": 0.0}; LAT = {}
async def call(key, prompt, model, tok=800):
    if key in C: return C[key]
    if USD["usd"] > 8.0: return None
    t0 = time.time()
    try: r = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": prompt}], model=model, temperature=0.0, thinking_budget=0, max_retries=3, max_output_tokens=tok)) or {}
    except Exception: r = {}
    LAT.setdefault(model, []).append(time.time() - t0); a, b = PRICE[model]; USD["usd"] += len(prompt) / 4 / 1e6 * a + tok / 2 / 1e6 * b
    C[key] = r; return r
days = sorted(LU.day.unique()); train_days = [d for d in days if d < CUT][-20:]; test_days = [d for d in days if CUT <= d <= "2026-11-10"]
TD = sorted(rng.choice(test_days, 5, replace=False).tolist()); info = L.set_index("id")[["name", "tagline"]].to_dict("index")
Xtr, ytr = [], []
for d in train_days:
    X, y, _ = rows_for(d, set(rng.choice(sorted(PEOPLE), size=min(1500, len(PEOPLE)), replace=False)))
    if len(X): Xtr.append(X); ytr.append(y)
PF = LogisticRegression(max_iter=500).fit(np.vstack(Xtr)[:, [0, 1]], np.concatenate(ytr))
SAMPLE = {"days": TD, "person_days": []}; PDS = []
for d in TD:
    lu = LU[LU.day == d]; ids = lu.id.tolist(); order = sorted(ids, key=lambda i: hashlib.sha1(i.encode()).hexdigest())
    voted = U[(U.lday == d)].groupby("person_id").target_id.agg(set); voted = {p: v & set(ids) for p, v in voted.items() if v & set(ids)}
    ps = sorted(voted); ps = rng.choice(ps, min(300, len(ps)), replace=False).tolist()
    for p in ps:
        h = sorted([(dd, t) for t, dd in hist.get(p, []) if dd < d], reverse=True)[:30]
        hl = "\n".join(f"- {info.get(t, {}).get('name', '?')} - {str(info.get(t, {}).get('tagline', ''))[:80]}" for _, t in h)
        fs = fol.get(p, set()); flags = [bool(team.get(i, set()) & fs) for i in order]
        ln = "\n".join(f"{k+1}. {info[i]['name']} - {str(info[i]['tagline'])[:90]}{' [follows team]' if f else ''}" for k, (i, f) in enumerate(zip(order, flags)))
        PDS.append({"p": p, "day": d, "order": order, "voted": sorted(voted[p]), "follow": flags, "prompt": PR["person_upvote"]["template"].format(history=hl or "- (none)", lineup=ln)})
        SAMPLE["person_days"].append({"person": p, "day": d, "lineup": order})
json.dump(SAMPLE, open(os.path.join(OUTP, "pilot_sample.json"), "w")); print("person-days", len(PDS), "days", TD, flush=True)
async def runA():
    sem = asyncio.Semaphore(16)
    async def one(x, m):
        async with sem: return await call(f"A|{m}|{x['p']}|{x['day']}", x["prompt"], m, tok=40 * len(x["order"]) + 100)
    out = {}
    for m in PRICE: out[m] = await asyncio.gather(*[one(x, m) for x in PDS]); json.dump(C, open(CF, "w"))
    return out
RA = asyncio.run(runA())
popz = dict(zip(LU.id, LU["pop"])); rk = lambda v: pd.Series(v).rank(pct=True).to_numpy()
def score(x, arm):
    pop = np.array([popz[i] for i in x["order"]]); fl = np.array(x["follow"], float)
    if arm == "pop": return pop
    if arm == "pop+follows": return PF.decision_function(np.c_[pop, fl])
    m = arm.split("|")[0]; r = RA[m][PDS.index(x)] if False else x["_r"][m]
    pv = (r or {}).get("p")
    if not isinstance(pv, list) or len(pv) != len(x["order"]): return None
    pv = np.array([float(z) if isinstance(z, (int, float)) else 0.0 for z in pv])
    return pv if not arm.endswith("blend") else (rk(pv) + rk(pop)) / 2
for k, x in enumerate(PDS): x["_r"] = {m: RA[m][k] for m in RA}
ARMS = ["pop", "pop+follows"] + [f"{m}|llm" for m in PRICE] + [f"{m}|blend" for m in PRICE]
per = {a: [] for a in ARMS}; valid = []
for x in PDS:
    S = {a: score(x, a) for a in ARMS}
    if any(v is None for v in S.values()): continue
    valid.append(x); y = np.array([i in set(x["voted"]) for i in x["order"]])
    for a, s in S.items():
        o = (-s).argsort().argsort(); h = [float(o[j] < 3) for j in np.flatnonzero(y)]; acc = [float((np.delete(s, j) < s[j]).mean()) for j in np.flatnonzero(y)]
        per[a].append((np.mean(h), np.mean(acc)))
def bt(v):
    v = np.array(v); bs = [v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res = {"design": __doc__.split("\n    python")[0], "days": TD, "person_days": len(PDS), "valid_person_days": len(valid)}
A = {}
for a in ARMS:
    A[a] = {"top3_hit": bt([z[0] for z in per[a]]), "ranking_accuracy": bt([z[1] for z in per[a]])}
    for b in ("pop", "pop+follows"):
        if a != b: A[f"{a} - {b}"] = {"top3_hit": bt([z[0] - w[0] for z, w in zip(per[a], per[b])]), "ranking_accuracy": bt([z[1] - w[1] for z, w in zip(per[a], per[b])])}
res["A_person"] = A
# launch score from summed p
LS = {}
for m in PRICE:
    agg = {}
    for x in valid:
        pv = x["_r"][m]["p"]
        for i, z in zip(x["order"], pv): agg[i] = agg.get(i, 0.0) + (float(z) if isinstance(z, (int, float)) else 0.0)
    g = LU[LU.day.isin(TD)].copy(); g["ls"] = g.id.map(agg).fillna(0); g["rank"] = g.id.map(dict(zip(L.id, L.daily_rank.astype(float))))
    sp_ls, sp_c, part = [], [], []
    for d, gg in g.groupby("day"):
        sp_ls.append(spearmanr(gg.ls, -gg["rank"]).correlation); sp_c.append(spearmanr(gg.honest, -gg["rank"]).correlation)
        rr = pd.Series(-gg["rank"].values).rank().values; cc = pd.Series(gg.honest.values).rank().values; ll = pd.Series(gg.ls.values).rank().values
        res_y = rr - np.polyval(np.polyfit(cc, rr, 1), cc); res_l = ll - np.polyval(np.polyfit(cc, ll, 1), cc); part.append(np.corrcoef(res_y, res_l)[0, 1])
    LS[m] = {"within_day_spearman_launch_score": [round(float(v), 3) for v in sp_ls], "clean": [round(float(v), 3) for v in sp_c], "partial_beyond_clean": [round(float(v), 3) for v in part],
             "mean": [round(float(np.mean(sp_ls)), 3), round(float(np.mean(sp_c)), 3), round(float(np.mean(part)), 3)]}
res["A_launch_score (indicative, 5 days)"] = LS
# (B) launch level
CN = pd.read_parquet(CNS)[["id", "day", "rank", "clean_v3_nosite"]].dropna(); CN["id"] = CN.id.astype(str); CN = CN[(CN.day >= "2026-10-26") & (CN.day <= "2026-11-11")]
LD = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); LD["id"] = LD.id.astype(str); LD = LD.set_index("id"); CN = CN[CN.id.isin(LD.index)]; json.dump({"days": sorted(CN.day.unique().tolist()), "launch_ids": CN.id.tolist()}, open(os.path.join(OUTP, "pilot_launch_sample.json"), "w"))
async def runB():
    sem = asyncio.Semaphore(16)
    async def one(i):
        r = LD.loc[i]; tp = ", ".join(json.loads(r.topics)) if isinstance(r.topics, str) and r.topics.startswith("[") else ""
        async with sem: return await call(f"B|{i}", PR["launch_level"]["template"].format(name=r["name"], tagline=r.tagline or "", topics=tp, description=str(r.description or "")[:1500]), "gemini-2.5-flash", tok=60)
    o = await asyncio.gather(*[one(i) for i in CN.id]); json.dump(C, open(CF, "w")); return o
RB = asyncio.run(runB())
fp = lambda r, k: float(r.get(k)) if r and isinstance(r.get(k), (int, float)) else np.nan
CN["p10"] = [fp(r, "p_top10") for r in RB]; CN["p3"] = [fp(r, "p_top3") for r in RB]; CN = CN.dropna(subset=["p10", "p3"])
z = lambda s: (s - s.mean()) / (s.std() or 1)
for c in ("clean_v3_nosite", "p10", "p3"): CN["z_" + c] = CN.groupby("day")[c].transform(z)
CN["y"] = CN.groupby("day")["rank"].transform(lambda r: z(-np.log(r)))
from sklearn.linear_model import Ridge  # noqa: E402
def ov(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
B = {"launches": len(CN), "days": CN.day.nunique()}
for nm, cols in (("+p_top10", ["z_p10"]), ("+p_top3", ["z_p3"]), ("+both", ["z_p10", "z_p3"]), ("p_top10 alone", None)):
    pr_ = pd.Series(np.nan, index=CN.index)
    for d in CN.day.unique():
        tr, te = CN[CN.day != d], CN[CN.day == d]
        if cols is None: pr_[te.index] = te.z_p10
        else: X = ["z_clean_v3_nosite"] + cols; pr_[te.index] = Ridge(alpha=1.0).fit(tr[X], tr.y).predict(te[X])
    CN["p_"] = pr_; per_ = np.array([np.array(ov(g, "p_")) - np.array(ov(g, "z_clean_v3_nosite")) for _, g in CN.groupby("day")])
    bs = np.array([per_[rng.integers(0, len(per_), len(per_))].mean(0) for _ in range(2000)])
    B[nm] = {"gain top3/5/10": [[round(float(per_[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]}
B["clean top3/5/10"] = np.array([ov(g, "z_clean_v3_nosite") for _, g in CN.groupby("day")]).mean(0).round(1).tolist()
cal = {}
for k, thr in (("p10", 10), ("p3", 3)):
    bins = pd.cut(CN[k], [0, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0], include_lowest=True); g = CN.assign(hit=(CN["rank"] <= thr).astype(float)).groupby(bins, observed=True)
    cal[k] = {str(b): {"n": int(len(x)), "mean_p": round(float(x[k].mean()), 3), "actual": round(float(x.hit.mean()), 3)} for b, x in g}
B["calibration"] = cal; res["B_launch"] = B
res["est_usd"] = round(USD["usd"], 2); res["latency_s_median"] = {m: round(float(np.median(v)), 2) for m, v in LAT.items()}
json.dump(C, open(CF, "w")); json.dump(res, open(os.path.join(OUTP, "pilot_base.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:3000])
