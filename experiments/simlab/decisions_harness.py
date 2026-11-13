"""Gemini Decisions API harness (orchestrator 05:34Z Nov 13). Dry run by default: builds every request for the fixed pilot samples,
validates it against the documented schema, and estimates tokens / cost. --send needs an AI Studio key (env GEMINI_API_KEY, or a
network secret the proxy injects as x-goog-api-key) and is NOT run until the key lands.
API (aistudio.google.com/docs/decisions-api, read Nov 13): POST https://generativelanguage.googleapis.com/v1beta/decisions, header
x-goog-api-key; body {model: "gemini-decision-1", input: str | Content[], questions: {key: {type: noul|choice|score, instructions?: str,
criteria: {option: description} (choice, 2-255) | [level descriptions] (score, 2-255)}}}; 1-1,000 questions per request; 262,144 tokens
shared by input + all questions; input billed once per request; $0.10 / 1M input tokens, output free. Response: answers[key] = {noul,
confidence} | {choice, probabilities, confidence} | {score, legend, probabilities, confidence}.
Uses (fixed samples, prompts as pilot/prompts.json):
  person   one request per person-day: input = the card (history + numbered line-up with [follows team] flags), one noul per launch
  launch   one request per day: input = the numbered line-up texts (name, tagline, topics, description[:600]); per launch noul top 10,
           noul top 3, choice band {top3, 4-10, 11-20, 21-30, 31+}; plus pairwise choice {A, B} for every pair among clean ranks 2-8
  judge    one request per launch: input = the real comments; one noul per predicted item ("same specific point as a real comment?")
    python decisions_harness.py <store dir> <launches dir> <salt dir> <clean_nosite.parquet> <pilot dir (samples)> <judge_sample.json> [--send]
"""
import glob, hashlib, itertools, json, os, sys, urllib.request
import numpy as np, pandas as pd
URL = "https://generativelanguage.googleapis.com/v1beta/decisions"; MODEL = "gemini-decision-1"; PRICE = 0.10e-6; MAXQ = 1000; MAXTOK = 262144
tok = lambda s: len(s) / 4
def q_noul(instr): return {"type": "noul", "instructions": instr}
def q_choice(instr, crit): return {"type": "choice", "instructions": instr, "criteria": crit}
def q_score(instr, levels): return {"type": "score", "instructions": instr, "criteria": levels}
def validate(req):
    errs = []
    if req.get("model") != MODEL: errs.append("model")
    if not isinstance(req.get("input"), (str, list)) or not req["input"]: errs.append("input")
    qs = req.get("questions")
    if not isinstance(qs, dict) or not 1 <= len(qs) <= MAXQ: errs.append(f"questions count {len(qs) if isinstance(qs, dict) else None}")
    for k, q in (qs or {}).items():
        t = q.get("type")
        if t not in ("noul", "choice", "score"): errs.append(f"{k}: type")
        if "instructions" in q and not isinstance(q["instructions"], str): errs.append(f"{k}: instructions")
        if t == "choice" and not (isinstance(q.get("criteria"), dict) and 2 <= len(q["criteria"]) <= 255): errs.append(f"{k}: choice criteria")
        if t == "score" and not (isinstance(q.get("criteria"), list) and 2 <= len(q["criteria"]) <= 255): errs.append(f"{k}: score criteria")
        if t == "noul" and "criteria" in q: errs.append(f"{k}: noul takes no criteria")
    if est_tokens(req) > MAXTOK: errs.append("context > 262,144 tokens")
    return errs
def est_tokens(req):
    t = tok(req["input"] if isinstance(req["input"], str) else json.dumps(req["input"]))
    for q in req["questions"].values(): t += tok(q.get("instructions", "")) + tok(json.dumps(q.get("criteria", ""))) + 8
    return t
def batch(inp, questions):
    ks = list(questions); return [{"model": MODEL, "input": inp, "questions": {k: questions[k] for k in ks[i:i + MAXQ]}} for i in range(0, len(ks), MAXQ)]
def send(req):
    key = os.environ.get("GEMINI_API_KEY", "proxy-injected")
    r = urllib.request.Request(URL, json.dumps(req).encode(), {"x-goog-api-key": key, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=300))
# ---------- builders ----------
BAND = {"top3": "finishes 1st-3rd", "r4_10": "finishes 4th-10th", "r11_20": "finishes 11th-20th", "r21_30": "finishes 21st-30th", "r31p": "finishes 31st or lower"}
def build_person(card_head, lineup_lines):
    inp = card_head + "\n\nToday's launches (numbered). A launch marked [follows team] is by a hunter or maker this member follows.\n" + "\n".join(lineup_lines)
    return batch(inp, {f"l{j+1}": q_noul(f"Does this member upvote launch {j+1} today? Members usually upvote only a few launches a day.") for j in range(len(lineup_lines))})
def build_launch(day_texts, mid_ids=None):
    inp = "Product Hunt launches competing today (ranked by upvotes over the day); about 25-40 launches compete on a typical day.\n\n" + "\n\n".join(f"[{i}] {t}" for i, t in day_texts)
    qs = {}
    for i, _ in day_texts:
        qs[f"t10_{i}"] = q_noul(f"Does launch [{i}] finish in the day's top 10?"); qs[f"t3_{i}"] = q_noul(f"Does launch [{i}] finish in the day's top 3?")
        qs[f"band_{i}"] = q_choice(f"Where does launch [{i}] finish in the day's ranking?", BAND)
    for a, b in itertools.combinations(mid_ids or [], 2): qs[f"pair_{a}_{b}"] = q_choice(f"Which gets more upvotes today: launch [{a}] or launch [{b}]?", {"A": f"launch [{a}]", "B": f"launch [{b}]"})
    return batch(inp, qs)
def build_judge(comments, items):
    inp = "Real user comments on a product launch:\n" + "\n".join(f"- {str(c)[:300]}" for c in comments[:40])
    return batch(inp, {f"i{k}": q_noul(f"Does this predicted comment make the same specific point (same concern, request or question) as at least one real comment above? Predicted: {it}") for k, it in enumerate(items)})
if __name__ == "__main__":
    V3, LDIR, SALTD, CNS, PDIR, JS = sys.argv[1:7]; SEND = "--send" in sys.argv
    SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); LD = L.set_index("id")
    def mk(m):
        try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
        except Exception: ms = []
        return {pid(x) for x in ms if x and not str(x).startswith("[")}
    team = {i: ({pid(p)} if isinstance(p, str) and p and not p.startswith("[") else set()) | mk(m) for i, p, m in zip(L.id, L.poster, L.makers)}; lday = dict(zip(L.id, L.day))
    P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
    E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[E.person_id.isin(COV)]
    U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()]
    hist = U.sort_values("lday").groupby("person_id").apply(lambda g: list(zip(g.lday, g.target_id))).to_dict(); fol = E[E.kind == "follows"].groupby("person_id").target_id.agg(set).to_dict()
    nt = lambda i: f"{LD.loc[i]['name']} - {str(LD.loc[i].tagline or '')[:90]}"
    REQ = {"person": [], "launch": [], "judge": []}
    S = json.load(open(os.path.join(PDIR, "pilot_sample.json")))
    for x in S["person_days"]:
        h = [(dd, t) for dd, t in hist.get(x["person"], []) if dd < x["day"]][-30:][::-1]; fs = fol.get(x["person"], set())
        head = "This Product Hunt member's most recent upvotes before today (newest first; product - tagline):\n" + ("\n".join(f"- {nt(t)}" for _, t in h if t in LD.index) or "- (none)")
        REQ["person"] += build_person(head, [f"{j+1}. {nt(i)}{' [follows team]' if team.get(i, set()) & fs else ''}" for j, i in enumerate(x["lineup"])])
    LS = json.load(open(os.path.join(PDIR, "pilot_launch_sample.json"))); CN = pd.read_parquet(CNS)[["id", "day", "clean_v3_nosite"]].dropna(); CN["id"] = CN.id.astype(str)
    for d in LS["days"]:
        g = CN[(CN.day == d) & CN.id.isin(LD.index)].sort_values("clean_v3_nosite", ascending=False); ids = g.id.tolist()
        def full(i):
            r = LD.loc[i]; tp = ", ".join(json.loads(r.topics)) if isinstance(r.topics, str) and r.topics.startswith("[") else ""
            return f"{r['name']} - {r.tagline or ''}\nTopics: {tp}\n{str(r.description or '')[:600]}"
        REQ["launch"] += build_launch([(i, full(i)) for i in ids], ids[1:8])
    if os.path.exists(JS):
        for j in json.load(open(JS)): REQ["judge"] += build_judge(j["comments"], j["items"])
    out = {}
    for use, rs in REQ.items():
        errs = [e for r in rs for e in validate(r)]; t = sum(est_tokens(r) for r in rs)
        out[use] = {"requests": len(rs), "questions": sum(len(r["questions"]) for r in rs), "max_questions_per_request": max([len(r["questions"]) for r in rs] or [0]),
                    "est_input_tokens": int(t), "est_usd": round(t * PRICE, 4), "schema_errors": len(errs), "first_errors": errs[:3]}
    print(json.dumps(out, indent=1))
    if SEND: print("send mode is not enabled in this version: run per use after the key lands")
