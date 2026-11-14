"""Per-item confidence for the simulator's concerns / questions (orchestrator 14:39Z Nov 14; no calls). Stored strict gemini-2.5-pro labels
(retrieval_rep cache, adj3: arms b20 and c = deployed ranked(); pasted path). Candidate pool per launch = b20's 3 + deployed's 3 items.
Features (all known at prediction time): arm, item rank, s1 (nearest-neighbour cosine), description words, item length, genericness (max
bge-small cosine to the constant list), cross-method agreement (max cosine to the other arm's items), within-arm redundancy.
Model: logistic regression, leave-one-launch-day-out. Reports AUC, reliability by decile, and p@3 / hit@3 of "top 3 of the 6 by confidence"
vs the current recipe (concerns: b20; questions: b20 1-2 + deployed 1), paired launch bootstrap. Writes the frozen coefficients
(fit on all) for the forward file.   python sim_confidence.py <rr cache json> <out dir>"""
import json, os, sys, re
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse as W
CF, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); C = json.load(open(CF)); rng = np.random.default_rng(0)
CONST = {"RC": ["Pricing is unclear or too high.", "How is this different from existing alternatives?", "Concerns about data privacy and security."],
         "RQ": ["How much does it cost?", "How is this different from existing alternatives?", "Is there an API or integrations?"]}
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
DAY = {**dict(zip(L.id, L.day)), **dict(zip(L.slug.astype(str), L.day))}
from sentence_transformers import SentenceTransformer
M = SentenceTransformer("BAAI/bge-small-en-v1.5", revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", device="cpu")
emb = lambda xs: M.encode(list(xs), normalize_embeddings=True, show_progress_bar=False)
res, FROZEN = {}, {}
for pre in ("RC", "RQ"):
    rows = []
    for k in [k for k in C if k.startswith("meta|")]:
        key = k[5:]; a = C.get(f"adj3|{pre}|{key}"); Ls = C.get(f"lists|{key}") or {}
        if not a or "ph|b20" not in a or "ph|c" not in a: continue
        day = DAY.get(key.split("|", 1)[1]); m = C[k]
        for arm, ak in (("b20", "ph|b20"), ("dep", "ph|c")):
            items = (Ls.get(f"{pre}|{ak}") or [])[:3]; lab = a[ak]["lab"][:3]
            for r, (it, y) in enumerate(zip(items, lab)):
                rows.append({"key": key, "day": day, "arm": arm, "rank": r + 1, "item": it, "y": int(y), "s1": m.get("sim1|ph"), "words": m.get("words") or 0})
    D = pd.DataFrame(rows); E = emb(D.item); EC = emb(CONST[pre])
    D["gen"] = (E @ EC.T).max(1); D["ilen"] = np.log1p(D.item.str.len())
    agree, redun = [], []
    for i, r in D.iterrows():
        g = D.index[(D.key == r.key)]; oth = [j for j in g if D.arm[j] != r.arm]; same = [j for j in g if D.arm[j] == r.arm and j != i]
        agree.append(float((E[oth] @ E[i]).max()) if oth else 0.0); redun.append(float((E[same] @ E[i]).max()) if same else 0.0)
    D["agree"], D["redun"] = agree, redun
    D["is_b20"] = (D.arm == "b20").astype(float); D["thin"] = (D.s1 < 0.898).astype(float); D["lwords"] = np.log1p(D.words)
    FE = ["is_b20", "rank", "s1", "thin", "lwords", "ilen", "gen", "agree", "redun"]
    D["p"] = np.nan
    for d in D.day.unique():   # leave-one-launch-day-out
        tr, te = D.day != d, D.day == d
        mdl = LogisticRegression(C=1.0, max_iter=2000).fit(D.loc[tr, FE], D.loc[tr, "y"]); D.loc[te, "p"] = mdl.predict_proba(D.loc[te, FE])[:, 1]
    auc = roc_auc_score(D.y, D.p); bs = []
    for _ in range(1000):
        ks = rng.choice(D.key.unique(), D.key.nunique()); S = pd.concat([D[D.key == k_] for k_ in ks[:200]]) if False else None
    D["dec"] = pd.qcut(D.p, 10, labels=False, duplicates="drop"); rel = D.groupby("dec").agg(stated=("p", "mean"), actual=("y", "mean"), n=("y", "size")).round(3).values.tolist()
    # selection: top 3 of the 6 by confidence vs the current recipe
    sel, cur = [], []
    for k_, g in D.groupby("key"):
        top = g.sort_values("p", ascending=False).head(3); sel.append([top.y.mean() * 100, 100.0 * top.y.any()])
        c = g[g.arm == "b20"].sort_values("rank").head(3) if pre == "RC" else pd.concat([g[g.arm == "b20"].sort_values("rank").head(2), g[g.arm == "dep"].sort_values("rank").head(1)])
        cur.append([c.y.mean() * 100, 100.0 * c.y.any()])
    S, Cu = np.array(sel), np.array(cur); dd = S - Cu; bb = np.array([dd[rng.integers(0, len(dd), len(dd))].mean(0) for _ in range(4000)])
    ci = lambda k: [round(dd[:, k].mean(), 1), round(np.percentile(bb[:, k], 2.5), 1), round(np.percentile(bb[:, k], 97.5), 1)]
    full = LogisticRegression(C=1.0, max_iter=2000).fit(D[FE], D.y)
    FROZEN[pre] = {"features": FE, "coef": dict(zip(FE, np.round(full.coef_[0], 4).tolist())), "intercept": round(float(full.intercept_[0]), 4),
                   "const_list": CONST[pre], "embedding": "BAAI/bge-small-en-v1.5@5c38ec7c (cosines)"}
    res[pre] = {"items": len(D), "launches": int(D.key.nunique()), "base rate": round(float(D.y.mean()), 3), "AUC (LODO)": round(float(auc), 3),
                "reliability (stated, actual, n) by decile": rel, "p@3 current recipe": round(Cu[:, 0].mean(), 1), "p@3 top-3-by-confidence": round(S[:, 0].mean(), 1),
                "top3-by-confidence - current: p@3 [95%]": ci(0), "hit@3 [95%]": ci(1), "coef (fit on all)": FROZEN[pre]["coef"]}
json.dump(res, open(os.path.join(OUT, "sim_confidence.json"), "w"), indent=1); json.dump(FROZEN, open(os.path.join(OUT, "frozen_sim_confidence.json"), "w"), indent=1)
print(json.dumps(res))
