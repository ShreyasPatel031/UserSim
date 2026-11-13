"""Replication of retrieval-condensed concerns / questions (b20), recipe frozen as reports/retrieval_react/RECIPE_b20.md (orchestrator
02:16Z Nov 13). Fresh set = the 100 most recent launches not in the first 70 that have a page read and >= 5 real comments (no unused fresh
Oct 27 - Nov 10 page read has >= 5 comments, so these are held S300 launches, Sep 14 - Oct 24, page read fetched Oct 25 = late, flagged).
Arms b20 / c (deployed ranked()) / d (constant), both input modes. ALL 170 (first 70 + new 100) re-adjudicated with the same strict
gemini-2.5-pro prompt on a b20 / c / d pool (so pool size is equal across sets); second adjudication with a different item order (seed 2) on
30 new launches = judge noise. Splits: thin neighbours (top-1 cosine in the bottom third, per mode), PH description < 40 words.
Leak check per target (20 neighbours): same slug stem after dropping a "-N" suffix (the run itself excludes only the exact stem), a slug / name
containing the target's, or a shared named maker (most makers are redacted in the launches table; counts only).
    python retrieval_rep.py <ph-website worktree> <scratchpad> <page_path out dir> <out dir>
"""
import os, sys, json, random, re, glob
HERE = os.path.dirname(os.path.abspath(__file__)); A = sys.argv[1:5]
RR = open(os.path.join(HERE, "retrieval_react.py")).read(); exec(RR[:RR.index("\nasync def one(x, sem):")])
used = {x["key"] for x in LAUNCH}; NEW = []
for i, v in BP.items():
    s = idmap.get(str(i))
    if s and "fail" not in v and s in ns["com"] and len(ns["com"][s]) >= 5 and f"H|{s}" not in used:
        r = bys[s]; NEW.append({"key": f"H|{s}", "fetch": "late (Oct 25)", "comments": list(ns["com"][s].values()), "read": v, "ph": (r.name, r.tagline or "", r.description or ""), "day": r.day, "topic": r.topic, "stem": s})
NEW = sorted(NEW, key=lambda x: x["day"], reverse=True)[:100]; FIRST = list(LAUNCH); print("new", len(NEW), NEW[-1]["day"], NEW[0]["day"], flush=True)
# makers / names per slug stem for the leak check (in memory only)
LA = pd.concat([pd.read_parquet(f, columns=["slug", "name", "makers", "day"]) for f in glob.glob(os.path.join(SP0, "early/launches/*.parquet"))])
st = lambda s: re.sub(r"-\d+$", "", str(s)); MK = {}; NM = {}
for r in LA.itertuples():
    try: ms = {str(m).lower() for m in json.loads(r.makers) if m and not str(m).startswith("[")} if isinstance(r.makers, str) and r.makers.startswith("[") else set()
    except Exception: ms = set()
    MK.setdefault(st(r.slug), set()).update(ms); NM.setdefault(st(r.slug), set()).add(str(r.name).lower().strip())
def leak(x, nb):
    s = st(x["stem"]); nm = str(x["ph"][0]).lower().strip(); mk = MK.get(s, set()); o = {"maker_known": int(bool(mk)), "same_stem": 0, "name_or_slug_contains": 0, "shared_maker": 0}
    for j in nb:
        t = st(RBM[j]["slug_stem"]); o["same_stem"] += t == s
        o["name_or_slug_contains"] += bool((len(s) >= 4 and (s in t or t in s)) or (len(nm) >= 4 and nm in NM.get(t, set())))
        o["shared_maker"] += bool(mk & MK.get(t, set()))
    return o
async def one(x, sem, seed2=False):
    async with sem:
        k = f"lists|{x['key']}"; rd = x["read"]
        modes = {"ph": x["ph"], "page": (rd.get("name") or x["ph"][0], rd.get("tagline") or "", rd.get("page_excerpt") or "")}
        if k not in C:
            pc = PPC.get(k, {}); out = {}
            for mo, (n, t, d) in modes.items():
                if not d.strip(): continue
                nb = await nearest(n, t, d, x["day"], x["stem"], None, 20)
                for pre in ("RC", "RQ"):
                    out[f"{pre}|{mo}|b20"] = await cond(n, t, d, nb, pre)
                    cc = (pc.get(f"{pre}_{'c_ph' if mo == 'ph' else 'b_raw'}") or [])[:3]
                    out[f"{pre}|{mo}|c"] = cc or (await ranked(n, t, d, "concerns" if pre == "RC" else "questions", x["day"]))[0][:3]
                    out[f"{pre}|{mo}|d"] = (CONST_C if pre == "RC" else CONST_Q)[:3]
            T = await cj(EX.format(c="\n".join(f"- {str(z)[:400]}" for z in list(x["comments"])[:40])), tok=1500)
            out["real|RC"] = [str(z) for z in (T.get("critical") or [])][:3]; out["real|RQ"] = [str(z) for z in (T.get("questions") or [])][:3]
            C[k] = out; csave()
        mk = f"meta|{x['key']}"
        if mk not in C:
            m = {"words": len(str(x["ph"][2]).split())}
            for mo, (n, t, d) in modes.items():
                if not d.strip(): continue
                q = (await emb([f"{n}. {t}. {d[:800]}"]))[0]; nb = await nearest(n, t, d, x["day"], x["stem"], None, 20)
                m[f"sim1|{mo}"] = float(RBE[nb[0]] @ q) if nb else None; m[f"leak|{mo}"] = leak(x, nb)
            C[mk] = m; csave()
        L_ = {kk: v for kk, v in C[k].items() if not kk.startswith("real|")}; res = {}
        for pre in ("RC", "RQ"):
            ls = {kk.split("|", 1)[1]: v for kk, v in L_.items() if kk.startswith(pre + "|") and v and kk.split("|")[2] in ("b20", "c", "d")}
            real = C[k][f"real|{pre}"]
            res[pre] = await adj(f"adj3|{pre}|{x['key']}", x["comments"], real, ls, pre) if real else None
            if seed2: res[pre + "_s2"] = await adj(f"adj3|{pre}|{x['key']}|s2", x["comments"], real, ls, pre) if real else None
        return x, res, C[mk]
async def main():
    sem = asyncio.Semaphore(5); s2 = {x["key"] for x in NEW[:30]}
    return await asyncio.gather(*[one(x, sem, x["key"] in s2) for x in FIRST + NEW])
R = asyncio.run(main())
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
met = {"p@3": lambda o: float(np.mean(o["lab"][:3])), "recall": lambda o: o["rec"] if o["rec"] is not None else np.nan, "top1": lambda o: float(o["lab"][0])}
g = lambda o, nm, m: met[m](o[nm]) if o and o.get(nm) and o[nm]["lab"] else np.nan
newk = {x["key"] for x in NEW}; firstk = {x["key"] for x in FIRST}
sims = {mo: [mt.get(f"sim1|{mo}") for _, _, mt in R if mt.get(f"sim1|{mo}") is not None] for mo in ("ph", "page")}
cut = {mo: float(np.percentile(v, 33.3)) for mo, v in sims.items()}
SETS = {"new100": lambda x, mt, mo: x["key"] in newk, "first70": lambda x, mt, mo: x["key"] in firstk, "pooled170": lambda x, mt, mo: True,
        "pooled thin neighbours (top-1 cos bottom third)": lambda x, mt, mo: (mt.get(f"sim1|{mo}") or 9) < cut[mo],
        "pooled PH description < 40 words": lambda x, mt, mo: mt["words"] < 40,
        "pooled excl. targets with a same-product / shared-maker neighbour": lambda x, mt, mo: not any(v for k_, v in mt.get(f"leak|{mo}", {}).items() if k_ != "maker_known")}
out = {"design": __doc__.split("\n    python")[0], "new_days": [NEW[-1]["day"], NEW[0]["day"]], "thin_cut_cos": cut, "est_usd_adjudicator_this_run": round(USD["usd"], 2)}
for sn, f in SETS.items():
    for pre, kind in (("RC", "concerns"), ("RQ", "questions")):
        for mo in ("page", "ph"):
            rows = [(x, r) for x, r, mt in R if f(x, mt, mo) and r.get(pre)]
            o_ = {"n": len(rows)}
            for m in ("p@3", "recall", "top1"):
                o_[m] = {a: mb([g(r[pre], f"{mo}|{a}", m) for _, r in rows]) for a in ("b20", "c", "d")}
                o_[m]["b20 - c"] = mb([g(r[pre], f"{mo}|b20", m) - g(r[pre], f"{mo}|c", m) for _, r in rows])
                o_[m]["b20 - d"] = mb([g(r[pre], f"{mo}|b20", m) - g(r[pre], f"{mo}|d", m) for _, r in rows])
            out[f"{sn}|{kind}|{mo}"] = o_
# judge noise: seed 1 vs seed 2 on 30 new launches
jn = {}
for pre, kind in (("RC", "concerns"), ("RQ", "questions")):
    for mo in ("page", "ph"):
        rows = [r for _, r, _ in R if r.get(pre + "_s2") and r.get(pre)]
        lab1 = [v for r in rows for a in ("b20", "c", "d") for v in (r[pre].get(f"{mo}|{a}") or {}).get("lab", [])]
        lab2 = [v for r in rows for a in ("b20", "c", "d") for v in (r[pre + "_s2"].get(f"{mo}|{a}") or {}).get("lab", [])]
        jn[f"{kind}|{mo}"] = {"n_launches": len(rows), "item_label_agreement": round(float(np.mean([a == b for a, b in zip(lab1, lab2)])) * 100, 1) if lab1 and len(lab1) == len(lab2) else None,
                              "b20 - c p@3 seed1": mb([g(r[pre], f"{mo}|b20", "p@3") - g(r[pre], f"{mo}|c", "p@3") for r in rows]),
                              "b20 - c p@3 seed2": mb([g(r[pre + "_s2"], f"{mo}|b20", "p@3") - g(r[pre + "_s2"], f"{mo}|c", "p@3") for r in rows])}
out["judge_noise_seed2"] = jn
lk = {mo: {k_: int(sum(mt.get(f"leak|{mo}", {}).get(k_, 0) for _, _, mt in R)) for k_ in ("maker_known", "same_stem", "name_or_slug_contains", "shared_maker")} for mo in ("ph", "page")}
lk["targets_with_any_flag"] = {mo: int(sum(any(v for k_, v in mt.get(f"leak|{mo}", {}).items() if k_ != "maker_known") for _, _, mt in R)) for mo in ("ph", "page")}; out["leak_check_neighbours_of_170"] = lk
out["est_usd_adjudicator_this_run"] = round(USD["usd"], 2); out["est_usd_b20_generation_this_run"] = round(USD["gen"], 3)
json.dump(out, open(os.path.join(OUT, "retrieval_rep.json"), "w"), indent=1, default=float); print("done", out["est_usd_adjudicator_this_run"], lk)
