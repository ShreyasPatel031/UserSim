"""Can we simulate what a SPECIFIC person says? (orchestrator 02:20Z Nov 12). Comment text = the launch thread dumps
(raw/ph_predict_data/comments, exact created_at); commenters mapped to complete pool people by the salted id (usernames never
leave this script; outputs carry pair indices only; comment text stays in the bucket).
Pairs: (person, launch) with the launch in Aug-Oct 2026, the person not on the launch team, a substantive comment (>= 12 words,
not a pure congratulation), and >= 10 earlier substantive comments by the person dated before the launch day. Sample 300 pairs,
at most 4 per person (only 88 people are eligible).
Conditions (gemini-2.5-flash, temperature 0.3), product-only launch inputs (name, tagline, description, topics):
  A  the person's 10-20 most recent earlier substantive comments as history
  B  a generic "typical Product Hunt member"
  C  another random person's history (shuffle control)
  D  A + the person's tools/interest summary from the store (names of up to 15 stack items and 15 most recent upvoted launches,
     all dated before the launch day for upvotes; stack lists are undated snapshots)
Judge (gemini-2.5-flash, blinded, per generated comment): theme 0/1/2 vs the real comment, stance of each (praise / question /
objection / feature_request / comparison / other), specificity 0-2. Forced choice: the real comment + the 4 generated in random
order -> which is closest (chance 25%). Type prediction: the real comment's stance vs (i) A's generated stance, (ii) the
person's most frequent historical stance (history classified in one call), (iii) the global base rate (most common stance).
Person-bootstrap 95% CIs.
    python person_sim.py <cf dir with page*.jsonl.gz> <launches dir> <salt file> <v3 dir> <uses2 export> <out dir>
"""
import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

CFD, LDIR, SALTF, V3, EXP, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def gem(prompt, temp=0.0, maxtok=1500):
    for i in range(6):
        try:
            req = urllib.request.Request(GEN, json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}).encode(),
                {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=180)); u = j.get("usageMetadata", {})
            USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
            return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(4 * (i + 1))
    return None


SALT = open(SALTF).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + h.lower()).encode()).hexdigest()[:16]
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
bys = {s: r for s, r in zip(L.slug, L.itertuples())}
CONG = re.compile(r"^\W*(congrat\w*|congrats|well done|great (job|work|launch)|good luck|awesome|amazing|love (it|this)|nice|cool|kudos|best of luck|upvoted)\b", re.I)
rows = []
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        r = bys[p_["slug"]]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower()
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", n.get("bodyHtml") or ""))).strip()
            if u and u not in r.team: rows.append((n.get("id"), pid(u), p_["slug"], r.day, n.get("createdAt"), t))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
C = pd.DataFrame(rows, columns=["cid", "person", "slug", "day", "ts", "text"]).drop_duplicates("cid")
C = C[C.person.isin(comp)].copy(); C["nw"] = C.text.str.split().str.len()
C["subst"] = (C.nw >= 12) & ~(C.text.str.match(CONG) & (C.nw < 25))
S_ = C[C.subst].sort_values("ts")
pairs = []
for p, g in S_.groupby("person"):
    for _, r in g[(g.day >= "2026-08-01") & (g.day <= "2026-10-31")].iterrows():
        hist = g[g.ts < r.day]                                   # strictly before the launch day (ISO strings compare)
        if len(hist) >= 10: pairs.append({"person": p, "slug": r.slug, "day": r.day, "real": r.text, "history": hist.text.tolist()[-20:]})
P = pd.DataFrame(pairs)
stats = {"substantive_comments_complete_people": int(len(S_)), "eligible_pairs": int(len(P)), "eligible_people": int(P.person.nunique()) if len(P) else 0}
print(stats, flush=True)
P = P.sample(frac=1, random_state=0).groupby("person").head(4)   # only 88 eligible people: cap 4 pairs each
people = P.person.unique(); rng.shuffle(people)
P = P[P.person.isin(people[:max(150, min(len(people), 300))])].sample(frac=1, random_state=1).head(300).reset_index(drop=True)
print("sample pairs", len(P), "people", P.person.nunique(), flush=True)

# tools/interest summary from the store (upvotes dated before the launch day; stack items undated)
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(set(P.person))]; ev["target_id"] = ev.target_id.astype(str)
lid = {str(i): (r.name, r.day) for i, r in zip(L.id, L.itertuples())}
Pe = pd.read_parquet(os.path.join(EXP, "people.parquet")); stack = dict(zip(Pe.person_id, Pe["stack"]))
def tools(p, d):
    up = [lid[t] for t in ev[ev.person_id == p].target_id if t in lid and lid[t][1] < d]
    up = [n for n, _ in sorted(up, key=lambda x: x[1])][-15:]; st = [str(x) for x in (stack.get(p) if stack.get(p) is not None else [])][:15]
    return f"Tools they list: {', '.join(st) or 'unknown'}. Recently upvoted launches: {', '.join(up) or 'unknown'}."
oth_idx = {}
for i in range(len(P)):
    j = int(rng.integers(0, len(P)))
    while P.person[j] == P.person[i]: j = int(rng.integers(0, len(P)))
    oth_idx[i] = j
others = {i: P.history[oth_idx[i]] for i in range(len(P))}


def launch_txt(s):
    r = bys[s]; tp = ", ".join(json.loads(r.topics)) if isinstance(r.topics, str) and r.topics.startswith("[") else ""
    return f"Product: {r.name} - {r.tagline}\nDescription: {(r.description or '')[:1200]}\nTopics: {tp}"


GENP = """{who}

A new product launched on Product Hunt today.
{launch}

Write the single comment {pron} would most likely leave on this launch, in {pron2} usual voice, length and focus. Stay grounded
in the product description; do not invent features. Never use names or @handles.
Return JSON {{"comment": "...", "stance": "praise|question|objection|feature_request|comparison|other"}}"""
def who(cond, i):
    h = P.history[i]; o = others[i]
    if cond == "A": return "Here are a Product Hunt member's own recent comments on other launches (oldest first):\n" + "\n".join(f"- {t[:300]}" for t in h)
    if cond == "B": return "You are a typical Product Hunt member."
    if cond == "C": return "Here are a Product Hunt member's own recent comments on other launches (oldest first):\n" + "\n".join(f"- {t[:300]}" for t in o)
    return who("A", i) + "\n" + tools(P.person[i], P.day[i])
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
def gen(i, c):
    pr = GENP.format(who=who(c, i), launch=launch_txt(P.slug[i]), pron="this member" if c != "B" else "they", pron2="their")
    return gem(pr, 0.3, 600) or {}
jobs = [(i, c) for i in range(len(P)) for c in "ABCD"]
with cf.ThreadPoolExecutor(8) as ex: G = dict(zip(jobs, ex.map(lambda j: run(f"gen|{j[0]}|{j[1]}", lambda: gen(*j)), jobs)))
json.dump(K, open(cache_f, "w")); print("generated usd", round(USD["usd"], 3), flush=True)

JP = """REAL = a comment a person actually left on a product launch. GEN = a generated comment for the same launch.
Rate: theme (0 = different points, 1 = same general topic, 2 = makes essentially the same point), the stance of REAL and of GEN
(praise / question / objection / feature_request / comparison / other), and GEN's specificity (0 generic, 1 somewhat, 2 specific).
Return JSON {{"theme": 0|1|2, "stance_real": "...", "stance_gen": "...", "specificity": 0|1|2}}
REAL: {r}
GEN: {g}"""
FC = """REAL = a comment a person actually left on a product launch. Below are four candidate comments. Which candidate is closest
to REAL in what it says and how it says it? Return JSON {{"closest": 1|2|3|4}}
REAL: {r}
{c}"""
HC = """Classify each comment's stance (praise / question / objection / feature_request / comparison / other).
Return JSON {{"stances": ["...", ...]}} in order.
{c}"""
def judge(i, c):
    return gem(JP.format(r=P.real[i][:800], g=str(G[(i, c)].get("comment", ""))[:800]), 0.0, 300) or {}
def forced(i):
    order = list("ABCD"); random.Random(i).shuffle(order)
    a = gem(FC.format(r=P.real[i][:800], c="\n".join(f"{k+1}. {str(G[(i, c)].get('comment', ''))[:600]}" for k, c in enumerate(order))), 0.0, 100) or {}
    try: return order[int(a.get("closest")) - 1]
    except Exception: return None
def hist_st(i):
    a = gem(HC.format(c="\n".join(f"{k+1}. {t[:300]}" for k, t in enumerate(P.history[i]))), 0.0, 600) or {}
    return a.get("stances") or []
with cf.ThreadPoolExecutor(8) as ex:
    J = dict(zip(jobs, ex.map(lambda j: run(f"judge|{j[0]}|{j[1]}", lambda: judge(*j)), jobs)))
    FCs = dict(zip(range(len(P)), ex.map(lambda i: run(f"fc|{i}", lambda: forced(i)), range(len(P)))))
    HS = dict(zip(range(len(P)), ex.map(lambda i: run(f"hs|{i}", lambda: hist_st(i)), range(len(P)))))
json.dump(K, open(cache_f, "w"))
norm = lambda s: str(s or "other").lower().strip().replace(" ", "_")
R = []
for i in range(len(P)):
    for c in "ABCD":
        j = J[(i, c)]
        R.append({"i": i, "person": P.person[i], "cond": c, "theme": float(j.get("theme", np.nan)) if j else np.nan, "theme2": float(j.get("theme") == 2) if j else np.nan,
                  "stance_match": float(norm(j.get("stance_real")) == norm(j.get("stance_gen"))) if j else np.nan, "spec": float(j.get("specificity", np.nan)) if j else np.nan,
                  "forced": float(FCs[i] == c) if FCs[i] else np.nan, "real_stance": norm(j.get("stance_real")) if j else None})
D = pd.DataFrame(R)


def pboot(df, col, B=2000):
    g = df.groupby("person")[col].mean().dropna().to_numpy(); bs = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(B)]
    return [round(float(g.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(g))]


res = {"design": __doc__.split("\n    python")[0], **stats, "sample_pairs": int(len(P)), "sample_people": int(P.person.nunique()), "means": {}, "paired": {}}
for c in "ABCD": res["means"][c] = {m: pboot(D[D.cond == c], m) for m in ("theme", "theme2", "stance_match", "spec", "forced")}
W = D.pivot_table(index=["i", "person"], columns="cond", values=["theme", "theme2", "stance_match", "spec", "forced"]).reset_index()
for a, b in (("A", "B"), ("A", "C"), ("D", "A")):
    res["paired"][f"{a} - {b}"] = {m: pboot(pd.DataFrame({"person": W.person, "x": W[(m, a)] - W[(m, b)]}), "x") for m in ("theme", "theme2", "stance_match", "spec", "forced")}
# type prediction
real = D[D.cond == "A"].set_index("i").real_stance
genA = {i: norm(G[(i, "A")].get("stance")) for i in range(len(P))}
histmaj = {i: (pd.Series([norm(s) for s in HS[i]]).mode().iloc[0] if HS[i] else "other") for i in range(len(P))}
glob_mode = real.value_counts().idxmax()
T = pd.DataFrame({"person": P.person, "real": real.reindex(range(len(P))).values})
T["genA"] = [float(genA[i] == T.real[i]) for i in range(len(P))]; T["hist_majority"] = [float(histmaj[i] == T.real[i]) for i in range(len(P))]
T["base_rate_mode"] = (T.real == glob_mode).astype(float)
res["type_prediction"] = {"real_stance_distribution": T.real.value_counts().to_dict(), "base_mode": glob_mode,
                          **{c: pboot(T, c) for c in ("genA", "hist_majority", "base_rate_mode")},
                          "hist_majority - base (paired)": pboot(T.assign(x=T.hist_majority - T.base_rate_mode), "x"),
                          "genA - base (paired)": pboot(T.assign(x=T.genA - T.base_rate_mode), "x")}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "person_sim.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
