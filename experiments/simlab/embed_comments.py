"""Meaning vectors (bge-small, local) for every comment text, for retrieving a person's most relevant past comments."""
import numpy as np, pandas as pd
from sentence_transformers import SentenceTransformer
from . import store

import os, sys
C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").reset_index(drop=True)
ONLY = sys.argv[1] if len(sys.argv) > 1 else None   # "sample": only people in the screening sample (fast)
if ONLY == "sample":
    from .variants import sample
    keep = {u for u, _ in sample()}
    C = C[C.person.isin(keep)].reset_index(drop=True)
m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
V = m.encode(C.text.tolist(), batch_size=128, normalize_embeddings=True, show_progress_bar=False).astype(np.float16)
np.save(f"{store.OUT}/comment_vecs.npy", V); C.to_parquet(f"{store.OUT}/comment_vec_text.parquet")  # rows match the vectors
print(len(C), V.shape)
