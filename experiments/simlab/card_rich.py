"""Richer person card (orchestrator 14:36Z Nov 13). Same 300 x 5 person-day sample and fixed prompt as pilot_base.py (A), rebuilt with the
same store and seed (checked against the saved pilot_sample.json), plus a profile block from the lossless store (14:35Z): headline, bio
(first 300 chars), badge names, and up to 3 reviews the member wrote BEFORE the day (dated events). Headline / bio / badges are snapshots
from the person's pull (Nov), so on Oct 20 - Nov 10 days they are read after the day: a mild leak, flagged. gemini-2.5-flash-lite only,
temperature 0, thinking off. Scores vs popularity and vs the plain-card flash-lite result (cached): top-3 hit, ranking accuracy, paired
bootstrap over person-days. Counts only.
    python card_rich.py <old store dir (pilot_base's)> <launches dir> <salt dir> <honest_preds_v2> <clean_nosite> <ph-website worktree> <pilot out dir> <new store dir> <out dir>
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); NEW, OUTR = sys.argv[8], sys.argv[9]; os.makedirs(OUTR, exist_ok=True); sys.argv = sys.argv[:8]
PB = open(os.path.join(HERE, "pilot_base.py")).read(); exec(PB[:PB.index("async def runA():")])
saved = json.load(open(os.path.join(OUTP, "pilot_sample.json")))
same = [(a["person"], a["day"]) for a in saved["person_days"]] == [(x["p"], x["day"]) for x in PDS]; print("same sample", same, len(PDS), flush=True)
NP = pd.read_parquet(os.path.join(NEW, "persons.parquet")).set_index("person_id")
NE = pd.read_parquet(os.path.join(NEW, "events.parquet"), columns=["person_id", "kind", "ts_hi", "fetched_at", "extra"]); RV = NE[NE.kind == "review"].copy(); RV["t"] = RV.ts_hi.fillna(RV.fetched_at)
RVg = {p: g.sort_values("t", ascending=False) for p, g in RV[RV.person_id.isin({x["p"] for x in PDS})].groupby("person_id")}
def prof(p, d):
    if p not in NP.index: return ""
    r = NP.loc[p]; out = []
    if isinstance(r.headline, str) and r.headline.strip(): out.append(f"Headline: {r.headline.strip()[:150]}")
    if isinstance(r.bio, str) and r.bio.strip(): out.append(f"Bio: {' '.join(r.bio.split())[:300]}")
    try: bd = [b.get("name") for b in json.loads(r.badges_json or "[]") if b.get("name")]
    except Exception: bd = []
    if bd: out.append("Badges: " + ", ".join(bd[:8]))
    g = RVg.get(p)
    if g is not None:
        d0 = pd.Timestamp(d).tz_localize("America/Los_Angeles").tz_convert("UTC"); g = g[g.t < d0].head(3); rs = []
        for e in g.extra:
            try: j = json.loads(e) if isinstance(e, str) else {}
            except Exception: j = {}
            t = (j.get("text") or j.get("body") or j.get("review") or "")
            if t: rs.append(f'"{" ".join(str(t).split())[:200]}"' + (f" (on {j.get('product') or j.get('name')})" if (j.get("product") or j.get("name")) else ""))
        if rs: out.append("Reviews this member wrote: " + " | ".join(rs))
    return ("About this member (profile):\n" + "\n".join(out) + "\n\n") if out else ""
MARK = "This member's most recent upvotes"
for x in PDS: pf = prof(x["p"], x["day"]); x["has_prof"] = bool(pf); x["prompt_rich"] = x["prompt"].replace(MARK, pf + MARK, 1)
M = "gemini-2.5-flash-lite"
async def run():
    sem = asyncio.Semaphore(16)
    async def one(x):
        async with sem: return await call(f"AR|{M}|{x['p']}|{x['day']}", x["prompt_rich"], M, tok=40 * len(x["order"]) + 100)
    async def plain(x):
        async with sem: return await call(f"A|{M}|{x['p']}|{x['day']}", x["prompt"], M, tok=40 * len(x["order"]) + 100)
    a = await asyncio.gather(*[one(x) for x in PDS]); b = await asyncio.gather(*[plain(x) for x in PDS]); json.dump(C, open(CF, "w")); return a, b
U0 = USD["usd"]; RR, RP = asyncio.run(run())
popz = dict(zip(LU.id, LU["pop"]))
def pv(r, n):
    v = (r or {}).get("p"); return np.array([float(z) if isinstance(z, (int, float)) else 0.0 for z in v]) if isinstance(v, list) and len(v) == n else None
per = {"pop": [], "plain": [], "rich": []}; hp = []
for x, rr, rp in zip(PDS, RR, RP):
    n = len(x["order"]); S = {"pop": np.array([popz[i] for i in x["order"]]), "plain": pv(rp, n), "rich": pv(rr, n)}
    if any(v is None for v in S.values()): continue
    y = np.array([i in set(x["voted"]) for i in x["order"]]); hp.append(x["has_prof"])
    for a, s in S.items():
        o = (-s).argsort().argsort(); per[a].append((np.mean([float(o[j] < 3) for j in np.flatnonzero(y)]), np.mean([float((np.delete(s, j) < s[j]).mean()) for j in np.flatnonzero(y)])))
def bt(v):
    v = np.array(v); bs = [v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
hp = np.array(hp); res = {"same_sample_as_pilot": same, "person_days_valid": len(per["pop"]), "share_with_profile_block": round(float(hp.mean()), 3), "usd_this_run": round(USD["usd"] - U0, 3)}
for m, k in (("top3_hit", 0), ("ranking_accuracy", 1)):
    o = {a: bt([z[k] for z in per[a]]) for a in per}
    o["rich - pop"] = bt([a[k] - b[k] for a, b in zip(per["rich"], per["pop"])]); o["rich - plain"] = bt([a[k] - b[k] for a, b in zip(per["rich"], per["plain"])])
    o["rich - plain, person-days with a profile block"] = bt([a[k] - b[k] for a, b, h in zip(per["rich"], per["plain"], hp) if h])
    res[m] = o
json.dump(res, open(os.path.join(OUTR, "card_rich.json"), "w"), indent=1); print(json.dumps(res))
