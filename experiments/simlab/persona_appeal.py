"""Persona-panel "appeal" score per launch (PREREG_persona_appeal.md). One Gemini 2.5 Flash call per launch (PH ops' llm.gemini_call,
temperature 0, JSON) with the live panel prompt (persona_prompt.py), the launch's warehouse name/tagline/description/topics (outcome-word
sentences masked in the sample file) and its persona cards (persona_cards_hist.py: upvotes on launches dated before D only).
appeal_high = share of personas with interest "high"; appeal_mean = mean interest (high 2, medium 1, low 0); n_personas.
Resumable (jsonl cache); hard stop when cumulative spend passes the cap.
    python persona_appeal.py <sample json> <cards json> <scratchpad> <out jsonl> [--cap 20]"""
import concurrent.futures as cf, json, os, sys, threading
SMP, CARDS, SP, OUT = sys.argv[1:5]; CAP = float(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 20.0
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
import persona_prompt as pm  # noqa: E402
cards = json.load(open(CARDS)); smp = json.load(open(SMP))
done = {json.loads(l)["slug"] for l in open(OUT)} if os.path.exists(OUT) else set()
SPF = OUT + ".spend.json"   # cumulative spend from the process-wide token counter (per-record deltas overlap across threads, so not used)
prev_usd = json.load(open(SPF))["usd"] if os.path.exists(SPF) else 0.0
lock = threading.Lock(); f = open(OUT, "a"); IV = {"high": 2, "medium": 1, "low": 0}
usd = lambda: prev_usd + llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50
def one(x):
    if usd() > CAP: return "cap"
    P_ = (cards.get(x["slug"]) or {}).get("personas") or []
    if not P_: return None
    tp = json.loads(x["topics"]) if isinstance(x["topics"], str) and x["topics"].startswith("[") else []
    txt = llm.gemini_call(pm.PROMPT.format(name=x["name"], tagline=x["tagline"] or "", desc=(x["description"] or "")[:1200], topics=", ".join(tp),
                                           groups="\n".join(pm.gtxt(i, g) for i, g in enumerate(P_))), 3000)
    try: R = [r for r in json.loads(txt)["reactions"] if isinstance(r, dict)]
    except Exception: R = []
    iv = [IV[r.get("interest")] for r in R if r.get("interest") in IV]
    rec = {"slug": x["slug"], "id": x["id"], "day": x["day"], "n_personas": len(P_), "n_parsed": len(iv),
           "appeal_high": (sum(v == 2 for v in iv) / len(iv)) if iv else None, "appeal_mean": (sum(iv) / len(iv)) if iv else None}
    with lock:
        f.write(json.dumps(rec) + "\n"); f.flush(); json.dump({"usd": round(usd(), 4), "tokens": llm.USAGE}, open(SPF, "w"))
    return "ok"
todo = [x for x in smp if x["slug"] not in done]
with cf.ThreadPoolExecutor(40) as ex: st = list(ex.map(one, todo))
total = round(usd(), 3)
open(os.path.join(HERE, "spend.jsonl"), "a").write(json.dumps({"t": "persona_appeal", "provider": "gcp", "usd": round(total - prev_usd, 3),
    "note": f"{st.count('ok')} Gemini 2.5 Flash calls (appeal backfill 2026-01..10), tokens in {llm.USAGE['in']} out {llm.USAGE['out']}"}) + "\n")
print(json.dumps({"called": st.count("ok"), "no_cards": st.count(None), "stopped_at_cap": st.count("cap"), "usd_cumulative": total}))
