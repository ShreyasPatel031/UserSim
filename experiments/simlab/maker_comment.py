"""Content of the makers' pre-launch comment as a 00:05 input (orchestrator 23:22Z Nov 13). Counts only.
Thread dumps (scratchpad cf/page*.jsonl.gz, backtest Jan 1 - Oct 24). Team comment = author is the launch's hunter (warehouse poster) or
carries the 'maker'/'hunter' badge on the comment; pre-launch = createdAt < 00:00 PT of the launch day (d0). Comment votes / replies are
post-launch and never used.
(a) structure: has_pre, n_pre (team comments), len_pre (characters, log), hrs_before (d0 - first team comment, hours, log), multi_team (>1 author)
(b) traits (gemini-2.5-flash-lite, temperature 0, one call per launch, fixed rubric 0-2): for_whom, offer, asks_feedback, founder_story,
    tech_depth, traction, backer. The scorer sees only the pre-launch team comment text with the product name, slug words, URLs and @handles
    masked; nothing after launch. Memorisation probe: on 150 launches the same model is asked to name the product from the masked text
    (exact/stem match rate) and to guess whether it finished top 3 (AUC vs truth).
Tests among launches with a pre-launch team comment, arm-2 days: standardized difference top 3 vs rest (day bootstrap); mean within-day
Spearman with the arm-2 residual; month-forward ridge on within-day z: arm 2 + count@00:00 (the bar) vs + structure vs + traits vs + both,
top 3/5/10 paired vs arm 2 and vs arm 2 + count@00:00 (all launches; trait = 0 when no comment), day bootstrap.
    python maker_comment.py <scratchpad> <arm2 parquet> <out dir>
"""
import asyncio, glob, gzip, hashlib, html, json, os, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
SP, A2P, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); sys.path[:0] = [os.path.join(SP, "phweb"), os.path.join(SP, "phweb", "src")]
from capability import gemini_config as GC  # noqa: E402
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
L = L[L.daily_rank.notna()].reset_index(drop=True); bys = dict(zip(L.slug, L.index))
TX = os.path.join(OUT, "texts.parquet")   # scratch-only content: kept out of git (see .gitignore note in report)
if not os.path.exists(TX):
    rows = {}
    for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
        for line in gzip.open(f):
            x = json.loads(line)
            try: p_ = json.loads(x["html"])["data"]["post"]
            except Exception: continue
            if not p_ or p_.get("slug") not in bys: continue
            i = bys[p_["slug"]]; r = L.iloc[i]; d0 = pd.Timestamp(r.day).tz_localize(PT).tz_convert("UTC"); hun = str(r.poster).lower(); out = rows.setdefault(i, {})
            def walk(n):
                u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt"); b = n.get("badges") or []
                if t:
                    ts = pd.Timestamp(t).tz_convert("UTC")
                    out[n.get("id")] = (u, ts, ts < d0, (u == hun) or any(z in ("maker", "hunter") for z in b), n.get("body") or "")
                for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
            for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
    T = []
    for i, c in rows.items():
        r = L.iloc[i]; d0 = pd.Timestamp(r.day).tz_localize(PT).tz_convert("UTC"); pre = sorted([v for v in c.values() if v[2] and v[3]], key=lambda v: v[1])
        txt = "\n\n".join(re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", v[4]))).strip() for v in pre)
        T.append({"id": r.id, "day": r.day, "has_pre": float(bool(pre)), "n_pre": float(len(pre)), "len_pre": float(len(txt)), "hrs_before": (d0 - pre[0][1]).total_seconds() / 3600 if pre else 0.0,
                  "multi_team": float(len({v[0] for v in pre}) > 1), "n_any_pre": float(sum(1 for v in c.values() if v[2])), "text": txt})
    pd.DataFrame(T).to_parquet(TX)
T = pd.read_parquet(TX).merge(L[["id", "name", "slug", "daily_rank"]], on="id"); print("launches", len(T), "with pre team comment", int(T.has_pre.sum()), flush=True)
def mask(t, name, slug):
    t = re.sub(r"https?://\S+|www\.\S+|\b[\w-]+\.(com|ai|io|app|co|dev|so|xyz|net|org)\b\S*", "[URL]", t); t = re.sub(r"@\w+", "@[HANDLE]", t)
    for w in sorted({name} | set(re.split(r"[\s\-_.:]+", name)) | set(slug.split("-")), key=len, reverse=True):
        if len(w) >= 3 and not w.isdigit(): t = re.sub(re.escape(w), "[PRODUCT]", t, flags=re.I)
    return t[:3000]
TR = ["for_whom", "offer", "asks_feedback", "founder_story", "tech_depth", "traction", "backer"]
RUB = """Score this maker's launch-day comment on a product launch site. The product name is masked. Use only the text.
Return JSON with integer 0, 1 or 2 for each key:
for_whom: states who the product is for (0 none, 1 vague, 2 specific audience)
offer: concrete launch offer, discount, free tier or deal for this launch (0 none, 1 generic "free to try", 2 specific code/discount)
asks_feedback: explicitly asks readers for feedback or questions (0/1/2)
founder_story: personal founder story or why they built it (0/1/2)
tech_depth: technical detail about how it works (0/1/2)
traction: mentions prior users, customers, revenue or growth numbers (0 none, 1 vague, 2 numbers)
backer: mentions a known investor, accelerator, company or notable backer (0 none, 1 vague, 2 named)

COMMENT:
{t}"""
PROBE = """This is a maker's launch comment with the product name masked as [PRODUCT]. Return JSON {{"name": "<your best guess of the product's real name, or empty>", "p_top3": <probability 0-1 that this launch finished in the top 3 of its day on Product Hunt>}}.

COMMENT:
{t}"""
SC = os.path.join(OUT, "traits.jsonl"); done = {json.loads(l)["id"] for l in open(SC)} if os.path.exists(SC) else set(); USD = {"in": 0, "out": 0}
async def call(p, tok=200):
    try:
        r = await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-flash-lite", temperature=0.0, max_retries=3, max_output_tokens=tok); USD["in"] += len(p) / 4; USD["out"] += tok / 2
        return GC.extract_json(r) or {}
    except Exception: return {}
async def score_all(D):
    sem = asyncio.Semaphore(16); f = open(SC, "a")
    async def one(r):
        async with sem:
            a = await call(RUB.format(t=mask(r.text, r.name, r.slug)))
            if a: f.write(json.dumps({"id": r.id, **{k: a.get(k) for k in TR}}) + "\n"); f.flush()
    await asyncio.gather(*[one(r) for r in D.itertuples() if r.id not in done]); f.close()
A2 = pd.read_parquet(A2P)[["id", "both"]]; A2["id"] = A2.id.astype(str); T = T.merge(A2, on="id")
asyncio.run(score_all(T[T.has_pre > 0]))
S = pd.DataFrame([json.loads(l) for l in open(SC)]).drop_duplicates("id")
for k in TR: S[k] = pd.to_numeric(S[k], errors="coerce").clip(0, 2)
T = T.merge(S, on="id", how="left")
for k in TR: T[k] = T[k].fillna(0)
res = {"design": __doc__.split("\n    python")[0], "arm2 launches with dumps": len(T), "with pre-launch team comment": int(T.has_pre.sum()), "scored": int(S.id.isin(T.id).sum()),
       "gemini cost est USD (flash-lite $0.10/M in, $0.40/M out)": round(USD["in"] / 1e6 * 0.10 + USD["out"] / 1e6 * 0.40, 3)}
# memorisation probe
pr = T[T.has_pre > 0].sample(min(150, int(T.has_pre.sum())), random_state=0)
async def probe():
    return await asyncio.gather(*[call(PROBE.format(t=mask(r.text, r.name, r.slug))) for r in pr.itertuples()])
P = asyncio.run(probe()); st = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
hit = [bool(st(a.get("name")) and (st(a.get("name")) == st(n) or (len(st(a.get("name"))) >= 4 and (st(a.get("name")) in st(n) or st(n) in st(a.get("name")))))) for a, n in zip(P, pr.name)]
pt = [float(a.get("p_top3")) if isinstance(a.get("p_top3"), (int, float)) else np.nan for a in P]; y = (pr.daily_rank.astype(float) <= 3).values; ok = ~np.isnan(pt)
res["memorisation probe (150 launches)"] = {"name recovered from masked text": round(float(np.mean(hit)), 3), "AUC of guessed P(top 3)": round(float(roc_auc_score(y[ok], np.array(pt)[ok])), 3) if y[ok].any() and (~y[ok]).any() else None, "n top3": int(y.sum())}
res["gemini cost est USD (flash-lite $0.10/M in, $0.40/M out)"] = round(USD["in"] / 1e6 * 0.10 + USD["out"] / 1e6 * 0.40, 3)
# tests
T["rank"] = T.daily_rank.astype(float); T = T[T.groupby("day").id.transform("count") >= 10].copy(); T["mon"] = T.day.str[:7]
z = lambda s: (s - s.mean()) / (s.std() or 1)
T["a2rank"] = T.groupby("day").both.rank(ascending=False); T["resid"] = T.a2rank - T["rank"]
ST = ["has_pre", "n_pre", "len_pre", "hrs_before", "multi_team"]; W = T[T.has_pre > 0]
def dboot(df, fn, B=1000):
    dd = df.day.unique(); g = {d: x for d, x in df.groupby("day")}; v = fn(df); bs = [fn(pd.concat([g[d] for d in rng.choice(dd, len(dd))])) for _ in range(B)]
    return [round(float(v), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]
def smd(c):
    def f(x):
        a, b = np.log1p(x[x["rank"] <= 3][c]), np.log1p(x[x["rank"] > 3][c]); s = np.sqrt((a.var() + b.var()) / 2); return (a.mean() - b.mean()) / s if s else np.nan
    return f
o1 = {"launches with comment": len(W), "of which top 3": int((W["rank"] <= 3).sum())}
for c in ST[1:] + TR:
    sp = [spearmanr(g[c], g.resid).correlation for _, g in W.groupby("day") if len(g) >= 4 and g[c].nunique() > 1]
    o1[c] = {"mean (comment launches)": round(float(W[c].mean()), 3), "SMD top3 vs rest": dboot(W, smd(c)), "within-day Spearman with arm2 residual": [round(float(np.mean(sp)), 3), len(sp)] if sp else None}
o1["has_pre (all launches): SMD top3 vs rest"] = dboot(T, smd("has_pre"))
res["(1) descriptive"] = o1
cnt = pd.read_json(os.path.join(os.path.dirname(OUT.rstrip("/")), "precom_timing", "precom_timing.json")) if False else None
for c in ST + TR + ["n_any_pre"]: T["z_" + c] = T.groupby("day")[c].transform(lambda s: z(np.log1p(s)))
T["zb"] = T.groupby("day").both.transform(z); T["y"] = T.groupby("day")["rank"].transform(lambda r: z(-np.log(r)))
ARMS = {"arm2": ["zb"], "arm2 + count@00:00 (all pre-launch commenters)": ["zb", "z_n_any_pre"], "arm2 + structure": ["zb"] + ["z_" + c for c in ST],
        "arm2 + traits": ["zb"] + ["z_" + c for c in TR], "arm2 + structure + traits": ["zb"] + ["z_" + c for c in ST + TR],
        "arm2 + count@00:00 + traits": ["zb", "z_n_any_pre"] + ["z_" + c for c in TR]}
mons = sorted(T.mon.unique())
for a, X in ARMS.items():
    T["p_" + a] = np.nan
    for m in mons[1:]:
        tr, te = T[T.mon < m], T[T.mon == m]; T.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
V = T[T.p_arm2.notna()]; days = sorted(V.day.unique())
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def pdiff(A, B):
    df = A - B; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
R = {a: np.array([dm(V[V.day == d], "p_" + a) for d in days]) for a in ARMS}; B0, BC = R["arm2"], R["arm2 + count@00:00 (all pre-launch commenters)"]
o2 = {"days": len(days), "launches": len(V), "arm2 top3/5/10": B0.mean(0).round(1).tolist()}
for a in list(ARMS)[1:]: o2[a] = {"top3/5/10": R[a].mean(0).round(1).tolist(), "vs arm2": pdiff(R[a], B0), "vs arm2 + count@00:00": pdiff(R[a], BC)}
res["(2) month-forward"] = o2
json.dump(res, open(os.path.join(OUT, "maker_comment.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
