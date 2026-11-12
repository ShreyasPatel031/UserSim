"""Does the /try "who" card hold up? (orchestrator, Nov 12). The site shows TYPES of members, never individuals, from two paths in
try_sim: (S) interest segments (_interest_people: 12 segments of the 13,581-profile index, ranked by lift among the 10% best
category matches for the page-read topics) and (T) similar-tools types (person_e5.summarize over the 5,096-person Gemini bundle:
the closest people described by roles + tool tier). Inputs: the page read (held Sep/Oct page reads + the 130 fresh) and, to size what
the page loses, the PH description.
Truth (time-ordered: person features only from upvotes dated strictly before the launch day): the launch's real pool voters
(complete store_v3 people who upvoted it). Segment of a real person = argmax cosine of their upvote topic-share vector (launch topics,
the index's 60-topic vocabulary) to the index's segment centroids (mean of index rows per segment); type of a bundle person = the
bundle's roles + tool tier. Base = all complete people with >= 3 dated upvotes before the day. A type is truly over-represented when
its share among the launch's voters / base share > 1.5 and >= 3 voters have it. Launches need >= 15 known voters in the population.
Metrics by launch (bootstrap CIs): p@3 / hit@3 of the predicted top 3 vs the truly over-represented set; lift of real voters in the
predicted top type vs a random type and vs the "globally most voting type" control (most voters over Jan-Aug launches).
Person level (internal, never exported; 5,096 bundle people): AUC and lift@1% of the site's product-only score for real voters vs
activity + recency (prior upvote count, days since last upvote) and their rank mean.
    python who_eval.py <ph-website worktree> <scratchpad> <out dir>
"""
import glob, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.metrics import roc_auc_score

WT, SP, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim, person_e5  # noqa: E402
I = try_sim.index(); META = I["meta"]; VOC = META["vocab"]; vix = {t: k for k, t in enumerate(VOC)}; NSEG = len(META["segments"])
CENT = np.vstack([I["Xn"][I["seg"] == s].mean(0) for s in range(NSEG)]); CENT /= np.linalg.norm(CENT, axis=1, keepdims=True) + 1e-9
B = person_e5.bundle(); RN = list(B["role_names"]); NU = B["n_uses"]
btype = [(" / ".join(RN[k] for k in np.flatnonzero(B["roles"][j])) or "member") + ", " + ("1-3 tools" if NU[j] <= 3 else "4-10 tools" if NU[j] <= 10 else "11+ tools") for j in range(len(NU))]

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
M = sparse.csr_matrix((np.ones(len(ev), np.float32), (ev.person_id.map(pix), ev.target_id.map(lix))), shape=(len(people), len(L))); MT = M.T.tocsr()
Pe = pd.read_parquet(os.path.join(SP, "uses2/export/people.parquet")); bix = np.array([pix.get(p, -1) for p in Pe.person_id])   # bundle row -> pool row

# inputs: page reads + PH descriptions
K = json.load(open(os.path.join(SP, "band_page/cache.json"))); FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
READ = {i: v for i, v in K.items() if "fail" not in v and i in lix and L.day.iat[lix[i]] >= "2026-09-01"}
READ.update({k.split("|", 1)[1]: v["read"] for k, v in FK.items() if k.startswith("p|") and "read" in v and k.split("|", 1)[1] in lix})
nvote = np.diff(MT.indptr); BSET = set(bix[bix >= 0].tolist())
S = [i for i in READ if nvote[lix[i]] >= 15]
print("launches with page read", len(READ), "with >= 15 pool voters", len(S), flush=True)
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
_tk = {"t": "", "at": 0}
def _token():
    if time.time() - _tk["at"] > 300: _tk["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tk["at"] = time.time()
    return _tk["t"]
def embed(texts, tag):
    f = os.path.join(OUT, f"emb_{tag}.npy")
    if os.path.exists(f) and len(np.load(f)) == len(texts): return np.load(f)
    out = []
    for i in range(0, len(texts), 200):
        for a in range(6):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:1200], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}}).encode(), {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
                j = json.load(urllib.request.urlopen(req, timeout=120)); break
            except Exception: time.sleep(3 * (a + 1))  # noqa: BLE001
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9; np.save(f, E); return E
phtop = lambda s: [t for t in (json.loads(s) if isinstance(s, str) and s.startswith("[") else []) if t in VOC][:4] or ["Productivity"]
INP = {"page": [{"topics": [t for t in (READ[i].get("topics") or []) if t in VOC][:4] or ["Productivity"],
                 "text": f"{READ[i].get('name')}. {READ[i].get('tagline')}. {READ[i].get('summary') or ''} {(READ[i].get('page_excerpt') or '')[:700]}"} for i in S],
       "ph": [{"topics": phtop(L.topics.iat[lix[i]]), "text": f"{L.name.iat[lix[i]]}. {L.tagline.iat[lix[i]]}. {(L.description.iat[lix[i]] or '')[:800]}"} for i in S]}
Q = {k: embed([x["text"] for x in v], k) for k, v in INP.items()}

# time-ordered person segments, by launch day
segcache, basecache, actcache = {}, {}, {}
def day_state(d):
    if d in segcache: return
    prior = (dnum < d).astype(np.float32); Mp = M.multiply(prior[None, :]).tocsr(); Mp.eliminate_zeros()
    n = np.asarray(Mp.sum(1)).ravel(); V = Mp @ TP; V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    segcache[d] = np.argmax(V @ CENT.T, axis=1); basecache[d] = n >= 3
    last = np.full(len(people), -10 ** 9); c = Mp.tocoo(); np.maximum.at(last, c.row, dnum[c.col]); actcache[d] = (np.log1p(n), np.where(last < 0, 9999, d - last))
rows, prows = [], []
# global most-voting segment / type (Jan-Aug launches)
early = np.flatnonzero(L.day.values < "2026-09-01"); day_state(int(dnum[early].max()) + 1); sg0 = segcache[int(dnum[early].max()) + 1]
vv = MT[early].indices; GLOBAL_SEG = list(pd.Series(sg0[vv]).value_counts().index[:3])
ROLE_NAMES = [person_e5.ROLE_TEXT.get(str(x), str(x)) for x in B["role_names"]]
ev_early = np.asarray(M[:, early].sum(1)).ravel()                                     # upvotes on Jan-Aug launches per pool person
wv = np.array([ev_early[bix[j]] if bix[j] >= 0 else 0.0 for j in range(len(bix))]); GLOBAL_T = [ROLE_NAMES[k] for k in np.argsort(-(B["roles"].astype(float) * wv[:, None]).sum(0))[:3]]
for qi, i in enumerate(S):
    k = lix[i]; d = int(dnum[k]); day_state(d); seg, base = segcache[d], basecache[d]; vot = MT[k].indices; vot = vot[base[vot]]
    if len(vot) < 15: continue
    bs = np.bincount(seg[base], minlength=NSEG) / base.sum(); vs = np.bincount(seg[vot], minlength=NSEG); lift = (vs / len(vot)) / (bs + 1e-9)
    truth = set(np.flatnonzero((lift > 1.5) & (vs >= 3)).tolist())
    r = {"id": i, "set": "fresh" if L.day.iat[k] >= "2026-10-27" else L.day.iat[k][:7], "n_voters": len(vot), "n_truth": len(truth)}
    for src in ("page", "ph"):
        a = {"topics": INP[src][qi]["topics"]}; out = try_sim._interest_people(a)
        name2id = {sg["name"]: sg["id"] for sg in META["segments"]}; pred = [name2id[s["name"]] for s in out["segments"]][:3]
        r[f"S_{src}_p3"] = np.mean([p in truth for p in pred]) if pred else np.nan; r[f"S_{src}_hit3"] = float(any(p in truth for p in pred)) if pred else np.nan
        r[f"S_{src}_lift_top"] = lift[pred[0]] if pred else np.nan
        # person-level (bundle people with history)
        sc = person_e5.score_text(B, Q[src][qi]); ok = bix >= 0; y = np.zeros(len(bix), bool); vset = set(MT[k].indices.tolist()); y[ok] = [bix[j] in vset for j in np.flatnonzero(ok)]
        act, rec = actcache[d]; a_ = np.where(ok, act[np.maximum(bix, 0)], 0); r_ = np.where(ok, rec[np.maximum(bix, 0)], 9999)
        if y.sum() >= 5:
            ar = pd.Series(a_).rank(pct=True).values - pd.Series(r_).rank(pct=True).values; comb = pd.Series(ar).rank(pct=True).values + pd.Series(sc).rank(pct=True).values
            for lab, v in (("score", sc), ("act_rec", ar), ("act_rec+score", comb)):
                r[f"P_{src}_{lab}_auc"] = roc_auc_score(y, v); top = np.argsort(-v)[: max(1, len(v) // 100)]; r[f"P_{src}_{lab}_lift1"] = y[top].mean() / y.mean()
        # similar-tools types at ROLE level (the cards' roles, in the site's display names); truth = roles over-represented among the
        # launch's voting bundle people (share of voters holding the role / base share > 1.5, >= 3 voters)
        bv = [j for j in np.flatnonzero(ok) if y[j]]
        if len(bv) >= 15:
            Rm = B["roles"][ok].astype(bool); Rv = B["roles"][bv].astype(bool); bsh = Rm.mean(0); vc = Rv.sum(0); tl = (vc / len(bv)) / (bsh + 1e-9)
            ttruth = {ROLE_NAMES[k] for k in np.flatnonzero((tl > 1.5) & (vc >= 3))}
            sm = person_e5.summarize(B, sc); tpred = []
            for p in sm["people"]:
                for ro in p["roles"]:
                    if ro != "no stated role" and ro not in tpred: tpred.append(ro)
            tpred = tpred[:3]; r[f"T_{src}_p3"] = np.mean([t in ttruth for t in tpred]) if tpred else np.nan; r[f"T_{src}_hit3"] = float(any(t in ttruth for t in tpred)) if tpred else np.nan
            r["T_n_truth"] = len(ttruth); r["T_global_p3"] = np.mean([t in ttruth for t in GLOBAL_T]); r["T_random_p3"] = len(ttruth) / len(ROLE_NAMES)
    r["S_global_p3"] = np.mean([g in truth for g in GLOBAL_SEG]); r["S_global_hit3"] = float(any(g in truth for g in GLOBAL_SEG)); r["S_random_p3"] = len(truth) / NSEG
    r["S_random_hit3"] = 1 - np.prod([(NSEG - len(truth) - j) / (NSEG - j) for j in range(3)]) if len(truth) <= NSEG - 3 else 1.0
    r["S_global_lift_top"] = lift[GLOBAL_SEG[0]]; r["S_random_lift"] = float(np.mean(lift))
    rows.append(r)
D = pd.DataFrame(rows)


def mb(v, B_=4000, scale=100):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B_)]
    return [round(float(v.mean()) * scale, 2), round(float(np.percentile(bs, 2.5)) * scale, 2), round(float(np.percentile(bs, 97.5)) * scale, 2), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "by_set": D.set.value_counts().to_dict(), "mean_true_segments": round(float(D.n_truth.mean()), 2),
       "segments": {}, "types": {}, "person": {}}
for c in ["S_page_p3", "S_ph_p3", "S_global_p3", "S_random_p3", "S_page_hit3", "S_ph_hit3", "S_global_hit3", "S_random_hit3"]: res["segments"][c] = mb(D[c])
for c in ["S_page_lift_top", "S_ph_lift_top", "S_global_lift_top", "S_random_lift"]: res["segments"][c] = mb(D[c], scale=1)
res["segments"]["page - global p3 (paired)"] = mb(D.S_page_p3 - D.S_global_p3); res["segments"]["page - random p3 (paired)"] = mb(D.S_page_p3 - D.S_random_p3)
res["segments"]["page - ph p3 (paired)"] = mb(D.S_page_p3 - D.S_ph_p3); res["segments"]["page lift_top - global lift_top (paired)"] = mb(D.S_page_lift_top - D.S_global_lift_top, scale=1)
res["segments"]["fresh only page p3"] = mb(D[D.set == "fresh"].S_page_p3)
if "T_page_p3" in D:
    for c in ["T_page_p3", "T_ph_p3", "T_global_p3", "T_random_p3", "T_page_hit3", "T_ph_hit3"]: res["types"][c] = mb(D[c])
    res["types"]["page - global p3 (paired)"] = mb(D.T_page_p3 - D.T_global_p3); res["types"]["launches"] = int(D.T_page_p3.notna().sum())
for src in ("page", "ph"):
    for lab in ("score", "act_rec", "act_rec+score"):
        c = f"P_{src}_{lab}_auc"
        if c in D: res["person"][f"{src} {lab} AUC"] = mb(D[c], scale=1); res["person"][f"{src} {lab} lift@1%"] = mb(D[f"P_{src}_{lab}_lift1"], scale=1)
    if f"P_{src}_act_rec+score_auc" in D: res["person"][f"{src} (act_rec+score) - act_rec AUC (paired)"] = mb(D[f"P_{src}_act_rec+score_auc"] - D[f"P_{src}_act_rec_auc"], scale=1)
json.dump(res, open(os.path.join(OUT, "who_eval.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
