"""Retrieval bundle for the website's reactions step (the BEST variant of reactions_v2: flash, temperature 0.3, k = 10 similar
past launches' comment THEMES as grounding). Anonymous: themes are paraphrases written by flash-lite from non-team comments
(never verbatim), @handles scrubbed; no usernames anywhere. Contents (npz + json):
  emb      float16 [n, 256]  gemini-embedding-001 (SEMANTIC_SIMILARITY, 256-d, L2-normalised) of "name. tagline. description[:800]"
  meta     json list of {"slug_stem", "day", "topic", "themes": [<= 6 strings]}  (row-aligned with emb)
Pool = every launch in the thread dumps with >= 5 non-team comments (Mar-Oct 2026).
    python reactions_retrieval_bundle.py <react_v2 dir (pool_emb.npy, cache_v2.json)> <cf dir> <launches dir> <out dir>
"""
import concurrent.futures as cf, glob, gzip, html, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

RV, CFD, LDIR, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True)
URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash-lite:generateContent"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def gem(prompt):
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 800, "responseMimeType": "application/json"}}).encode(),
                {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=120)); u = j.get("usageMetadata", {})
            USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.10 + u.get("candidatesTokenCount", 0) / 1e6 * 0.40
            return (json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])) or {}).get("themes") or []
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(3 * (i + 1))
    return []


# same pool construction as reactions_v2.py
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set())
             for m, p in zip(L.makers, L.poster)]
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
bys = {s: r for s, r in zip(L.slug, L.itertuples())}
com = {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        r = bys[p_["slug"]]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower()
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", n.get("bodyHtml") or ""))).strip()
            if u not in r.team and len(t) > 15: com.setdefault(p_["slug"], {})[n.get("id")] = t
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
pool = [s for s, c in com.items() if len(c) >= 5]
PE = np.load(os.path.join(RV, "pool_emb.npy")); assert PE.shape[0] == len(pool)
C = json.load(open(os.path.join(RV, "cache_v2.json")))
NT = """Below are real user comments on a past product launch. Summarise the distinct points users raised as short themes
(praise, objection, question, feature request, comparison). Do not quote; paraphrase; no names or handles.
Return JSON {{"themes": ["<type>: <theme>", ...]}} with at most 6 themes.
Comments:
{c}"""
need = [s for s in pool if f"nbth|{s}" not in C]
print("pool", len(pool), "themes cached", len(pool) - len(need), "to extract", len(need), flush=True)
with cf.ThreadPoolExecutor(8) as ex:
    for s, th in zip(need, ex.map(lambda s: gem(NT.format(c="\n".join(f"- {t[:300]}" for t in list(com[s].values())[:30]))), need)):
        C[f"nbth|{s}"] = th[:6]
scrub = lambda t: re.sub(r"@\w[\w.-]*", "someone", str(t))
meta = [{"slug_stem": re.sub(r"-\d+$", "", s), "day": bys[s].day, "topic": bys[s].topic, "themes": [scrub(t) for t in (C.get(f"nbth|{s}") or [])][:6]} for s in pool]
np.savez_compressed(os.path.join(OUT, "reactions_retrieval_v1.npz"), emb=PE.astype(np.float16))
json.dump(meta, open(os.path.join(OUT, "reactions_retrieval_v1.json"), "w"))
print("bundle", len(meta), "usd", round(USD["usd"], 3), "with themes", sum(bool(m["themes"]) for m in meta), flush=True)
