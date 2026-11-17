"""Part 1: tally / fillout / typeform study vs WEAK truth (public discussion themes found by web search). Broad themes only."""
import json, os, re, sys, asyncio, numpy as np
SP = sys.argv[1]; OUT = f"{SP}/e2r"; sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
sys.path[:0] = [f"{SP}/phweb", f"{SP}/phweb/src"]; from mvp.ph_site import safe_fetch
rng = np.random.default_rng(0); J = lambda t: json.loads(re.search(r"\{.*\}", t, re.S).group(0))
TRUTH = {  # weak truth: themes from public comparison pages, review-site snippets and community posts surfaced by web search on Nov 17 2026
 "Tally": {"url": "https://tally.so", "complaints": ["No HIPAA compliance, unsuitable for healthcare data", "Reporting and analytics are basic; need integrations for reports", "Design and one-question-at-a-time mode less polished than Typeform", "Support is chat only, no phone", "No mobile app"],
           "praise": ["Free plan with unlimited forms and submissions", "Simple document-style editor, quick to build forms", "Cheapest option for small teams"]},
 "Typeform": {"url": "https://typeform.com", "complaints": ["Expensive, and prices keep rising", "Free plan very limited (about 10 responses a month); plans capped by response count", "Conversational one-at-a-time style not ideal for long data entry", "Designer/editor can be hard to use for advanced layouts"],
              "praise": ["Polished, engaging design and clean UX; high completion rates", "Many native integrations", "Easy to create, share and embed forms", "Rich analytics and insights from responses"]},
 "Fillout": {"url": "https://fillout.com", "complaints": ["Support response times can lag", "Smaller template library", "Limitations integrating with some third-party apps", "Limited design options, a bit too simple", "Problems with photo/file uploads", "Mobile autosave and session persistence unreliable", "Some features (analytics, larger uploads) need a paid plan"],
             "praise": ["Generous free tier (about 1,000 responses)", "Deeper conditional logic and integrations than rivals", "Easy to use"]}}
d = json.load(open(f"{OUT}/report.json")); site = {"Product": "Tally", "Fillout": "Fillout", "Typeform": "Typeform"}
def runs(p):
    L = []
    for c in d["cells"]:
        if site.get(c["site"]) != p: continue
        L.append(f"- task: {c['task'].split(chr(10))[0]} | reached: {c['goal_reached']} | ended: {c['driver_outcome']} | steps {c['steps']} | judge: {c['judge_reason']}")
    return "\n".join(L)
FMT = 'Return JSON only: {"complaints": ["<under 16 words>", ...up to 8, most important first], "praise": ["<under 16 words>", ...up to 5]}'
def study_themes(p):
    extra = ("\nThe study's own summary for this product: " + d["summary"]["verdict_summary"] + " Recommendations: " + "; ".join(r["action"] for r in d["summary"]["recommendations"])) if p == "Tally" else ""
    return J(llm.gemini_call(f"Six simulated users each tried six tasks on the live product {p} ({TRUTH[p]['url']}) in a real browser, with accounts. Results of the 36 runs:\n{runs(p)}{extra}\n\nFrom these runs only, list what real users of {p} would most likely complain about, and what they would praise. Product-level themes, not test artefacts.\n{FMT}", 1500))
async def home(p):
    try: r = await safe_fetch.fetch_product(TRUTH[p]["url"]); return (r.get("text") or r.get("page_text") or json.dumps(r))[:5000]
    except Exception as e: return f"(homepage not fetched: {e})"
def baseline(p, txt):
    return J(llm.gemini_call(f"Product: {p} ({TRUTH[p]['url']}). Text of its homepage:\n{txt}\n\nPredict what real users of this product most often complain about in reviews and discussions, and what they praise.\n{FMT}", 1500))
def match(p, kind, pred):
    real = TRUTH[p][kind]
    r = J(llm.gemini_call(f"Product: {p}. REAL {kind} themes (from public user discussions):\n" + "\n".join(f"R{i+1}: {x}" for i, x in enumerate(real)) + f"\n\nPREDICTED {kind}:\n" + "\n".join(f"P{i+1}: {x}" for i, x in enumerate(pred)) +
        "\n\nBROAD rule: a predicted item matches a real theme if it is about the same topic (e.g. both about pricing, both about support, both about design flexibility). Return JSON only: {\"matches\": {\"P1\": \"R2\" or null, ...}} for every predicted item.", 800))["matches"]
    return [(int(v[1:]) - 1 if isinstance(v, str) and v[1:].isdigit() and 0 < int(v[1:]) <= len(real) else None) for k, v in sorted(r.items(), key=lambda kv: int(kv[0][1:])) if k[1:].isdigit()][:len(pred)]
O = {"truth_label": "WEAK truth: themes from public comparison pages, review snippets and community posts via web search (no raw reviews; G2/Capterra/TrustRadius pages refuse automated reads; no Reddit/HN threads surfaced)", "products": {}}
H = {p: asyncio.run(home(p)) for p in TRUTH}
for p in TRUTH:
    S = study_themes(p); B = baseline(p, H[p]); R = {"study": S, "baseline": B, "homepage_chars": len(H[p])}
    for arm, P_ in (("study", S), ("baseline", B)):
        for kind in ("complaints", "praise"):
            m = match(p, kind, P_.get(kind, [])); R[f"{arm}_{kind}_matches"] = m
    O["products"][p] = R
def pool(arm, kind):
    rec, prec = [], []
    for p, R in O["products"].items():
        m = R[f"{arm}_{kind}_matches"]; got = {x for x in m if x is not None}
        rec += [1.0 if i in got else 0.0 for i in range(len(TRUTH[p][kind]))]; prec += [1.0 if x is not None else 0.0 for x in m]
    ci = lambda v: f"{np.mean(v)*100:.0f}% [{np.percentile([np.mean(rng.choice(v, len(v))) for _ in range(2000)], 2.5)*100:.0f}, {np.percentile([np.mean(rng.choice(v, len(v))) for _ in range(2000)], 97.5)*100:.0f}] (n {len(v)})"
    return {"recall": ci(np.array(rec)), "precision": ci(np.array(prec))}
O["scores"] = {f"{arm} {kind}": pool(arm, kind) for arm in ("study", "baseline") for kind in ("complaints", "praise")}
O["study_cells"] = {p: {"runs": sum(1 for c in d["cells"] if site.get(c["site"]) == p), "goal_reached": sum(1 for c in d["cells"] if site.get(c["site"]) == p and c["goal_reached"])} for p in TRUTH}
O["usd"] = round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)
json.dump(O, open(f"{OUT}/part1_result.json", "w"), indent=1); print(json.dumps({k: O[k] for k in ("scores", "study_cells", "usd")}, indent=1))
for p, R in O["products"].items(): print(p, "STUDY", R["study"], "\n   BASE", R["baseline"])
