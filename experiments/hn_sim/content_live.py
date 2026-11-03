"""Content model score for live posts (content_ft.py deploy_base: ModernBERT-base trained on every post up to
2026-10-14), on CPU. Returned as a percentile against a fixed reference (the deploy model's scores on a 5,000-post sample of Sep 1 - Oct 14
posts), so it is on the same scale as the training input of the odds tool (the cut-Jun-30 model's out-of-sample score
as a percentile within Jul 1 - Oct 14).

    python content_live.py ref      # once: reference distribution (5,000 posts on CPU), uploads content_ref.npy
"""
import os
import sys

import numpy as np
import pandas as pd

import content_ft as CF
import store as S
import top100 as H

SIZE = os.environ.get("CONTENT_MODEL", "base")       # "large": ModernBERT-large deploy model (CPU: 160 posts in 84 s on 2 vCPU)
DIR = os.path.join(H.CACHE, f"content_model_deploy_{SIZE}")
REF = os.path.join(H.CACHE, "content_ref.npy" if SIZE == "base" else f"content_ref_{SIZE}.npy")
PRE = "" if SIZE == "base" else f"{SIZE}_"
_M = {}


def text(rows):
    dom = rows.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]
    body = rows.text.fillna("").map(CF.clean).str[:400]
    return (rows.title.fillna("") + " [" + dom.where(dom != "", "self") + "] " + body).tolist()


def _load():
    if "m" not in _M:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        if not os.path.exists(os.path.join(DIR, "config.json")):
            os.makedirs(DIR, exist_ok=True)
            for x in S._bucket().list_blobs(prefix=CF.PFX + f"model_deploy_{SIZE}/"):
                x.download_to_filename(os.path.join(DIR, x.name.split("/")[-1]))
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        _M["tok"] = AutoTokenizer.from_pretrained(DIR)
        _M["m"] = AutoModelForSequenceClassification.from_pretrained(DIR).eval()
    return _M["tok"], _M["m"]


def logits(rows, bs=64):
    import torch
    tok, m = _load()
    X = text(rows.reset_index(drop=True))
    out = np.zeros(len(X), np.float32)
    with torch.no_grad():
        for i in range(0, len(X), bs):
            enc = tok(X[i:i + bs], truncation=True, max_length=128, padding=True, return_tensors="pt")
            out[i:i + bs] = m(**enc).logits.squeeze(-1).numpy()
    return out


def ref():
    if not os.path.exists(REF):
        x = S._bucket().get_blob(CF.PFX + os.path.basename(REF))
        if x is None:
            raise FileNotFoundError("content_ref.npy: run python content_live.py ref")
        x.download_to_filename(REF)
    return np.load(REF)


def pct(rows):
    """Percentile of each post's content score against the reference (0..1)."""
    R = ref()
    return np.searchsorted(R, logits(rows)) / len(R)


def build_ref():
    p = H.stories()
    q = p[(p.day >= "2026-09-01") & (p.day <= "2026-10-14")]
    q = q.sample(min(5000, len(q)), random_state=0).reset_index(drop=True)      # a percentile map needs no more (CPU)
    s = np.sort(logits(q))
    np.save(REF, s)
    S._bucket().blob(CF.PFX + "content_ref.npy").upload_from_filename(REF)
    print(f"reference: {len(s)} posts, median logit {np.median(s):.3f}", flush=True)


def train_pct(post_ids):
    """Training input for the odds tool: the cut-Jun-30 model's out-of-sample score, as a percentile within Jul 1 -
    Oct 14 (content_ft.py gate downloads content_scores_jun30.parquet)."""
    f = os.path.join(H.CACHE, f"content_scores_{PRE}jun30.parquet")
    if not os.path.exists(f):
        S._bucket().get_blob(CF.PFX + f"scores_{PRE}jun30.parquet").download_to_filename(f)
    sc = pd.read_parquet(f).drop_duplicates("post_id")
    R = np.sort(sc.s.to_numpy())
    v = pd.Series(post_ids).map(sc.set_index("post_id").s).to_numpy(float)
    return np.where(np.isnan(v), np.nan, np.searchsorted(R, np.nan_to_num(v)) / len(R))


if __name__ == "__main__" and sys.argv[1:] == ["ref"]:
    build_ref()
