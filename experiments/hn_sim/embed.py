"""Title embeddings for HN stories (Vertex text-embedding-005, 768 dims; Gemini/Vertex only). Text = title + domain.
Stories since 2023 with a comment, 3+ points, or posted from 2026-07-01 (the forecast window). Resumable; cost is the
billable characters Vertex reports x its list price, logged to the spend table. -> <cache>/title_emb.parquet

    python embed.py
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import google.auth.transport.requests
import numpy as np
import pandas as pd
import requests

import store as S
import top100 as H
from auth import vertex_credentials

MODEL = "text-embedding-005"
USD_PER_1K_CHARS = 0.000025                 # Vertex list price for text embeddings
PROJ = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox")
URL = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJ}/locations/us-central1/publishers/google/models/{MODEL}:predict"
OUT = os.path.join(H.CACHE, "title_emb.parquet")
PART = os.path.join(H.CACHE, "title_emb_parts")


def domain(u):
    return urlsplit(u).netloc.lower().removeprefix("www.") if isinstance(u, str) and u else ""


def main():
    p = H.stories()
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["story_id"]).story_id.value_counts()
    keep = p[(p.points >= 3) | (p.day >= "2026-07-01") | p.post_id.isin(c.index)].reset_index(drop=True)
    keep["text"] = keep.title.fillna("") + " (" + keep.url.map(domain) + ")"
    os.makedirs(PART, exist_ok=True)
    done = {int(f.split(".")[0]) for f in os.listdir(PART)}
    chunks = [(i, keep.iloc[i:i + 250]) for i in range(0, len(keep), 250) if i not in done]
    print(len(keep), "stories;", len(chunks), "chunks to embed", flush=True)
    cred = vertex_credentials()
    cred.refresh(google.auth.transport.requests.Request())
    chars = [0]
    t0 = time.time()

    def one(job):
        i, df = job
        for attempt in range(5):
            try:
                if not cred.valid:
                    cred.refresh(google.auth.transport.requests.Request())
                r = requests.post(URL, headers={"Authorization": f"Bearer {cred.token}"}, timeout=120, json={
                    "instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in df.text]})
                if r.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        else:
            print("chunk", i, "failed", r.status_code, r.text[:200], flush=True)
            return 0
        pr = r.json()["predictions"]
        E = np.array([x["embeddings"]["values"] for x in pr], np.float32)
        pd.DataFrame({"post_id": df.post_id.to_numpy(), "emb": list(E)}).to_parquet(os.path.join(PART, f"{i}.parquet"))
        return int(df.text.str.len().sum())

    with ThreadPoolExecutor(4) as ex:
        for n, k in enumerate(ex.map(one, chunks)):
            chars[0] += k
            if n % 200 == 0:
                print(n, "chunks", f"{time.time() - t0:.0f}s", flush=True)
    usd = chars[0] / 1000 * USD_PER_1K_CHARS
    if chars[0]:
        S.spend("hn_sim.embed", usd, f"{MODEL}: {chars[0]} chars, {len(chunks)} requests")
    print(f"embedded {chars[0]} chars, ${usd:.3f}", flush=True)
    parts = [pd.read_parquet(os.path.join(PART, f)) for f in sorted(os.listdir(PART), key=lambda s: int(s.split(".")[0]))]
    E = pd.concat(parts, ignore_index=True)
    E.to_parquet(OUT)
    print("saved", OUT, E.shape, flush=True)


if __name__ == "__main__":
    main()
