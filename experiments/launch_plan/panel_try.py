"""Step 3: (a) the 24-persona panel (persona_prompt.py, the live prompt) on each candidate's best pitch; persona cards from the same-topic
backer pool of the 30 days before 2026-11-12 (the launch has no team history), built by persona_cards_hist.py; (b) the /try simulator's pasted
path exactly as deployed (try_sim.step_text -> step_launch band, step_reactions, step_asks)."""
import asyncio, json, os, sys, subprocess, importlib.util
SP, WT = sys.argv[1:3]; OUT = f"{SP}/selfplan"; HERE = "/home/user/UserSim/experiments/simlab"
C = json.load(open(f"{OUT}/candidates.json")); BEST = json.loads(sys.argv[3])
samp = [{"slug": f"usersim-{c.lower()}", "id": f"self{c}", "day": "2026-11-12", "poster": None, "makers": "[]", "topics": json.dumps(C[c]["default_topics"]), "name": C[c]["variants"][BEST[c]]["name"], "tagline": C[c]["variants"][BEST[c]]["tagline"]} for c in C]
json.dump(samp, open(f"{OUT}/self_sample.json", "w"))
subprocess.run(f"cd {HERE} && SEG_SP={SP} PANEL_K=24 python3 persona_cards_hist.py {SP}/store_live {OUT}/self_sample.json {OUT}/self_cards.json", shell=True, check=True)
cards = json.load(open(f"{OUT}/self_cards.json"))
sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
res = {}
for c in C:
    v = C[c]["variants"][BEST[c]]; P_ = (cards.get(f"usersim-{c.lower()}") or {}).get("personas") or []
    if not P_: res[c] = {"panel": None, "note": cards.get(f"usersim-{c.lower()}")}; continue
    txt = llm.gemini_call(pm.PROMPT.format(name=v["name"], tagline=v["tagline"], desc=v["description"], topics=", ".join(C[c]["default_topics"]), groups="\n".join(pm.gtxt(i, g) for i, g in enumerate(P_))), max(3000, 300 * len(P_)))
    try: R = json.loads(txt)["reactions"]
    except Exception: R = []
    items = [{"segment": P_[int(r["group"]) - 1]["segment"], "n_people": P_[int(r["group"]) - 1]["n_people"], "reaction": r.get("reaction"), "concern": r.get("concern"), "question": r.get("question"), "interest": r.get("interest")} for r in R if 0 < int(r.get("group", 0)) <= len(P_)]
    res[c] = {"variant": BEST[c] + 1, "source_people": cards[f"usersim-{c.lower()}"].get("source"), "n_source_people": cards[f"usersim-{c.lower()}"].get("n_source_people"), "panel": items}
    print("panel", c, len(items), flush=True)
for k, v in {"TRY_SIGNING_KEY": "local-dummy-key-for-offline-eval-0123456789", "TRY_LOCAL_LIMITS": "1", "TRY_GLOBAL_DAY": "100000", "TRY_PER_IP_DAY": "100000", "TRY_PER_IP_HOUR": "100000"}.items(): os.environ[k] = v
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim  # noqa: E402
async def tr():
    for c in C:
        v = C[c]["variants"][BEST[c]]
        try:
            an = await try_sim.step_text(v["name"][:80], v["tagline"][:140], v["description"][:2000], "10.0.0.1"); tok = an["token"]
            band = try_sim.step_launch(tok); rx = (await try_sim.step_reactions(tok)).get("reactions"); asks = await try_sim.step_asks(tok)
            res[c]["try"] = {"band": band, "reactions": [r.get("comment") for r in (rx or [])][:6], "concern": asks.get("concern"), "question": asks.get("question")}
        except Exception as e: res[c]["try"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print("try", c, json.dumps(res[c]["try"])[:400], flush=True)
asyncio.run(tr())
json.dump({"results": res, "usd_panel": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}, open(f"{OUT}/panel_try.json", "w"), indent=1)
