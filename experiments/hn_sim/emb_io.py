"""Title embeddings as a compact array: <cache>/title_emb.npy (float16, unit length, memory-mapped) and
title_emb_ids.npy (post ids), converted once from embed.py's parquet in batches (lists of floats in pandas take ~3x
the memory).

    python emb_io.py            # convert
"""
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import top100 as H

NPY = os.path.join(H.CACHE, "title_emb.npy")
IDS = os.path.join(H.CACHE, "title_emb_ids.npy")


def convert():
    f = pq.ParquetFile(os.path.join(H.CACHE, "title_emb.parquet"))
    n = f.metadata.num_rows
    out = np.lib.format.open_memmap(NPY, mode="w+", dtype=np.float16, shape=(n, 768))
    ids, i = np.zeros(n, np.int64), 0
    for b in f.iter_batches(batch_size=20000, columns=["post_id", "emb"]):
        e = np.array(b.column("emb").flatten().to_numpy(), np.float32).reshape(-1, 768)
        e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-9
        out[i:i + len(e)] = e.astype(np.float16)
        ids[i:i + len(e)] = b.column("post_id").to_numpy()
        i += len(e)
    out.flush()
    np.save(IDS, ids)
    print("saved", NPY, out.shape, flush=True)


def load():
    """(embeddings float16 memmap, Series post_id -> row)."""
    ids = np.load(IDS)
    return np.load(NPY, mmap_mode="r"), pd.Series(np.arange(len(ids)), index=ids)


if __name__ == "__main__":
    convert()
