"""Competitor run: (1) deployed pitch prompt on the same 14 line-ups as our own versions; (2) /try band + /try asks on the pitch text;
(3) 24-persona panel (same-topic backers, 30 days before 2026-11-12) and a 3-line summary of its concerns."""
import asyncio, json, os, re, sys, subprocess, importlib.util, numpy as np, pandas as pd, concurrent.futures as cf
SP, WT = sys.argv[1:3]; OUT = f"{SP}/comp"; HERE = "/home/user/UserSim/experiments/simlab"
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
C = json.load(open(f"{OUT}/competitors.json")); scrub = lambda s: re.sub(r"@\w+", "a user", s) if isinstance(s, str) else s
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); W = X[X.day >= "2026-09-18"]
days = sorted(W.day.unique()); wd = pd.to_datetime(pd.Series(days)).dt.weekday.values; pick = [d for w in range(7) for d in [x for x, y in zip(days, wd) if y == w][2:7:4]]
basis = "the pitch (name, tagline, description, topics)"
def one(a):
    d, i = a; g = W[W.day == d]; v = C[i]
    items = [f"[{r.id}] {r['name']} — {r.tagline}\n  topics: {', '.join(r.topics)}\n  description: {(r.description or '')[:400]}" for _, r in g.iterrows()]
    items.insert(len(items) // 2, f"[usersim] {v['name']} — {v['tagline']}\n  topics: {', '.join(v['topics'])}\n  description: {v['description'][:400]}")
    try:
        txt = llm.gemini_call(llm.PROMPT.format(n=len(items), day=d, basis=basis, items="\n".join(items)), 60 * len(items) + 500)
        res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0)); s = float(res["usersim"]["score"]); oth = np.array([float(x["score"]) for k, x in res.items() if k != "usersim"])
    except Exception: return None
    return {"i": i, "day": d, "score": s, "pct": float((oth < s).mean() + 0.5 * (oth == s).mean())}
with cf.ThreadPoolExecutor(8) as ex: R = [r for r in ex.map(one, [(d, i) for d in pick for i in range(len(C))]) if r]
T = pd.DataFrame(R); T.to_parquet(f"{OUT}/pitch.parquet"); rng = np.random.default_rng(0)
for i, c in enumerate(C):
    s = T[T.i == i].score.values
    if len(s): b = [rng.choice(s, len(s)).mean() for _ in range(2000)]; c["pitch"] = {"score": round(float(s.mean()), 1), "lo": round(float(np.percentile(b, 2.5)), 1), "hi": round(float(np.percentile(b, 97.5)), 1), "pct": round(float(T[T.i == i].pct.mean() * 100)), "calls": len(s)}
print("pitch calls", len(T), "usd", round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3), flush=True)
samp = [{"slug": f"comp-{i}", "id": f"comp{i}", "day": "2026-11-12", "poster": None, "makers": "[]", "topics": json.dumps(c["topics"]), "name": c["name"], "tagline": c["tagline"]} for i, c in enumerate(C)]
json.dump(samp, open(f"{OUT}/sample.json", "w"))
subprocess.run(f"cd {HERE} && SEG_SP={SP} PANEL_K=24 python3 persona_cards_hist.py {SP}/store_live {OUT}/sample.json {OUT}/cards.json", shell=True, check=True)
cards = json.load(open(f"{OUT}/cards.json")); sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
def panel(i):
    c = C[i]; P_ = (cards.get(f"comp-{i}") or {}).get("personas") or []
    if not P_: return i, None
    try:
        txt = llm.gemini_call(pm.PROMPT.format(name=c["name"], tagline=c["tagline"], desc=c["description"], topics=", ".join(c["topics"]), groups="\n".join(pm.gtxt(k, g) for k, g in enumerate(P_))), max(3000, 300 * len(P_)))
        Rr = json.loads(txt)["reactions"]; lines = "\n".join(f"- [{P_[int(r['group']) - 1]['segment'].split(' / ')[0]}] concern: {r.get('concern')} | question: {r.get('question')}" for r in Rr if 0 < int(r.get("group", 0)) <= len(P_))
        s = llm.gemini_call("Below are concerns and questions from a simulated panel of 24 Product Hunt voter personas about one product. Return JSON {\"top\": [three strings]}: the three most common distinct concerns, each under 14 words, plain language, most common first. Do not name any person.\n\n" + lines, 400)
        return i, {"n": len(Rr), "source_people": cards[f"comp-{i}"].get("n_source_people"), "top": [scrub(x) for x in json.loads(re.search(r"\{.*\}", s, re.S).group(0))["top"]][:3], "raw": scrub(lines)}
    except Exception as e: return i, {"error": str(e)[:150]}
with cf.ThreadPoolExecutor(6) as ex:
    for i, p in ex.map(panel, range(len(C))): C[i]["panel"] = p
print("panel done usd", round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3), flush=True)
for k, v in {"TRY_SIGNING_KEY": "local-dummy-key-for-offline-eval-0123456789", "TRY_LOCAL_LIMITS": "1", "TRY_GLOBAL_DAY": "100000", "TRY_PER_IP_DAY": "100000", "TRY_PER_IP_HOUR": "100000"}.items(): os.environ[k] = v
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim  # noqa: E402
async def tr():
    for c in C:
        try:
            an = await try_sim.step_text(c["name"][:80], c["tagline"][:140], c["description"][:2000], "10.0.0.1"); tok = an["token"]; b = try_sim.step_launch(tok); asks = await try_sim.step_asks(tok)
            c["try"] = {"percentile": b["percentile"], "likely": b["rank_band"]["likely"], "median": b["rank_band"]["median"], "top3": b["share_top3"], "top10": b["share_top10"], "concern": scrub(asks.get("concern")), "question": scrub(asks.get("question"))}
        except Exception as e: c["try"] = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
asyncio.run(tr())
json.dump({"competitors": C, "days": pick, "usd_pitch_panel": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}, open(f"{OUT}/results.json", "w"), indent=1)
for c in C: print(c["job"], "|", c["name"], "|", c.get("pitch"), "|", (c.get("finish") or {}).get("rank"), "|", {k: v for k, v in (c.get("try") or {}).items() if k in ("percentile", "median", "error")}, "|", (c.get("panel") or {}).get("top") or c.get("panel"))
