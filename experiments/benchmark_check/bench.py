"""Go/no-go benchmark: does arm 3 (the published 00:05 PT forecast) beat simple public baselines? (Nov 19 2026)
Pre-registered rule (from the task, fixed before scoring): GO only if arm 3 beats EVERY available baseline by >= 5 daily top-3 points
with the 95% day-bootstrap interval clear of zero; otherwise NO-GO. Aggregates only; no usernames are written anywhere.

Predictors, each ranking its own line-up of day d (a launch it does not list cannot be picked):
  arm3      frozen month-forward backtest preds (origin/claude/ph-ops-agent c3a9f91c:experiments/ph_predict/results/arm3_vs_arm2_preds.parquet,
            20 seeds, 2026 Apr-Oct, 183 scored days). Live days: pred_arm3 in raw/daily/<d>/forecast_<d>.parquet (published Nov 17+).
  B1 ph0005 Product Hunt's own ranking order (rank_now) at the recorder's 00:06 PT read (raw/vote_snapshots/<d>.jsonl). Exists Nov 2+ only.
  B2 track  hunter/maker track record from strictly earlier days (2024-2025 official-API lists raw/ph_history + 2026 warehouse launches).
            Test launch team = hunter + the LAST listed maker if named (the 00:05 view names at most one maker, always the last list entry;
            the rest are named after the day ends, which leaks the winner). Score = best (lowest) past final daily rank of anyone on the
            team; tie-break: more past top-10 finishes; no history ranks last. Variants: B2c = count of past top-10 finishes;
            B2_leaky = all final-list makers (NOT leak-free, shown only to size the maker leak).
  B3 follow PH follower count of hunter + makers read at or before 00:15 PT on launch day (warehouse at_launch_followers; hunter also from
            the 00:05 forecast input ph_hunter_followers). Held only from late Oct; backtest days have no dated follower count.
  B4 llm    Gemini 2.5 Flash, listwise per day, name + tagline only, temperature 0, score = P(top 5) in %. Cached in llm_cache/<d>.json.
  pub       the published 00:05 line of each live night (published_rank, else pred), whichever model was published then (supplementary).
  h0345     Product Hunt's order at 03:45 PT (recorder read at 03:45, else the 15-min capture's API ranking snapshot at 03:45).
Truth: warehouse launches.daily_rank <= k, days with >= 10 ranked. Metric: |our top k & true top k| / k * 100, k = 3, 5, 10.
Paired day bootstrap, 10,000 draws, seed 0.
usage: BENCH_CACHE=<dir with vs/, live/, daily/, hist/> python bench.py [--llm]  (run from experiments/benchmark_check)"""
import glob, io, json, os, re, subprocess, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
C = os.environ["BENCH_CACHE"]; K = (3, 5, 10); TZ = "America/Los_Angeles"
ARM3_SRC = "c3a9f91c:experiments/ph_predict/results/arm3_vs_arm2_preds.parquet"
RED = "[REDACTED]"

# ---------- data ----------
P = pd.read_parquet(io.BytesIO(subprocess.run(["git", "show", ARM3_SRC], capture_output=True, check=True, cwd=HERE).stdout))
P["id"] = P.id.astype(str); P = P[P.year == "2026"]
L = W.query("SELECT CAST(id AS VARCHAR) id, day, name, tagline, poster, makers, daily_rank FROM launches", do_sync=False)
L["makers"] = L.makers.map(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
RK = L.dropna(subset=["daily_rank"]).set_index("id").daily_rank.to_dict()
TRUTH = {d: g.dropna(subset=["daily_rank"]) for d, g in L.groupby("day")}

def hits(order, d):
    t = TRUTH.get(d)
    if t is None or len(t) < 10: return None
    return [len(set(order[:k]) & set(t.id[t.daily_rank <= k])) / k * 100 for k in K]

def order_by(ids, score, asc=False):
    df = pd.DataFrame({"id": list(ids), "s": list(score)}); df["s"] = pd.to_numeric(df.s, errors="coerce")
    df["s"] = df.s.fillna(np.inf if asc else -np.inf)
    return df.sort_values(["s", "id"], ascending=[asc, True]).id.tolist()

# ---------- B2 track record ----------
hist = []   # (day, person, rank)
for fn in sorted(glob.glob(f"{C}/hist/202[45]/*.json")):
    d = os.path.basename(fn)[:10]
    for r in json.load(open(fn)):
        rk = pd.to_numeric(r.get("dailyRank"), errors="coerce")
        if pd.isna(rk): continue
        u = (r.get("user") or {}).get("username"); ms = [m.get("username") for m in (r.get("makers") or [])]
        for p in {u, *ms} - {None, RED, ""}: hist.append((d, p, float(rk)))
for r in L.dropna(subset=["daily_rank"]).itertuples():
    for p in {r.poster, *r.makers} - {None, RED, ""}: hist.append((r.day, p, float(r.daily_rank)))
H = pd.DataFrame(hist, columns=["day", "p", "rk"]).sort_values("day")
HBY = {p: g[["day", "rk"]].to_numpy() for p, g in H.groupby("p")}
LI = L.set_index("id")

def team(i, leaky=False):
    if i not in LI.index: return []
    r = LI.loc[i]; ms = [m for m in r.makers if m and m != RED]
    t = {r.poster} | (set(ms) if leaky else ({r.makers[-1]} if r.makers and r.makers[-1] != RED else set()))
    return [p for p in t if p]

def track(ids, d, mode="best", leaky=False):
    out = []
    for i in ids:
        rks = np.concatenate([a[a[:, 0] < d, 1].astype(float) for p in team(i, leaky) if p in HBY for a in [HBY[p]]] or [np.array([])])
        if mode == "count": out.append(float((rks <= 10).sum()) + (1e-3 * (1 / rks.min()) if len(rks) else 0))
        else: out.append(-(rks.min()) + 1e-3 * (rks <= 10).sum() if len(rks) else np.nan)
    return order_by(ids, out)

# ---------- B4 Gemini ----------
GEM = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
       "models/gemini-2.5-flash:generateContent")
PROMPT = """You are predicting Product Hunt launch-day results. Below are the {n} products featured on Product Hunt on one day.
Judge ONLY from each product's name and tagline. For EVERY product return a score 0-100 = your estimated probability (in %)
that it finishes in the day's top 5 by upvotes, and "known": true only if you specifically recognise this exact product launch.

Products:
{items}

Reply with JSON only: {{"<id>": {{"score": <0-100>, "known": <true|false>}}, ...}}"""
USE = {"in": 0, "out": 0}; LK = threading.Lock(); TOK = {"t": "", "at": 0}

def tok():
    with LK:
        if time.time() - TOK["at"] > 300:
            TOK["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); TOK["at"] = time.time()
        return TOK["t"]

def gem_day(d, ids):
    fn = f"{HERE}/llm_cache/{d}.json"
    if os.path.exists(fn): return json.load(open(fn))
    sub = LI.loc[[i for i in ids if i in LI.index]]
    items = "\n".join(f"- id {i}: {r.name} — {r.tagline}" for i, r in sub.iterrows())
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(n=len(sub), items=items)}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8000, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for a in range(5):
        try:
            req = urllib.request.Request(GEM, json.dumps(body).encode(), {"Authorization": "Bearer " + tok(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r); u = j.get("usageMetadata", {})
            txt = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
            out = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            res = {str(k): {"score": float(v.get("score", np.nan)), "known": bool(v.get("known"))} for k, v in out.items() if isinstance(v, dict)}
            with LK: USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
            os.makedirs(os.path.dirname(fn), exist_ok=True); json.dump(res, open(fn, "w")); return res
        except Exception as e:  # noqa: BLE001
            print("gemini retry", d, a, str(e)[:100], flush=True); time.sleep(5 * (a + 1))
    return {}

# ---------- PH order (B1 / h0345) ----------
def ph_order(d, hhmm, tol_min=10, late_min=2, capture=True):
    """PH's own dailyRank at the latest read in [T - tol, T] PT from the 15-min capture's official-API snapshot; else the recorder's
    rank_now read in [T - tol, T + late_min] (the recorder reads at 00:06 / 03:45:xx)."""
    T = pd.Timestamp(f"{d} {hhmm}", tz=TZ); lo = T - pd.Timedelta(minutes=tol_min)
    fn = f"{C}/live/{d}/board_ts.jsonl"
    if capture and os.path.exists(fn):
        B = pd.DataFrame([r for r in map(json.loads, open(fn)) if r.get("page") == "api_v2_ranking"])
        if len(B):
            B["a"] = pd.to_datetime(B.snapshot_ts, utc=True).dt.tz_convert(TZ); B = B[(B.a >= lo) & (B.a <= T)]
            if len(B):
                B = B[B.a == B.a.max()].copy(); B["launch_id"] = B.launch_id.astype(str)
                # PH's own rank is the API's dailyRank field (the hidden-period rank); the API list position is not ordered by it
                B["dr"] = pd.to_numeric(B.daily_rank, errors="coerce").fillna(1e6)
                return B.sort_values(["dr", "position"]).launch_id.tolist(), "capture " + B.a.max().strftime("%H:%M")
    fn = f"{C}/vs/{d}.jsonl"
    if os.path.exists(fn):
        V = pd.DataFrame([json.loads(l) for l in open(fn) if l.strip()]); V["a"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(TZ)
        V = V[(V.a >= lo) & (V.a <= T + pd.Timedelta(minutes=late_min))].dropna(subset=["rank_now"])
        if len(V):
            V = V[V.a == V.a.max()]; V["launch_id"] = V.launch_id.astype(str)
            return order_by(V.launch_id, V.rank_now, asc=True), "recorder " + V.a.max().strftime("%H:%M")
    return None, None

# ---------- B3 followers ----------
F = W.query("SELECT CAST(launch_id AS VARCHAR) launch_id, day, role, person, ph_followers, read_at FROM at_launch_followers", do_sync=False)
F["r"] = pd.to_datetime(F.read_at, utc=True).dt.tz_convert(TZ)
F = F[F.r <= pd.to_datetime(F.day).dt.tz_localize(TZ) + pd.Timedelta(minutes=15)]
FOL = F.drop_duplicates(["launch_id", "person"]).groupby("launch_id").ph_followers.sum().to_dict()

def followers(ids, d, fc=None):
    hf = dict(zip(fc.id.astype(str), fc.ph_hunter_followers)) if fc is not None and "ph_hunter_followers" in fc else {}
    s = [FOL.get(i, np.nan) if i in FOL else hf.get(i, np.nan) for i in ids]
    return order_by(ids, s) if np.isfinite(pd.to_numeric(pd.Series(s), errors="coerce")).any() else None

# ---------- scoring ----------
def boot(x, n=10000):
    x = np.asarray(x, float); rng = np.random.default_rng(0); idx = rng.integers(0, len(x), (n, len(x)))
    b = x[idx].mean(1) if x.ndim == 1 else x[idx].mean(1)
    return x.mean(0), np.percentile(b, 2.5, axis=0), np.percentile(b, 97.5, axis=0)

def table(rows, a, b):
    R = [(r[a], r[b]) for r in rows if r.get(a) is not None and r.get(b) is not None]
    if not R: return None
    A = np.array([x for x, _ in R]); Bm = np.array([y for _, y in R]); m, lo, hi = boot(A - Bm)
    return dict(n=len(R), a=A.mean(0).round(1).tolist(), b=Bm.mean(0).round(1).tolist(), diff=m.round(1).tolist(), lo=lo.round(1).tolist(), hi=hi.round(1).tolist())

def main():
    do_llm = "--llm" in sys.argv
    days = sorted(P.day.unique()); rows = []
    if do_llm:
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda d: gem_day(d, P[P.day == d].id.tolist()), days))
    for d in days:
        g = P[P.day == d]; ids = g.id.tolist(); h = hits(order_by(ids, g.arm3), d)
        if h is None: continue
        n = len(ids); rnd = [min(k, n) / n * 100 for k in K]   # expected hit rate of a random order on this line-up
        r = dict(day=d, arm3=h, random=rnd, B2=hits(track(ids, d), d), B2c=hits(track(ids, d, "count"), d), B2_leaky=hits(track(ids, d, leaky=True), d))
        fn = f"{HERE}/llm_cache/{d}.json"
        if os.path.exists(fn):
            G = json.load(open(fn)); r["B4"] = hits(order_by(ids, [G.get(i, {}).get("score", np.nan) for i in ids]), d)
            r["known"] = np.mean([G.get(i, {}).get("known", False) for i in ids])
        o, _ = ph_order(d, "00:05"); r["B1"] = hits(o, d) if o else None
        rows.append(r)
    # live nights
    live = []
    for fn in sorted(glob.glob(f"{C}/daily/forecast_*.parquet")):
        d = fn[-18:-8]; fc = pd.read_parquet(fn); fc["id"] = fc.id.astype(str); ids = fc.id.tolist()
        if hits(ids, d) is None: continue
        pub = order_by(ids, fc.published_rank, asc=True) if "published_rank" in fc and fc.published_rank.notna().any() else order_by(ids, fc.pred)
        r = dict(day=d, pub=hits(pub, d), B2=hits(track(ids, d), d))
        if "pred_arm3" in fc and fc.pred_arm3.notna().all(): r["arm3"] = hits(order_by(ids, fc.pred_arm3), d)
        o, src = ph_order(d, "00:05"); r["B1"] = hits(o, d) if o else None; r["B1_src"] = src
        o, _ = ph_order(d, "00:05", capture=False); r["B1r"] = hits(o, d) if o else None   # recorder 00:06 read on every night
        f = followers(ids, d, fc); r["B3"] = hits(f, d) if f else None
        o, src = ph_order(d, "03:45", tol_min=15); r["h0345"] = hits(o, d) if o else None; r["h0345_src"] = src
        if do_llm:
            G = gem_day(d, ids); r["B4"] = hits(order_by(ids, [G.get(i, {}).get("score", np.nan) for i in ids]), d)
        live.append(r)
    # all nights with both a 00:05 PH order and a 03:45 PH order (not only forecast nights)
    h345 = []
    for d in pd.date_range("2026-11-01", "2026-11-18").strftime("%Y-%m-%d"):
        o1, s1 = ph_order(d, "00:05"); o2, s2 = ph_order(d, "03:45", tol_min=15)
        if o1 and o2 and hits(o1, d) is not None: h345.append(dict(day=d, B1=hits(o1, d), h0345=hits(o2, d), s1=s1, s2=s2))
    out = dict(
        backtest={b: table(rows, "arm3", b) for b in ("random", "B2", "B2c", "B2_leaky", "B4", "B1")},
        backtest_levels={k: (np.mean([r[k] for r in rows if r.get(k)], 0).round(1).tolist() if any(r.get(k) for r in rows) else None)
                         for k in ("arm3", "random", "B2", "B2c", "B2_leaky", "B4", "B1")},
        backtest_days=len(rows), llm_known_share=float(np.mean([r["known"] for r in rows if "known" in r])) if any("known" in r for r in rows) else None,
        live={f"{a}-{b}": table(live, a, b) for a in ("arm3", "pub") for b in ("B1", "B1r", "B2", "B3", "B4")},
        live_levels={k: np.mean([r[k] for r in live if r.get(k)], 0).round(1).tolist() for k in ("pub", "arm3", "B1", "B1r", "B2", "B3", "B4", "h0345")},
        h0345_levels={k: np.mean([r[k] for r in h345], 0).round(1).tolist() for k in ("B1", "h0345")},
        live_days=[r["day"] for r in live], live_b1_src=sorted({r["B1_src"] for r in live if r.get("B1_src")}),
        h0345_vs_B1=table(h345, "h0345", "B1"), h0345_days=[r["day"] for r in h345], h0345_src=sorted({r["s2"] for r in h345}),
        gemini_tokens=USE)
    json.dump(out, open(f"{HERE}/result.json", "w"), indent=1, default=float)
    pd.DataFrame([{k: v for k, v in r.items()} for r in rows]).to_json(f"{HERE}/per_day_backtest.jsonl", orient="records", lines=True)
    pd.DataFrame(live).to_json(f"{HERE}/per_day_live.jsonl", orient="records", lines=True)
    print(json.dumps(out, indent=1, default=float))

if __name__ == "__main__":
    main()
