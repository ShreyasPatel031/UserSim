"""Segment-level preference pilot (orchestrator 07:38Z Nov 11): is 'which audiences want this product' predictable?
Segments  k-means (K=40) on complete people with >= 5 upvotes dated BEFORE Sep 1 (nothing from label days): mean product
          embedding of their upvoted launches (emb_fields.npz tag+desc, 384 -> PCA 24), share of upvotes per it9b
          attribute (51), top-60 PH topic shares; blocks z-scored. (Headline/bio embeddings exist for too few people.)
Labels    days Sep 1 - Nov 8. Browser person-days = clustered people with >= 1 upvote on d's line-up, label filter applied;
          for launch L the people tied to L's team (arrivals C(L)) are dropped. Pick rate r_sL = (v_sL + a r_L)/(n_sL + a),
          a = 10; target = log(r_sL / r_L) (lift over the all-browser rate: the launch's popularity removed).
Model     LightGBM regression (weights n_sL) on product-only x segment features: L's embedding PCA, L's attributes,
          segment centroid embedding PCA and attribute shares, cos(L, segment centroid), attribute-lift dot product.
          Train Sep 1 - Oct 19, test Oct 20 - Nov 8 (honest: segments from pre-Sep behaviour, model from pre-test days).
Scores    per test launch across segments with n_sL >= MIN_N: Spearman(pred, real lift); top-segment hit (real-argmax in
          predicted top 3; random = 3/K); shuffled control (people assigned to random segments of the same sizes, labels
          and model redone); cold-start launches only. Split-half reliability of the real lifts (people split at random
          within segment; Spearman across segments per launch, Spearman-Brown corrected).
usage: SIMBT=<dir> python segment_pilot.py -> results/segment_pilot.json"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; S_ = os.path.dirname(WORK)
K = int(os.environ.get("SEG_K", "40")); MIN_N = int(os.environ.get("MIN_N", "15")); A_SM = 10.0
CENTER = os.environ.get("CENTER", "1") == "1"
SEG_CUT, D0, TEST0, D1 = "2026-09-01", "2026-09-01", "2026-10-20", "2026-11-08"


def main():
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    import lightgbm as lgb
    import two_level as T
    from attr_feats import AttrFeats
    rng = np.random.default_rng(0)
    ok, _ = T._label_maps()
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str); day = dict(zip(I.id, I.day))
    Z = np.load(f"{WORK}/product_attrs/emb_fields.npz"); eid = {str(i): k for k, i in enumerate(Z["ids"])}
    emb = (Z["tag"] + Z["desc"]) / 2; emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    AF = AttrFeats(WORK); At = AF.A
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["item"] = E.item.astype(str); E["date"] = E.date.astype(str).str[:10]
    up = E[(E.kind == "upvote") & E.item.isin(day)].copy(); up["lday"] = up.item.map(day)
    # --- segments from pre-Sep behaviour
    pre = up[(up.lday < SEG_CUT) & up.item.isin(eid) & up.item.isin(At.index)]
    cnt = pre.groupby("person").size(); people = cnt[cnt >= 5].index; pre = pre[pre.person.isin(people)]
    pv = pre.groupby("person").item.apply(list)
    pemb = np.vstack([emb[[eid[i] for i in its]].mean(0) for its in pv.values])
    pat = np.vstack([At.loc[its].values.mean(0) for its in pv.values])
    top = pd.Series([t for x in I.topics.dropna() for t in (json.loads(x) if isinstance(x, str) else list(x))]).value_counts().index[:60]
    tmap = {r.id: set(json.loads(r.topics) if isinstance(r.topics, str) else list(r.topics or [])) for r in I.itertuples()}
    ptop = np.vstack([[np.mean([t in tmap.get(i, ()) for i in its]) for t in top] for its in pv.values])
    pca = PCA(24, random_state=0).fit(pemb)
    zs = lambda M: (M - M.mean(0)) / (M.std(0) + 1e-9)
    Fp = np.hstack([zs(pca.transform(pemb)), zs(pat) * np.sqrt(24 / pat.shape[1]), zs(ptop) * np.sqrt(24 / ptop.shape[1])])
    seg_real = pd.Series(KMeans(K, n_init=5, random_state=0).fit_predict(Fp), index=pv.index)
    seg_shuf = pd.Series(rng.permutation(seg_real.values), index=pv.index)
    gat = pat.mean(0) + 1e-6
    def profiles(seg):
        P = {}
        for s in range(K):
            m = (seg.values == s)
            ce = pemb[m].mean(0); ce = ce / (np.linalg.norm(ce) + 1e-9)
            P[s] = (ce, pca.transform(ce[None])[0], pat[m].mean(0))
        return P
    # --- labels: browser person-days Sep 1 - Nov 8
    tied = {}
    for f in glob.glob(f"{WORK}/arrivals/2026-*.parquet"):
        d = os.path.basename(f)[:10]
        if D0 <= d <= D1:
            R = pd.read_parquet(f, columns=["person", "id"]); tied[d] = set(zip(R.person, R.id.astype(str)))
    lab = up[(up.lday >= D0) & (up.lday <= D1) & (up.date == up.lday) & up.person.isin(people)]
    rows = []
    for d, g in lab.groupby("lday"):
        g = g[ok(g.person, d)]
        lineup = I[I.day == d].id.tolist(); act = g.person.unique()
        tset = tied.get(d, set()); votes = set(zip(g.person, g.item))
        for L in lineup:
            if L not in eid or L not in At.index:
                continue
            pp = [p for p in act if (p, L) not in tset]
            rows.append((d, L, np.array(pp), np.array([(p, L) in votes for p in pp])))
    cold = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); cold["id"] = cold.id.astype(str)
    cold = set(cold[(cold.hist_hunter_n.fillna(0) == 0) & (cold.hist_maker_n.fillna(0) == 0)].id)

    def labels(seg, persons_mask=None):
        out = []
        for d, L, pp, y in rows:
            if persons_mask is not None:
                k = np.array([persons_mask.get(p, False) for p in pp], dtype=bool); pp, y = pp[k], y[k]
            if len(pp) == 0 or y.sum() == 0:
                continue
            s = seg.reindex(pp).values; rL = y.mean()
            for sg in range(K):
                m = s == sg; n = int(m.sum())
                if n == 0:
                    continue
                v = int(y[m].sum()); r = (v + A_SM * rL) / (n + A_SM)
                out.append((d, L, sg, n, v, np.log(r / rL)))
        D = pd.DataFrame(out, columns=["day", "id", "seg", "n", "v", "lift"])
        if CENTER:   # remove the segment's day-level activity (main effect): only segment x launch interaction remains
            D["lift"] = D.lift - D.groupby(["day", "seg"]).lift.transform("mean")
        return D

    def feats(D, P):
        le = np.vstack([emb[eid[i]] for i in D.id]); la = At.loc[D.id].values
        ce = np.vstack([P[s][0] for s in D.seg]); cp = np.vstack([P[s][1] for s in D.seg]); sa = np.vstack([P[s][2] for s in D.seg])
        X = np.hstack([pca.transform(le)[:, :12], la, cp[:, :12], sa,
                       (le * ce).sum(1, keepdims=True), (la[:, :pat.shape[1]] * np.log((sa + 1e-3) / (gat + 1e-3))).sum(1, keepdims=True)])
        return X

    def run(seg, tag):
        P = profiles(seg); D = labels(seg)
        tr, te = D[D.day < TEST0], D[D.day >= TEST0].copy()
        m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1, verbose=-1, n_jobs=4)
        m.fit(feats(tr, P), tr.lift, sample_weight=tr.n)
        te["pred"] = m.predict(feats(te, P))
        out = {}
        for sub, msk in (("all", te.id.notna()), ("cold_start", te.id.isin(cold))):
            Q = te[msk & (te.n >= MIN_N)]
            sp, hit, kk = [], [], []
            for L, g in Q.groupby("id"):
                if len(g) < 5 or g.v.sum() < 5:
                    continue
                sp.append(spearmanr(g.pred, g.lift).correlation)
                hit.append(float(g.loc[g.lift.idxmax(), "seg"] in set(g.nlargest(3, "pred").seg))); kk.append(3 / len(g))
            sp = np.array(sp); hit = np.array(hit)
            bs = lambda x: [round(float(x.mean()), 3)] + [round(float(v), 3) for v in np.percentile([x[rng.integers(0, len(x), len(x))].mean() for _ in range(3000)], [2.5, 97.5])] if len(x) > 1 else [None]
            out[sub] = {"launches": int(len(sp)), "spearman_pred_real": bs(sp), "top_segment_in_pred_top3": bs(hit), "random_top3": round(float(np.mean(kk)), 3) if kk else None}
        return out, D, te

    res = {"K": K, "MIN_N": MIN_N, "centered": CENTER, "people_clustered": int(len(people)), "segment_sizes": np.bincount(seg_real.values, minlength=K).tolist()}
    r_real, D, te = run(seg_real, "real"); r_shuf, Ds, _ = run(seg_shuf, "shuffled")
    res["real_segments"] = r_real; res["shuffled_segments"] = r_shuf
    res["test_label_cells"] = {"cells": int((te.n >= MIN_N).sum()), "median_n": float(te.n.median()), "median_votes_per_cell": float(te.v.median())}
    # split-half reliability of the real lifts on test launches
    rel = {}
    for nm, seg in (("real", seg_real), ("shuffled", seg_shuf)):
        half = pd.Series(rng.random(len(seg)) < 0.5, index=seg.index)
        Ha = labels(seg, half.to_dict()); Hb = labels(seg, (~half).to_dict())
        Ha, Hb = Ha[Ha.day >= TEST0], Hb[Hb.day >= TEST0]
        M = Ha.merge(Hb, on=["day", "id", "seg"], suffixes=("_a", "_b"))
        M = M[(M.n_a >= MIN_N // 2) & (M.n_b >= MIN_N // 2)]
        rs = [spearmanr(g.lift_a, g.lift_b).correlation for _, g in M.groupby("id") if len(g) >= 5 and (g.v_a.sum() + g.v_b.sum()) >= 5]
        rs = np.array([x for x in rs if not np.isnan(x)]); r = float(rs.mean()) if len(rs) else np.nan
        rel[nm] = {"launches": int(len(rs)), "split_half_spearman": round(r, 3), "spearman_brown": round(2 * r / (1 + r), 3) if r > -1 else None}
        # pooled cell-level reliability (lift values across all cells)
        rel[nm]["cell_pearson"] = round(float(np.corrcoef(M.lift_a, M.lift_b)[0, 1]), 3) if len(M) > 10 else None
    res["reliability_test_days"] = rel
    json.dump(res, open(os.path.join(HERE, "results", "segment_pilot.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "segment_sizes"}, indent=1, default=float))


if __name__ == "__main__":
    main()
