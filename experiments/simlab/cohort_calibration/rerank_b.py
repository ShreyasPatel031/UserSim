"""SIM-RERANK-1 Stage B (PREREG addendum 7): history-built agents vote on the structural shortlist; frozen before 03:45 PT.
    python rerank_b.py <store dir> <scratchpad> <D> [--max-launches 20]"""
import concurrent.futures as cf, gzip, io, json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP, sim_model
from pipeline import warehouse
ST, SP, D = sys.argv[1:4]; NL = int(sys.argv[sys.argv.index("--max-launches") + 1]) if "--max-launches" in sys.argv else 20
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
now = pd.Timestamp.now(tz="UTC"); close = PP.close_utc(D); start = close - pd.Timedelta(days=1); deadline = start + pd.Timedelta(hours=3, minutes=45)
SL = json.loads(gcat(f"{B}/results/structural/{D}/shortlist.json") or b"{}")
SL_SRC = f"results/structural/{D}/shortlist.json"
if not SL.get("launches"):   # fallback allowed by the orchestrator until the PH agent's file lands: the frozen 00:05 forecast order
    fc = json.loads(gcat(f"{B}/results/web/forecast_0005/{D}.json") or b"{}")
    if not fc.get("forecast"): sys.exit(f"no structural shortlist or 00:05 forecast for {D}")
    SL = {"launches": [{"id": x["id"], "structural_rank": x["predicted_rank"], "structural_score": None, "name": None} for x in fc["forecast"]]}; SL_SRC = f"results/web/forecast_0005/{D}.json (fallback)"
short = sorted(SL["launches"], key=lambda x: x["structural_rank"])[:NL]
V2 = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/backer_pred_v2/{D}.parquet"))); V2["launch_id"] = V2.launch_id.astype(str)
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
INFO = {i: (n, t, tp) for i, n, t, tp in zip(W.id, W.name, W.tagline, W.topics)}; U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
H = U[(U.lday < D) & (U.ft < start)]; first = H.groupby("person_id").ft.min()
d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
active = sorted(set(H[H.lday >= d30].person_id) & COMPLETE)
TC = pd.read_parquet(os.path.join(SP, "kinds", "tracked_comments.parquet")); TC["launch_id"] = TC.launch_id.astype(str); TC["lday"] = TC.launch_id.map(dict(zip(W.id, W.day)))
TC = TC[TC.lday < D]
T0 = {str(x["id"]): x for x in json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json") or b"[]")}
def topics(i):
    t = INFO.get(i, (0, 0, None))[2]; return json.loads(t) if isinstance(t, str) and t.startswith("[") else []
def page(lid):
    f = os.path.join(SP, "forward", f"{D}_{lid}.json.gz")
    if os.path.exists(f):
        r = (json.load(gzip.open(f)) or {}).get("read")
        if isinstance(r, dict) and r.get("summary"): return f"{r.get('name', '')} - {r.get('tagline', '')}\n{r.get('summary', '')}\nTopics: {', '.join(r.get('topics') or [])}", "page_read"
    t = T0.get(lid) or {}; return f"{t.get('name', '')} - {t.get('tagline', '')}\n{str(t.get('description') or '')[:900]}", "ph_0005_text"
scrub = lambda s: re.sub(r"\s+", " ", re.sub(r"@[A-Za-z0-9_]{2,}", "", str(s)))[:220]
NDAY = max(len(T0), len(SL["launches"]))
VR = H[H.lday >= d30].groupby("person_id").apply(lambda x: len(x) / max(1, x.lday.nunique())).to_dict()
HB = H.sort_values("lday", ascending=False).drop_duplicates(["person_id", "target_id"]).groupby("person_id").target_id.apply(lambda s: list(s[:30])).to_dict()
CM = TC.sort_values("lday", ascending=False).groupby("person_id").apply(lambda x: [f"on {n}: \"{scrub(t)}\"" for n, t in zip(x.launch_name, x.text)][:5]).to_dict()
PROMPT = """You are simulating one specific, real Product Hunt user. Everything you know about them is their own activity below.
Launches they upvoted recently (newest first):
{ups}
{cms}
Today this launch appears on Product Hunt:
{page}

{rate}
Would this person upvote this one today? Answer as this person, keeping their usual rate in mind.
JSON only: {{"vote": "yes"|"no", "p": <0-100 probability they upvote>, "comment": "<one line they might write, in their voice>", "sentiment": "pos"|"neu"|"neg"}}"""
def agent(args):
    lid, pid, src, ptxt = args
    ups = "\n".join(f"- {INFO[i][0]} - {INFO[i][1]} [{', '.join(topics(i))}]" for i in HB.get(pid, []) if i in INFO) or "- (no upvotes visible)"
    cms = ("Their own past comments:\n" + "\n".join(f"- {c}" for c in CM.get(pid, []))) if CM.get(pid) else ""
    k = VR.get(pid, 0.0)
    rate = (f"On days they are active, this person upvotes about {k:.1f} of the roughly {NDAY} launches of the day (about {100 * k / max(1, NDAY):.0f}% of them)."
            if k else f"This person has upvoted nothing in the last 30 days; today there are roughly {NDAY} launches.")
    prompt = PROMPT.format(ups=ups, cms=cms, page=ptxt, rate=rate); raw = None
    try: raw = sim_model.call(prompt, 300); j = json.loads(raw)
    except Exception: j = {}
    v = str(j.get("vote", "")).lower(); p = j.get("p")
    return {"launch_id": lid, "person_id": pid, "panel": src, "vote": 1 if v == "yes" else 0 if v == "no" else np.nan,
            "p": float(p) / 100 if isinstance(p, (int, float)) else np.nan, "comment": scrub(j.get("comment", ""))[:200], "prompt": prompt, "raw": raw, "sentiment": j.get("sentiment") if j.get("sentiment") in ("pos", "neu", "neg") else None}
jobs, src_page = [], {}
for x in short:
    lid = str(x["id"]); rng = np.random.default_rng(int(lid)); ptxt, srcp = page(lid); src_page[lid] = srcp
    top = V2[V2.launch_id == lid].sort_values("p", ascending=False).person_id.head(200).tolist()
    pick = list(rng.choice(top, min(50, len(top)), replace=False)) if top else []
    rnd = [p for p in rng.choice(active, 40, replace=False) if p not in set(pick)][:20]
    jobs += [(lid, p, "backer_top", ptxt) for p in pick] + [(lid, p, "random_active", ptxt) for p in rnd]
with cf.ThreadPoolExecutor(12) as ex: A = pd.DataFrame(list(ex.map(agent, jobs)))
g = A.groupby("launch_id"); rows = []
for x in short:
    lid = str(x["id"]); a = A[A.launch_id == lid]; s = a.sentiment.value_counts(normalize=True)
    rows.append({"id": lid, "name": x.get("name"), "structural_rank": x["structural_rank"], "structural_score": x.get("structural_score"), "agents": int(a.vote.notna().sum()),
                 "yes_share": float(a.vote.mean()) if a.vote.notna().any() else None, "mean_p": float(a.p.mean()) if a.p.notna().any() else None,
                 "yes_share_backer_top": float(a[a.panel == "backer_top"].vote.mean()) if (a.panel == "backer_top").any() else None,
                 "yes_share_random": float(a[a.panel == "random_active"].vote.mean()) if (a.panel == "random_active").any() else None,
                 "sentiment": {k: round(float(s.get(k, 0)), 3) for k in ("pos", "neu", "neg")}, "page_source": src_page[lid]})
R = pd.DataFrame(rows); ys = R.yes_share.fillna(R.yes_share.mean()); zz = (ys - ys.mean()) / (ys.std() + 1e-9)
R["key"] = R.structural_rank - 2 * zz; R = R.sort_values(["key", "structural_rank"]); R["rerank"] = np.arange(1, len(R) + 1)
out = {"day": D, "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "predicted_at": pd.Timestamp.now(tz="UTC").isoformat(), "before_0345_pt": bool(pd.Timestamp.now(tz="UTC") < deadline), "freeze_deadline": pd.Timestamp(f"{D} 03:30", tz="America/Los_Angeles").tz_convert("UTC").isoformat(), "before_0330_pt": bool(pd.Timestamp.now(tz="UTC") < pd.Timestamp(f"{D} 03:30", tz="America/Los_Angeles").tz_convert("UTC")), "prereg": "PREREG.md addendum 7",
       "model": sim_model.MODEL, "rule": "key = structural_rank - 2 * z(yes share), z within the shortlist", "shortlist_source": SL_SRC,
       "agents_total": int(A.vote.notna().sum()), "agent_calls": len(A), "usd": sim_model.usd(),
       "launches": R.drop(columns=["key"]).to_dict("records"),
       "leak": "agents see only their own upvotes/comments on launches before D (reads before D's start) and the launch page; no counts, ranks or others' comments"}
cal = os.path.join(tempfile.gettempdir(), f"rerank_{D}.json"); json.dump(out, open(cal, "w"), indent=1, default=float)
DRY = "--dry" in sys.argv
if not DRY: subprocess.run(["gsutil", "-q", "cp", cal, f"{B}/results/calibration/{D}/rerank_frozen.json"], check=True)
pv = os.path.join(tempfile.gettempdir(), f"agents_{D}.parquet"); A.to_parquet(pv, index=False)
if not DRY: subprocess.run(["gsutil", "-q", "cp", pv, f"{B}/tmp/e5/private/agents/{D}.parquet"], check=True)   # private: salted ids + synthetic comments
print(json.dumps({k: v for k, v in out.items() if k != "launches"}, default=float)); print(R[["structural_rank", "rerank", "yes_share", "mean_p", "agents"]].to_string(index=False))
(open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a") if not DRY else open(os.devnull, "w")).write(json.dumps({"t": "sim_rerank_b", "day": D, "provider": "gcp", "usd": out["usd"], "calls": len(A)}) + "\n")
