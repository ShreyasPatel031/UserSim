"""Pairwise near-tie baseline for the Decisions API pilot (orchestrator 05:34Z Nov 13). gemini-2.5-flash on Vertex, temperature 0, thinking
off, prompt pilot/prompts.json "pairwise" (00:05-safe text only). For each day: the clean model's ranks 2-8 (7 launches); all 21 pairs in
both orders (42 calls); P(A beats B) = mean of p_a and 1 - p_b' over the two orders. Re-order ranks 2-8 by (a) wins (sum of P over the 6
opponents) and (b) Bradley-Terry strengths (MM fit), rank 1 kept. Compare top 3 / top 5 overlap with the final daily rank vs the clean
order, paired day bootstrap. Sets: LIVE = Oct 26 - Nov 11 (clean_v3_nosite; th_n_pre not held) and BACK = 40 random honest_preds_v2 days
Apr - Oct (seed 0; possibly inside the model's training data).
    python pairwise_base.py <launches dir> <honest_preds_v2.parquet> <clean_nosite.parquet> <ph-website worktree> <out dir>
"""
import glob, itertools, json, os, sys, asyncio
import numpy as np, pandas as pd
LDIR, HP, CNS, WT, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; sys.path[:0] = [WT, os.path.join(WT, "src")]
from capability import gemini_config as GC  # noqa: E402
TPL = json.load(open(os.path.join(HERE, "pilot", "prompts.json")))["pairwise"]["template"]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); LD = L.set_index("id")
CN = pd.read_parquet(CNS)[["id", "day", "rank", "clean_v3_nosite"]].dropna().rename(columns={"clean_v3_nosite": "score"}); CN["id"] = CN.id.astype(str); CN = CN[(CN.day >= "2026-10-26") & (CN.day <= "2026-11-11")]
H = pd.read_parquet(HP)[["id", "day", "honest"]].rename(columns={"honest": "score"}); H["id"] = H.id.astype(str); H["rank"] = H.id.map(dict(zip(L.id, L.daily_rank))); H = H.dropna()
bd = sorted(H[(H.day >= "2026-04-01") & (H.day <= "2026-10-24")].day.unique()); BD = sorted(rng.choice(bd, 40, replace=False).tolist())
SETS = {"LIVE": CN[CN.id.isin(LD.index)], "BACK": H[H.day.isin(BD) & H.id.isin(LD.index)]}
CF = os.path.join(OUT, "cache_pair.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}; USD = {"usd": 0.0}
def txt(i):
    r = LD.loc[i]; tp = ", ".join(json.loads(r.topics)) if isinstance(r.topics, str) and r.topics.startswith("[") else ""
    return {"name": r["name"], "tagline": r.tagline or "", "topics": tp, "desc": str(r.description or "")[:600]}
async def ask(a, b, sem):
    k = f"{a}|{b}"
    if k in C: return C[k]
    if USD["usd"] > 4.0: return None
    A, B = txt(a), txt(b); pr = TPL.format(**{f"a_{x}": v for x, v in A.items()}, **{f"b_{x}": v for x, v in B.items()})
    async with sem:
        try: r = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": pr}], model="gemini-2.5-flash", temperature=0.0, thinking_budget=0, max_retries=3, max_output_tokens=60)) or {}
        except Exception: r = {}
    USD["usd"] += len(pr) / 4 * 0.30e-6 + 30 * 2.5e-6; C[k] = r; return r
def pa(r):
    if not r: return None
    p = r.get("p_a")
    if isinstance(p, (int, float)): return float(min(max(p, 0), 1))
    return 1.0 if str(r.get("winner", "")).upper() == "A" else 0.0 if str(r.get("winner", "")).upper() == "B" else None
async def day_pairs(g, sem):
    g = g.sort_values("score", ascending=False); ids = g.id.tolist()[:8]; mid = ids[1:8]; jobs = []
    for a, b in itertools.combinations(mid, 2): jobs += [ask(a, b, sem), ask(b, a, sem)]
    rs = await asyncio.gather(*jobs); P = {}
    for n, (a, b) in enumerate(itertools.combinations(mid, 2)):
        x, y = pa(rs[2 * n]), pa(rs[2 * n + 1]); v = [z for z in (x, None if y is None else 1 - y) if z is not None]
        if v: P[(a, b)] = float(np.mean(v)); P[(b, a)] = 1 - P[(a, b)]
    return g, ids, mid, P
def bt(mid, P, it=200):
    s = {i: 1.0 for i in mid}
    for _ in range(it):
        for i in mid:
            w = sum(P.get((i, j), 0.5) for j in mid if j != i); den = sum(1 / (s[i] + s[j]) for j in mid if j != i); s[i] = max(w, 1e-3) / den
        m = np.mean(list(s.values())); s = {k: v / m for k, v in s.items()}
    return s
async def main():
    sem = asyncio.Semaphore(16); out = {}
    for nm, D in SETS.items(): out[nm] = await asyncio.gather(*[day_pairs(g, sem) for _, g in D.groupby("day") if len(g) >= 10])
    json.dump(C, open(CF, "w")); return out
RES = asyncio.run(main())
def ov(order, g, k): t = g.sort_values("rank").id.tolist()[:k]; return len(set(order[:k]) & set(t)) / k * 100
res = {"design": __doc__.split("\n    python")[0], "backtest_days": BD}
for nm, rows in RES.items():
    per = {"clean": [], "wins": [], "bt": []}; acc = []
    for g, ids, mid, P in rows:
        if len(P) < 30: continue
        w = {i: sum(P.get((i, j), 0.5) for j in mid if j != i) for i in mid}; s = bt(mid, P)
        orders = {"clean": ids, "wins": [ids[0]] + sorted(mid, key=lambda i: -w[i]) + ids[8:], "bt": [ids[0]] + sorted(mid, key=lambda i: -s[i]) + ids[8:]}
        for k_, o in orders.items(): per[k_].append([ov(o, g, 3), ov(o, g, 5)])
        rk = dict(zip(g.id, g["rank"])); acc += [float((P[(a, b)] > 0.5) == (rk[a] < rk[b])) for (a, b) in P if a < b]
    o_ = {"days": len(per["clean"]), "pair_accuracy_vs_final_order": round(float(np.mean(acc)) * 100, 1) if acc else None, "clean top3/top5": np.array(per["clean"]).mean(0).round(1).tolist()}
    for k_ in ("wins", "bt"):
        d = np.array(per[k_]) - np.array(per["clean"]); bs = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(2000)])
        o_[f"{k_} - clean top3/top5"] = [[round(float(d[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(2)]
    res[nm] = o_
res["est_usd"] = round(USD["usd"], 2); json.dump(res, open(os.path.join(OUT, "pairwise_base.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k not in ("design", "backtest_days")}, default=float))
