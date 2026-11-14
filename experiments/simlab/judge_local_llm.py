"""Local judge-like models vs stored strict-judge labels (orchestrator 15:04Z Nov 14; no API calls). Items and comments as proxy_scorer.py.
Per item, candidate comment sentences = the 20 with the highest bge-small cosine to the item; scores = max over them of
  nli: cross-encoder/nli-deberta-v3-small entailment probability (premise = comment sentence, hypothesis = item)
  rerank: BAAI/bge-reranker-base relevance
  llm: Qwen/Qwen2.5-0.5B-Instruct P("yes") to "Do these comments raise the same point as the item?" (top-8 sentences in one prompt), on a
       random subsample of LLM_N items (CPU time).
Gate: item AUC >= 0.80; launch-level p@3 correlation; arm and thin/non-thin ordering.   python judge_local.py <rr cache json> <out dir>"""

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

import time
from sklearn.metrics import roc_auc_score
T = {}
cand = []
for i, r in D.iterrows():
    S = ES[r.key]
    cand.append([] if len(S) == 0 else [SENT[r.key][j] for j in np.argsort(-(S @ EI[i]))[:20]])
D["cand"] = cand
FE = []
res = {'items': len(D)}
LN = int(os.environ.get("LLM_N", "300"))
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    tk = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct"); lm = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct", torch_dtype=torch.float32); lm.eval()
    yes, no = tk.encode("yes", add_special_tokens=False)[0], tk.encode("no", add_special_tokens=False)[0]
    sub = D.sample(min(LN, len(D)), random_state=0).index; t0 = time.time(); sc = {}
    for i in sub:
        r = D.loc[i]; com = "\n".join(f"- {c}" for c in r.cand[:8]) or "- (none)"
        msg = [{"role": "user", "content": f"Real user comments on a product launch:\n{com}\n\nPredicted point: {r['item']}\n\nDoes at least one comment raise the same specific point as the predicted point? Answer yes or no."}]
        enc = tk.apply_chat_template(msg, add_generation_prompt=True, return_tensors="pt", return_dict=True); ids = enc["input_ids"]
        with torch.no_grad(): lg = lm(ids).logits[0, -1]
        sc[i] = float(torch.softmax(lg[[yes, no]], 0)[0])
    D["llm"] = pd.Series(sc); T["qwen2.5-0.5b (subsample)"] = [round(time.time() - t0, 1), len(sub)]
    s_ = D.loc[sub]; res["item AUC on LLM subsample"] = {f: round(float(roc_auc_score(s_.y, s_[f])), 3) for f in FE + ["llm"]}; res["llm subsample n"] = len(sub)
except Exception as ex: print("llm failed", str(ex)[:300], flush=True)
res["llm item AUC (subsample)"] = round(float(roc_auc_score(D.loc[sub].y, D.loc[sub].llm)), 3); res["timing"] = T
res["bge cos_rel AUC on same subsample (from proxy_items)"] = None
json.dump(res, open(os.path.join(OUT, "judge_local_llm.json"), "w"), indent=1, default=str); print(json.dumps(res, default=str))
