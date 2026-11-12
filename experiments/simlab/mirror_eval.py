"""Mirror of the gap test (orchestrator 03:40Z Nov 12): users ask about what the page MENTIONS. Same 300 post-cutoff launches.
Uses gap_eval.py's labels (which of 12 needs the page answers/mentions; the need of each RANKED item) and the existing per-item
judge verdicts of concerns_rank / questions_rank.
  RERANK     RANKED concerns / questions re-ordered with "the page mentions this item's need" as a positive vote (+0.5 on a 0-1
             position score), scored with the existing per-item verdicts (item level)
  MENTIONED  a list of the needs the page mentions, ordered by the need's base rate of being raised among EARLIER sample launches,
             phrased as items ("Users will ask about <need> - <the product>"), judged at item level with the same judge prompts
             as concerns_rank / questions_rank (gemini-2.5-flash)
precision@3 and hit@3, launch-bootstrap 95% CIs, paired vs the RANKED lists.
    python mirror_eval.py <gap dir (cache.json)> <conc dir (cache.json)> <qrank dir (cache.json)> <out dir> <complaints dir (cache.json: ctruth)>
"""
import concurrent.futures as cf, json, os, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

GAP, CON, QR, OUT, COMPL = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}
NEEDS = ["pricing", "privacy", "integrations", "platforms", "open_source", "comparison", "how_it_works", "limits", "team", "roadmap", "security", "onboarding"]
PHR = {"pricing": "pricing and whether there is a free tier", "privacy": "how user data is handled and kept private", "integrations": "integrations with other tools and APIs",
       "platforms": "supported platforms (mobile, desktop, browser)", "open_source": "open source, the repository or self-hosting", "comparison": "how it differs from named alternatives",
       "how_it_works": "how it works under the hood / which AI model it uses", "limits": "usage limits and quotas", "team": "who is behind it",
       "roadmap": "what is coming next on the roadmap", "security": "security and compliance", "onboarding": "setup and getting started"}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def gem(prompt):
    for i in range(6):
        try:
            req = urllib.request.Request(GEN, json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 300, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}).encode(),
                {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=120)); u = j.get("usageMetadata", {})
            USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
            return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(3 * (i + 1))
    return None


G = json.load(open(os.path.join(GAP, "cache.json"))); CT = json.load(open(os.path.join(COMPL, "cache.json"))); CN = json.load(open(os.path.join(CON, "cache.json"))); CQ = json.load(open(os.path.join(QR, "cache.json")))
S = sorted({k.split("|", 1)[1] for k in G if k.startswith("page|")})
ans = pd.DataFrame([{n: bool((G[f"page|{s}"] or {}).get(n, False)) for n in NEEDS} for s in S], index=S)
ask = pd.DataFrame([{n: bool((G[f"asked|{s}"] or {}).get(n, False)) for n in NEEDS} for s in S], index=S)
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
order_s = sorted(S, key=lambda s: s)            # base rates from other sample launches (leave-one-out; dates not stored here)
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
rows = []
def mentioned_list(s):
    br = ask.drop(index=s).mean().sort_values(ascending=False)
    return [f"Users will ask about {PHR[n]}" for n in br.index if ans.loc[s, n]][:5]
for which, truth_key, ranked_key, judge_key, item_key, JP, C_ in (("concerns", "ctruth|", "ranked|", "j|RANKED|", "ic|", JC, CN), ("questions", "qtruth|", "qranked|", "qj|RANKED|", "iq|", JQ, CQ)):
    jobs = []
    for s in S:
        truth = (CT.get(f"ctruth|{s}") if which == "concerns" else CQ.get(f"qtruth|{s}")) or []
        v = C_.get(f"{judge_key}{s}"); cats = G.get(f"{item_key}{s}") or []
        if not truth or not v or len(cats) != len(v): continue
        sc = [(5 - i) / 5 + (0.5 if (c in NEEDS and ans.loc[s, c]) else 0.0) for i, c in enumerate(cats)]
        o = np.array(v, float); n_ = o[list(np.argsort(-np.array(sc), kind="stable"))]
        ml = mentioned_list(s)
        jobs.append((s, truth, ml))
        rows.append({"which": which, "s": s, "p3_ranked": o[:3].mean(), "hit3_ranked": float(o[:3].any()), "p3_rerank": n_[:3].mean(), "hit3_rerank": float(n_[:3].any())})
    def jm(j):
        s, truth, ml = j
        if not ml: return s, None
        a = run(f"{which}|{s}", lambda: (gem(JP.format(a="\n".join(f"{k+1}. {t}" for k, t in enumerate(truth)), b="\n".join(f"{k+1}. {t}" for k, t in enumerate(ml)))) or {}).get("b_matches"))
        return s, a
    with cf.ThreadPoolExecutor(8) as ex: M = dict(ex.map(jm, jobs))
    for r in rows:
        if r["which"] == which:
            m = M.get(r["s"])
            r["p3_mentioned"] = np.mean(m[:3]) if m else np.nan; r["hit3_mentioned"] = float(any(m[:3])) if m else np.nan
json.dump(K, open(cache_f, "w"))
D = pd.DataFrame(rows)


def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "usd": None, "results": {}}
for w, g in D.groupby("which"):
    res["results"][w] = {f"{m}_{v}": mb(g[f"{m}_{v}"]) for m in ("p3", "hit3") for v in ("ranked", "rerank", "mentioned")} | {
        f"{m} rerank - ranked (paired)": mb(g[f"{m}_rerank"] - g[f"{m}_ranked"]) for m in ("p3", "hit3")} | {
        f"{m} mentioned - ranked (paired)": mb(g[f"{m}_mentioned"] - g[f"{m}_ranked"]) for m in ("p3", "hit3")}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "mirror_eval.json"), "w"), indent=1, default=str)
print(json.dumps(res["results"], indent=1), res["usd"])
