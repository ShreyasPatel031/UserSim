"""Existing-fame prior at 00:05, LLM-knowledge version (orchestrator 23:00Z / 23:20Z Nov 11): 300-launch pilot.
Question: does an LLM's prior knowledge of the product/company predict the per-launch surprise r = logv - honest LM?
Model: Gemini 2.5 Flash-Lite on Vertex (temperature 0, JSON). Its stated knowledge cutoff is January 2025; every launch here
is dated Mar-Oct 2026, so the model cannot have seen launch coverage: the whole pilot is the post-cutoff (clean) slice.
Inputs only: product name, tagline, website domain (when resolved, else "unknown"), launch month. No votes, ranks, comments,
maker handles or other PH text.
Questions: (a) heard of the product/company before the launch month, 0-3; (b) existing user base bucket none / thousands /
hundreds of thousands / millions; (c) new version of an established product y/n; (d) venture-backed or known brand y/n/unknown.
Pilot: every launch on 12 random scored days of the PH comment-forecast set (cf_rows, cut +4h, 207 scored days), so that
within-day statistics and the placebo work. Metrics: within-day Spearman of each answer with r (day-bootstrap CI), pooled
Spearman with day-demeaned r (launch bootstrap); placebo = answers shuffled among launches of the same day.
The full run happens only if the pilot shows a residual correlation with its 95% interval above zero.
    python fame_pilot.py <cf dir: cf_rows.parquet honest_preds.parquet> <sites.jsonl> <launches dir> <out dir>
"""
import concurrent.futures as cf, glob, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from scipy.stats import spearmanr

CFD, SITES, LDIR, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
       "models/gemini-2.5-flash-lite:generateContent")
_tok = {"t": "", "at": 0}; USAGE = {"in": 0, "out": 0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


PROMPT = """Answer from your own prior knowledge only. A product is launching on Product Hunt in {month}.
Product name: {name}
Tagline: {tagline}
Website domain: {domain}

Return JSON with exactly these keys:
"heard_before": 0-3 (0 = never heard of this product or its company before {month}, 1 = vaguely, 2 = known, 3 = well known),
"user_base": one of "none", "thousands", "hundreds_of_thousands", "millions" (its existing users before {month}),
"new_version_of_established": "y" or "n",
"venture_or_known_brand": "y", "n" or "unknown"."""


def ask(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 200, "responseMimeType": "application/json"}}
    for i in range(5):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r); u = j.get("usageMetadata", {}); USAGE["in"] += u.get("promptTokenCount", 0); USAGE["out"] += u.get("candidatesTokenCount", 0)
                return json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:150], flush=True); time.sleep(3 * (i + 1))
    return None


X = pd.read_parquet(os.path.join(CFD, "cf_rows.parquet")).query("cut == 4")
H = pd.read_parquet(os.path.join(CFD, "honest_preds.parquet"))[["id", "honest", "logv"]]; H["id"] = H.id.astype(str)
X = X.merge(H, on="id", how="inner"); X["r"] = X.logv - X.honest
days = sorted(X.day.unique())[31:]                                  # scored days (first month trains only in comment_forecast)
pick = sorted(rng.choice(days, 12, replace=False)); S = X[X.day.isin(pick)].copy()
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str); S = S.merge(L[["id", "name", "tagline"]], on="id", how="left")
dom = {}
for line in open(SITES):
    x = json.loads(line)
    if x.get("url"): dom[str(x["id"])] = re.sub(r"^www\.", "", re.sub(r"^https?://", "", x["url"]).split("/")[0])
S["domain"] = S.id.map(dom).fillna("unknown")
print("pilot days", pick, "launches", len(S), "with domain", round((S.domain != "unknown").mean(), 2), flush=True)
cache = os.path.join(OUT, "fame_answers.jsonl"); done = {}
if os.path.exists(cache):
    for line in open(cache): z = json.loads(line); done[z["id"]] = z["a"]
todo = [r for r in S.itertuples() if r.id not in done]
with cf.ThreadPoolExecutor(8) as ex:
    futs = {ex.submit(ask, PROMPT.format(month=pd.Timestamp(r.day).strftime("%B %Y"), name=r.name, tagline=r.tagline or "", domain=r.domain)): r.id for r in todo}
    with open(cache, "a") as f:
        for fu in cf.as_completed(futs):
            a = fu.result(); done[futs[fu]] = a; f.write(json.dumps({"id": futs[fu], "a": a}) + "\n")
cost = USAGE["in"] / 1e6 * 0.10 + USAGE["out"] / 1e6 * 0.40
print("tokens", USAGE, "usd", round(cost, 4), flush=True)
UB = {"none": 0, "thousands": 1, "hundreds_of_thousands": 2, "millions": 3}
def g(a, k, m=None):
    if not isinstance(a, dict) or k not in a: return np.nan
    v = a[k]; return (m.get(str(v).lower(), np.nan) if m else pd.to_numeric(v, errors="coerce"))
S["heard"] = [g(done.get(i), "heard_before") for i in S.id]
S["users"] = [g(done.get(i), "user_base", UB) for i in S.id]
S["newver"] = [g(done.get(i), "new_version_of_established", {"y": 1, "n": 0}) for i in S.id]
S["brand"] = [g(done.get(i), "venture_or_known_brand", {"y": 1, "n": 0, "unknown": 0.5}) for i in S.id]
S["fame"] = S[["heard", "users", "newver", "brand"]].rank(pct=True).mean(1)
S["r_dm"] = S.r - S.groupby("day").r.transform("mean")


def dboot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(v))]


def lboot(a, b, B=2000):
    a, b = np.asarray(a, float), np.asarray(b, float); m = ~(np.isnan(a) | np.isnan(b)); a, b = a[m], b[m]
    bs = [spearmanr(a[s], b[s]).correlation for s in (rng.integers(0, len(a), len(a)) for _ in range(B))]
    return [round(float(spearmanr(a, b).correlation), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3), int(len(a))]


res = {"design": __doc__.split("\n    python")[0], "days": [str(d) for d in pick], "launches": int(len(S)), "usd": round(cost, 4),
       "valid_answers": int(S.heard.notna().sum()),
       "distributions": {c: S[c].value_counts(dropna=False).sort_index().to_dict() for c in ("heard", "users", "newver", "brand")}, "results": {}}
for c in ("heard", "users", "newver", "brand", "fame"):
    wd = S.groupby("day").apply(lambda q: spearmanr(q[c], q.r).correlation if q[c].nunique() > 1 else np.nan)
    sh = S.copy(); sh[c] = sh.groupby("day")[c].transform(lambda s: s.sample(frac=1, random_state=1).to_numpy())
    wdp = sh.groupby("day").apply(lambda q: spearmanr(q[c], q.r).correlation if q[c].nunique() > 1 else np.nan)
    res["results"][c] = {"within_day_spearman_with_r": dboot(wd.values), "pooled_spearman_with_day_demeaned_r": lboot(S[c], S.r_dm),
                         "placebo_within_day": dboot(wdp.values), "pooled_spearman_with_logv (raw fame)": lboot(S[c], S.logv),
                         "pooled_spearman_with_LM": lboot(S[c], S.honest)}
S[["id", "day", "r", "heard", "users", "newver", "brand", "fame"]].to_parquet(os.path.join(OUT, "fame_pilot_rows.parquet"), index=False)
json.dump(res, open(os.path.join(OUT, "fame_pilot.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
