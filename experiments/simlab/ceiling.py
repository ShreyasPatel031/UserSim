"""Noise ceiling for "what users will say" (orchestrator 04:00Z Nov 12). Real comments are themselves a sample. For launches with
>= 16 non-team comments (Aug-Oct 2026; the 300-launch sample first, extended from the same pool to reach 150), split the real
comments at random into halves A and B (3 splits). One extraction call per half (gemini-2.5-flash, temperature 0) returns, in the
same style as the earlier truth passes: up to 8 themes with counts, up to 6 critical themes (objections, doubting questions,
feature requests, most frequent first) and up to 6 questions. Then, with the SAME judge prompts as reactions_eval /
concerns_rank / questions_rank:
  ceiling   half A as a "prediction" of half B: themes recall / precision; p@3 and hit@3 of A's top 3 critical themes and
            questions against B's
  ours      our deployed outputs against the same half-B truth: BEST reactions (recall / precision), RANKED concerns and RANKED
            questions (p@3, hit@3) - available for launches in the 300 sample
Launch-bootstrap 95% CIs; ceiling by comment-count band; ours / ceiling ratios on the shared launches.
    python ceiling.py <cf dir> <launches dir> <react_v2 dir (cache_v2.json)> <conc dir (cache.json)> <qrank dir (cache.json)> <out dir>
"""
import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")

CFD, LDIR, RV2, CON, QR, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def gem(prompt, maxtok=2000):
    for i in range(6):
        try:
            req = urllib.request.Request(GEN, json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}).encode(),
                {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=180)); u = j.get("usageMetadata", {})
            USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
            return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(4 * (i + 1))
    return None


L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
bys = {s: r for s, r in zip(L.slug, L.itertuples())}; com = {}
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
elig = [s for s, c in com.items() if len(c) >= 8 and "2026-08" <= bys[s].day <= "2026-10-31"]; random.Random(0).shuffle(elig); S300 = elig[:300]
big300 = [s for s in S300 if len(com[s]) >= 16]
pool = [s for s in elig[300:] if len(com[s]) >= 16]
S = big300 + pool[: max(0, 150 - len(big300))]
print("300-sample launches with >= 16 comments", len(big300), "extended to", len(S), flush=True)
EX = """Below are real user comments on a product launch (makers' own comments removed). Return JSON with three lists:
"themes": the main themes users raised (praise, objections/concerns, questions, feature requests, comparisons) as
  [{{"theme": "<one specific sentence>", "n_comments": <int>}}], at most 8, most frequent first (generic thanks at most one theme);
"critical": ONLY critical themes (objections/concerns, doubting questions, feature requests), at most 6, most frequent first;
"questions": ONLY questions users asked the makers, at most 6, most frequent first.
Comments:
{c}"""
JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""
JC = """List A = critical points real users raised about a product launch (objections, doubting questions, feature requests).
List B = a ranked list of predicted concerns. For each item in B, does it substantially match some item in A (the same specific
concern, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
JQ = """List A = questions real users asked the makers of a product launch. List B = a ranked list of predicted questions or
reactions. For each item in B, does it substantially match some question in A (asks for the same specific thing, not merely the
same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
RVC = json.load(open(os.path.join(RV2, "cache_v2.json"))); CN = json.load(open(os.path.join(CON, "cache.json"))); CQ = json.load(open(os.path.join(QR, "cache.json")))
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
num = lambda l: "\n".join(f"{k+1}. {t}" for k, t in enumerate(l))
def extract(s, split, half):
    cs = list(com[s].values()); idx = np.random.default_rng(split * 1000 + int(hashlib.md5(s.encode()).hexdigest()[:6], 16)).permutation(len(cs))
    part = [cs[i] for i in (idx[: len(cs) // 2] if half == "A" else idx[len(cs) // 2:])][:40]
    return gem(EX.format(c="\n".join(f"- {t[:400]}" for t in part))) or {}
def themes(x): return [str(t.get("theme")) for t in (x.get("themes") or []) if isinstance(t, dict) and t.get("theme")][:8]
def judge_rp(real, cand):
    if not real or not cand: return None
    a = gem(JUDGE.format(a=num(real), b=num(cand)), 800) or {}
    ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(real) and len(bp) == len(cand) else None
def judge_list(JP, real, cand):
    if not real or not cand: return None
    bm = (gem(JP.format(a=num(real), b=num(cand[:3])), 300) or {}).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else bm
    return (float(np.mean(bm)), float(any(bm))) if isinstance(bm, list) and len(bm) == len(cand[:3]) else None
def work(job):
    s, sp = job; A = run(f"ex|{s}|{sp}|A", lambda: extract(s, sp, "A")); B = run(f"ex|{s}|{sp}|B", lambda: extract(s, sp, "B"))
    tB, tA = themes(B), themes(A); cB, cA = (B.get("critical") or [])[:6], (A.get("critical") or [])[:6]; qB, qA = (B.get("questions") or [])[:6], (A.get("questions") or [])[:6]
    r = {"s": s, "split": sp, "n_comments": len(com[s]), "in300": s in big300}
    r["ceil_rp"] = run(f"crp|{s}|{sp}", lambda: judge_rp(tB, tA)); r["ceil_c"] = run(f"cc|{s}|{sp}", lambda: judge_list(JC, cB, cA)); r["ceil_q"] = run(f"cq|{s}|{sp}", lambda: judge_list(JQ, qB, qA))
    if s in big300:
        r["ours_rp"] = run(f"orp|{s}|{sp}", lambda: judge_rp(tB, RVC.get(f"gen|BEST|{s}") or []))
        r["ours_c"] = run(f"oc|{s}|{sp}", lambda: judge_list(JC, cB, CN.get(f"ranked|{s}") or []))
        r["ours_q"] = run(f"oq|{s}|{sp}", lambda: judge_list(JQ, qB, CQ.get(f"qranked|{s}") or []))
    return r
jobs = [(s, sp) for sp in range(3) for s in S]
with cf.ThreadPoolExecutor(10) as ex: R = list(ex.map(work, jobs))
json.dump(K, open(cache_f, "w")); print("usd", round(USD["usd"], 3), flush=True)
rows = []
for r in R:
    d = {k: r[k] for k in ("s", "split", "n_comments", "in300")}
    for k, a, b in (("ceil_rp", "ceil_recall", "ceil_precision"), ("ours_rp", "ours_recall", "ours_precision"), ("ceil_c", "ceil_c_p3", "ceil_c_hit3"),
                    ("ours_c", "ours_c_p3", "ours_c_hit3"), ("ceil_q", "ceil_q_p3", "ceil_q_hit3"), ("ours_q", "ours_q_p3", "ours_q_hit3")):
        v = r.get(k); d[a], d[b] = (v[0], v[1]) if v else (np.nan, np.nan)
    rows.append(d)
D = pd.DataFrame(rows); P = D.groupby("s").mean(numeric_only=True)                       # average the 3 splits per launch


def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


M = ["recall", "precision", "c_p3", "c_hit3", "q_p3", "q_hit3"]
sh = P[P.in300 > 0]
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(S)), "from_300_sample": len(big300),
       "ceiling_all": {m: mb(P[f"ceil_{m}"]) for m in M},
       "shared_launches (in the 300 sample)": {m: {"ceiling": mb(sh[f"ceil_{m}"]), "ours": mb(sh[f"ours_{m}"]),
                                                    "ours / ceiling": round(float(np.nanmean(sh[f"ours_{m}"]) / np.nanmean(sh[f"ceil_{m}"])), 2) if np.nanmean(sh[f"ceil_{m}"]) > 0 else None} for m in M},
       "ceiling by comment count": {}}
P["band"] = pd.cut(P.n_comments, [15, 24, 40, 1e9], labels=["16-24", "25-40", "41+"])
for b, g in P.groupby("band", observed=True): res["ceiling by comment count"][str(b)] = {"n": int(len(g)), **{m: mb(g[f"ceil_{m}"]) for m in ("recall", "precision", "c_p3", "q_p3")}}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "ceiling.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
