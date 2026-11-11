"""Segment x product-ATTRIBUTE preference pilot (orchestrator 07:45Z Nov 11), follow-up to segment_pilot.py.
Segments  as segment_pilot.py (k-means on 6.6k complete people from pre-Sep 1 behaviour; K = SEG_K).
Exposure  per day d (Sep 1 - Nov 8) and launch L on d's line-up: label-filtered people of a segment exposed to L, tied
          people (arrivals C(L)) dropped. Two populations:
            voters    every person-day with >= 1 upvote on d's line-up (all voting person-days)
            browsers  person-days with >= 3 upvotes on the line-up and >= 5 active days in the 30 days before d
Labels    attribute a (it9b binary attributes + top-40 PH topics): v_sa = segment s's votes on launches with a,
          e_sa = sum over those launches of (s's exposed person-days x L's all-population pick rate) -> launch
          popularity removed. lift_sa = log((v_sa + 5) / (e_sa + 5)), then double-centered (minus the segment's mean over
          attributes = activity, minus the attribute's mean over segments).
Scores    split-half reliability (people split at random within segment; Pearson over cells and mean within-attribute
          Spearman across segments) in each period; temporal stability (Sep 1 - Oct 19 vs Oct 20 - Nov 8);
          prediction: a test launch's segment lifts = mean of the TRAIN lifts of its attributes; scored per attribute
          group of test launches (pooled test votes, Spearman across segments, mean over attributes with >= 30 test votes),
          shuffled-segment control (segments re-drawn at random, same sizes), cold-start test launches only.
usage: SIMBT=<dir> SEG_K=12 python segment_attr_pilot.py -> results/segment_attr_pilot_k<K>.json"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; S_ = os.path.dirname(WORK)
K = int(os.environ.get("SEG_K", "12")); AL = 5.0
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
    top60 = pd.Series([t for v in tmap.values() for t in v]).value_counts().index[:60]
    ptop = np.vstack([[np.mean([t in tmap.get(i, ()) for i in its]) for t in top60] for its in pv.values])
    zs = lambda M: (M - M.mean(0)) / (M.std(0) + 1e-9)
    Fp = np.hstack([zs(PCA(24, random_state=0).fit_transform(pemb)), zs(pat) * np.sqrt(24 / pat.shape[1]), zs(ptop) * np.sqrt(24 / ptop.shape[1])])
    seg_real = pd.Series(KMeans(K, n_init=5, random_state=0).fit_predict(Fp), index=pv.index)
    seg_shuf = pd.Series(rng.permutation(seg_real.values), index=pv.index)
    half = pd.Series(rng.random(len(people)) < 0.5, index=pv.index)
    # attributes per launch
    top40 = pd.Series([t for v in tmap.values() for t in v]).value_counts().index[:40]
    ATTR = [b for b in BIN] + [f"topic:{t}" for t in top40]
    amat = {}
    for L in I.id:
        s = set()
        if L in At.index:
            r = At.loc[L]; s |= {b for b in BIN if r[b] > 0}
        s |= {f"topic:{t}" for t in tmap.get(L, ()) if t in set(top40)}
        amat[L] = s
    cold = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); cold["id"] = cold.id.astype(str)
    cold = set(cold[(cold.hist_hunter_n.fillna(0) == 0) & (cold.hist_maker_n.fillna(0) == 0)].id)
    tied = {}
    for f in glob.glob(f"{WORK}/arrivals/2026-*.parquet"):
        d = os.path.basename(f)[:10]
        if D0 <= d <= D1:
            R = pd.read_parquet(f, columns=["person", "id"]); tied[d] = set(zip(R.person, R.id.astype(str)))
    adays = E[["person", "date"]].drop_duplicates()
    # per (d, L): arrays of exposed people + votes, for both populations
    lab = up[(up.lday >= D0) & (up.lday <= D1) & (up.date == up.lday) & up.person.isin(people)]
    cells = {"voters": [], "browsers": []}
    for d, g in lab.groupby("lday"):
        g = g[ok(g.person, d)]
        nup = g.groupby("person").size()
        cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        a30 = adays[(adays.date < d) & (adays.date >= cut)].groupby("person").size()
        pops = {"voters": nup.index.values, "browsers": nup[(nup >= 3) & (a30.reindex(nup.index).fillna(0) >= 5)].index.values}
        votes = set(zip(g.person, g.item)); ts = tied.get(d, set())
        for L in I[I.day == d].id:
            for nm, act in pops.items():
                pp = np.array([p for p in act if (p, L) not in ts])
                if len(pp):
                    cells[nm].append((d, L, pp, np.array([(p, L) in votes for p in pp], dtype=bool)))

    def pooled(cl, seg, keep=None, launches=None, period=None):
        """v[s,a], e[s,a] summed over (d, L) cells."""
        si = {a: i for i, a in enumerate(ATTR)}
        v = np.zeros((K, len(ATTR))); e = np.zeros((K, len(ATTR))); vs = np.zeros(K); es = np.zeros(K)
        for d, L, pp, y in cl:
            if period == "train" and d >= TEST0 or period == "test" and d < TEST0:
                continue
            if launches is not None and L not in launches:
                continue
            if keep is not None:
                k = keep.reindex(pp).fillna(False).values.astype(bool); pp, y = pp[k], y[k]
            if len(pp) == 0:
                continue
            rL = y.mean()
            s = seg.reindex(pp).values.astype(int)
            vv = np.bincount(s, weights=y.astype(float), minlength=K); nn = np.bincount(s, minlength=K) * rL
            vs += vv; es += nn
            for a in amat.get(L, ()):
                if a in si:
                    v[:, si[a]] += vv; e[:, si[a]] += nn
        lift = np.log((v + AL) / (e + AL)) - np.log((vs + AL) / (es + AL))[:, None]
        lift = lift - lift.mean(0, keepdims=True)
        return lift, v

    def rel(A, B, va, vb, minv=30):
        m = (va.sum(0) >= minv) & (vb.sum(0) >= minv)
        if m.sum() < 3:
            return {"attrs": int(m.sum())}
        sp = [spearmanr(A[:, j], B[:, j]).correlation for j in np.where(m)[0]]
        r = float(np.corrcoef(A[:, m].ravel(), B[:, m].ravel())[0, 1]); s = float(np.nanmean(sp))
        return {"attrs": int(m.sum()), "cell_pearson": round(r, 3), "within_attr_spearman": round(s, 3), "spearman_brown_cell": round(2 * r / (1 + r), 3) if r > -1 else None}

    res = {"K": K, "people": int(len(people)), "attributes": len(ATTR)}
    art = {}
    for pop in ("voters", "browsers"):
        cl = cells[pop]; out = {"person_days_x_launch": int(sum(len(c[2]) for c in cl)), "votes": int(sum(c[3].sum() for c in cl))}
        for sname, seg in (("real", seg_real), ("shuffled", seg_shuf)):
            o = {}
            for per in ("train", "test"):
                a, va = pooled(cl, seg, half, period=per); b, vb = pooled(cl, seg, ~half, period=per)
                o[f"split_half_{per}"] = rel(a, b, va, vb)
            tr, vtr = pooled(cl, seg, period="train"); te, vte = pooled(cl, seg, period="test")
            o["temporal_train_vs_test"] = rel(tr, te, vtr, vte)
            # prediction per attribute group of test launches: predicted = mean over the group's launches of the mean
            # train lift of each launch's attributes; real = pooled test lift of that attribute
            si = {x: i for i, x in enumerate(ATTR)}
            for sub, launches in (("all", None), ("cold_start", cold)):
                tl_, vtl = pooled(cl, seg, launches=launches, period="test")
                test_L = {L for d, L, pp, y in cl if d >= TEST0 and (launches is None or L in launches)}
                sp = []
                for j, a in enumerate(ATTR):
                    if vtl[:, j].sum() < 30:
                        continue
                    grp = [L for L in test_L if a in amat.get(L, ())]
                    if not grp:
                        continue
                    pred = np.mean([np.mean([tr[:, si[x]] for x in amat[L] if x in si], axis=0) for L in grp], axis=0)
                    sp.append(spearmanr(pred, tl_[:, j]).correlation)
                sp = np.array([x for x in sp if not np.isnan(x)])
                ci = np.percentile([sp[rng.integers(0, len(sp), len(sp))].mean() for _ in range(3000)], [2.5, 97.5]) if len(sp) > 1 else [np.nan, np.nan]
                o[f"predict_{sub}"] = {"attrs": int(len(sp)), "spearman": [round(float(sp.mean()), 3) if len(sp) else None, round(float(ci[0]), 3), round(float(ci[1]), 3)]}
            # person-disjoint (orchestrator 07:50Z): lifts learned on half A (train period), scored on half B (test)
            trA, vA = pooled(cl, seg, half, period="train")
            for sub, launches in (("all", None), ("cold_start", cold)):
                teB, vB = pooled(cl, seg, ~half, launches=launches, period="test")
                test_L = {L for d, L, pp, y in cl if d >= TEST0 and (launches is None or L in launches)}
                sp = []
                for j, a in enumerate(ATTR):
                    if vB[:, j].sum() < 30:
                        continue
                    grp = [L for L in test_L if a in amat.get(L, ())]
                    if grp:
                        pred = np.mean([np.mean([trA[:, si[x]] for x in amat[L] if x in si], axis=0) for L in grp], axis=0)
                        sp.append(spearmanr(pred, teB[:, j]).correlation)
                sp = np.array([x for x in sp if not np.isnan(x)])
                ci = np.percentile([sp[rng.integers(0, len(sp), len(sp))].mean() for _ in range(3000)], [2.5, 97.5]) if len(sp) > 1 else [np.nan, np.nan]
                o[f"disjoint_predict_{sub}"] = {"attrs": int(len(sp)), "spearman": [round(float(sp.mean()), 3) if len(sp) else None, round(float(ci[0]), 3), round(float(ci[1]), 3)]}
            o["disjoint_temporal_A_train_vs_B_test"] = rel(trA, pooled(cl, seg, ~half, period="test")[0], vA, pooled(cl, seg, ~half, period="test")[1])
            out[sname] = o
            if sname == "real":
                art[pop] = tr
        res[pop] = out
    json.dump(res, open(os.path.join(HERE, "results", f"segment_attr_pilot_k{K}.json"), "w"), indent=1, default=float)
    # artifacts for the person-level test and the readable output (salted ids only, scratch only)
    gp = pat.mean(0); gt = ptop.mean(0); desc = {}
    for s_ in range(K):
        m = seg_real.values == s_
        la = np.log((pat[m].mean(0) + 1e-3) / (gp + 1e-3)); lt = np.log((ptop[m].mean(0) + 1e-3) / (gt + 1e-3))
        desc[s_] = {"size": int(m.sum()), "top_attrs": [BIN[i] for i in np.argsort(-la[:len(BIN)])[:4]],
                    "top_topics": [str(top60[i]) for i in np.argsort(-lt)[:4]]}
    pickle.dump({"seg": seg_real, "ATTR": ATTR, "amat": amat, "lift_train": art, "desc": desc, "cold": cold}, open(f"{WORK}/segattr_k{K}.pkl", "wb"))
    print(json.dumps(res, default=float))


if __name__ == "__main__":
    main()
