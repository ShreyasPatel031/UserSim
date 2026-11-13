"""Reactions retrieval bank v2 (orchestrator 02:39Z Nov 13). v1 = 3,371 launches (Jan 1 - Oct 24) with >= 5 non-team comments in the
thread dumps. v2 adds every other ranked launch with >= 3 non-team comments in the same dumps (Jan 1 - Oct 24) and the API comment pulls
for Oct 27 - Nov 10 (try_e2e/apic; maker = first top-level commenter, as truth_c). Themes for new rows: the v1 prompt and model
(gemini-2.5-flash-lite, temperature 0, <= 6 paraphrased themes, @handles scrubbed). Embedding for every row = landing_retrieval's
gemini-embedding-001 256-d of "name. tagline. description[:800]" (the v1 text). Rows carry launch id, slug stem, day, topic, n comments.
    python bank_v2.py <scratchpad> <out dir>
"""
import concurrent.futures as cf, glob, gzip, html, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); HERE = os.path.dirname(os.path.abspath(__file__))
RB = open(os.path.join(HERE, "reactions_retrieval_bundle.py")).read(); exec(RB[RB.index("_tok = {"):RB.index("# same pool construction")]); exec(RB[RB.index("NT = \"\"\""):RB.index("need = [")])
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].sort_values(["day", "id"]).reset_index(drop=True); L["id"] = L.id.astype(str)
LE = np.load(os.path.join(SP, "land/launch_emb256.npy")); assert len(LE) == len(L)
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
bys = {s: k for k, s in enumerate(L.slug)}; byid = {i: k for k, i in enumerate(L.id)}; com = {}
for f in sorted(glob.glob(os.path.join(SP, "cf/page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        k = bys[p_["slug"]]; team = L.team.iat[k]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", n.get("bodyHtml") or ""))).strip()
            if u not in team and len(t) > 15: com.setdefault(k, {})[n.get("id")] = t
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
cl = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip(); bp = {}
for f in glob.glob(os.path.join(SP, "try_e2e/apic/*/*.jsonl")):
    for l in open(f): x = json.loads(l); bp.setdefault(str(x["post_id"]), {})[x["comment_id"]] = x
for p, cs in bp.items():
    if p not in byid: continue
    cs = list(cs.values()); tops = sorted([(c["createdAt"], c["commenter_user_id"]) for c in cs if not c.get("parentId")]); mk = tops[0][1] if tops else None
    com.setdefault(byid[p], {}).update({c["comment_id"]: cl(c["body"]) for c in cs if c["commenter_user_id"] != mk and len(cl(c["body"])) > 15})
V1 = json.load(open(os.path.join(SP, "rbundle/reactions_retrieval_v1.json"))); v1 = {}
st = lambda s: re.sub(r"-\d+$", "", str(s))
for m in V1:
    for k in np.flatnonzero((L.day == m["day"]).to_numpy()):
        if st(L.slug.iat[k]) == m["slug_stem"]: v1[k] = m["themes"]; break
CF = os.path.join(OUT, "themes_cache.json"); TC = json.load(open(CF)) if os.path.exists(CF) else {}
rows = sorted(k for k, c in com.items() if len(c) >= 3); need = [k for k in rows if k not in v1 and str(L.id.iat[k]) not in TC]
print("v1 mapped", len(v1), "of", len(V1), "| v2 candidates", len(rows), "new to extract", len(need), flush=True)
with cf.ThreadPoolExecutor(8) as ex:
    for k, th in zip(need, ex.map(lambda k: gem(NT.format(c="\n".join(f"- {t[:300]}" for t in list(com[k].values())[:30]))), need)):
        TC[str(L.id.iat[k])] = th[:6]
json.dump(TC, open(CF, "w"))
scrub = lambda t: re.sub(r"@\w[\w.-]*", "someone", str(t))
meta = []
for k in rows:
    th = v1.get(k) if k in v1 else [scrub(t) for t in (TC.get(str(L.id.iat[k])) or [])][:6]
    if th: meta.append({"id": L.id.iat[k], "slug_stem": st(L.slug.iat[k]), "day": L.day.iat[k], "topic": L.topic.iat[k], "n_comments": len(com[k]), "in_v1": k in v1, "themes": th, "_k": int(k)})
E2 = LE[[m.pop("_k") for m in meta]]
np.save(os.path.join(OUT, "bank_v2_emb.npy"), E2.astype(np.float32)); json.dump(meta, open(os.path.join(OUT, "bank_v2.json"), "w"))
mon = pd.Series([m["day"][:7] for m in meta]).value_counts().sort_index().to_dict()
print("bank v2", len(meta), "in v1", sum(m["in_v1"] for m in meta), "days", meta[0]["day"], meta[-1]["day"], "themes/launch", round(np.mean([len(m["themes"]) for m in meta]), 2), mon, "usd", round(USD["usd"], 3))
