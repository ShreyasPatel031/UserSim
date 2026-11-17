"""Chain stage runner. For one stage: pitch-score our 3 versions and the competitors (deployed prompt, 14 real line-ups); standard 24-persona
panel on our best version and on competitors; FORCED-CHOICE panel (each persona sees the product inside a real day's line-up, picks 3 to back,
gives one reason it would not use ours) for ours and 3 competitors; real comments on competitors' launches from held captures, tagged to themes."""
import asyncio, json, os, re, sys, subprocess, importlib.util, gzip, glob, html, collections, numpy as np, pandas as pd, concurrent.futures as cf
SP, STAGE = sys.argv[1], sys.argv[2]; OUT = f"{SP}/chain"; HERE = "/home/user/UserSim/experiments/simlab"
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
usd = lambda: round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3); scrub = lambda s: re.sub(r"@\w+", "", s) if isinstance(s, str) else s
CFG = json.load(open(f"{OUT}/stage{STAGE}.json")); OURS = CFG["ours"]; COMP = CFG["competitors"]
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); W = X[X.day >= "2026-09-18"]
CACHE = {c["name"]: c for c in json.load(open(f"{SP}/comp/results.json"))["competitors"]}
for st in "1234":
    if st < STAGE and os.path.exists(f"{OUT}/out{st}.json"):
        for c in json.load(open(f"{OUT}/out{st}.json"))["competitors"]: CACHE.setdefault(c["name"], c)
for c in COMP:
    if "tagline" not in c:
        r = X[(X.name == c["name"]) & ((X.day == c["day"]) if c.get("day") else True)].sort_values("day").iloc[-1]
        c.update({"tagline": r.tagline, "description": r.description, "topics": list(r.topics)[:3], "source": "held",
                  "finish": {"day": r.day, "rank": int(r.dailyRank), "launches_that_day": int(r.ph_day_n_launches), "votes": int(r.votes), "hunter_prior_hunts": int(r.hist_hunter_n)}})
    else: c.setdefault("finish", None); c.setdefault("source", "web")
    k = CACHE.get(c["name"]) or {}
    for f in ("pitch", "panel"):
        if k.get(f) and f not in c: c[f] = k[f]
days = sorted(W.day.unique()); wd = pd.to_datetime(pd.Series(days)).dt.weekday.values; pick = [d for w in range(7) for d in [x for x, y in zip(days, wd) if y == w][2:7:4]]
basis = "the pitch (name, tagline, description, topics)"
ENT = [dict(v, topics=OURS["topics"], _k=("ours", i)) for i, v in enumerate(OURS["variants"])] + [dict(c, _k=("comp", i)) for i, c in enumerate(COMP)]
def one(a):
    d, e = a; g = W[W.day == d]
    items = [f"[{r.id}] {r['name']} — {r.tagline}\n  topics: {', '.join(r.topics)}\n  description: {(r.description or '')[:400]}" for _, r in g.iterrows()]
    items.insert(len(items) // 2, f"[usersim] {e['name']} — {e['tagline']}\n  topics: {', '.join(e['topics'])}\n  description: {e['description'][:400]}")
    try:
        txt = llm.gemini_call(llm.PROMPT.format(n=len(items), day=d, basis=basis, items="\n".join(items)), 60 * len(items) + 500)
        res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0)); s = float(res["usersim"]["score"]); oth = np.array([float(x["score"]) for k, x in res.items() if k != "usersim"])
        return e["_k"], s, float((oth < s).mean() + 0.5 * (oth == s).mean())
    except Exception: return None
todo = [e for e in ENT if not (e["_k"][0] == "comp" and COMP[e["_k"][1]].get("pitch")) and not (e["_k"][0] == "ours" and OURS["variants"][e["_k"][1]].get("pitch"))]
with cf.ThreadPoolExecutor(8) as ex: R = [r for r in ex.map(one, [(d, e) for d in pick for e in todo]) if r]
rng = np.random.default_rng(0); by = collections.defaultdict(list)
for k, s, p in R: by[k].append((s, p))
for k, v in by.items():
    s = np.array([a for a, _ in v]); b = [rng.choice(s, len(s)).mean() for _ in range(2000)]
    P = {"score": round(float(s.mean()), 1), "lo": round(float(np.percentile(b, 2.5)), 1), "hi": round(float(np.percentile(b, 97.5)), 1), "pct": round(float(np.mean([p for _, p in v]) * 100)), "calls": len(s)}
    (OURS["variants"] if k[0] == "ours" else COMP)[k[1]]["pitch"] = P
bi = int(np.argmax([v["pitch"]["score"] for v in OURS["variants"]])); BEST = dict(OURS["variants"][bi], topics=OURS["topics"]); OURS["best"] = bi
print("pitch usd", usd(), [(v["tagline"][:40], v["pitch"]["score"]) for v in OURS["variants"]], flush=True)
ALL = [BEST] + COMP
samp = [{"slug": f"e-{i}", "id": f"e{i}", "day": "2026-11-12", "poster": None, "makers": "[]", "topics": json.dumps(e["topics"]), "name": e["name"], "tagline": e["tagline"]} for i, e in enumerate(ALL)]
json.dump(samp, open(f"{OUT}/sample{STAGE}.json", "w"))
subprocess.run(f"cd {HERE} && SEG_SP={SP} PANEL_K=24 python3 persona_cards_hist.py {SP}/store_live {OUT}/sample{STAGE}.json {OUT}/cards{STAGE}.json > /dev/null", shell=True, check=True)
cards = json.load(open(f"{OUT}/cards{STAGE}.json")); sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
PERS = lambda i: (cards.get(f"e-{i}") or {}).get("personas") or (cards.get("e-0") or {}).get("personas") or []
grp = lambda p: p["segment"].split(" / ")[0]
def panel(i):
    e = ALL[i]; P_ = PERS(i)
    try:
        Rr = json.loads(llm.gemini_call(pm.PROMPT.format(name=e["name"], tagline=e["tagline"], desc=e["description"], topics=", ".join(e["topics"]), groups="\n".join(pm.gtxt(k, g) for k, g in enumerate(P_)), ), max(3000, 300 * len(P_))))["reactions"]
        lines = [f"[{grp(P_[int(r['group']) - 1])}] concern: {r.get('concern')} | question: {r.get('question')}" for r in Rr if 0 < int(r.get("group", 0)) <= len(P_)]
        if i == 0: return i, {"lines": lines, "source_people": (cards.get("e-0") or {}).get("n_source_people")}
        s = llm.gemini_call("Below are concerns and questions from a simulated panel of 24 Product Hunt voter personas about one product. Return JSON {\"top\": [three strings]}: the three most common distinct concerns, each under 14 words, plain language, most common first. Do not name any person.\n\n" + "\n".join(lines), 400)
        return i, {"top": [scrub(x) for x in json.loads(re.search(r"\{.*\}", s, re.S).group(0))["top"]][:3]}
    except Exception as ex_: return i, {"error": str(ex_)[:120]}
fdays = [d for d in pick if 20 <= len(W[W.day == d]) <= 40][:3]
FCP = """You simulate a panel of Product Hunt voter personas. Each persona stands for a group of real voters and is described below.
Today's Product Hunt line-up is listed after the personas. Each persona can back exactly 3 products today. Choose as that persona would, from what it has backed before; most products get no vote from most personas.
Also say where product {code} would sit if this persona ordered the whole line-up from most to least likely to back (1 = first, {n} = last); be honest, most products sit in the middle or lower.
Then, for product {code} only, give the single strongest reason this persona would NOT use it (under 18 words, specific to the product, no person names). Give the reason even if the persona picked it.
Return JSON: {{"personas": [{{"group": <persona number>, "picks": ["<code>", "<code>", "<code>"], "place": <integer 1..{n}>, "why_not": "..."}}]}} with one entry per persona.

PERSONAS
{groups}

LINE-UP ({n} products)
{items}
"""
def fc(a):
    i, d = a; e = ALL[i]; P_ = list({p["segment"]: p for p in PERS(i)}.values()); g = W[W.day == d].reset_index(drop=True); items = [(r["name"], r.tagline, (r.description or "")[:160]) for _, r in g.iterrows()]; pos = (len(items) * (3 + i)) // 7 % (len(items) + 1); items.insert(pos, (e["name"], e["tagline"], e["description"][:160]))
    code = f"L{pos + 1}"; txt_items = "\n".join(f"[L{k + 1}] {n} — {t}. {ds}" for k, (n, t, ds) in enumerate(items))
    try:
        res = json.loads(re.search(r"\{.*\}", llm.gemini_call(FCP.format(code=code, groups="\n".join(pm.gtxt(k, gg) for k, gg in enumerate(P_)), n=len(items), items=txt_items), 4500), re.S).group(0))["personas"]
        return i, d, len(items), [(grp(P_[int(r["group"]) - 1]), code in [str(x).strip("[]") for x in r.get("picks", [])], scrub(r.get("why_not")), float(r.get("place") or len(items)) / len(items), P_[int(r["group"]) - 1]["n_people"]) for r in res if 0 < int(r.get("group", 0)) <= len(P_)]
    except Exception as ex_: return i, d, len(items), None
fci = [0] + [i + 1 for i, c in enumerate(COMP) if c.get("fc")]
with cf.ThreadPoolExecutor(8) as ex:
    pj = list(ex.map(panel, [0] + [i + 1 for i, c in enumerate(COMP) if not c.get("panel")])); fj = list(ex.map(fc, [(i, d) for i in fci for d in fdays]))
for i, p in pj:
    if i == 0: OURS["panel"] = p
    else: COMP[i - 1]["panel"] = p
FC = collections.defaultdict(list); NS = []
for i, d, n, rows in fj:
    NS.append(n)
    if rows: FC[i] += rows
def fcsum(rows):
    g = collections.defaultdict(list)
    for gr, pk, _, pl, w in rows: g[gr].append((pk, pl, w))
    f = lambda v: {"picked_top3": round(100 * np.average([a for a, _, _ in v], weights=[w for _, _, w in v]), 1), "placed_top_third": round(100 * np.average([b <= 1 / 3 for _, b, _ in v], weights=[w for _, _, w in v]), 1), "mean_place_pct": round(100 * np.average([b for _, b, _ in v], weights=[w for _, _, w in v])), "n": len(v)}
    return dict(f([x[1:] if False else (x[1], x[3], x[4]) for x in rows]), share_all=f([(x[1], x[3], x[4]) for x in rows])["picked_top3"], by_group={k: f(v) for k, v in g.items()})
OURS["forced_choice"] = dict(fcsum(FC[0]), chance=round(300 / np.mean(NS), 1), days=fdays) if FC[0] else None
for i in fci[1:]: COMP[i - 1]["forced_choice"] = fcsum(FC[i]) if FC[i] else None
print("panel+fc usd", usd(), flush=True)
# real comments on competitors' launches, by name match in held captures
names = {c["name"] for c in COMP if c["source"] == "held"} | set(CFG.get("extra_comment_names", [])); raw = collections.defaultdict(dict); team = collections.defaultdict(set)
clean = lambda b: re.sub(r"@\w+", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b or "")))).strip()
for f in sorted(glob.glob(f"{SP}/rb/h25data/comments/*.jsonl.gz")):
    with gzip.open(f, "rt") as fh:
        for line in fh:
            try: post = json.loads(json.loads(line)["html"])["data"]["post"]
            except Exception: continue
            if not post or post.get("name") not in names: continue
            def add(n):
                u = n.get("user") or {}; bl = json.dumps(n.get("badges") or []).lower()
                if "maker" in bl or "hunter" in bl or str(u.get("id")) == str((post.get("user") or {}).get("id")): team[post["name"]].add(u.get("id"))
                raw[post["name"]][n["id"]] = (u.get("id"), clean(n.get("body") or n.get("bodyHtml")))
            for e in post["threads"]["edges"]:
                add(e["node"])
                for e2 in (e["node"].get("replies") or {}).get("edges") or []: add(e2["node"])
code = {}; lines = []
for nm in raw:
    for cid, (u, t) in raw[nm].items():
        if u in team[nm] or len(t) <= 15: continue
        lines.append(f"[{code.setdefault((nm, u), f'c{len(code) + 1}')} | {nm}] {t[:600]}")
CM = {"products": sorted(raw), "n_commenters": len(code), "themes": []}
if lines:
    PR = """Below are real comments left by Product Hunt users on the launches of several products that do a similar job. Team replies are removed.
Each line: [commenter code | product] comment.
Group what the commenters said into themes. A theme has a kind: "asked" (a feature or answer they asked for), "complained" (a complaint, doubt or worry) or "praised" (something they liked).
A theme must be specific to what the product does (not congratulations). Merge near-duplicates aggressively: aim for at most 14 themes. For each theme list every commenter code that raised it.
Return JSON: {"themes": [{"kind": "...", "theme": "<under 16 words, plain language, no person names>", "commenters": ["c1", ...], "products": ["..."]}]}
Do not name any person.

"""
    try:
        th = json.loads(re.search(r"\{.*\}", llm.gemini_call(PR + "\n".join(lines[:260]), 6000), re.S).group(0))["themes"]
        CM["themes"] = sorted([{"kind": t["kind"], "theme": scrub(t["theme"]), "n": len(set(t.get("commenters", [])) & set(code.values())), "products": sorted(set(t.get("products", [])))} for t in th], key=lambda t: -t["n"])
    except Exception as ex_: CM["error"] = str(ex_)[:100]
# themes in our own panel feedback (standard panel + forced-choice reasons)
OT = None
if OURS.get("panel", {}).get("lines"):
    L2 = OURS["panel"]["lines"] + [f"[{g}] reason not to use: {w}" for g, _, w, _, _ in FC[0] if w]
    PR2 = """Below is feedback on ONE product from a simulated panel of Product Hunt voter personas. Each line starts with the persona's voter group in brackets.
Group the feedback into at most 10 themes. Kinds: "asked" (wants a feature or an answer), "doubt" (a reason not to use it or a worry).
Return JSON: {"themes": [{"kind": "...", "theme": "<under 16 words, plain, specific>", "lines": <number of lines raising it>, "groups": ["<voter group>", ...]}]} sorted by lines, most first.

"""
    try: OT = json.loads(re.search(r"\{.*\}", llm.gemini_call(PR2 + "\n".join(L2), 3000), re.S).group(0))["themes"]
    except Exception as ex_: OT = [{"error": str(ex_)[:100]}]
OURS["panel_themes"] = OT; OURS["panel"] = {"source_people": OURS.get("panel", {}).get("source_people"), "n_lines": len(OURS.get("panel", {}).get("lines") or [])}
json.dump({"stage": STAGE, "ours": OURS, "competitors": COMP, "comments": CM, "usd": usd(), "pitch_days": pick}, open(f"{OUT}/out{STAGE}.json", "w"), indent=1)
print("usd", usd()); print("OURS best", bi + 1, [(i + 1, v["pitch"]) for i, v in enumerate(OURS["variants"])]); print("FC ours", json.dumps(OURS["forced_choice"]))
for t in OT or []: print("  OT", json.dumps(t)[:230])
for c in COMP: print("C|", c["name"], "|", c.get("pitch", {}).get("score"), "|", (c["finish"] or {}).get("rank"), "/", (c["finish"] or {}).get("launches_that_day"), "| fc", {k: v for k, v in (c.get("forced_choice") or {}).items() if k != "by_group"}, "|", (c.get("panel") or {}).get("top"))
print("COMMENTS", CM["products"], CM["n_commenters"], CM.get("error"))
for t in CM["themes"]: print(f"  {t['n']:>2} {t['kind']:<10} {t['theme']} {t['products']}")
