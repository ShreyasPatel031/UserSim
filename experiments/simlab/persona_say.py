"""Persona-panel "say" (website item 2; Gemini authorised by Shreyas in this session, Nov 15). One Gemini 2.5 Flash call per launch (PH ops'
llm.gemini_call, temperature 0, JSON), given the launch's 00:05 text (name, tagline, description, topics) and its persona cards
(tmp/e5/persona_cards/<day>.json: each persona aggregates >= 20 held people of one segment; topic shares and products they commonly upvoted;
no usernames, ids or headlines). Returns per persona: a short reaction in that audience's voice, one concern, one question. Merged into
results/web/explain/<day>.json say.persona_panel (each item tagged with its persona's segment and people count). Spend logged to spend.jsonl.
    python persona_say.py <day> <scratchpad> [--no-upload] [--limit N]"""
import concurrent.futures as cf, json, os, subprocess, sys
D, SP = sys.argv[1:3]; UP = "--no-upload" not in sys.argv; LIM = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
cards = json.loads(gcat(f"{B}/tmp/e5/persona_cards/{D}.json") or open(os.path.join(SP, "persona", f"persona_cards_{D}.json")).read())["launches"]
line = {str(p["id"]): p for p in json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json"))}
PROMPT = """You simulate how distinct audience groups on Product Hunt react to a product launch. Each group below is a real aggregate of
20 or more Product Hunt users (their role, how active they are, the topics they upvote and products they commonly upvoted). Speak as a
typical member of each group, in a short Product Hunt comment voice. Be specific to THIS product; do not praise generically.

LAUNCH
Name: {name}
Tagline: {tagline}
Description: {desc}
Topics: {topics}

GROUPS
{groups}

For EVERY group (same order), return JSON only:
{{"reactions": [{{"group": <number>, "reaction": "<1-2 sentences>", "concern": "<one specific concern or objection>", "question": "<one question they would ask the makers>", "interest": "high"|"medium"|"low"}}, ...]}}"""
def gtxt(i, g):
    tops = ", ".join(f"{t['topic']} {round(100 * t['share'])}%" for t in g.get("topic_shares", []))
    prods = ", ".join(p["product"] for p in g.get("products_they_commonly_upvoted", [])[:5])
    return f"{i + 1}. {g['segment']} ({g['n_people']} people; median {g['median_upvotes_last_30_days']:.0f} upvotes in 30 days); upvote topics: {tops}; products they upvoted: {prods}"
def one(lid):
    c = cards.get(lid) or {}; P_ = c.get("personas") or []; p = line.get(lid)
    if not P_ or not p: return lid, None
    topics = ", ".join(e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or []))
    txt = llm.gemini_call(PROMPT.format(name=p.get("name"), tagline=p.get("tagline"), desc=(p.get("description") or "")[:1200], topics=topics,
                                        groups="\n".join(gtxt(i, g) for i, g in enumerate(P_))), 3000)
    try: R = json.loads(txt)["reactions"]
    except Exception: return lid, {"status": "not available (model reply not parseable)"}
    items = []
    for r in R:
        k = int(r.get("group", 0)) - 1
        if 0 <= k < len(P_): items.append({"segment": P_[k]["segment"], "n_people": P_[k]["n_people"], **({"segment_profile": P_[k]["segment_profile"]} if P_[k].get("segment_profile") else {}), "reaction": r.get("reaction"), "concern": r.get("concern"),
                                           "question": r.get("question"), "interest": r.get("interest")})
    return lid, {"source_people": c.get("source"), "items": items}
ids = [i for i in line if (cards.get(i) or {}).get("personas")][:LIM]
with cf.ThreadPoolExecutor(6) as ex: OUT = dict(ex.map(one, ids))
usd = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
open(os.path.join(HERE, "spend.jsonl"), "a").write(json.dumps({"t": f"persona_say_{D}", "provider": "gcp", "usd": usd, "note": f"{len(ids)} Gemini 2.5 Flash calls, tokens in {llm.USAGE['in']} out {llm.USAGE['out']}"}) + "\n")
LABEL = ("persona panel: Gemini 2.5 Flash speaking as up to 24 groups of this launch's likely voters (team's earlier voters when >= 20, else the "
         "CF-only top 200), each >= 20 real people of one data-driven segment (kind of user: activity, making, followers, curation, links, comments, "
         "taste; k chosen by held-out fit; profiles in results/web/segments/latest.json), grounded in what that segment says in its own past comments "
         "(paraphrased). Given only the launch's 00:05 text. Simulated, not real comments. Validated on 276 past launches against real PH comments "
         "(segments fit before every launch): recall of points raised 64.8% [62.2, 67.3] vs 54.3% for the previous 12-persona panel (paired +10.5 "
         "[8.1, 12.9]), precision +5.6 [1.6, 9.7], real complaints caught 23.7% (unchanged, +0.2 [-3.0, 3.3]). Panel interest does not predict "
         "rank beyond the rank model (within-day Spearman with its residual -0.01 [-0.05, 0.02]); read it as likely reactions, not a forecast")

p = os.path.join(SP, "explain", f"{D}.json")
J = json.loads(gcat(f"{B}/results/web/explain/{D}.json") or open(p).read())
for lid, v in OUT.items():
    if lid in J["launches"] and v:
        J["launches"][lid].setdefault("say", {})["persona_panel"] = {**v, "accuracy_label": LABEL}
os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(J, open(p, "w"), indent=1)
if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/explain/{D}.json"], check=True)
print(json.dumps({"day": D, "launches": len(ids), "with_panel": sum(1 for v in OUT.values() if v and v.get("items")), "usd": usd, "tokens": llm.USAGE}))
