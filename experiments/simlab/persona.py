"""Persona engine v0: real people from the store react to a launch, using only what was known before launch day.

For launch L on day d:
  candidates  people active (any comment/upvote) in the 90 days before d, not on L's team
  choose      N_MATCH most taste-matched (meaning of their past launches vs L's pitch) + N_RAND random candidates
  card        each person as of d: segment labels, headlines, the launches they backed most recently, tools they use
  react       Gemini Flash writes each person's first-person reaction (10 people per request)
  score       SSR: the reaction's similarity to five reference statements -> a 1-5 score (Maier et al. 2025)
usage: python -m simlab.persona react 2026-09-01 2026-10-24   (resumable; cache/persona_reactions.jsonl)
       python -m simlab.persona score                          (cache/persona_scores.parquet: per-launch features)
Undated inputs used on cards (current segments / LinkedIn) are listed in the output's `undated` field."""
import json, os, random, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
RAW = store.RAW
N_MATCH, N_RAND, PER_CALL = 40, 10, 10
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
       "models/gemini-2.5-flash:generateContent")
ANCHORS = ["I would scroll past this. It is not for me and I would not upvote it.",
           "Probably not for me. I doubt I would upvote it or try it.",
           "Maybe. It is somewhat interesting, but I am not sure I would upvote it.",
           "This looks useful. I would likely upvote it and might try it.",
           "I love this. I would definitely upvote it and try it right away."]
PROMPT = """You are simulating real Product Hunt users scrolling today's launches on the homepage.

Launch:
{launch}

For each person below, write their honest first-person reaction on seeing this launch, in 1-2 sentences: would they
click, upvote or try it, and why. Most people scroll past most launches; stay true to each person's role, interests
and what they have backed before. Reply with JSON only: [{{"id": <n>, "reaction": "..."}}, ...]

People:
{people}"""
lock = threading.Lock()
TOK = {}


def gemini(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 3000, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for a in range(5):
        if a or "v" not in TOK:
            TOK["v"] = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
        try:
            r = requests.post(URL, json=body, headers={"Authorization": f"Bearer {TOK['v']}"}, timeout=120)
            if r.status_code == 200:
                c = (r.json().get("candidates") or [{}])[0]
                return "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
        except requests.RequestException:
            pass
        time.sleep(5 * (a + 1))
    return ""


def launch_text(it):
    return f"{it['name']} — {it['tagline']}\nTopics: {', '.join(json.loads(it['topics']))}\n{(it['description'] or '')[:600]}"


def card(p, hist, names, day):
    js = lambda v, d: json.loads(v) if isinstance(v, str) else d
    seg = js(p.get("seg"), {})
    bits = [f"{k}: {seg[k]}" for k in ("role", "seniority", "company_type", "domain", "tech_level", "buyer_type", "country")
            if seg.get(k) and seg[k] != "unknown"]
    if seg.get("interests"):
        bits.append("interests: " + ", ".join(seg["interests"][:5]))
    for k, lab in (("headline", "PH headline"), ("li_headline", "LinkedIn")):
        if isinstance(p.get(k), str) and p[k] not in ("None", "nan", ""):
            bits.append(f"{lab}: {str(p[k])[:120]}")
    tools = [s[0] for s in js(p.get("stacks"), []) if s[1] and s[1] < day][:8]
    if tools:
        bits.append("uses: " + ", ".join(t for t in tools if t))
    if hist:
        bits.append("recently backed: " + "; ".join(names[i] for i in hist[-6:]))
    return " | ".join(bits)


def plan(day_from, day_to, seed=0):
    """Yield (launch row, [(person, card)]) for every launch in the window."""
    people, items, events = store.load()
    items = items.reset_index(drop=True)
    Z = np.load(f"{RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}
    keep = items.id.isin(li.keys()); items = items[keep].reset_index(drop=True)
    E = Z["launch"][[li[x] for x in items.id]]
    iix = {x: k for k, x in enumerate(items.id)}
    names = [f"{r.name} ({r.tagline[:60]})" for r in items.itertuples()]
    ev = events[events.item.isin(iix)].copy(); ev["ii"] = ev.item.map(iix)
    pe = {p: k for k, p in enumerate(people.person)}; ev = ev[ev.person.isin(pe)]; ev["pi"] = ev.person.map(pe)
    ev = ev.sort_values("date").reset_index(drop=True)
    pdict = people.set_index("person").to_dict("index")
    S = np.zeros((len(people), E.shape[1]), np.float32); last = np.full(len(people), "", object)
    hist = {}
    rng = random.Random(seed); e = 0
    for d in sorted(items.day[(items.day >= day_from) & (items.day <= day_to)].unique()):
        while e < len(ev) and ev.date[e] < d:
            S[ev.pi[e]] += E[ev.ii[e]]; last[ev.pi[e]] = ev.date[e]; hist.setdefault(ev.pi[e], []).append(ev.ii[e]); e += 1
        cut = (pd.Timestamp(d) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        cand = np.where(last >= cut)[0]
        Sn = S[cand] / (np.linalg.norm(S[cand], axis=1, keepdims=True) + 1e-9)
        for k in np.where(items.day.values == d)[0]:
            it = items.iloc[k]
            team = set(json.loads(it.makers)) | {it.poster}
            sim = Sn @ E[k]
            order = [cand[j] for j in np.argsort(-sim) if people.person[cand[j]] not in team]
            chosen = order[:N_MATCH] + rng.sample(order[N_MATCH:], min(N_RAND, max(0, len(order) - N_MATCH)))
            yield it, [(people.person[i], "match" if j < N_MATCH else "random",
                        card(pdict[people.person[i]], hist.get(i, []), names, d)) for j, i in enumerate(chosen)]


def react(day_from, day_to, threads=32):
    os.makedirs(CACHE, exist_ok=True)
    out = f"{CACHE}/persona_reactions.jsonl"
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    jobs = [(it, ps) for it, ps in plan(day_from, day_to) if it.id not in done]
    print("launches", len(jobs), "requests", sum((len(p) + PER_CALL - 1) // PER_CALL for _, p in jobs), flush=True)

    def one(job):
        it, ps = job
        res = []
        for i in range(0, len(ps), PER_CALL):
            chunk = ps[i:i + PER_CALL]
            txt = gemini(PROMPT.format(launch=launch_text(it), people="\n".join(f"{j}. {c}" for j, (_, _, c) in enumerate(chunk))))
            try:
                got = {int(o["id"]): o.get("reaction", "") for o in json.loads(re.search(r"\[.*\]", txt, re.S).group(0))}
            except Exception:  # noqa: BLE001
                got = {}
            res += [{"person": u, "pick": kind, "reaction": got.get(j)} for j, (u, kind, _) in enumerate(chunk)]
        with lock, open(out, "a") as f:
            f.write(json.dumps({"id": it.id, "day": it.day, "reactions": res, "undated": ["seg", "li_headline"]}) + "\n")

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, jobs))


def score():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    A = m.encode(ANCHORS, normalize_embeddings=True)
    recs = [json.loads(l) for l in open(f"{CACHE}/persona_reactions.jsonl")]
    rows, prow = [], []
    for r in recs:
        R = [x for x in r["reactions"] if x.get("reaction")]
        if not R:
            continue
        V = m.encode([x["reaction"] for x in R], normalize_embeddings=True, batch_size=64)
        sim = V @ A.T
        p = sim - sim.min(1, keepdims=True); p = p / (p.sum(1, keepdims=True) + 1e-9)
        s = p @ np.arange(1, 6)
        mt = np.array([x["pick"] == "match" for x in R])
        prow += [{"id": r["id"], "person": x["person"], "pick": x["pick"], "score": float(v), "p_top": float(p[j, 3] + p[j, 4])}
                 for j, (x, v) in enumerate(zip(R, s))]
        rows.append({"id": r["id"], "persona_mean": s.mean(), "persona_top_share": float((s >= 3.5).mean()),
                     "persona_p5": float(p[:, 4].mean()), "persona_match_mean": s[mt].mean() if mt.any() else np.nan,
                     "persona_rand_mean": s[~mt].mean() if (~mt).any() else np.nan, "persona_n": len(R)})
    df = pd.DataFrame(rows); df.to_parquet(f"{CACHE}/persona_scores.parquet")
    pd.DataFrame(prow).to_parquet(f"{CACHE}/persona_person_scores.parquet")
    print(len(df), df.describe().T[["mean", "std"]].round(3))


if __name__ == "__main__":
    if sys.argv[1] == "react":
        react(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 32)
    else:
        score()
