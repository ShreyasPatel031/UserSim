"""A "who" learned from real voters (orchestrator, Nov 12). Same 426 launches, truth rules and time ordering as who_eval.py
(person segment = nearest index-segment centroid of the person's upvote topic shares, upvotes before the launch day).
Two truths per launch: POOL lift = segment share among the launch's voters / share among pool people with >= 3 prior upvotes;
DAY lift = share among the launch's voters / share among ALL voters of that day's launches (removes "active people vote").
Truly over-represented: lift > 1.5 and >= 3 voters.
Predictors (month-forward: only launches dated before the test month's first day are used):
  SITE      the site's _interest_people top 3 (page-read topics)
  CONTROL   the 3 segments with the most voters over Jan-Aug launches; RANDOM expected values
  RETR-k    mean of the real voter lift vectors (per truth) of the k most similar earlier launches with >= 15 voters
            (gemini-embedding of name. tagline. description; query = page read or PH description), k = 5 / 10 / 30, plain and
            similarity-weighted (softmax over cosine, temperature 0.05)
  RIDGE     ridge (alpha 10) from the query embedding to log lift per segment, trained on earlier launches with >= 15 voters
Person level (internal): candidates = people who voted for any launch that day; AUC / lift@1% for the launch's voters of activity
(prior upvotes) alone, + the predicted lift of the person's segment (RETR-10, day truth), + overlap (voted for any of the 10
retrieved neighbours); rank-mean combinations.
    python who_learn.py <ph-website worktree> <scratchpad> <who_eval out dir (emb_page.npy, emb_ph.npy)> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score

WT, SP, WE, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim  # noqa: E402
I = try_sim.index(); META = I["meta"]; VOC = META["vocab"]; vix = {t: k for k, t in enumerate(VOC)}; NSEG = len(META["segments"])
CENT = np.vstack([I["Xn"][I["seg"] == s].mean(0) for s in range(NSEG)]); CENT /= np.linalg.norm(CENT, axis=1, keepdims=True) + 1e-9
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L = L.sort_values(["day", "id"]).reset_index(drop=True); lix = {i: k for k, i in enumerate(L.id)}
TP = np.zeros((len(L), len(VOC)), np.float32)
for k, t in enumerate(L.topics):
    for x in (json.loads(t) if isinstance(t, str) and t.startswith("[") else []):
        if x in vix: TP[k, vix[x]] = 1
dnum = pd.to_datetime(L.day).to_numpy().astype("datetime64[D]").astype(np.int64)
comp = set(pd.read_parquet(os.path.join(SP, "tl/v3/persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(SP, "tl/v3/events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; ev["target_id"] = ev.target_id.astype(str); ev = ev[ev.target_id.isin(lix)].drop_duplicates(["person_id", "target_id"])
people = sorted(ev.person_id.unique()); pix = {p: k for k, p in enumerate(people)}
M = sparse.csr_matrix((np.ones(len(ev), np.float32), (ev.person_id.map(pix), ev.target_id.map(lix))), shape=(len(people), len(L))); MT = M.T.tocsr(); nvote = np.diff(MT.indptr)

# per-day state (time-ordered segments, base, activity) and per-launch voter lifts under both truths
ST = {}
def state(d):
    if d not in ST:
        prior = (dnum < d).astype(np.float32); Mp = M.multiply(prior[None, :]).tocsr(); Mp.eliminate_zeros(); n = np.asarray(Mp.sum(1)).ravel()
        V = Mp @ TP; V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9); ST[d] = (np.argmax(V @ CENT.T, axis=1), n >= 3, n)
    return ST[d]
days = sorted(set(dnum.tolist())); LIFT_P, LIFT_D, VC = {}, {}, {}
for d in days:
    if d < np.datetime64("2026-02-01").astype(np.int64): continue
    seg, base, n = state(d); ks = np.flatnonzero(dnum == d); dayv = np.unique(np.concatenate([MT[k].indices for k in ks])) if len(ks) else np.array([], int)
    dayv = dayv[base[dayv]]; bp = np.bincount(seg[base], minlength=NSEG) / max(1, base.sum()); bd = np.bincount(seg[dayv], minlength=NSEG) / max(1, len(dayv))
    for k in ks:
        v = MT[k].indices; v = v[base[v]]
        if len(v) < 15: continue
        c = np.bincount(seg[v], minlength=NSEG); sh = c / len(v); LIFT_P[k] = sh / (bp + 1e-9); LIFT_D[k] = sh / (bd + 1e-9); VC[k] = c
print("launches with lifts", len(LIFT_P), flush=True)
# queries: the 426 test launches of who_eval (page / PH embeddings in its order) and an embedding for every launch (PH text)
K = json.load(open(os.path.join(SP, "band_page/cache.json"))); FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
READ = {i: v for i, v in K.items() if "fail" not in v and i in lix and L.day.iat[lix[i]] >= "2026-09-01"}
READ.update({k.split("|", 1)[1]: v["read"] for k, v in FK.items() if k.startswith("p|") and "read" in v and k.split("|", 1)[1] in lix})
S_all = [i for i in READ if nvote[lix[i]] >= 15]                              # who_eval order (embeddings aligned)
QP, QH = np.load(os.path.join(WE, "emb_page.npy")), np.load(os.path.join(WE, "emb_ph.npy")); assert len(QP) == len(S_all)
LE = np.load(os.path.join(SP, "land/launch_emb256.npy")); Lv = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
Lv = Lv[Lv.daily_rank.notna() & Lv.votes.notna() & (Lv.day < "2026-11-11")].sort_values(["day", "id"]); Lv["id"] = Lv.id.astype(str); assert len(Lv) == len(LE)
emb_of = {i: LE[k] for k, i in enumerate(Lv.id)}
pool_ids = np.array([k for k in LIFT_P]); PE = np.vstack([emb_of.get(L.id.iat[k], np.zeros(256, np.float32)) for k in pool_ids]); PEok = np.array([L.id.iat[k] in emb_of for k in pool_ids])
if os.environ.get("EXPORT"):                       # server-side bundle: segment descriptions + ridge (embedding -> log day-lift), no people
    ks_ = [k for k in LIFT_D if L.id.iat[k] in emb_of]; X_ = np.vstack([emb_of[L.id.iat[k]] for k in ks_]); Y_ = np.log(np.vstack([LIFT_D[k] for k in ks_]) + 0.05)
    rg_ = Ridge(alpha=10.0).fit(X_, Y_)
    out_ = {"version": "who-segments-v1", "trained_on_launches": len(ks_), "days": [L.day.iat[min(ks_)], L.day.iat[max(ks_)]],
            "target": "ln(0.05 + segment share among the launch's voters / share among all voters of that day) per segment",
            "query": {"embedding": "gemini-embedding-001, 256-d, SEMANTIC_SIMILARITY, L2-normalised (person_e5.embed)",
                      "page_text": "name. tagline. summary page_excerpt[:700]", "paste_text": "name. tagline. description[:800]"},
            "segments": [{"id": sg["id"], "name": sg["name"], "top_topics": sg["top_topics"], "maker_share": sg["maker_share"]} for sg in META["segments"]],
            "coef": [[round(float(x), 6) for x in row] for row in rg_.coef_], "intercept": [round(float(x), 6) for x in rg_.intercept_],
            "use": "pred = intercept + coef @ q; show the top 3 segments by pred; predicted lift = exp(pred) - 0.05 ('votes for this more than for the day's other launches')"}
    json.dump(out_, open(os.path.join(OUT, "who_segments_v1.json"), "w")); print("exported", len(ks_)); sys.exit(0)
early = np.flatnonzero(L.day.values < "2026-09-01"); seg0 = state(int(dnum[early].max()) + 1)[0]; CONTROL = list(pd.Series(seg0[MT[early].indices]).value_counts().index[:3])
name2id = {sg["name"]: sg["id"] for sg in META["segments"]}
rows, prow = [], []
for qi, i in enumerate(S_all):
    k = lix[i]
    if k not in LIFT_P: continue
    d = dnum[k]; m0 = np.datetime64(L.day.iat[k][:7] + "-01").astype(np.int64)
    tr = PEok & (dnum[pool_ids] < m0); tk = pool_ids[tr]; TE_ = PE[tr]
    truthP = set(np.flatnonzero((LIFT_P[k] > 1.5) & (VC[k] >= 3)).tolist()); truthD = set(np.flatnonzero((LIFT_D[k] > 1.5) & (VC[k] >= 3)).tolist())
    r = {"id": i, "set": "fresh" if L.day.iat[k] >= "2026-10-27" else L.day.iat[k][:7], "nP": len(truthP), "nD": len(truthD)}
    preds = {"CONTROL": CONTROL}
    for src, Q in (("page", QP[qi]), ("ph", QH[qi])):
        tps = [t for t in (READ[i].get("topics") or []) if t in VOC][:4] if src == "page" else [t for t in (json.loads(L.topics.iat[k]) if isinstance(L.topics.iat[k], str) else []) if t in VOC][:4]
        preds[f"SITE_{src}"] = [name2id[s["name"]] for s in try_sim._interest_people({"topics": tps or ["Productivity"]})["segments"]][:3]
        sims = TE_ @ Q; order = np.argsort(-sims)
        for tname, LD in (("P", LIFT_P), ("D", LIFT_D)):
            for kk in (5, 10, 30):
                nb = order[:kk]; Lm = np.log(np.vstack([LD[tk[j]] for j in nb]) + 0.05)
                preds[f"RETR{kk}_{tname}_{src}"] = list(np.argsort(-Lm.mean(0))[:3])
                w = np.exp((sims[nb] - sims[nb].max()) / 0.05); w /= w.sum(); preds[f"RETR{kk}w_{tname}_{src}"] = list(np.argsort(-(w[:, None] * Lm).sum(0))[:3])
            Y = np.log(np.vstack([LD[j] for j in tk]) + 0.05); rg = Ridge(alpha=10.0).fit(TE_, Y); preds[f"RIDGE_{tname}_{src}"] = list(np.argsort(-rg.predict(Q[None])[0])[:3])
            if src == "page" and tname == "D": PRED_LIFT = np.exp(np.log(np.vstack([LD[tk[j]] for j in order[:10]]) + 0.05).mean(0)); NB10 = tk[order[:10]]
    for nm, p in preds.items():
        for tname, truth, LL in (("P", truthP, LIFT_P[k]), ("D", truthD, LIFT_D[k])):
            r[f"{nm}|{tname}|p3"] = np.mean([x in truth for x in p]); r[f"{nm}|{tname}|hit3"] = float(any(x in truth for x in p)); r[f"{nm}|{tname}|lift_top"] = LL[p[0]]
    for tname, truth, LL in (("P", truthP, LIFT_P[k]), ("D", truthD, LIFT_D[k])):
        r[f"RANDOM|{tname}|p3"] = len(truth) / NSEG; r[f"RANDOM|{tname}|lift_top"] = float(np.mean(LL))
    rows.append(r)
    # person level within the day's voters
    seg, base, n = state(d); ks = np.flatnonzero(dnum == d); cand = np.unique(np.concatenate([MT[j].indices for j in ks])); cand = cand[base[cand]]
    y = np.isin(cand, MT[k].indices)
    if 5 <= y.sum() < len(cand):
        act = np.log1p(n[cand]); pl = PRED_LIFT[seg[cand]]; ov = np.asarray(M[cand][:, NB10].sum(1)).ravel()
        rk = lambda v: pd.Series(v).rank(pct=True).values
        sc = {"activity": act, "activity+seg_lift": rk(act) + rk(pl), "activity+overlap": rk(act) + rk(ov), "activity+seg_lift+overlap": rk(act) + rk(pl) + rk(ov), "overlap": ov}
        pr = {"id": i}
        for nm, v in sc.items():
            pr[f"{nm}|auc"] = roc_auc_score(y, v); top = np.argsort(-v)[: max(1, len(v) // 100)]; pr[f"{nm}|lift1"] = y[top].mean() / y.mean()
        prow.append(pr)
D = pd.DataFrame(rows); P = pd.DataFrame(prow)


def mb(v, B=4000, sc=100):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * sc, 2), round(float(np.percentile(bs, 2.5)) * sc, 2), round(float(np.percentile(bs, 97.5)) * sc, 2), int(len(v))]
methods = sorted({c.split("|")[0] for c in D.columns if "|" in c})
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "mean_true_P": round(float(D.nP.mean()), 2), "mean_true_D": round(float(D.nD.mean()), 2), "by_truth": {}}
for tname in ("P", "D"):
    t = {}
    for m in methods:
        if f"{m}|{tname}|p3" not in D: continue
        t[m] = {"p3": mb(D[f"{m}|{tname}|p3"]), "lift_top": mb(D[f"{m}|{tname}|lift_top"], sc=1)}
        if f"{m}|{tname}|hit3" in D: t[m]["hit3"] = mb(D[f"{m}|{tname}|hit3"])
        if m not in ("CONTROL", "RANDOM"): t[m]["minus CONTROL p3 (paired)"] = mb(D[f"{m}|{tname}|p3"] - D[f"CONTROL|{tname}|p3"])
    res["by_truth"]["pool_lift" if tname == "P" else "day_lift"] = t
res["person_within_day"] = {c: mb(P[c], sc=1) for c in P.columns if c != "id"}
res["person_within_day"]["+seg_lift+overlap - activity AUC (paired)"] = mb(P["activity+seg_lift+overlap|auc"] - P["activity|auc"], sc=1)
json.dump(res, open(os.path.join(OUT, "who_learn.json"), "w"), indent=1, default=str)
for tn, t in res["by_truth"].items():
    print("==", tn); best = sorted(((v["p3"][0], m) for m, v in t.items() if v["p3"]), reverse=True)[:8]
    for _, m in best: print(" ", m, t[m])
    print("  CONTROL", t["CONTROL"], "\n  RANDOM", t["RANDOM"], "\n  SITE_page", t["SITE_page"])
print(json.dumps(res["person_within_day"], indent=0))
