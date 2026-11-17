"""Complaint / question recall before launch: which method names most of what real users later complain about or ask?
Test set: 150 held 2026 launches (Aug 1 - Nov 10) with >= 8 real comments from non-team users, sampled at random (seed 0) from those with a
launch embedding. Truth: real comments tagged to complaint and question themes (Gemini), counted by distinct commenters.
Arms (pre-launch inputs only): A persona panel as deployed; B persona-free prompt on the pitch; C retrieval (non-team comments on the 5 most
similar earlier launches, written before the target's launch day, same hunter/makers excluded); D = A + C; F = B + C; E task-run prompt on the
held site capture (6 personas x 6 tasks, text only), with B_site (persona-free with the same site text) as its control.
Every arm returns 10 ranked complaints and 10 ranked questions. One blind judge call per launch and kind matches all arms' items to the real themes."""
import json, os, re, sys, subprocess, importlib.util, threading, numpy as np, pandas as pd, concurrent.futures as cf
SP = sys.argv[1]; OUT = f"{SP}/cr"; HERE = "/home/user/UserSim/experiments/simlab"; STOP = float(os.environ.get("USD_STOP", 12)); NT = int(os.environ.get("N_TEST", 150))
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
usd = lambda: llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5; lock = threading.Lock(); scrub = lambda s: re.sub(r"@\w+", "", str(s))
X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "day", "name", "tagline", "description", "topics", "hunter_id", "maker_ids"]); X["id"] = X.id.astype(str); X = X.drop_duplicates("id").set_index("id")
C = pd.read_parquet(f"{OUT}/comments.parquet"); C = C[(~C.team) & (C.text.str.len() > 15)]; cnt = C.groupby("launch_id").size()
z = np.load(f"{SP}/rb/h25data/emb.npz", allow_pickle=True); eid = [str(x) for x in z["launch_ids"]]; EM = z["launch"] / np.linalg.norm(z["launch"], axis=1, keepdims=True); epos = {i: k for k, i in enumerate(eid)}
team = {i: {str(r.hunter_id)} | {str(m) for m in (r.maker_ids if r.maker_ids is not None else [])} for i, r in X.iterrows()}
cand = sorted(i for i in cnt[cnt >= 8].index if X.day[i] >= "2026-08-01" and i in epos); test = sorted(np.random.default_rng(0).choice(cand, min(NT, len(cand)), replace=False))
pool = [i for i in cnt[cnt >= 3].index if i in epos]
SITES = {}
for l in open(f"{SP}/rb/h25data/sites_ph.jsonl"):
    r = json.loads(l)
    if str(r.get("status")) == "200" and str(r.get("parked")) != "True" and len(r.get("text") or "") > 500: SITES[str(r["id"])] = r["text"]
def cache(name, ids, fn, workers=10):
    path = f"{OUT}/{name}.jsonl"; done = {json.loads(l)["id"]: json.loads(l) for l in open(path)} if os.path.exists(path) else {}
    def w(i):
        if usd() > STOP: return
        try:
            v = fn(i)
            if v is not None:
                with lock: open(path, "a").write(json.dumps({"id": i, "v": v}) + "\n"); done[i] = {"id": i, "v": v}
        except Exception as e:
            with lock: open(f"{OUT}/err.log", "a").write(f"{name} {i} {type(e).__name__} {str(e)[:150]}\n")
    with cf.ThreadPoolExecutor(workers) as ex: list(ex.map(w, [i for i in ids if i not in done]))
    print(name, len(done), "of", len(ids), "usd", round(usd(), 2), flush=True); return {i: done[i]["v"] for i in ids if i in done}
J = lambda t: json.loads(re.search(r"\{.*\}", t, re.S).group(0))
pitch = lambda i: f"Product: {X.name[i]} — {X.tagline[i]}\nTopics: {', '.join(list(X.topics[i])[:4])}\nDescription: {(X.description[i] or '')[:600]}"
# truth
def truth(i):
    g = C[C.launch_id == i]; code = {u: f"c{k + 1}" for k, u in enumerate(g.uid.unique())}
    t = J(llm.gemini_call("Below are real comments left by Product Hunt users on one product launch (team replies removed). Each line: [commenter code] comment.\n"
        "List the distinct COMPLAINTS (complaints, doubts, worries, things missing or broken) and the distinct QUESTIONS (things commenters asked the makers) that they raised. Be specific to this product; ignore praise and congratulations; merge near-duplicates; at most 12 of each. A point can be both only if two different commenters framed it differently.\n"
        "Return JSON: {\"complaints\": [{\"theme\": \"<under 18 words>\", \"commenters\": [\"c1\"]}], \"questions\": [{\"theme\": \"...\", \"commenters\": [\"c2\"]}]}\n\n" + "\n".join(f"[{code[u]}] {t[:500]}" for u, t in zip(g.uid, g.text)), 3000))
    f = lambda L: [{"theme": scrub(x["theme"]), "n": len(set(x.get("commenters", [])) & set(code.values()))} for x in L if len(set(x.get("commenters", [])) & set(code.values()))]
    return {"complaints": f(t.get("complaints", [])), "questions": f(t.get("questions", [])), "n_commenters": len(code), "n_comments": len(g)}
T = cache("truth", test, truth)
FMT = 'Return JSON only: {"complaints": ["<under 18 words>", ... exactly 10, most likely first], "questions": ["<under 18 words>", ... exactly 10, most likely first]}'
ASK = "Predict what real Product Hunt commenters will say on launch day: the 10 complaints, doubts or worries they are most likely to raise, and the 10 questions they are most likely to ask the makers. Be specific to this product."
lst = lambda v: {"complaints": [scrub(x) for x in v.get("complaints", [])][:10], "questions": [scrub(x) for x in v.get("questions", [])][:10]}
B = cache("armB", test, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\n{ASK}\n{FMT}", 1500))))
# retrieval
def neigh(i):
    s = EM[[epos[p] for p in pool]] @ EM[epos[i]]; out = []
    for k in np.argsort(-s):
        p = pool[k]
        if X.day[p] < X.day[i] and not (team[p] & team[i]):
            g = C[(C.launch_id == p) & (C.created < X.day[i])]
            if len(g) >= 3: out.append((p, g.text.tolist()[:12]))
        if len(out) == 5: break
    return out
NB = {i: neigh(i) for i in test}
ntxt = lambda i: "\n\n".join(f"Similar earlier launch: {X.name[p]} — {X.tagline[p]}\n" + "\n".join("- " + t[:400] for t in ts) for p, ts in NB[i])
Cc = cache("armC", test, lambda i: lst(J(llm.gemini_call(f"Below are real comments (team replies removed) on 5 earlier Product Hunt launches of products similar to a new one you have not seen.\n\n{ntxt(i)}\n\nFrom these comments only, list the 10 complaints, doubts or worries and the 10 questions most likely to come up again on the launch of a new product of this kind. Phrase them generally enough to apply to the new product.\n{FMT}", 1500))))
Ff = cache("armF", test, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\nReal comments (team replies removed) on 5 earlier launches of similar products:\n\n{ntxt(i)}\n\n{ASK} Use the earlier comments as evidence of what this audience raises.\n{FMT}", 1500))))
# persona panel as deployed
if not os.path.exists(f"{OUT}/cards.json"):
    from pipeline import warehouse
    W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W = W.set_index("id")
    samp = [{"slug": f"t-{i}", "id": i, "day": X.day[i], "poster": (W.poster.get(i) if i in W.index else None), "makers": (W.makers.get(i) if i in W.index else "[]"), "topics": json.dumps(list(X.topics[i])), "name": X.name[i], "tagline": X.tagline[i]} for i in test]
    json.dump(samp, open(f"{OUT}/sample.json", "w")); subprocess.run(f"cd {HERE} && SEG_SP={SP} PANEL_K=24 python3 persona_cards_hist.py {SP}/store_live {OUT}/sample.json {OUT}/cards.json", shell=True, check=True); os.remove(f"{OUT}/sample.json")
cards = json.load(open(f"{OUT}/cards.json")); sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
def panel(i):
    P_ = (cards.get(f"t-{i}") or {}).get("personas") or []
    if not P_: return None
    R = json.loads(llm.gemini_call(pm.PROMPT.format(name=X.name[i], tagline=X.tagline[i], desc=X.description[i] or "", topics=", ".join(list(X.topics[i])[:4]), groups="\n".join(pm.gtxt(k, g) for k, g in enumerate(P_))), max(3000, 300 * len(P_))))["reactions"]
    return {"lines": [f"concern: {scrub(r.get('concern'))} | question: {scrub(r.get('question'))}" for r in R], "source": cards[f"t-{i}"].get("source")}
PN = cache("panel_raw", test, panel, 8); tp = [i for i in test if i in PN]
CONS = "Merge them into distinct themes and rank by how many personas raised each, most common first."
A = cache("armA", tp, lambda i: lst(J(llm.gemini_call(f"A simulated panel of 24 Product Hunt voter personas reacted to a product. Their concerns and questions:\n\n" + "\n".join("- " + l for l in PN[i]["lines"]) + f"\n\n{CONS} List the 10 complaints or concerns and the 10 questions.\n{FMT}", 1500))))
Dd = cache("armD", tp, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\nA simulated panel of 24 Product Hunt voter personas reacted to this product. Their concerns and questions:\n\n" + "\n".join("- " + l for l in PN[i]["lines"]) + f"\n\nReal comments (team replies removed) on 5 earlier launches of similar products:\n\n{ntxt(i)}\n\n{ASK} Combine the panel's points with what the earlier comments show this audience raises.\n{FMT}", 1500))))
# site arms
ts = [i for i in test if i in SITES]; site = lambda i: SITES[i][:6000]
E = cache("armE", ts, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\nText of the product's own website:\n{site(i)}\n\nRun a simulated user test using only what this site says. Six different prospective users (a solo founder, a developer, a designer, a marketer, a team lead evaluating for a company, and a casual first-time visitor) each attempt six tasks: understand what the product does; find the price and what is free; sign up or get started; complete the product's main job once; check whether it works with the tools they already use; decide whether to trust it with their data. For each user and task note where they get stuck, what is missing or unclear, and what they would ask.\nThen report what real Product Hunt commenters will therefore say on launch day: the 10 complaints, doubts or worries most likely to be raised and the 10 questions most likely to be asked.\n{FMT}", 2500))))
Bs = cache("armBsite", ts, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\nText of the product's own website:\n{site(i)}\n\n{ASK}\n{FMT}", 1500))))
ARMS = {"A": A, "B": B, "C": Cc, "D": Dd, "F": Ff, "E": E, "Bsite": Bs}
# blind judge
def judge(key):
    i, kind = key.split("|"); real = T[i][kind]
    if not real: return {"m": {}}
    items = sorted({x for a in ARMS.values() if i in a for x in a[i][kind]}); order = np.random.default_rng(abs(hash(key)) % 2**32).permutation(len(items)); items = [items[k] for k in order]
    r = J(llm.gemini_call(f"A product launched on Product Hunt.\n{pitch(i)}\n\nREAL {kind} raised by commenters:\n" + "\n".join(f"R{k + 1}: {x['theme']}" for k, x in enumerate(real)) + f"\n\nPREDICTED {kind} (written before launch):\n" + "\n".join(f"P{k + 1}: {x}" for k, x in enumerate(items)) +
        "\n\nFor each predicted item, say which real item it matches, if any. MATCH only if the prediction names the same specific issue: a reader of the real comment would agree the prediction anticipated it. The same broad topic alone (for example both mention pricing, but one asks about a free tier and the other about enterprise billing) is NOT a match. Most predictions match nothing.\n"
        "Return JSON only: {\"matches\": {\"P1\": \"R3\" or null, ...}} with every predicted item.", 60 * len(items) + 300))["matches"]
    return {"m": {items[int(k[1:]) - 1]: (int(v[1:]) - 1 if isinstance(v, str) and v[1:].isdigit() and 0 < int(v[1:]) <= len(real) else None) for k, v in r.items() if k[1:].isdigit() and 0 < int(k[1:]) <= len(items)}}
JG = cache("judge", [f"{i}|{k}" for i in test if i in T for k in ("complaints", "questions")], judge, 10)
json.dump({"test": test, "n_candidates_aug_on": len(cand), "n_qualifying_2026": int((cnt >= 8).sum()), "pool": len(pool), "with_site": len(ts), "with_panel": len(tp), "panel_source": pd.Series([PN[i]["source"] for i in tp]).value_counts().to_dict(), "neighbours_found": float(np.mean([len(NB[i]) for i in test])), "usd": round(usd(), 2)}, open(f"{OUT}/meta_run.json", "w"), indent=1)
print("usd", round(usd(), 2))
