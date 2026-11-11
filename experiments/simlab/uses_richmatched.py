"""Rich-text-matched re-evaluation of uses v2 (fixes the S1 artifact found 07:05Z Nov 11: API products_info text exists for
74.5% of held-out items but 28% of pop-matched negatives). Same held-out items and profiles as the v2 sets; negatives
re-drawn (seed 1) from the same pool-popularity decile AND the same rich-text status as the held-out item, excluding the
person's own lists. Scores: S0 card text bge-small, S1 rich text bge-small, S2 rich text bge-base (when present); mean of
top-5 cosine to the profile. Paired by person.
    python uses_richmatched.py <uses2 dir>"""
import json, os, sys, numpy as np, pandas as pd
D = sys.argv[1]; rng = np.random.default_rng(1)
P = pd.read_parquet(D + "/export/products.parquet"); ix = {s: i for i, s in enumerate(P.slug)}
rich = (P.rich_text != P.text).to_numpy(); dec = P.pop_decile.to_numpy(); pop = P["pop"].to_numpy()
T = pd.read_parquet(D + "/export/eval_sets.parquet"); PE = pd.read_parquet(D + "/export/people.parquet").set_index("person_id")
mine = {p: {ix[s] for k in ("stack", "review", "collection", "upvote") for s in r[k] if s in ix} for p, r in PE.iterrows()}
pools = {(d, rr): np.where((dec == d) & (rich == rr))[0] for d in range(10) for rr in (False, True)}
allpool = {rr: np.where(rich == rr)[0] for rr in (False, True)}
rows = []
for r in T.drop_duplicates(["task"]).itertuples():
    tg = ix[r.heldout]; own = mine[r.person_id]
    pool = pools[(dec[tg], rich[tg])] if r.neg_kind == "pop_matched" else allpool[rich[tg]]
    pick = rng.choice(pool, min(400, len(pool)), replace=False); negs = [i for i in pick if i not in own and i != tg][:50]
    if len(negs) >= 20:
        rows.append({"task": r.task, "person_id": r.person_id, "heldout": r.heldout, "type": r.type, "neg_kind": r.neg_kind, "heldout_rich": bool(rich[tg]),
                     "negatives": [P.slug[i] for i in negs], "profile": list(r.profile)})
R = pd.DataFrame(rows); R.to_parquet(D + "/export/eval_sets_richmatched.parquet", index=False)
embs = {"S0": D + "/emb_small_card.npy", "S1": D + "/emb_small_rich.npy", "S2": D + "/emb_base_rich.npy"}
E = {k: np.load(f) for k, f in embs.items() if os.path.exists(f)}
out = []
for r in R.itertuples():
    cand = np.array([ix[r.heldout]] + [ix[s] for s in r.negatives]); prof = np.array([ix[s] for s in r.profile])
    rec = {"person": r.person_id, "kind": r.neg_kind, "type": r.type, "hr": r.heldout_rich}
    for nm, M in E.items():
        S = M[cand] @ M[prof].T; k = min(5, S.shape[1]); v = np.sort(S, 1)[:, -k:].mean(1) + rng.random(len(cand)) * 1e-9
        a = int((v[1:] > v[0]).sum()); rec[nm + "_auc"] = float((v[1:] < v[0]).mean()); rec[nm + "_h10"] = float(a + 1 <= 10)
    v = pop[cand] - np.array([c in mine[r.person_id] for c in cand]) + rng.random(len(cand)) * 1e-6
    rec["pop_auc"] = float((v[1:] < v[0]).mean()); rec["pop_h10"] = float(int((v[1:] > v[0]).sum()) + 1 <= 10)
    out.append(rec)
O = pd.DataFrame(out)
def boot(v, B=2000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]
res = {"tasks": int(len(R)), "steps": list(E)}
for kind in ("pop_matched", "random"):
    for sub, m in (("all", O.kind == kind), ("heldout rich", (O.kind == kind) & O.hr), ("heldout card-only", (O.kind == kind) & ~O.hr)):
        g = O[m].groupby("person").mean(numeric_only=True); x = {c: boot(g[c]) for c in g.columns if c.endswith(("auc", "h10"))}
        for s in E:
            if s != "S0": x[f"{s}-S0 auc (paired)"] = boot(g[s + "_auc"] - g["S0_auc"]); x[f"{s}-S0 h10 (paired)"] = boot(g[s + "_h10"] - g["S0_h10"])
        res[f"{kind} | {sub}"] = x
json.dump(res, open(D + "/uses_richmatched.json", "w"), indent=1); print(json.dumps(res, indent=1))
