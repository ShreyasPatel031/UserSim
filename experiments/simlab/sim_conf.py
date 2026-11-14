"""Per-item confidence written next to each simulator concern / question in the forward file (frozen from sim_confidence.py; logistic, LODO
AUC 0.61 concerns / 0.62 questions, reliability by decile within a few points). conf(pre, b20_items, dep_items, s1, words) ->
(b20_confs, dep_confs). Needs bge-small (pinned); returns None lists on any failure (the forward file then carries no confidence)."""
import json, os
import numpy as np
FZ = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "sim_confidence", "frozen_sim_confidence.json")))
_M = {}
def _emb(xs):
    if "m" not in _M:
        from sentence_transformers import SentenceTransformer
        _M["m"] = SentenceTransformer("BAAI/bge-small-en-v1.5", revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", device="cpu")
    return _M["m"].encode(list(xs), normalize_embeddings=True, show_progress_bar=False)
def conf(pre, b20, dep, s1, words):
    try:
        z = FZ[pre]; b20, dep = list(b20 or [])[:3], list(dep or [])[:3]; items = [("b20", i, x) for i, x in enumerate(b20)] + [("dep", i, x) for i, x in enumerate(dep)]
        if not items: return None, None
        E = _emb([x for _, _, x in items]); EC = _emb(z["const_list"]); out = []
        for a, (arm, r, x) in enumerate(items):
            oth = [b for b, it in enumerate(items) if it[0] != arm]; same = [b for b, it in enumerate(items) if it[0] == arm and b != a]
            f = {"is_b20": float(arm == "b20"), "rank": r + 1, "s1": float(s1 if s1 is not None else 0.9), "thin": float((s1 if s1 is not None else 0.9) < 0.898),
                 "lwords": float(np.log1p(words or 0)), "ilen": float(np.log1p(len(x))), "gen": float((EC @ E[a]).max()),
                 "agree": float((E[oth] @ E[a]).max()) if oth else 0.0, "redun": float((E[same] @ E[a]).max()) if same else 0.0}
            out.append(round(float(1 / (1 + np.exp(-(z["intercept"] + sum(z["coef"][k] * f[k] for k in z["features"]))))), 3))
        return out[:len(b20)], out[len(b20):]
    except Exception:
        return None, None
