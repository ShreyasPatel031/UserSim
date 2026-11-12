"""Sharpen the voter-learned "who" and test "who -> where it lands" (orchestrator, Nov 12). Builds on who_learn.py (same people,
launches, time ordering: person vectors from upvotes dated before the launch day).
A1 segmentations (fit on data before Sep 1 2026; test launches Sep 1 - Nov 10):
   IDX12   the site index's 12 segments (who_segments_v1)
   KM20/30/50  k-means on person upvote topic-share vectors as of Aug 31 (people with >= 3 upvotes), assignment per day = nearest
           centroid of the person's vector before the day
   NMF20   20 latent factors of the person x launch upvote matrix (launches before Sep 1); a person's segment = argmax loading
           (people without pre-Sep upvotes are unassigned and dropped from voters and base)
   Each segment described by its top topics (mean topic shares). Truth (day lift): share among the launch's voters / share among
   all that day's voters > 1.5 with >= 3 voters AND an expected count (day share x voters) >= 1 (so small segments are not
   rewarded by noise). Predictor: ridge (alpha 10) from the launch embedding to per-segment log day-lift, trained month-forward on
   earlier launches with >= 15 voters; queries = the 426 page reads (and PH text).
   Metrics by launch: p@3, hit@3, real day-lift of the top-1 and mean of the top-3, vs the control (the segmentation's 3 most-voting
   segments over Jan-Aug) and random; paired top-1 / top-3 real lift vs IDX12.
A2 calibration (IDX12 ridge): reliability of predicted lift >= 1.5 / >= 2 / >= 3 -> share with real day-lift >= 1.5 (>= 3 voters).
B  "addressable voters" = sum over segments of (segment's share of all upvotes in the 30 days before the launch day) x predicted
   lift (IDX12 ridge, PH input for every launch; page input for page-read launches). Within-day Spearman with -final rank alone;
   added to the clean 00:05 LM (honest_preds_v2) by ridge month-forward over Sep-Oct (daily top 3/5/10, paired day bootstrap); and
   pooled partial gain over launch_band_page_v1 on the page-read launches.
    python who_sharp.py <ph-website worktree> <scratchpad> <who_eval dir> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF

WT, SP, WE, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim  # noqa: E402
I = try_sim.index(); META = I["meta"]; VOC = META["vocab"]; vix = {t: k for k, t in enumerate(VOC)}
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L = L.sort_values(["day", "id"]).reset_index(drop=True); lix = {i: k for k, i in enumerate(L.id)}
TP = np.zeros((len(L), len(VOC)), np.float32)
for k, t in enumerate(L.topics):
    for x in (json.loads(t) if isinstance(t, str) and t.startswith("[") else []):
        if x in vix: TP[k, vix[x]] = 1
dnum = pd.to_datetime(L.day).to_numpy().astype("datetime64[D]").astype(np.int64); SEP = np.datetime64("2026-09-01").astype(np.int64)
comp = set(pd.read_parquet(os.path.join(SP, "tl/v3/persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(SP, "tl/v3/events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; ev["target_id"] = ev.target_id.astype(str); ev = ev[ev.target_id.isin(lix)].drop_duplicates(["person_id", "target_id"])
people = sorted(ev.person_id.unique()); pix = {p: k for k, p in enumerate(people)}
M = sparse.csr_matrix((np.ones(len(ev), np.float32), (ev.person_id.map(pix), ev.target_id.map(lix))), shape=(len(people), len(L))); MT = M.T.tocsr(); nvote = np.diff(MT.indptr)
CENT12 = np.vstack([I["Xn"][I["seg"] == s].mean(0) for s in range(len(META["segments"]))]); CENT12 /= np.linalg.norm(CENT12, axis=1, keepdims=True) + 1e-9
pre = (dnum < SEP).astype(np.float32); Mpre = M.multiply(pre[None, :]).tocsr(); Mpre.eliminate_zeros(); npre = np.asarray(Mpre.sum(1)).ravel()
Vpre = Mpre @ TP; Vpre = Vpre / (np.linalg.norm(Vpre, axis=1, keepdims=True) + 1e-9)
SEGS = {"IDX12": CENT12}
for k in (20, 30, 50):
    km = KMeans(k, n_init=4, random_state=0).fit(Vpre[npre >= 3]); C = km.cluster_centers_; SEGS[f"KM{k}"] = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
act = npre >= 3; cols = np.flatnonzero((dnum < SEP) & (nvote >= 5))
nmf = NMF(20, init="nndsvda", random_state=0, max_iter=300).fit(Mpre[act][:, cols]); W = np.zeros((len(people), 20), np.float32); W[act] = nmf.transform(Mpre[act][:, cols])
NMF_SEG = np.where(W.max(1) > 0, W.argmax(1), -1)
H = nmf.components_; nmf_topics = (H @ TP[cols]) / (H.sum(1, keepdims=True) + 1e-9)
print("segmentations ready", flush=True)


def describe(name):
    if name == "NMF20": T_ = nmf_topics
    else: T_ = SEGS[name]
    return [[VOC[j] for j in np.argsort(-T_[s])[:3]] for s in range(T_.shape[0])]


ST = {}
def state(d):
    if d not in ST:
        prior = (dnum < d).astype(np.float32); Mp = M.multiply(prior[None, :]).tocsr(); Mp.eliminate_zeros(); n = np.asarray(Mp.sum(1)).ravel()
        V = Mp @ TP; V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
        seg = {nm: np.argmax(V @ C.T, axis=1) for nm, C in SEGS.items()}; seg["NMF20"] = NMF_SEG
        recent = ((dnum < d) & (dnum >= d - 30)).astype(np.float32); vol = np.asarray(M.multiply(recent[None, :]).sum(1)).ravel()
        ST[d] = (seg, n >= 3, vol)
    return ST[d]
NS = {nm: C.shape[0] for nm, C in SEGS.items()}; NS["NMF20"] = 20
LIFT, CNT, EXP = {nm: {} for nm in NS}, {nm: {} for nm in NS}, {nm: {} for nm in NS}
days = sorted(set(dnum.tolist()))
for d in days:
    if d < np.datetime64("2026-02-01").astype(np.int64): continue
    seg, base, vol = state(d); ks = np.flatnonzero(dnum == d)
    dayv = np.unique(np.concatenate([MT[k].indices for k in ks])); dayv = dayv[base[dayv]]
    for nm, ns in NS.items():
        sg = seg[nm]; dv = dayv[sg[dayv] >= 0]; bd = np.bincount(sg[dv], minlength=ns) / max(1, len(dv))
        for k in ks:
            v = MT[k].indices; v = v[base[v] & (sg[v] >= 0)]
            if len(v) < 15: continue
            c = np.bincount(sg[v], minlength=ns); LIFT[nm][k] = (c / len(v)) / (bd + 1e-9); CNT[nm][k] = c; EXP[nm][k] = bd * len(v)
print("lifts", {nm: len(v) for nm, v in LIFT.items()}, flush=True)
LE = np.load(os.path.join(SP, "land/launch_emb256.npy")); Lv = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
Lv = Lv[Lv.daily_rank.notna() & Lv.votes.notna() & (Lv.day < "2026-11-11")].sort_values(["day", "id"]); Lv["id"] = Lv.id.astype(str); emb_of = {i: LE[k] for k, i in enumerate(Lv.id)}
K = json.load(open(os.path.join(SP, "band_page/cache.json"))); FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
READ = {i: v for i, v in K.items() if "fail" not in v and i in lix and L.day.iat[lix[i]] >= "2026-09-01"}
READ.update({k.split("|", 1)[1]: v["read"] for k, v in FK.items() if k.startswith("p|") and "read" in v and k.split("|", 1)[1] in lix})
S_all = [i for i in READ if nvote[lix[i]] >= 15]; QP = np.load(os.path.join(WE, "emb_page.npy")); qp = dict(zip(S_all, QP))
early = np.flatnonzero(dnum < SEP); seg0 = state(int(dnum[early].max()) + 1)[0]
CONTROL = {nm: list(pd.Series(seg0[nm][MT[early].indices]).loc[lambda s: s >= 0].value_counts().index[:3]) for nm in NS}
FIT = {}
def ridge_for(nm, m0):
    key = (nm, m0)
    if key not in FIT:
        ks_ = [k for k in LIFT[nm] if dnum[k] < m0 and L.id.iat[k] in emb_of]; X_ = np.vstack([emb_of[L.id.iat[k]] for k in ks_]); Y_ = np.log(np.vstack([LIFT[nm][k] for k in ks_]) + 0.05)
        FIT[key] = Ridge(alpha=10.0).fit(X_, Y_)
    return FIT[key]
rows, calib = [], []
for i in S_all:
    k = lix[i]
    if k not in LIFT["IDX12"]: continue
    m0 = np.datetime64(L.day.iat[k][:7] + "-01").astype(np.int64); r = {"id": i}
    for nm, ns in NS.items():
        if k not in LIFT[nm]: continue
        lift, c, e = LIFT[nm][k], CNT[nm][k], EXP[nm][k]; truth = set(np.flatnonzero((lift > 1.5) & (c >= 3) & (e >= 1)).tolist())
        pr = ridge_for(nm, m0).predict(qp[i][None])[0]; top = list(np.argsort(-pr)[:3])
        r[f"{nm}|p3"] = np.mean([t in truth for t in top]); r[f"{nm}|hit3"] = float(any(t in truth for t in top)); r[f"{nm}|l1"] = lift[top[0]]; r[f"{nm}|l3"] = float(np.mean(lift[top]))
        ct = CONTROL[nm]; r[f"{nm}|ctl_p3"] = np.mean([t in truth for t in ct]); r[f"{nm}|ctl_l1"] = lift[ct[0]]; r[f"{nm}|rand_p3"] = len(truth) / ns; r[f"{nm}|ntruth"] = len(truth)
        if nm == "IDX12":
            pl = np.exp(pr) - 0.05
            for s in range(ns): calib.append({"pred": pl[s], "real_ok": float(lift[s] >= 1.5 and c[s] >= 3)})
    rows.append(r)
D = pd.DataFrame(rows)


def mb(v, B=4000, sc=100):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * sc, 2), round(float(np.percentile(bs, 2.5)) * sc, 2), round(float(np.percentile(bs, 97.5)) * sc, 2), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "A1": {}, "A2_calibration_IDX12": {}, "B": {}}
for nm in NS:
    if f"{nm}|p3" not in D: continue
    res["A1"][nm] = {"segments": NS[nm], "mean_true": round(float(D[f"{nm}|ntruth"].mean()), 2), "p3": mb(D[f"{nm}|p3"]), "hit3": mb(D[f"{nm}|hit3"]),
                     "real_lift_top1": mb(D[f"{nm}|l1"], sc=1), "real_lift_top3_mean": mb(D[f"{nm}|l3"], sc=1), "control_p3": mb(D[f"{nm}|ctl_p3"]),
                     "control_lift_top1": mb(D[f"{nm}|ctl_l1"], sc=1), "random_p3": mb(D[f"{nm}|rand_p3"]), "p3 - control (paired)": mb(D[f"{nm}|p3"] - D[f"{nm}|ctl_p3"]),
                     "descriptions_top_topics": describe(nm)}
    if nm != "IDX12":
        res["A1"][nm]["top1 lift - IDX12 (paired)"] = mb(D[f"{nm}|l1"] - D["IDX12|l1"], sc=1); res["A1"][nm]["top3 lift - IDX12 (paired)"] = mb(D[f"{nm}|l3"] - D["IDX12|l3"], sc=1)
C = pd.DataFrame(calib)
for lo, hi in ((0, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 99)):
    g = C[(C.pred >= lo) & (C.pred < hi)]; res["A2_calibration_IDX12"][f"pred lift {lo}-{hi}"] = {"n": int(len(g)), "share_real_day_lift_ge_1.5": round(float(g.real_ok.mean()), 3) if len(g) else None}
for thr in (1.5, 2.0):
    g = C[C.pred >= thr]; res["A2_calibration_IDX12"][f"pred >= {thr}"] = {"n": int(len(g)), "share_real_ge_1.5": round(float(g.real_ok.mean()), 3) if len(g) else None}
# ---------- B: addressable voters ----------
H_ = pd.read_parquet(os.path.join(SP, "honest_preds_v2.parquet")); H_["id"] = H_.id.astype(str); hon = dict(zip(H_.id, H_.honest))
Bk = [k for k in range(len(L)) if L.day.iat[k] >= "2026-09-01" and L.day.iat[k] <= "2026-10-31" and L.id.iat[k] in emb_of and L.id.iat[k] in hon]
AR = []
for k in Bk:
    d = dnum[k]; seg, base, vol = state(d); sg = seg["IDX12"]; share = np.bincount(sg, weights=vol, minlength=12); share = share / max(1, share.sum())
    m0 = np.datetime64(L.day.iat[k][:7] + "-01").astype(np.int64); pl = np.exp(ridge_for("IDX12", m0).predict(emb_of[L.id.iat[k]][None])[0]) - 0.05
    a = {"id": L.id.iat[k], "day": L.day.iat[k], "rank": float(L.daily_rank.iat[k]), "y": np.log1p(float(L.votes.iat[k])) if pd.notna(L.votes.iat[k]) else np.nan, "honest": hon[L.id.iat[k]], "addr_ph": float(share @ pl)}
    if L.id.iat[k] in qp: a["addr_page"] = float(share @ (np.exp(ridge_for("IDX12", m0).predict(qp[L.id.iat[k]][None])[0]) - 0.05))
    AR.append(a)
A = pd.DataFrame(AR); A["mon"] = A.day.str[:7]
wd = [spearmanr(g.addr_ph, -g["rank"]).correlation for d, g in A.groupby("day") if len(g) >= 8]
res["B"]["within_day_spearman_addr_ph_alone"] = mb(np.array(wd), sc=1)
res["B"]["within_day_spearman_clean_LM"] = mb(np.array([spearmanr(g.honest, -g["rank"]).correlation for d, g in A.groupby("day") if len(g) >= 8]), sc=1)
# stacking on the clean LM: ridge trained on Sep, tested on Oct (and vice versa)
def topk(df, col):
    out = {}
    for d, g in df.groupby("day"):
        if len(g) >= 10 and (g["rank"] <= 3).sum() == 3: out[d] = [len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)]
    return pd.DataFrame(out, index=["top3", "top5", "top10"]).T
A2 = A.dropna(subset=["y"]).copy(); A2["s_lm"] = np.nan; A2["s_both"] = np.nan
for tr_m, te_m in (("2026-09", "2026-10"), ("2026-10", "2026-09")):
    tr, te = A2[A2.mon == tr_m], A2[A2.mon == te_m]
    for col, feats in (("s_lm", ["honest"]), ("s_both", ["honest", "addr_ph"])):
        mu, sd = tr[feats].mean(), tr[feats].std() + 1e-9; A2.loc[te.index, col] = Ridge(alpha=1.0).fit((tr[feats] - mu) / sd, tr.y).predict((te[feats] - mu) / sd)
T0, T1 = topk(A2, "s_lm"), topk(A2, "s_both"); j = T0.index.intersection(T1.index); dd = (T1.loc[j] - T0.loc[j]).values
bs = np.array([dd[rng.integers(0, len(dd), len(dd))].mean(0) for _ in range(2000)])
res["B"]["clean LM top3/5/10"] = [round(float(x), 1) for x in T0.loc[j].mean()]; res["B"]["+addressable top3/5/10"] = [round(float(x), 1) for x in T1.loc[j].mean()]
res["B"]["difference (paired, day bootstrap)"] = {c: [round(float(dd[:, q].mean()), 1), round(float(np.percentile(bs[:, q], 2.5)), 1), round(float(np.percentile(bs[:, q], 97.5)), 1)] for q, c in enumerate(["top3", "top5", "top10"])} | {"days": int(len(j))}
res["B"]["partial_spearman_addr_ph_with_y_given_LM"] = round(float(spearmanr(A2.y - np.poly1d(np.polyfit(A2.honest, A2.y, 1))(A2.honest), A2.addr_ph).correlation), 3)
# partial gain over launch_band_page_v1 on the page-read launches (pooled): Spearman of residual(-rank | band) with addr_page
LBP = json.load(open(os.path.join(SP, "band_page/launch_band_page_v1.json"))); Pg = A[A.addr_page.notna()].copy() if "addr_page" in A else A.iloc[:0]
Pg["band"] = [try_sim._band_score(LBP, READ[i].get("name") or "", READ[i].get("tagline") or "", (READ[i].get("summary") or "") + " " + (READ[i].get("page_excerpt") or "")[:1500],
                                  [t for t in (READ[i].get("topics") or []) if t in VOC][:4]) for i in Pg.id]
if len(Pg) > 20:
    rr = lambda v: pd.Series(v).rank().values; res_rank = rr(-Pg["rank"].values) - np.poly1d(np.polyfit(rr(Pg.band), rr(-Pg["rank"].values), 1))(rr(Pg.band))
    res["B"]["page-read launches"] = {"n": int(len(Pg)), "spearman band": round(float(spearmanr(Pg.band, -Pg["rank"]).correlation), 3), "spearman addr_page": round(float(spearmanr(Pg.addr_page, -Pg["rank"]).correlation), 3),
                                      "partial spearman addr_page | band": round(float(spearmanr(res_rank, Pg.addr_page).correlation), 3)}
    bsp = []
    for _ in range(2000):
        j_ = rng.integers(0, len(Pg), len(Pg)); bsp.append(spearmanr(res_rank[j_], Pg.addr_page.values[j_]).correlation)
    res["B"]["page-read launches"]["partial ci"] = [round(float(x), 3) for x in np.percentile(bsp, [2.5, 97.5])]
json.dump(res, open(os.path.join(OUT, "who_sharp.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str)[:7000])
