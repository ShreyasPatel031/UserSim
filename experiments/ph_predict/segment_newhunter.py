"""Segment model for launches whose hunter has no ranked history (orchestrator 06:33Z Nov 13; 214 days Apr-Oct; counts only).
Segment = hist_hunter_n == 0 in the clean build (no earlier ranked launch hunted by the same hunter in the 2026 lists).
Inputs (00:05-safe, no hunter history): llm_pitch, llm_brand, text ridge (TF-IDF of name + tagline + description, fitted
leave-one-MONTH-out on z(log votes) within day), topic prior (leave-one-month-out shrunk mean of the within-day z target), media
count, video, team size, topic count, text lengths, hunter account age, th_n_pre, line-up size, weekday.
Model: LightGBM classifier on segment rows only, target = final top 10 (and top 3), leave-one-day-out, 5 seeds.
(a) within-segment AUC on each test day's segment launches (pooled) vs the clean_nosite score (tw_nosite OOF) and vs clean + th_n_pre.
(b) plug-in: score = base (LODO ridge z(clean) + z(th_n_pre)) + w * z(segment logit) for segment launches (0 for others), z within
the day's segment launches; w tuned on Apr-Jul days, confirmed on Aug-Oct; overall top 3/5/10 and new-hunter winners caught.
Input file: the VM cache export (scratchpad seg_export.parquet). usage: python segment_newhunter.py <export.parquet>"""
import os, sys
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score


def main(path):
    from pipeline import warehouse as W
    X = pd.read_parquet(path); X["id"] = X.id.astype(str); X = X[X.dailyRank.notna()].copy(); X["mon"] = X.day.str[:7]
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, poster FROM launches", do_sync=False); L["poster"] = L.poster.fillna("").str.lower()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [(pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(minutes=5)).tz_convert("UTC") for d in K.day]
    X["npre"] = X.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = X.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id", how="left")
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    X["yz"] = X.groupby("day").logv.transform(zf)
    # leave-one-month-out text ridge and topic prior
    txt = (X.name.fillna("") + " " + X.tagline.fillna("") + " " + X.description.fillna("")).values
    X["txt"] = np.nan; X["tprior"] = np.nan
    for m in X.mon.unique():
        tr, te = X.mon != m, X.mon == m
        v = TfidfVectorizer(min_df=2, max_features=20000, ngram_range=(1, 2), sublinear_tf=True); A_ = v.fit_transform(txt[tr.values])
        X.loc[te, "txt"] = Ridge(alpha=3.0).fit(A_, X.yz[tr]).predict(v.transform(txt[te.values]))
        ex = X[tr][["topics", "yz"]].assign(t=X[tr].topics.str.split("|")).explode("t"); st = ex.groupby("t").yz.agg(["mean", "count"])
        tm = (st["mean"] * st["count"] / (st["count"] + 20)).to_dict()
        X.loc[te, "tprior"] = [max([tm.get(t, 0) for t in str(ts).split("|") if t] or [0]) for ts in X[te].topics]
    X["n_day"] = X.groupby("day").id.transform("size")
    FT = ["llm_pitch", "llm_brand", "txt", "tprior", "ph_n_media", "ph_has_video", "ph_n_makers", "ph_n_topics", "ph_desc_len", "ph_tagline_len",
          "ph_name_len", "ph_hunter_age_d", "npre", "n_day", "ph_weekday"]
    X["seg"] = (X.hist_hunter_n.fillna(0) == 0)
    X["t10"] = (X.dailyRank <= 10).astype(int); X["t3"] = (X.dailyRank <= 3).astype(int)
    E = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31") & X.clean.notna()].copy(); days = sorted(E.day.unique())
    for c in ("clean", "npre"):
        E["z_" + c] = E.groupby("day")[c].transform(zf)
    E["y"] = E.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    S = X[X.seg]; P = {"t10": {}, "t3": {}}
    P0 = dict(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.7, verbose=-1, n_jobs=4)
    for d in days:
        tr, te = S[S.day != d], S[S.day == d]
        if te.empty:
            continue
        for tg in ("t10", "t3"):
            p = np.mean([lgb.LGBMClassifier(random_state=s, **P0).fit(tr[FT], tr[tg]).predict_proba(te[FT])[:, 1] for s in range(5)], axis=0)
            P[tg].update(dict(zip(te.id, p)))
    E["seg10"] = E.id.map(P["t10"]); E["seg3"] = E.id.map(P["t3"])
    base = {}
    for d in days:   # base: LODO ridge z(clean) + z(th_n_pre)
        te, tr = E[E.day == d], E[E.day != d]
        base.update(dict(zip(te.id, Ridge(alpha=3.0).fit(tr[["z_clean", "z_npre"]], tr.y).predict(te[["z_clean", "z_npre"]]))))
    E["base"] = E.id.map(base)
    G = E[E.seg]
    md = [f"# Segment model: new-hunter launches ({len(days)} days Apr-Oct; segment {E.seg.mean():.1%} of launches, {E[E.dailyRank <= 3].seg.mean():.1%} of top 3, "
          f"{E[E.dailyRank <= 10].seg.mean():.1%} of top 10; LightGBM, 5 seeds, LODO)", "", "## (a) within-segment AUC (pooled test-day segment launches)", "",
          "| score | AUC final top 10 | AUC final top 3 |", "|---|---|---|"]
    for nm, c in (("clean_nosite", "clean"), ("clean + th_n_pre (base)", "base"), ("segment model (target top 10)", "seg10"), ("segment model (target top 3)", "seg3")):
        g = G[G[c].notna()]
        md.append(f"| {nm} | {roc_auc_score(g.t10, g[c]):.3f} | {roc_auc_score(g.t3, g[c]):.3f} |")
    # within-day AUC average for robustness
    def wd_auc(c, tg):
        a = [roc_auc_score(g[tg], g[c]) for _, g in G.groupby("day") if g[tg].nunique() == 2 and g[c].notna().all()]
        return np.mean(a), len(a)
    md += ["", "Within-day AUC (mean over days with both classes in the segment): " + "; ".join(
        f"{nm} top10 {wd_auc(c, 't10')[0]:.3f} (n {wd_auc(c, 't10')[1]}) top3 {wd_auc(c, 't3')[0]:.3f} (n {wd_auc(c, 't3')[1]})"
        for nm, c in (("base", "base"), ("seg10", "seg10"), ("seg3", "seg3")))]
    # (b) plug-in
    for c in ("seg10", "seg3"):
        E["zs_" + c] = 0.0
        m = E.seg & E[c].notna()
        E.loc[m, "zs_" + c] = E[m].groupby("day")[c].transform(lambda s: (np.log(s / (1 - s)) - np.log(s / (1 - s)).mean()) / (np.log(s / (1 - s)).std() + 1e-9))
    E["zb"] = E.groupby("day").base.transform(zf)
    def evalw(dset, c, w):
        out, caught, tot = [], 0, 0
        for d in dset:
            g = E[E.day == d]; s = g.zb + w * g["zs_" + c]
            o = g.assign(s=s).sort_values(["s", "id"], ascending=[False, True]).id.tolist(); t = g.sort_values("dailyRank").id.tolist()
            out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
            nw = set(g[(g.dailyRank <= 3) & g.seg].id); caught += len(nw & set(o[:3])); tot += len(nw)
        return np.array(out), caught, tot
    tune = [d for d in days if d < "2026-08-01"]; conf = [d for d in days if d >= "2026-08-01"]; rng = np.random.default_rng(0)
    md += ["", "## (b) plug-in: z(base) + w * z(segment logit) on segment launches; w tuned on Apr-Jul, confirmed on Aug-Oct", "",
           "| target | w (tuned) | tune: base t3/t5/t10 -> blend | confirm: base t3/t5/t10 | confirm: blend t3/t5/t10 | confirm diff (95%) | new-hunter top-3 winners caught (confirm) |",
           "|---|---|---|---|---|---|---|"]
    for c in ("seg10", "seg3"):
        grid = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
        sc = {w: evalw(tune, c, w)[0].mean(0) for w in grid}; wbest = max(grid, key=lambda w: (sc[w][0] + sc[w][1] + sc[w][2], -w))
        B0, c0, n0 = evalw(conf, c, 0.0); B1, c1, n1 = evalw(conf, c, wbest); dP = B1 - B0
        b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {c} | {wbest} | {sc[0.0][0]:.1f}/{sc[0.0][1]:.1f}/{sc[0.0][2]:.1f} -> {sc[wbest][0]:.1f}/{sc[wbest][1]:.1f}/{sc[wbest][2]:.1f} | "
                  f"{B0[:,0].mean():.1f}/{B0[:,1].mean():.1f}/{B0[:,2].mean():.1f} | {B1[:,0].mean():.1f}/{B1[:,1].mean():.1f}/{B1[:,2].mean():.1f} | " +
                  " / ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) +
                  f" | {c0} -> {c1} of {n0} |")
        md.append(f"| {c} all w (tune days, t3/t5/t10) | " + "; ".join(f"{w}: {sc[w][0]:.1f}/{sc[w][1]:.1f}/{sc[w][2]:.1f}" for w in grid) + " | | | | | |")
    # calibration view: where do segment winners sit in the base ranking
    W_ = E[(E.dailyRank <= 3) & E.seg].copy(); W_["base_pos"] = [int((E[(E.day == d)].base > b_).sum()) + 1 for d, b_ in zip(W_.day, W_.base)]
    md += ["", f"Calibration: new-hunter top-3 winners' position in the base ranking: median {W_.base_pos.median():.0f}, "
           f"share at 4-10 {((W_.base_pos >= 4) & (W_.base_pos <= 10)).mean():.1%}, share beyond 10 {(W_.base_pos > 10).mean():.1%} (n {len(W_)})"]
    open(os.path.join(HERE, "results", "segment_newhunter.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1])
