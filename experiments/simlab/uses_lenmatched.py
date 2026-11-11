"""Uses v2, length-controlled (orchestrator 07:12Z Nov 11: text length alone scores pop-matched AUC ~0.64-0.67).
Negatives re-drawn (seed 3) matched on pool-popularity decile x rich-text status x text-length decile of the S1 input text
(rich_text where present, else card text), excluding the person's own lists. Same held-out items and profiles.
Scorers: LEN (text length alone), POP, S0 (card, bge-small), S1 (rich, bge-small), S2 (rich, bge-base);
and SHUFFLED-PROFILE controls S1sh / S2sh: the same candidates scored against a random OTHER person's profile, which measures
how much of the score is product-level (non-personal) appeal rather than this person's taste. Personal taste = S - Ssh.
    python uses_lenmatched.py <uses2 dir>"""
import json, os, sys, numpy as np, pandas as pd
D = sys.argv[1]; rng = np.random.default_rng(3)
P = pd.read_parquet(D + "/export/products.parquet"); ix = {s: i for i, s in enumerate(P.slug)}
rich = (P.rich_text != P.text).to_numpy(); dec = P.pop_decile.to_numpy(); pop = P["pop"].to_numpy()
L = P.rich_text.str.len().to_numpy(); ldec = pd.qcut(L + rng.random(len(L)) * 1e-3, 10, labels=False)
T = pd.read_parquet(D + "/export/eval_sets.parquet").drop_duplicates("task"); PE = pd.read_parquet(D + "/export/people.parquet")
mine = {p: {ix[s] for k in ("stack", "review", "collection", "upvote") for s in r[k] if s in ix} for p, r in zip(PE.person_id, PE.to_dict("records"))}
pools = {}
for i in range(len(P)): pools.setdefault((dec[i], rich[i], ldec[i]), []).append(i)
pools = {k: np.array(v) for k, v in pools.items()}
profs = T.profile.tolist()
E = {k: np.load(D + f) for k, f in (("S0", "/emb_small_card.npy"), ("S1", "/emb_small_rich.npy"), ("S2", "/emb_base_rich.npy"))}
out = []
for r in T.itertuples():
    if r.neg_kind != "pop_matched": continue
    tg = ix[r.heldout]; own = mine[r.person_id]; pool = pools[(dec[tg], rich[tg], ldec[tg])]
    pick = rng.choice(pool, min(400, len(pool)), replace=False); negs = [i for i in pick if i not in own and i != tg][:50]
    if len(negs) < 20: continue
    cand = np.array([tg] + negs); prof = np.array([ix[s] for s in r.profile])
    other = np.array([ix[s] for s in profs[rng.integers(len(profs))]])
    rec = {"person": r.person_id, "hr": bool(rich[tg]), "type": r.type}
    def score(v, nm):
        v = v + rng.random(len(v)) * 1e-9; a = int((v[1:] > v[0]).sum())
        rec[nm + "_auc"] = float((v[1:] < v[0]).mean()); rec[nm + "_h10"] = float(a + 1 <= 10)
    score(L[cand].astype(float), "LEN"); score(pop[cand] - np.array([c in own for c in cand]), "POP")
    for nm, M in E.items():
        for tag, pr in (("", prof), ("sh", other)):
            S = M[cand] @ M[pr].T; k = min(5, S.shape[1]); score(np.sort(S, 1)[:, -k:].mean(1), nm + tag)
    out.append(rec)
O = pd.DataFrame(out)
def boot(v, B=2000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]
res = {"tasks": int(len(O))}
for sub, m in (("all", O.hr | ~O.hr), ("heldout rich", O.hr), ("heldout card-only", ~O.hr)):
    g = O[m].groupby("person").mean(numeric_only=True); x = {c: boot(g[c]) for c in g.columns if c.endswith("_auc") or c.endswith("_h10")}
    for s in ("S0", "S1", "S2"):
        x[f"{s} personal (auc - shuffled-profile auc)"] = boot(g[s + "_auc"] - g[s + "sh_auc"])
    x["S1-S0 auc"] = boot(g.S1_auc - g.S0_auc); x["S2-S0 auc"] = boot(g.S2_auc - g.S0_auc); x["S2-S1 auc"] = boot(g.S2_auc - g.S1_auc)
    x["S1 personal - S0 personal"] = boot((g.S1_auc - g.S1sh_auc) - (g.S0_auc - g.S0sh_auc))
    res[sub] = x
json.dump(res, open(D + "/uses_lenmatched.json", "w"), indent=1); print(json.dumps(res, indent=1))
