"""Judge-free proxy for "this predicted item is raised in the launch's comments" (orchestrator 14:45Z Nov 14; no calls). Truth = stored strict
gemini-2.5-pro labels (retrieval_rep cache, adj3, pasted path: arms b20 / c = deployed / d = constant), 3 items per arm per launch.
Comments = warehouse comments table (launch id, or slug stem), split into sentences (> 15 chars).
Scores per item: bge-small (pinned) max cosine to own comment sentences, mean of top-3, the same minus the mean over 10 other launches' sentence
sets (shuffled baseline), lexical overlap (max token Jaccard); optional cross-encoder (ms-marco MiniLM) max score.
Evaluation: item AUC of each score; a logistic combination fitted leave-one-launch-day-out; launch-level proxy p@3 (share of items above a
LODO-fitted threshold) vs judged p@3: Pearson / Spearman across launches; recipe ordering (b20 vs deployed vs constant; thin vs non-thin);
AUC by comment-volume bin.    python proxy_scorer.py <rr cache json> <out dir>"""
import json, os, re, sys
import numpy as np, pandas as pd, duckdb
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse as W
CF, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); C = json.load(open(CF)); rng = np.random.default_rng(0)
cm = duckdb.connect().execute(f"select launch_id, slug, text from read_parquet('{os.path.expanduser('~/.usersim_sim/comments/*.parquet')}', union_by_name=true)").df()
cm["launch_id"] = cm.launch_id.astype(str); cm["stem"] = cm.slug.astype(str).str.replace(r"-\d+$", "", regex=True)
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
DAY = {**dict(zip(L.id, L.day)), **dict(zip(L.slug.astype(str), L.day))}
def sents(txts):
    out = []
    for t in txts:
        for s in re.split(r"(?<=[.!?])\s+|\n+", str(t)):
            s = s.strip()
            if len(s) > 15: out.append(s[:400])
    return out
rows, SENT = [], {}
for k in [k[5:] for k in C if k.startswith("meta|")]:
    kid = k.split("|", 1)[1]; g = cm[(cm.launch_id == kid)] if k.startswith("F|") else cm[cm.stem == kid]
    if g.empty: continue
    SENT[k] = sents(g.text.tolist()); Ls = C.get(f"lists|{k}") or {}; m = C.get(f"meta|{k}") or {}
    for pre in ("RC", "RQ"):
        a = C.get(f"adj3|{pre}|{k}")
        if not a: continue
        for arm, ak in (("b20", "ph|b20"), ("dep", "ph|c"), ("const", "ph|d")):
            if ak not in a: continue
            for r, (it, y) in enumerate(zip((Ls.get(f"{pre}|{ak}") or [])[:3], a[ak]["lab"][:3])):
                rows.append({"key": k, "day": DAY.get(kid), "pre": pre, "arm": arm, "rank": r + 1, "item": it, "y": int(y), "s1": m.get("sim1|ph"), "n_comments": len(g)})
D = pd.DataFrame(rows); print(json.dumps({"items": len(D), "launches": int(D.key.nunique())}), flush=True)
from sentence_transformers import SentenceTransformer
M = SentenceTransformer("BAAI/bge-small-en-v1.5", revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", device="cpu")
EI = M.encode(D.item.tolist(), normalize_embeddings=True, show_progress_bar=False, batch_size=64)
ES = {k: M.encode(v, normalize_embeddings=True, show_progress_bar=False, batch_size=64) if v else np.zeros((0, 384), np.float32) for k, v in SENT.items()}
keys = list(SENT); tok = lambda s: set(re.findall(r"[a-z]{3,}", s.lower()))
f_max, f_top3, f_rel, f_lex = [], [], [], []
for i, r in D.iterrows():
    S = ES[r.key]; e = EI[i]
    if len(S) == 0: f_max.append(0.0); f_top3.append(0.0); f_rel.append(0.0); f_lex.append(0.0); continue
    c = S @ e; f_max.append(float(c.max())); f_top3.append(float(np.sort(c)[-3:].mean()))
    oth = [k for k in rng.choice(keys, 12, replace=False) if k != r.key][:10]
    f_rel.append(float(c.max() - np.mean([(ES[o] @ e).max() for o in oth if len(ES[o])])))
    ti = tok(r["item"]); f_lex.append(max((len(ti & tok(s)) / max(len(ti | tok(s)), 1) for s in SENT[r.key]), default=0.0))
D["cos_max"], D["cos_top3"], D["cos_rel"], D["lex"] = f_max, f_top3, f_rel, f_lex
try:
    from sentence_transformers import CrossEncoder
    CE = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu"); ce = []
    for i, r in D.iterrows():
        ss = SENT[r.key][:150]; ce.append(float(CE.predict([(r["item"], s) for s in ss]).max()) if ss else -10.0)
    D["ce_max"] = ce
except Exception as ex:
    print("cross-encoder unavailable:", str(ex)[:120], flush=True)
FE = [c for c in ("cos_max", "cos_top3", "cos_rel", "lex", "ce_max") if c in D]
res = {"items": len(D), "launches": int(D.key.nunique()), "judge base rate": round(float(D.y.mean()), 3),
       "item AUC per score": {f: round(float(roc_auc_score(D.y, D[f])), 3) for f in FE}}
D["p"] = np.nan; D["thr_hit"] = np.nan
for d in D.day.unique():
    tr, te = D.day != d, D.day == d
    mdl = LogisticRegression(max_iter=2000).fit(D.loc[tr, FE], D.loc[tr, "y"]); D.loc[te, "p"] = mdl.predict_proba(D.loc[te, FE])[:, 1]
    ptr = mdl.predict_proba(D.loc[tr, FE])[:, 1]; thr = np.quantile(ptr, 1 - D.loc[tr, "y"].mean())   # threshold matching the training base rate
    D.loc[te, "thr_hit"] = (D.loc[te, "p"] >= thr).astype(float)
res["item AUC, LODO logistic of all scores"] = round(float(roc_auc_score(D.y, D.p)), 3)
res["item AUC by kind"] = {pre: round(float(roc_auc_score(g.y, g.p)), 3) for pre, g in D.groupby("pre")}
G = D.groupby(["key", "pre", "arm"]).agg(judged=("y", "mean"), proxy=("thr_hit", "mean"), proxy_p=("p", "mean"), n=("n_comments", "first"), s1=("s1", "first")).reset_index()
res["launch-level p@3 proxy vs judged"] = {"pearson (thresholded)": round(float(pearsonr(G.judged, G.proxy)[0]), 3), "pearson (mean prob)": round(float(pearsonr(G.judged, G.proxy_p)[0]), 3),
                                           "spearman (mean prob)": round(float(spearmanr(G.judged, G.proxy_p).correlation), 3), "n launch-arm-kind cells": len(G)}
order = {}
for pre, g in G.groupby("pre"):
    order[pre] = {"judged p@3 by arm": g.groupby("arm").judged.mean().mul(100).round(1).to_dict(), "proxy p@3 by arm": g.groupby("arm").proxy.mean().mul(100).round(1).to_dict(),
                  "judged by thin": g[g.arm == "b20"].groupby(g.s1 < 0.898).judged.mean().mul(100).round(1).to_dict(), "proxy by thin": g[g.arm == "b20"].groupby(g.s1 < 0.898).proxy.mean().mul(100).round(1).to_dict()}
res["recipe ordering"] = order
D["nbin"] = pd.cut(D.n_comments, [0, 4, 9, 19, 39, 10 ** 6], labels=["<5", "5-9", "10-19", "20-39", "40+"])
res["item AUC by comment volume"] = {str(b): [round(float(roc_auc_score(g.y, g.p)), 3) if g.y.nunique() > 1 else None, len(g), int(g.key.nunique())] for b, g in D.groupby("nbin", observed=True)}
D.drop(columns=["item"]).to_parquet(os.path.join(OUT, "proxy_items.parquet")); json.dump(res, open(os.path.join(OUT, "proxy_scorer.json"), "w"), indent=1)
print(json.dumps(res))
