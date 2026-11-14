"""FORWARD test of the /try simulator on a past launch day (orchestrator 06:33Z Nov 13). Run each morning on the previous day
(script only, not scheduled). Everything the simulator sees is dated before the launch: the 00:05 PT read (name, tagline,
description, topics; launches missing from that read are added from the warehouse launches table, same submitted text), the site's retrieval bank (reactions_retrieval_v1, Jan 1 - Oct 24) and models (launch_band.json trained to
Nov 10; page band to Aug 31); page text only from E5's forward page read of that day (tmp/e5/band/forward/<day>/, fetched on the
launch day) when held. No Product Hunt requests: comments come from the bucket's launch-day API pulls
(raw/ph_at_launch/<day>/{api_comments,api_replies,api_comments_catchup,api_fills}/*.jsonl, union, deduplicated); team comments (hunter / makers by PH user id, and the first
top-level commenter) are dropped; launches with >= 5 remaining comments are judged.
Simulator, exactly as deployed (mvp/ph_site/try_sim.py, branch claude/ph-website): step_text (pasted path) / new_run(page read)
(page path) -> step_reactions (6 reactions), step_asks (1 question + 1 concern), step_launch (band). b20 (RECIPE_b20_concerns):
concerns on both paths, questions on the pasted path; thin-neighbour rule (PH 0.898 / page 0.886: fall back / constant).
Judge: gemini-2.5-pro, temperature 0, sees the real comments, one pooled blinded call per launch per kind (concerns, questions,
reactions) with the launch's real top points (flash extraction) -> precision (p@1 for the deployed single item, p@3 for b20, over
6 for reactions), recall of real points, top-1. Band: final daily rank inside the 10th-90th percentile rank band; within-day
Spearman of the percentile with final rank (all launches of the day with a pasted-path score).
Output: <out>/forward_sim_<day>.json (counts and scores only) and per-launch rows <out>/forward_sim_<day>_rows.jsonl (ids, labels).
    python forward_sim.py <YYYY-MM-DD> <ph-website worktree> <scratchpad> <out dir>
"""
import asyncio, glob, hashlib, html, json, os, random, re, subprocess, sys, time
import numpy as np, pandas as pd
from scipy.stats import spearmanr
DAY, WT, SP, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); HERE = os.path.dirname(os.path.abspath(__file__)); rng = np.random.default_rng(0)
for k, v in {"TRY_SIGNING_KEY": "local-dummy-key-for-offline-eval-0123456789", "TRY_LOCAL_LIMITS": "1", "TRY_GLOBAL_DAY": "100000", "TRY_PER_IP_DAY": "100000", "TRY_PER_IP_HOUR": "100000"}.items(): os.environ[k] = v
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim, person_e5  # noqa: E402
from capability import gemini_config as GC  # noqa: E402
BK = "gs://usersim-bakeoff-347838016394/usersim_sim"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
ls = lambda p: [l for l in subprocess.run(["gsutil", "ls", p], capture_output=True, text=True).stdout.split("\n") if l.strip()]
LU = json.loads(gcat(f"{BK}/raw/daily/{DAY}/today_0005.json")); _have = {str(x["id"]) for x in LU}
for _f in sorted(glob.glob(os.path.expanduser("~/.usersim_sim/launches/*.parquet"))):   # launches missing from the 00:05 read: warehouse rows, same submitted text
    try:
        _d = pd.read_parquet(_f); _d = _d[_d.day == DAY]
        for r in _d.itertuples():
            if str(r.id) in _have: continue
            try: _mk = [m for m in json.loads(r.makers) if m and not str(m).startswith("[")] if isinstance(r.makers, str) and r.makers.startswith("[") else []
            except Exception: _mk = []
            LU.append({"id": str(r.id), "name": r.name, "tagline": r.tagline, "description": r.description, "slug": r.slug, "user": {"username": r.poster} if isinstance(r.poster, str) and not r.poster.startswith("[") else {},
                       "makers": [{"username": m} for m in _mk], "_from": "warehouse"}); _have.add(str(r.id))
    except Exception: pass
CF = os.path.join(OUT, f"cache_{DAY}.json"); PREDICT = os.environ.get("FWD_PREDICT") == "1"   # nightly mode: predict every launch, freeze, no judging
FROZEN = os.environ.get("FWD_FROZEN") or f"{BK}/tmp/e5/forward_sim/{DAY}/predictions_frozen.json"
if not os.path.exists(CF) and subprocess.run(["gsutil", "-q", "cp", FROZEN, CF], capture_output=True).returncode == 0: print("restored frozen predictions", flush=True)
C = json.load(open(CF)) if os.path.exists(CF) else {}
csave = lambda: json.dump(C, open(CF, "w")); USD = {"judge": 0.0}
# ---------- comments ----------
com = {}
for sub in ("api_comments", "api_replies", "api_comments_catchup", "api_fills"):
    for f in ls(f"{BK}/raw/ph_at_launch/{DAY}/{sub}/"):
        if not f.endswith(".jsonl"): continue
        for l in gcat(f).decode().split("\n"):
            if l.strip():
                x = json.loads(l)
                if x.get("post_id") and x.get("comment_id") and x.get("body") is not None and x.get("createdAt"): com.setdefault(str(x["post_id"]), {}).setdefault(x["comment_id"], x)
clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
real = {}
for x in LU:
    # team by PH user id: comment usernames in the bucket are "[REDACTED]", so matching on usernames dropped every comment on any
    # launch with a redacted maker name (fixed 21:00Z Nov 13)
    team = {str(u.get("id")) for u in [x.get("user") or {}] + (x.get("makers") or []) if u.get("id")}
    cs = list(com.get(str(x["id"]), {}).values()); tops = sorted([(c["createdAt"], c.get("commenter_user_id")) for c in cs if not c.get("parentId")])
    first = tops[0][1] if tops else None
    keep = [clean(c["body"]) for c in sorted(cs, key=lambda c: c["createdAt"]) if str(c.get("commenter_user_id")) not in team and c.get("commenter_user_id") != first and len(clean(c["body"])) > 15]
    if len(keep) >= 5: real[str(x["id"])] = keep
# ---------- final ranks (official, if already in the warehouse cache / clean_nosite) ----------
rank = {}
for f in sorted(glob.glob(os.path.expanduser("~/.usersim_sim/launches/*.parquet"))) + [os.path.join(SP, "clean_nosite.parquet")]:
    try:
        d = pd.read_parquet(f); rc = "daily_rank" if "daily_rank" in d else "rank"; d = d[(d.day == DAY) & d[rc].notna()]
        rank.update({str(i): float(r) for i, r in zip(d.id, d[rc])})
    except Exception: pass
# ---------- page reads (E5 forward job) ----------
PR = {}
for f in ls(f"{BK}/tmp/e5/band/forward/{DAY}/"):
    if f.endswith(".json.gz"):
        try:
            import gzip; d = json.loads(gzip.decompress(gcat(f)))
            if d.get("read") and not d.get("fail"): PR[str(d["id"])] = d["read"]
        except Exception: pass
# ---------- b20 (frozen recipe) ----------
REC = open(os.path.join(HERE, "reports/retrieval_react/RECIPE_b20_concerns.md")).read(); COND = REC[REC.index("```\n") + 4:REC.index("\n```", REC.index("```\n") + 4)]
COND = COND.replace("{", "{{").replace("}", "}}").replace("{{name}}", "{n}").replace("{{tagline}}", "{t}").replace("{{text}}", "{d}").replace("{{points}}", "{p}").replace("{{what}}", "{what}")
WHAT = {"RC": "concerns, objections or feature requests", "RQ": "questions to the makers"}; PREX = {"RC": ("objection", "question", "feature request", "feature_request"), "RQ": ("question",)}
# PH-path thin rule dropped (orchestrator 14:34Z Nov 14; cached strict-judge labels, 164 launches; CORRECTED arm mapping c = deployed,
# d = constant): on thin PH launches (s1 < 0.898) b20 vs deployed ranked() concerns p@3 30.2 vs 25.3 (+4.9 [-1.2, +11.7]); always-b20
# overall vs the old recipe +1.6 [-0.4, +3.9], non-thin unchanged; best overall p@3 of the arms, and no empty lists. Page path keeps 0.886.
THR = {"ph": float(os.environ.get("B20_THR_PH", "0.0")), "page": 0.886}; CONST = {"RC": ["Pricing is unclear or too high.", "How is this different from existing alternatives?", "Concerns about data privacy and security."],
      "RQ": ["What does the pricing look like?", "Does it integrate with the tools I already use?", "Is there a free plan or trial?"],
      "RX": ["Congrats on the launch!", "How is this different from existing alternatives?", "What does the pricing look like?", "Does it integrate with the tools I already use?", "The interface looks clean and easy to use.", "Is there a free plan or trial?"]}
st = lambda s: re.sub(r"-\d+$", "", str(s))
async def cj(prompt, model="gemini-2.5-flash", tok=900, temp=0.0, tb=None):
    kw = {"thinking_budget": tb} if tb is not None else {}
    try: return GC.extract_json(await GC.gemini_chat([{"role": "user", "content": prompt}], model=model, temperature=temp, max_retries=3, max_output_tokens=tok, **kw)) or {}
    except Exception: return {}
async def b20(n, t, d, pre, path, slug):
    R = try_sim._retrieval(); q = await person_e5.embed(f"{n}. {t}. {d[:800]}"); s = R["emb"] @ q; ts = st(slug); nb = []
    for j in np.argsort(-s):
        m = R["rows"][int(j)]; ms = st(m.get("slug_stem") or "")
        if m.get("day", "0") >= DAY or ms == ts or (len(ts) >= 4 and len(ms) >= 4 and (ts in ms or ms in ts)): continue
        nb.append((int(j), float(s[j])))
        if len(nb) == 20: break
    if not nb or nb[0][1] < THR[path]: return None, (nb[0][1] if nb else None)   # thin: recipe falls back (deployed / constant)
    pts = "\n".join(f"[{i+1}] {th.split(':', 1)[1].strip()}" for i, (j, _) in enumerate(nb) for th in [x for x in R["rows"][j].get("themes", []) if x.split(":", 1)[0].strip().lower() in PREX[pre] and ":" in x][:4])
    r = await cj(COND.format(n=n, t=t, d=d[:1500], p=pts[:6000], what=WHAT[pre]), tok=600)
    return [str(x) for x in (r.get("items") or [])][:3], nb[0][1]
# ---------- judge ----------
EX = """Below are real user comments on a product launch (makers' own comments removed). Return JSON with three lists:
"critical": ONLY critical themes (objections/concerns, doubting questions, feature requests), at most 6, most frequent first;
"questions": ONLY questions users asked the makers, at most 6, most frequent first;
"points": the 6 most common distinct points of any kind (praise, questions, objections, requests, comparisons), most frequent first.
Comments:
{c}"""
ADJ = """You are adjudicating whether predicted {what} match what REAL users said in a product's launch comments.
SAME_POINT = a reader would say the item makes the same specific point ({one}) as at least one real comment. Otherwise NOT.
REAL COMMENTS:
{comments}

REAL POINTS (numbered R1..):
{real}

PREDICTED ITEMS (numbered 1..):
{items}

Return JSON {{"items": ["SAME_POINT"|"NOT" per predicted item], "real": [[numbers of the predicted items that make the same point as R1], ...one list per real point]}}"""
WD = {"RC": ("concerns", "concern, objection or request"), "RQ": ("questions", "question"), "RX": ("launch comments", "praise, question, objection, request or comparison")}
async def adj(key, comments, realp, lists, pre):
    if key in C: return C[key]
    pool = list(dict.fromkeys(x for v in lists.values() for x in v)); random.Random(key).shuffle(pool)
    if not pool or not realp: return None
    p = ADJ.format(what=WD[pre][0], one=WD[pre][1], comments="\n".join(f"- {c[:300]}" for c in comments[:40]), real="\n".join(f"R{i+1}. {x}" for i, x in enumerate(realp)), items="\n".join(f"{i+1}. {str(x)[:400]}" for i, x in enumerate(pool)))
    a = await cj(p, model="gemini-2.5-pro", tok=4000, tb=128); USD["judge"] += len(p) / 4 * 1.25e-6 + (128 + 12 * len(pool)) * 10e-6
    it, rr = a.get("items") or [], a.get("real") or []
    if len(it) != len(pool) or len(rr) != len(realp): return None
    lab = {x: str(y).upper() == "SAME_POINT" for x, y in zip(pool, it)}; idx = {x: i + 1 for i, x in enumerate(pool)}
    sets = [set(int(z) for z in (r if isinstance(r, list) else []) if str(z).isdigit()) for r in rr]
    o = {nm: {"lab": [lab[x] for x in v], "rec": float(np.mean([bool(s & {idx[x] for x in v}) for s in sets]))} for nm, v in lists.items()}
    C[key] = o; csave(); return o
# ---------- per launch ----------
async def one(x, sem):
    i = str(x["id"]); k = f"sim|{i}"
    async with sem:
        if k not in C:
            o = {"id": i}; n, t, d = x["name"], x.get("tagline") or "", " ".join(str(x.get("description") or "").split())
            ip = "fwd-" + hashlib.sha1(i.encode()).hexdigest()[:8]
            paths = {}
            if len(d) >= 80:
                try: an = await try_sim.step_text(n[:80], t[:140], d[:2000], ip); paths["ph"] = (an["token"], an["analysis"])
                except Exception as e: o["ph_err"] = type(e).__name__
            if i in PR:
                try: paths["page"] = (try_sim.new_run(PR[i]), PR[i])
                except Exception as e: o["page_err"] = type(e).__name__
            for pth, (tok, an) in paths.items():
                try: o[f"band|{pth}"] = try_sim.step_launch(tok)
                except Exception as e: o[f"band|{pth}"] = {"err": type(e).__name__}
                if i in real or PREDICT:
                    try: o[f"RX|{pth}"] = [r.get("comment") for r in (await try_sim.step_reactions(tok))["reactions"]][:6]
                    except Exception: o[f"RX|{pth}"] = []
                    try: a = await try_sim.step_asks(tok); o[f"RC|{pth}|dep"] = [a["concern"]] if a.get("concern") else []; o[f"RQ|{pth}|dep"] = [a["question"]] if a.get("question") else []
                    except Exception: pass
                    src = (n, t, d) if pth == "ph" else (an.get("name") or n, an.get("tagline") or t, an.get("page_excerpt") or "")
                    for pre in (("RC", "RQ") if pth == "ph" else ("RC",)):
                        items, s1 = await b20(*src, pre, pth, x.get("slug") or "")
                        if pre == "RQ" and pth == "ph" and items and o.get("RQ|ph|dep"):   # questions: b20 top 2 + the deployed question
                            items = list(items[:2]) + [q for q in o["RQ|ph|dep"][:1] if q not in items[:2]]   # (orchestrator 14:36Z; +3.9 [+0.8, +6.7] p@3)
                        o[f"{pre}|{pth}|b20"] = items; o[f"sim1|{pth}"] = s1
                        if pth == "ph":   # measured chance each item is judged right (sim_confidence.py; observability, order unchanged)
                            import sim_conf
                            cb, cd = sim_conf.conf(pre, items, o.get(f"{pre}|ph|dep"), s1, len(str(d).split()))
                            o[f"{pre}|ph|b20|conf"] = cb; o[f"{pre}|ph|dep|conf"] = cd
            o["pred_at"] = pd.Timestamp.now(tz="UTC").isoformat()
            if i in real and not PREDICT:
                T = await cj(EX.format(c="\n".join(f"- {c[:400]}" for c in real[i][:40])), tok=1500)
                o["real"] = {"RC": [str(z) for z in T.get("critical") or []][:3], "RQ": [str(z) for z in T.get("questions") or []][:3], "RX": [str(z) for z in T.get("points") or []][:6]}
            C[k] = o; csave()
        o = C[k]; J = {}
        if i in real and not o.get("real") and not PREDICT:   # morning: real points for a launch predicted at night (predictions untouched)
            T = await cj(EX.format(c="\n".join(f"- {c[:400]}" for c in real[i][:40])), tok=1500)
            o["real"] = {"RC": [str(z) for z in T.get("critical") or []][:3], "RQ": [str(z) for z in T.get("questions") or []][:3], "RX": [str(z) for z in T.get("points") or []][:6]}; C[k] = o; csave()
        if i in real and o.get("real"):
            for pre in ("RC", "RQ", "RX"):
                ls_ = {kk.split("|", 1)[1]: v for kk, v in o.items() if kk.startswith(pre + "|") and isinstance(v, list) and v}
                if pre == "RX": ls_ = {kk.split("|")[0] + "|dep": v for kk, v in ls_.items()}
                ls_[f"const"] = CONST[pre]
                J[pre] = await adj(f"adj|{pre}|{i}", real[i], o["real"][pre], ls_, pre)
        return o, J
async def main():
    sem = asyncio.Semaphore(4); return await asyncio.gather(*[one(x, sem) for x in LU])
t0 = time.time(); RES = asyncio.run(main())
if PREDICT:
    subprocess.run(["gsutil", "-q", "cp", "-n", CF, FROZEN])   # -n: never overwrite the first frozen copy
    print(json.dumps({"day": DAY, "mode": "predict", "lineup": len(LU), "pasted_path": sum(1 for o, _ in RES if "band|ph" in o), "page_path": sum(1 for o, _ in RES if "band|page" in o),
                      "page_reads_held": len(PR), "frozen": FROZEN, "at": pd.Timestamp.now(tz="UTC").isoformat()})); sys.exit(0)
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
g = lambda J, pre, nm, f: f(J[pre][nm]) if J.get(pre) and J[pre].get(nm) and J[pre][nm]["lab"] else np.nan
prec = lambda o: float(np.mean(o["lab"])); top1 = lambda o: float(o["lab"][0]); rec = lambda o: o["rec"]
out = {"design": __doc__.split("\n    python")[0], "day": DAY, "lineup": len(LU), "lineup_from_warehouse": sum(1 for x in LU if x.get("_from")), "judged_launches_5plus_comments": len(real), "page_reads_held": len(PR),
       "final_ranks_available": len(rank), "minutes": round((time.time() - t0) / 60, 1)}
for pre, arms in (("RC", ["ph|dep", "page|dep", "ph|b20", "page|b20", "const"]), ("RQ", ["ph|dep", "page|dep", "ph|b20", "const"]), ("RX", ["ph|dep", "page|dep", "const"])):
    o_ = {}
    for a in arms: o_[a] = {"precision": mb([g(J, pre, a, prec) for _, J in RES]), "recall": mb([g(J, pre, a, rec) for _, J in RES]), "top1": mb([g(J, pre, a, top1) for _, J in RES])}
    if pre in ("RC", "RQ"): o_["ph b20 - const p@3"] = mb([g(J, pre, "ph|b20", prec) - g(J, pre, "const", prec) for _, J in RES]); o_["ph b20 - dep top1"] = mb([g(J, pre, "ph|b20", top1) - g(J, pre, "ph|dep", top1) for _, J in RES])
    out[{"RC": "concerns", "RQ": "questions", "RX": "reactions"}[pre]] = o_
B = []
for o, _ in RES:
    for pth in ("ph", "page"):
        b = o.get(f"band|{pth}")
        if isinstance(b, dict) and "percentile" in b and o["id"] in rank: B.append((pth, o["id"], b["percentile"], b["rank_band"]["likely"], rank[o["id"]]))
band = {}
for pth in ("ph", "page"):
    rows = [r for r in B if r[0] == pth]
    if len(rows) >= 5:
        cov = [float(lo <= rk <= hi) for _, _, _, (lo, hi), rk in rows]
        band[pth] = {"n": len(rows), "coverage_10_90": mb(cov), "spearman_pct_vs_final_rank": round(float(spearmanr([r[2] for r in rows], [-r[4] for r in rows]).correlation), 3)}
out["band"] = band or "final ranks not available yet"; out["est_usd_judge"] = round(USD["judge"], 2)
json.dump(out, open(os.path.join(OUT, f"forward_sim_{DAY}.json"), "w"), indent=1, default=float)
with open(os.path.join(OUT, f"forward_sim_{DAY}_rows.jsonl"), "w") as f:
    for o, J in RES: f.write(json.dumps({"id": o["id"], "judged": bool(J), "labels": J, "band": {p: (o.get(f"band|{p}") or {}).get("percentile") for p in ("ph", "page")}, "final_rank": rank.get(o["id"])}, default=float) + "\n")
print(json.dumps({k: v for k, v in out.items() if k != "design"}, default=float)[:3000])
