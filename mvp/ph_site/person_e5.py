"""E5's anonymous "people with similar tools" scorer (Gemini-256 embeddings + 200 boosted trees), person AUC 0.692.

Bundle: site/person_bundle_gemini_v1.npz (copy of E5's tmp/e5/website/person_bundle_gemini.npz). 5,096 people in
shuffled order with role flags and use counts only: no ids, handles, bios or product names. Per request: one
gemini-embedding-001 call (256-d, SEMANTIC_SIMILARITY), one 16k x 256 matvec, trees evaluated for all people at once.
Only role flags, a use-count tier and aggregates leave this module (E5's display rules)."""
from __future__ import annotations

import io

import numpy as np

from mvp.ph_site import gcs

_B: dict = {}
TIERS = [(1, 3, "lists 1-3 tools"), (4, 10, "lists 4-10 tools"), (11, 10**9, "lists 11+ tools")]
ROLE_TEXT = {"dev": "developer", "design": "designer", "market": "marketer", "founder": "founder", "product": "product person",
             "data_ai": "data / AI person", "sales": "sales", "student": "student", "invest": "investor"}


def bundle() -> dict:
    if not _B:
        raw = gcs.read_bytes("site/person_bundle_gemini_v1.npz", ttl=86400)
        if raw is None:
            raise RuntimeError("person bundle missing")
        z = np.load(io.BytesIO(raw), allow_pickle=False)
        _B.update({k: z[k] for k in z.files})
        _B["IE"] = _B["item_emb"].astype(np.float32)
        _B["n"] = len(_B["person_ptr"]) - 1
    return _B


async def embed(text: str) -> np.ndarray:
    """gemini-embedding-001 on Vertex, 256-d, SEMANTIC_SIMILARITY; L2-normalised here."""
    import asyncio

    import httpx
    from auth import cached_vertex_credentials, vertex_credentials
    from capability.gemini_config import gemini_location, gemini_project

    loc = gemini_location()
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{gemini_project()}/locations/{loc}/publishers/google/models/"
           "gemini-embedding-001:predict")
    body = {"instances": [{"content": text[:1200], "task_type": "SEMANTIC_SIMILARITY"}],
            "parameters": {"outputDimensionality": 256}}
    creds = cached_vertex_credentials() or await asyncio.to_thread(vertex_credentials)
    async with httpx.AsyncClient(timeout=20) as c:
        for attempt in range(3):
            r = await c.post(url, json=body, headers={"Authorization": f"Bearer {creds.token}"})
            if r.status_code in (429, 500, 503) and attempt < 2:
                await asyncio.sleep(1 + attempt)
                continue
            r.raise_for_status()
            v = np.asarray(r.json()["predictions"][0]["embeddings"]["values"], np.float32)
            return v / (np.linalg.norm(v) + 1e-9)
    raise RuntimeError("embedding failed")


def _features(B: dict, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    s = B["IE"] @ q
    ptr, idx, hi = B["person_ptr"], B["person_items"], float(B["hi"])
    n = B["n"]
    F = np.zeros((n, 5), np.float32)
    ok = np.zeros(n, bool)
    for j in range(n):
        v = s[idx[ptr[j]:ptr[j + 1]]]
        if len(v):
            vs = np.sort(v)
            ok[j] = True
            F[j] = [vs[-1], vs[-5:].mean(), v.mean(), (v > hi).mean(), np.log1p(len(v))]
    return F, ok


def _trees(B: dict, F: np.ndarray) -> np.ndarray:
    """Sum of 200 trees for every row at once (rule: x[f] <= thr -> left)."""
    feat, thr, left, right, val = B["tree_feat"], B["tree_thr"], B["tree_left"], B["tree_right"], B["tree_value"]
    rows = np.arange(len(F))
    tot = np.zeros(len(F), np.float64)
    for r in B["tree_roots"]:
        node = np.full(len(F), r, np.int64)
        for _ in range(64):
            f = feat[node]
            live = f >= 0
            if not live.any():
                break
            fl = np.where(live, f, 0)
            go_left = F[rows, fl] <= thr[node]
            nxt = np.where(go_left, left[node], right[node])
            node = np.where(live, nxt, node)
        tot += val[node]
    return tot


def score_text(B: dict, q: np.ndarray) -> np.ndarray:
    F, ok = _features(B, q)
    sc = _trees(B, F)
    sc[~ok] = -1e9
    return sc


def summarize(B: dict, score: np.ndarray, k_people: int = 8) -> dict:
    thr = B["pct99_tree"]
    likely = score >= thr
    margin = score - thr
    roles, names, nu = B["roles"], [str(x) for x in B["role_names"]], B["n_uses"]
    base = likely.mean()
    segs = []
    for k, nm in enumerate(names):
        m = roles[:, k] == 1
        nl = int((likely & m).sum())
        if nl >= 20:
            share = nl / m.sum()
            segs.append({"name": ROLE_TEXT.get(nm, nm), "size": int(m.sum()), "likely": nl, "share": round(float(share), 4),
                         "lift": round(float(share / (base + 1e-9)), 2)})
    segs.sort(key=lambda r: -r["lift"])
    tiers = []
    for lo, hi_, label in TIERS:
        m = (nu >= lo) & (nu <= hi_)
        tiers.append({"tier": label, "size": int(m.sum()), "likely": int((likely & m).sum()),
                      "share": round(float((likely & m).mean() / max(m.mean(), 1e-9)), 4)})
    # Closest people: distinct (role set, tier) combinations so the list shows different kinds of people.
    people, seen = [], set()
    for j in np.argsort(-margin)[:2000]:
        rs = tuple(names[k] for k in range(len(names)) if roles[j, k])
        tier = next(lbl for lo, hi_, lbl in TIERS if lo <= nu[j] <= hi_)
        key = (rs[:2], tier)
        if key in seen:
            continue
        seen.add(key)
        people.append({"roles": [ROLE_TEXT.get(r, r) for r in rs] or ["no stated role"], "tier": tier,
                       "likely": bool(likely[j]), "strength": "strong" if margin[j] > 0 else "moderate"})
        if len(people) == k_people:
            break
    return {"people_scored": int(B["n"]), "likely_count": int(likely.sum()), "likely_share": round(float(base), 4),
            "segments": segs, "tiers": tiers, "people": people}
