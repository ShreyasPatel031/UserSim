"""Meaning-based text vectors (bge-small, runs locally, free) for launches and people.
Launch: name. tagline. description.
Person: headline, bio, and products they use (Stacks) / reviewed, counting only stacks/reviews dated before 2026-03-01
        so nothing written after a test launch leaks in.
Output: data/emb.npz with launch_ids, launch (n x 384), people, person (m x 384); all unit length."""
import ast, glob, gzip, json, os
import numpy as np
from sentence_transformers import SentenceTransformer

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CUT = "2026-03-01"


def lit(x):
    return x if isinstance(x, list) else (ast.literal_eval(x) if x else [])


def main():
    lid, ltxt = [], []
    for f in sorted(glob.glob(f"{D}/days/2026-*.json")):
        for p in json.load(open(f)):
            lid.append(p["id"]); ltxt.append(f"{p['name']}. {p['tagline']}. {(p.get('description') or '')[:600]}")
    used = {}
    for fn in (f"{D}/ph_tabs_rest.jsonl.gz", f"{D}/profile_tabs.jsonl.gz"):
        if os.path.exists(fn):
            for l in gzip.open(fn, "rt"):
                t = json.loads(l)
                names = [s.get("name") or s.get("slug") for s in lit(t.get("stacks")) if (s.get("added") or "9")[:10] < CUT]
                names += [r.get("product_slug") for r in lit(t.get("reviews")) if (r.get("created") or "9")[:10] < CUT]
                used[t["username"]] = [n for n in names if n][:30]
    pid, ptxt = [], []
    for fn in (f"{D}/ph_profiles2.jsonl.gz", f"{D}/ph_profiles_rest.jsonl.gz"):
        for l in gzip.open(fn, "rt"):
            p = json.loads(l)
            parts = [x for x in (p.get("headline"), p.get("about")) if x and x != "None"]
            if used.get(p["username"]):
                parts.append("Uses: " + ", ".join(used[p["username"]]))
            if parts:
                pid.append(p["username"]); ptxt.append(" | ".join(parts)[:800])
    print("launches", len(lid), "people with text", len(pid), flush=True)
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    E = lambda x: m.encode(x, batch_size=64, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
    np.savez(f"{D}/emb.npz", launch_ids=np.array(lid), launch=E(ltxt), people=np.array(pid), person=E(ptxt))


if __name__ == "__main__":
    main()
