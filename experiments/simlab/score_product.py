"""Score an arbitrary product text against the complete-people uses profiles (for the website "try a product URL" page).
Bundle (gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/website/person_bundle.npz, built by --build):
  item_emb   float16 [n_items, 768]  bge-base-en-v1.5 embeddings (normalised) of every product in any person's uses lists
  item_ptr   int64 [n_people + 1]     CSR pointers: person i's uses items are item_emb[item_ptr[i]:item_ptr[i+1]]
  roles      uint8 [n_people, 9]      role flags from headline/bio keywords (ROLE_NAMES); the text itself is NOT in the bundle
  n_uses     int32 [n_people]         number of uses items (activity tier)
  pct99      float32 [n_people]       the person's 99th-percentile score over 3,000 reference products ("likely user" threshold)
No handles, names, salted ids, bios or product lists are in the bundle; rows are anonymous.
Scorer: S2 of uses_v2 (mean of the top-5 cosine similarities between the product and the person's uses items); person-level
AUC 0.636 popularity-matched (taste only), see reports/uses_v2. "Likely user" = the product falls in the person's top
percentile of the reference products (thresholds per person in pct99). Population validation: reports/uses_population.
Usage:
    python score_product.py --build <uses2 dir> <out.npz>           (one-off, done by E5)
    python score_product.py --build-small <uses2 dir> <out.npz>     (bge-small variant, ~35 MB, for small serverless hosts)
    python score_product.py <bundle.npz> "Name. Tagline. Description"
Runtime: ~0.3 s to embed one product on CPU (bge-base), ~20 ms to score all 5,096 people.
"""
import json, os, sys
import numpy as np

ROLE_NAMES = ["dev", "design", "market", "founder", "product", "data_ai", "sales", "student", "invest"]


def _build(D, out, emb="emb_base_rich.npy", model="BAAI/bge-base-en-v1.5"):
    import re, pandas as pd
    ROLES = {"dev": r"develop|engineer|programm|coder|software|full.?stack|backend|frontend|devops|\bcto\b",
             "design": r"design|\bux\b|\bui\b|creative|artist", "market": r"market|growth|seo|content|brand|social media",
             "founder": r"founder|\bceo\b|entrepreneur|indie ?hacker|maker|builder|bootstrap", "product": r"product manager|\bpm\b|product lead|head of product",
             "data_ai": r"\bai\b|machine learning|\bml\b|data scien|llm|research", "sales": r"sales|\bbd\b|business develop|revenue",
             "student": r"student|universit|college|learning", "invest": r"invest|\bvc\b|angel|partner at"}
    P = pd.read_parquet(os.path.join(D, "export", "products.parquet")); Pe = pd.read_parquet(os.path.join(D, "export", "people.parquet"))
    E = np.load(os.path.join(D, emb)).astype(np.float32); pix = {s: i for i, s in enumerate(P.slug)}
    order = np.random.default_rng(0).permutation(len(Pe))                    # anonymous row order
    items, ptr, roles, nu = [], [0], [], []
    for i in order:
        r = Pe.iloc[i]; u = sorted({pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix})
        items += u; ptr.append(len(items)); nu.append(len(u))
        roles.append([int(bool(re.search(p, r.headline_bio or "", re.I))) for p in ROLES.values()])
    IE = E[np.array(items)]
    ref = E[np.random.default_rng(1).choice(len(E), 3000, replace=False)]   # reference products for per-person percentiles
    pct99 = np.zeros(len(order), np.float32)
    for j in range(len(order)):
        S = ref @ IE[ptr[j]:ptr[j + 1]].T
        if S.shape[1] == 0: continue
        k = min(5, S.shape[1]); sc = np.sort(S, 1)[:, -k:].mean(1); pct99[j] = np.percentile(sc, 99)
    np.savez_compressed(out, item_emb=IE.astype(np.float16), item_ptr=np.array(ptr), roles=np.array(roles, np.uint8),
                        n_uses=np.array(nu, np.int32), pct99=pct99, role_names=np.array(ROLE_NAMES), model=np.array(model))
    print("bundle", out, IE.shape, len(order))


def score(bundle, text):
    from sentence_transformers import SentenceTransformer
    z = np.load(bundle); IE = z["item_emb"].astype(np.float32); ptr = z["item_ptr"]
    q = SentenceTransformer(str(z["model"]) if "model" in z else "BAAI/bge-base-en-v1.5", device="cpu").encode([text], normalize_embeddings=True)[0]
    s = IE @ q; out = np.zeros(len(ptr) - 1, np.float32)
    for j in range(len(out)):
        v = s[ptr[j]:ptr[j + 1]]
        if len(v): out[j] = np.sort(v)[-5:].mean()
    likely = out >= z["pct99"]
    roles = z["roles"]; names = list(z["role_names"])
    seg = {n: {"people": int(roles[:, k].sum()), "likely_share": round(float(likely[roles[:, k] == 1].mean()), 4) if roles[:, k].sum() else None}
           for k, n in enumerate(names)}
    base = float(likely.mean())
    for n in seg: seg[n]["lift"] = round(seg[n]["likely_share"] / base, 2) if seg[n]["likely_share"] is not None and base > 0 else None
    return {"people": int(len(out)), "likely_users": int(likely.sum()), "likely_share": round(base, 4), "segments": seg,
            "activity_tiers": {t: round(float(likely[m].mean()), 4) for t, m in (("1-3 uses", z["n_uses"] <= 3), ("4-10", (z["n_uses"] > 3) & (z["n_uses"] <= 10)), ("11+", z["n_uses"] > 10)) if m.any()}}


if __name__ == "__main__":
    if sys.argv[1] == "--build": _build(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--build-small": _build(sys.argv[2], sys.argv[3], "emb_small_rich.npy", "BAAI/bge-small-en-v1.5")
    else: print(json.dumps(score(sys.argv[1], sys.argv[2]), indent=1))
