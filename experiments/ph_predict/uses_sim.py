"""User-simulation track on E5's uses harness v2 (pre-registered with E5, Nov 11; PASS with notes):
  card    Gemini 2.5 Flash-Lite writes a structured persona card per person from headline+bio, the person's uses items
          (stack / review / collection) EXCLUDING every item held out in any of that person's tasks, and up to 25 of the
          person's upvoted products (held-out slugs excluded too). Cached (cards.jsonl, template sha), frozen before
          any judge run is scored.
  judge   for a seeded sample of 500 people: the person's first pop-matched task (held-out item + its <= 50 negatives),
          candidates shuffled, product text only (name. tagline. description[:300]), no popularity; Gemini scores each
          0-10 for "would this person use it". One call per person. Name-masked variant on a 100-person subset (names
          replaced by Product A, B, ...; name mentions in text masked too).
  score   pop-matched AUC (share of negatives scored below the held-out), Hit@1, Hit@10 among the candidates, ties
          broken at random; against E5's U-taste and popularity on the same tasks (pop_loo); also on pop decile <= 5.
Inputs: gs://.../tmp/e5/uses/{products,people,eval_sets}.parquet (salted ids). Outputs under <USES_DIR>; counts only.
usage: USES_DIR=<dir> python uses_sim.py card [threads] | judge [n_people] [masked] | score"""
import hashlib, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
import llm

U = os.environ["USES_DIR"]
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/"
       "gemini-2.5-flash-lite:generateContent")
LK = threading.Lock(); USE = {"in": 0, "out": 0}
CARD_SCHEMA = {"type": "OBJECT", "properties": {
    "role": {"type": "STRING"}, "seniority": {"type": "STRING", "enum": ["student", "junior", "mid", "senior", "founder_exec", "unknown"]},
    "domain": {"type": "STRING"}, "tools_used": {"type": "ARRAY", "items": {"type": "STRING"}},
    "looks_for": {"type": "ARRAY", "items": {"type": "STRING"}}, "avoids": {"type": "ARRAY", "items": {"type": "STRING"}},
    "price_sensitivity": {"type": "STRING", "enum": ["low", "medium", "high", "unknown"]},
    "platforms": {"type": "ARRAY", "items": {"type": "STRING"}}, "technical_depth": {"type": "INTEGER", "minimum": 1, "maximum": 5},
    "summary": {"type": "STRING"}},
    "required": ["role", "seniority", "domain", "tools_used", "looks_for", "avoids", "price_sensitivity", "platforms", "technical_depth", "summary"]}
CARD_PROMPT = """Write a persona card for this Product Hunt user, from what they wrote about themselves and the products they
use or saved. Describe who they are and what kind of products they want. Be concrete. Do not list the products back.

About them: {bio}

Products they use or saved (name. tagline):
{uses}

Products they upvoted (name. tagline):
{ups}"""
JUDGE_SCHEMA = {"type": "OBJECT", "properties": {"scores": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "id": {"type": "STRING"}, "score": {"type": "INTEGER", "minimum": 0, "maximum": 10}}, "required": ["id", "score"]}}}, "required": ["scores"]}
JUDGE_PROMPT = """You are simulating one specific person. Persona card:
{card}

For EACH product below, rate 0-10 how likely this person is to use it or save it (10 = certainly, 0 = never), judging only
from the persona and the product description. Return a score for every id.

{items}"""


def tsha(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def gem(prompt, schema, max_out=2000):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_out, "responseMimeType": "application/json", "responseSchema": schema}}
    err = ""
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(refresh=i > 0), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.load(r)
            u = j.get("usageMetadata", {})
            with LK:
                USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
            return json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]; time.sleep(3 * (i + 1))
    raise RuntimeError(err)


def load():
    P = pd.read_parquet(f"{U}/products.parquet"); Pe = pd.read_parquet(f"{U}/people.parquet"); E = pd.read_parquet(f"{U}/eval_sets.parquet")
    return P, Pe, E


def short(t, n=160):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t[:n]


def card(threads=8):
    P, Pe, E = load(); txt = dict(zip(P.slug, P.text))
    held = E.groupby("person_id").heldout.apply(set).to_dict()
    path = f"{U}/cards.jsonl"; done = set()
    if os.path.exists(path):
        done = {json.loads(l)["person_id"] for l in open(path)}
    f = open(path, "a"); sha = tsha(CARD_PROMPT, CARD_SCHEMA)

    def one(r):
        h = held.get(r.person_id, set())
        uses = [s for k in ("stack", "review", "collection") for s in (getattr(r, k) if getattr(r, k) is not None else []) if s not in h and s in txt]
        ups = [s for s in (r.upvote if r.upvote is not None else []) if s not in h and s in txt]
        rng = np.random.default_rng(int(r.person_id[2:10], 16))
        uses = list(dict.fromkeys(uses))[:40]; ups = list(rng.permutation(list(dict.fromkeys(ups))))[:25]
        p = CARD_PROMPT.format(bio=short(r.headline_bio, 600) or "(none)", uses="\n".join("- " + short(txt[s]) for s in uses) or "(none)",
                               ups="\n".join("- " + short(txt[s]) for s in ups) or "(none)")
        try:
            c = gem(p, CARD_SCHEMA, 800)
        except Exception as e:  # noqa: BLE001
            return {"person_id": r.person_id, "error": str(e)[:200]}
        rec = {"person_id": r.person_id, "card": c, "n_uses_in": len(uses), "n_ups_in": len(ups), "excluded_heldout": len(h),
               "template_sha": sha, "model": "gemini-2.5-flash-lite", "at": pd.Timestamp.now(tz="UTC").isoformat()}
        with LK:
            f.write(json.dumps(rec) + "\n"); f.flush()
        return rec
    todo = Pe[~Pe.person_id.isin(done)]
    with ThreadPoolExecutor(threads) as ex:
        errs = sum("error" in x for x in ex.map(one, todo.itertuples()))
    print(json.dumps({"cards_todo": len(todo), "errors": errs, **USE, "template_sha": sha}))


def mask_names(items):
    out = []
    for k, (s, t) in enumerate(items):
        name = t.split(".")[0].strip(); lab = f"Product {chr(65 + k % 26)}{k // 26 or ''}"
        body = t[len(name):] if t.startswith(name) else t
        if name:
            body = re.sub(re.escape(name), lab, body, flags=re.I)
        out.append((s, lab + body))
    return out


def judge(n_people=500, masked=False, threads=8):
    P, Pe, E = load(); txt = dict(zip(P.slug, P.text))
    cards = {json.loads(l)["person_id"]: json.loads(l)["card"] for l in open(f"{U}/cards.jsonl") if "card" in json.loads(l)}
    T = E[(E.neg_kind == "pop_matched") & E.person_id.isin(cards)].sort_values(["person_id", "task"]).groupby("person_id").head(1)
    rng = np.random.default_rng(0)
    T = T.iloc[rng.permutation(len(T))[:n_people]]
    tag = "judge_masked" if masked else "judge"
    path = f"{U}/{tag}.jsonl"; done = set()
    if os.path.exists(path):
        done = {json.loads(l)["task"] for l in open(path)}
    f = open(path, "a")

    def one(r):
        cand = [r.heldout] + list(r.negatives)
        order = np.random.default_rng(int(r.task)).permutation(len(cand))
        items = [(cand[i], short(txt.get(cand[i], ""), 300)) for i in order]
        if masked:
            items = mask_names(items)
        ids = {f"c{k}": s for k, (s, _) in enumerate(items)}
        p = JUDGE_PROMPT.format(card=json.dumps(cards[r.person_id]), items="\n".join(f"[c{k}] {t}" for k, (_, t) in enumerate(items)))
        try:
            out = gem(p, JUDGE_SCHEMA, 3000)
        except Exception as e:  # noqa: BLE001
            return {"task": int(r.task), "error": str(e)[:200]}
        sc = {ids.get(x["id"]): x["score"] for x in out.get("scores", []) if ids.get(x["id"])}
        rec = {"task": int(r.task), "person_id": r.person_id, "heldout": r.heldout, "scores": sc, "n_cand": len(cand), "n_scored": len(sc),
               "masked": masked, "template_sha": tsha(JUDGE_PROMPT, JUDGE_SCHEMA)}
        with LK:
            f.write(json.dumps(rec) + "\n"); f.flush()
        return rec
    todo = T[~T.task.isin(done)]
    if masked:
        todo = todo.head(100)
    with ThreadPoolExecutor(threads) as ex:
        errs = sum("error" in x for x in ex.map(one, todo.itertuples()))
    print(json.dumps({"judge": tag, "tasks": len(todo), "errors": errs, **USE}))


def score():
    P, Pe, E = load(); dec = dict(zip(P.slug, P.pop_decile)); rng = np.random.default_rng(0)
    Et = E.set_index("task")
    res = {}
    for tag in ("judge", "judge_masked"):
        p = f"{U}/{tag}.jsonl"
        if not os.path.exists(p):
            continue
        rows = []
        for l in open(p):
            r = json.loads(l); t = Et.loc[r["task"]]; cand = [t.heldout] + list(t.negatives)
            js = np.array([r["scores"].get(s, np.nan) for s in cand], float)
            pop = np.concatenate([[t.pop_loo_heldout], np.asarray(t.pop_loo_negatives, float)])
            for nm, s in (("judge", js), ("popularity", pop), ("random", rng.random(len(cand)))):
                s = np.where(np.isnan(s), -1, s) + rng.random(len(s)) * 1e-6
                rows.append({"task": r["task"], "scorer": nm, "auc": float((s[1:] < s[0]).mean()), "hit1": float((s[1:] > s[0]).sum() == 0),
                             "hit10": float((s[1:] > s[0]).sum() < 10), "low_pop": dec.get(t.heldout, 9) <= 5, "coverage": float(np.isfinite(js).mean())})
        R = pd.DataFrame(rows); out = {"tasks": int(R.task.nunique()), "score_coverage": round(float(R.coverage.mean()), 3)}
        for sub, m in (("all", R.task.notna()), ("pop_decile_le5", R.low_pop)):
            for sc, g in R[m].groupby("scorer"):
                b = lambda c: [round(float(g[c].mean()), 3)] + [round(float(x), 3) for x in np.percentile([g[c].values[rng.integers(0, len(g), len(g))].mean() for _ in range(2000)], [2.5, 97.5])] + [int(len(g))]
                out[f"{sub} | {sc}"] = {c: b(c) for c in ("auc", "hit1", "hit10")}
        res[tag] = out
    json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "uses_sim.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "card":
        card(int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    elif c == "judge":
        judge(int(sys.argv[2]) if len(sys.argv) > 2 else 500, len(sys.argv) > 3 and sys.argv[3] == "masked")
    else:
        score()
