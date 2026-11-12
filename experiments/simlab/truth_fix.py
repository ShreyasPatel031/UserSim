"""Truth quality (orchestrator 07:55Z Nov 12, item 4). The comment truth of reactions / concerns / questions / ceiling excluded
"team" comments only when the team was NAMED; PH names only the day #1's makers after the day, so non-winners kept their makers'
comments. Identity-free rule: the author of the earliest top-level comment is a maker (the maker's first comment) - drop all of
that author's comments and replies - plus the hunter (poster). For the launches of the 300-sample whose comment set changes,
the truth is extracted under the OLD and the NEW rule with the same prompt (ceiling.py EX: themes / critical / questions, up to
40 comments) and the deployed outputs are judged against both with the same judges: BEST reactions (recall / precision), RANKED
concerns and RANKED questions (p@3 / hit@3); plus the split-half bar (3 splits) for affected launches with >= 16 new comments.
Unaffected launches keep identical truth (difference 0). Paired new - old over the affected set and over all 300, bootstrap CIs.
    python truth_fix.py <scratchpad> <out dir>
"""

import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")

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

SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
C = json.load(open(os.path.join(SP, "truthq_comments.json"))); Q = pd.read_parquet(os.path.join(SP, "truthq.parquet"))
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
bys = {s: r for s, r in zip(L.slug, L.itertuples())}
def sets(s):
    c = C.get(s, {}); r = bys[s]
    tops = sorted([(v[2], v[0]) for v in c.values() if v[3] and v[2]]); fa = tops[0][1] if tops else ""
    nt = r.team | ({fa, str(r.poster or "").lower()} - {""})
    old = [v[1] for v in c.values() if v[0] not in r.team and len(v[1]) > 15]; new = [v[1] for v in c.values() if v[0] not in nt and len(v[1]) > 15]
    return old, new
RVC = json.load(open(os.path.join(SP, "react_v2/cache_v2.json"))); CN = json.load(open(os.path.join(SP, "conc/cache.json"))); CQ = json.load(open(os.path.join(SP, "qrank/cache.json")))
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K or K[key] is None: K[key] = fn()
    return K[key]
AFF = list(Q[Q.dropped > 0].s); print("affected", len(AFF), flush=True)
def ex(cs): return gem(EX.format(c="\n".join(f"- {t[:400]}" for t in cs[:40]))) or {}
def score(T, s):
    tt, tc, tq = themes(T), (T.get("critical") or [])[:6], (T.get("questions") or [])[:6]
    return {"rp": judge_rp(tt, RVC.get(f"gen|BEST|{s}") or []), "c": judge_list(JC, tc, CN.get(f"ranked|{s}") or []), "q": judge_list(JQ, tq, CQ.get(f"qranked|{s}") or [])}
def work(s):
    old, new = sets(s); r = {"s": s, "n_old": len(old), "n_new": len(new)}
    for lab, cs in (("old", old), ("new", new)):
        T = run(f"ex|{lab}|{s}", lambda: ex(cs)); sc = run(f"sc|{lab}|{s}", lambda: score(T, s)); r[lab] = sc
        if len(new) >= 16:
            bars = []
            for sp in range(3):
                idx = np.random.default_rng(sp * 1000 + int(hashlib.md5(s.encode()).hexdigest()[:6], 16)).permutation(len(cs))
                A = run(f"h|{lab}|{s}|{sp}|A", lambda: ex([cs[i] for i in idx[: len(cs) // 2]])); B = run(f"h|{lab}|{s}|{sp}|B", lambda: ex([cs[i] for i in idx[len(cs) // 2:]]))
                bars.append(run(f"bar|{lab}|{s}|{sp}", lambda: {"rp": judge_rp(themes(B), themes(A)), "c": judge_list(JC, (B.get("critical") or [])[:6], (A.get("critical") or [])[:6])}))
            r[lab + "_bar"] = bars
    return r
with cf.ThreadPoolExecutor(10) as exr: R = list(exr.map(work, AFF))
json.dump(K, open(cache_f, "w")); print("usd", round(USD["usd"], 3), flush=True)
def g(x, k, j):
    v = x.get(k) if x else None; return v[j] if v else np.nan
rows = []
for r in R:
    d = {"s": r["s"]}
    for lab in ("old", "new"):
        x = r[lab]; d[f"{lab}_recall"], d[f"{lab}_precision"] = g(x, "rp", 0), g(x, "rp", 1); d[f"{lab}_c_p3"], d[f"{lab}_c_hit3"] = g(x, "c", 0), g(x, "c", 1)
        d[f"{lab}_q_p3"], d[f"{lab}_q_hit3"] = g(x, "q", 0), g(x, "q", 1)
        if lab + "_bar" in r:
            b = r[lab + "_bar"]; d[f"{lab}_bar_recall"] = np.nanmean([g(z, "rp", 0) for z in b]); d[f"{lab}_bar_precision"] = np.nanmean([g(z, "rp", 1) for z in b]); d[f"{lab}_bar_c_p3"] = np.nanmean([g(z, "c", 0) for z in b])
    rows.append(d)
D = pd.DataFrame(rows)
def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches_300": 300, "affected": len(AFF), "share_comments_dropped_mean_all300": round(float(Q.share.mean()), 3),
       "dropped_by_rank_group": Q.assign(g=np.where(Q["rank"] == 1, "1", np.where(Q["rank"] <= 3, "2-3", np.where(Q["rank"] <= 10, "4-10", "11+")))).groupby("g").share.mean().round(3).to_dict(), "affected_set": {}, "all300_shift": {}}
for m in ("recall", "precision", "c_p3", "c_hit3", "q_p3", "q_hit3", "bar_recall", "bar_precision", "bar_c_p3"):
    if f"old_{m}" not in D: continue
    res["affected_set"][m] = {"old": mb(D[f"old_{m}"]), "new": mb(D[f"new_{m}"]), "new - old (paired)": mb(D[f"new_{m}"] - D[f"old_{m}"])}
    dd = (D[f"new_{m}"] - D[f"old_{m}"]).dropna(); res["all300_shift"][m] = round(float(dd.sum() / 300 * 100), 2) if not m.startswith("bar") else None
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "truth_fix.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
