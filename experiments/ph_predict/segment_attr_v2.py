"""Segment x attribute pilot v2: E5 review fixes (Nov 11 07:45Z).
(c) person-disjoint: people split at random into A / B. Segments are FIT on A only (k-means, pre-Sep 1 behaviour); B is
    assigned to the nearest A centroid. Train lifts from A's Sep 1 - Oct 19 cells; real test lifts from B's
    Oct 20 - Nov 8 cells.
(a) scoring per attribute a: G_a = test launches carrying a. pred_a = mean over L in G_a of pred_L minus the mean of
    pred_L over ALL test launches (pred_L = mean train lift over L's attributes), so the segment main effect of
    frequency-weighted averaging is removed. real_a = B's pooled test lift on G_a minus B's pooled lift over all test
    launches (same centering). Spearman across segments, mean over attributes with >= 30 B test votes.
    Control: attribute SETS permuted across test launches within the same day (keeps attribute frequency and set
    size), 20 permutations, same scoring. Report real, control, real - control.
(b) smoothing alpha in {1, 5, 20}.
(d1) exposure is already per segment member active that day (e = sum over the segment's voters that day x the launch's
    pick rate), not the whole population. (d3) attribute sets: all 86 / topics only (40) / it9b only (46).
Population: all label-filtered voting person-days, tied people (arrivals C(L)) dropped.
usage: SIMBT=<dir> SEG_K=12 python segment_attr_v2.py -> results/segment_attr_v2_k<K>.json"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; S_ = os.path.dirname(WORK)
K = int(os.environ.get("SEG_K", "12")); NPERM = 20
SEG_CUT, D0, TEST0, D1 = "2026-09-01", "2026-09-01", "2026-10-20", "2026-11-08"


def main():
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    import two_level as T
    from attr_feats import AttrFeats, BIN
    rng = np.random.default_rng(0)
    ok, _ = T._label_maps()
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str); day = dict(zip(I.id, I.day))
    Z = np.load(f"{WORK}/product_attrs/emb_fields.npz"); eid = {str(i): k for k, i in enumerate(Z["ids"])}
    emb = (Z["tag"] + Z["desc"]) / 2; emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    At = AttrFeats(WORK).A
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["item"] = E.item.astype(str); E["date"] = E.date.astype(str).str[:10]
    up = E[(E.kind == "upvote") & E.item.isin(day)].copy(); up["lday"] = up.item.map(day)
    pre = up[(up.lday < SEG_CUT) & up.item.isin(eid) & up.item.isin(At.index)]
    cnt = pre.groupby("person").size(); people = cnt[cnt >= 5].index; pre = pre[pre.person.isin(people)]
    pv = pre.groupby("person").item.apply(list)
    pemb = np.vstack([emb[[eid[i] for i in its]].mean(0) for its in pv.values])
    pat = np.vstack([At.loc[its].values.mean(0) for its in pv.values])
    tl = lambda x: (json.loads(x) if isinstance(x, str) else list(x)) if x is not None else []
    tmap = {r.id: set(tl(r.topics)) for r in I.itertuples()}
    tc = pd.Series([t for v in tmap.values() for t in v]).value_counts()
    top60, top40 = tc.index[:60], tc.index[:40]
    ptop = np.vstack([[np.mean([t in tmap.get(i, ()) for i in its]) for t in top60] for its in pv.values])
    halfA = rng.random(len(pv)) < 0.5
    # fit scaling + PCA + k-means on A only; B by nearest centroid
    pca = PCA(24, random_state=0).fit(pemb[halfA])
    blocks = [pca.transform(pemb), pat, ptop]
    mu = [b[halfA].mean(0) for b in blocks]; sd = [b[halfA].std(0) + 1e-9 for b in blocks]
    w = [1.0, np.sqrt(24 / pat.shape[1]), np.sqrt(24 / ptop.shape[1])]
    Fp = np.hstack([(b - m) / s * ww for b, m, s, ww in zip(blocks, mu, sd, w)])
    km = KMeans(K, n_init=5, random_state=0).fit(Fp[halfA])
    seg = pd.Series(km.predict(Fp), index=pv.index); grpA = pd.Series(halfA, index=pv.index)
    BINS = list(BIN); TOP = [f"topic:{t}" for t in top40]
    amat = {}
    for L in I.id:
        s = set()
        if L in At.index:
            r = At.loc[L]; s |= {b for b in BIN if r[b] > 0}
        s |= {f"topic:{t}" for t in tmap.get(L, ()) if t in set(top40)}
        amat[L] = s
    cold = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); cold["id"] = cold.id.astype(str)
    cold = set(cold[(cold.hist_hunter_n.fillna(0) == 0) & (cold.hist_maker_n.fillna(0) == 0)].id)
    lab = up[(up.lday >= D0) & (up.lday <= D1) & (up.date == up.lday) & up.person.isin(people)]
    # per cell (d, L): segment exposure counts and votes for A and B, plus L's all-population pick rate
    cells = []
    for d, g in lab.groupby("lday"):
        g = g[ok(g.person, d)]
        f = f"{WORK}/arrivals/{d}.parquet"
        ts = set(zip(*pd.read_parquet(f, columns=["person", "id"]).astype(str).values.T)) if os.path.exists(f) else set()
        act = g.person.unique(); votes = set(zip(g.person, g.item))
        for L in I[I.day == d].id:
            pp = np.array([p for p in act if (p, L) not in ts])
            if not len(pp):
                continue
            y = np.array([(p, L) in votes for p in pp], float); rL = y.mean()
            s = seg.reindex(pp).values.astype(int); a = grpA.reindex(pp).values.astype(bool)
            cells.append({"d": d, "L": L, "rL": rL,
                          "nA": np.bincount(s[a], minlength=K) * 1.0, "vA": np.bincount(s[a], weights=y[a], minlength=K),
                          "nB": np.bincount(s[~a], minlength=K) * 1.0, "vB": np.bincount(s[~a], weights=y[~a], minlength=K)})

    def train_lifts(ATTR, al):
        si = {x: i for i, x in enumerate(ATTR)}
        v = np.zeros((K, len(ATTR))); e = np.zeros((K, len(ATTR))); vs = np.zeros(K); es = np.zeros(K)
        for c in cells:
            if c["d"] >= TEST0:
                continue
            ee = c["nA"] * c["rL"]; vs += c["vA"]; es += ee
            for x in amat.get(c["L"], ()):
                if x in si:
                    v[:, si[x]] += c["vA"]; e[:, si[x]] += ee
        lift = np.log((v + al) / (e + al)) - np.log((vs + al) / (es + al))[:, None]
        return lift - lift.mean(0, keepdims=True)

    def score(ATTR, al, sets, launches=None):
        si = {x: i for i, x in enumerate(ATTR)}; tr = train_lifts(ATTR, al)
        test = [c for c in cells if c["d"] >= TEST0 and (launches is None or c["L"] in launches)]
        predL = {c["L"]: (tr[:, [si[x] for x in sets[c["L"]] if x in si]].mean(1) if any(x in si for x in sets[c["L"]]) else np.zeros(K)) for c in test}
        pbar = np.mean([predL[c["L"]] for c in test], axis=0)
        vs = sum(c["vB"] for c in test); es = sum(c["nB"] * c["rL"] for c in test); base = np.log((vs + al) / (es + al))
        sp = []
        for x in ATTR:
            G = [c for c in test if x in sets[c["L"]]]
            if not G:
                continue
            v = sum(c["vB"] for c in G)
            if v.sum() < 30:
                continue
            e = sum(c["nB"] * c["rL"] for c in G)
            real = np.log((v + al) / (e + al)) - base
            pred = np.mean([predL[c["L"]] for c in G], axis=0) - pbar
            r = spearmanr(pred, real).correlation
            if not np.isnan(r):
                sp.append(r)
        return np.array(sp)

    def permuted_sets():
        S = dict(amat)
        byday = {}
        for c in cells:
            if c["d"] >= TEST0:
                byday.setdefault(c["d"], []).append(c["L"])
        for d, Ls in byday.items():
            perm = rng.permutation(len(Ls))
            for L, j in zip(Ls, perm):
                S[L] = amat[Ls[j]]
        return S

    res = {"K": K, "people": int(len(pv)), "A": int(halfA.sum()), "B": int((~halfA).sum()),
           "segment_sizes_A": np.bincount(seg[grpA].values, minlength=K).tolist(), "rows": {}}
    perms = [permuted_sets() for _ in range(NPERM)]
    for aname, ATTR in (("all86", BINS + TOP), ("topics40", TOP), ("it9b46", BINS)):
        for al in (1.0, 5.0, 20.0):
            for sub, launches in (("all", None), ("cold_start", cold)):
                r = score(ATTR, al, amat, launches)
                ctrl = [score(ATTR, al, S, launches) for S in perms]
                cm = np.array([c.mean() for c in ctrl if len(c)])
                bs = [r[rng.integers(0, len(r), len(r))].mean() for _ in range(3000)] if len(r) > 1 else [np.nan]
                res["rows"][f"{aname} | alpha {al:g} | {sub}"] = {
                    "attrs": int(len(r)), "real": round(float(r.mean()), 3) if len(r) else None,
                    "real_ci": [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])],
                    "control_mean": round(float(cm.mean()), 3), "control_sd": round(float(cm.std()), 3),
                    "real_minus_control": round(float(r.mean() - cm.mean()), 3) if len(r) else None,
                    "z_vs_control": round(float((r.mean() - cm.mean()) / (cm.std() + 1e-9)), 1) if len(r) else None}
                print(f"{aname} | alpha {al:g} | {sub}", res["rows"][f"{aname} | alpha {al:g} | {sub}"], flush=True)
    json.dump(res, open(os.path.join(HERE, "results", f"segment_attr_v2_k{K}.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
