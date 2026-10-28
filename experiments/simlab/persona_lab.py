"""Persona design test (step 1): which persona design adds most on top of simcore's choice model, per dollar?
Same screening sample as variants.py (1,000 Sep + 1,000 Oct active person-days), same comment card as taste v3.
  rate    rate every launch in the day's line-up 1-5 for fit (as taste v3)            models: Flash-Lite (Flash exists: p3)
  pick3   "which 3 would you upvote, in order?"                                        models: Flash, Flash-Lite
  summary one taste summary per person per month (comments before the month), embedded with bge-small and matched
          to each launch's embedding: one call per person-month instead of one per person-day   models: Flash, Flash-Lite
Every call logs Gemini's token usage, so the cost is measured. Scored like seq.py: simcore choice inputs + one persona
feature, trained on Sep, tested on Oct, top-3 hit with a bootstrap interval.
usage: SIMLAB_DATA=data_v2 python -m simlab.persona_lab call [threads] ; python -m simlab.persona_lab score"""
import json, os, random, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests
from . import store
from .persona import card, CACHE
from .taste import PROMPT as RATE_PROMPT
from .variants import sample

OUT = os.path.join(CACHE, "persona_lab.jsonl")
MODELS = {"flash": "gemini-2.5-flash", "lite": "gemini-2.5-flash-lite"}
PRICE = {"flash": (0.30, 2.50), "lite": (0.10, 0.40)}   # $ per 1M input / output tokens (Vertex pricing page, Oct 27)
PICK = """You are this Product Hunt user, looking at today's launches. Which 3 would you upvote? Judge by your own interests
and work only, not by who made them or how popular they are.

Person: {card}

Launches:
{lineup}

Reply with JSON only: {{"picks": [<launch number you would upvote first>, <second>, <third>]}}"""
SUMMARY = """Here is a Product Hunt user. In about 80 words, describe the products they would upvote: the problems, tools
and categories they care about, and what they would scroll past. Write it as a plain description, no preamble.

Person: {card}"""
TOK, lock = {}, threading.Lock()


def gem(prompt, model):
    url = (f"https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
           f"models/{MODELS[model]}:generateContent")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800, "thinkingConfig": {"thinkingBudget": 0}}}
    for a in range(5):
        if a or "v" not in TOK:
            TOK["v"] = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
        try:
            r = requests.post(url, json=body, headers={"Authorization": f"Bearer {TOK['v']}"}, timeout=120)
            if r.status_code == 200:
                j = r.json(); c = (j.get("candidates") or [{}])[0]; u = j.get("usageMetadata", {})
                return "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", [])), \
                    u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
        except requests.RequestException:
            pass
        time.sleep(5 * (a + 1))
    return "", 0, 0


def cards():
    """Comment cards per (person, day) for the sample, and per (person, month start) for the summaries."""
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); names = {r.id: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    slug2name = {r.slug: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    pdict = P.set_index("person").to_dict("index")
    C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").sort_values("date")
    Cg = C.groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text)), include_groups=False).to_dict()
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    lineups = {}
    for i, d in day.items():
        lineups.setdefault(d, []).append(i)

    def make(u, d):
        h = [it for dt, it in hist.get(u, []) if dt < d]
        c = card(pdict[u], list(range(len(h))), {k: names[it] for k, it in enumerate(h)}, d)
        cs = [(dt, sl, t) for dt, sl, t in Cg.get(u, []) if dt < d][-5:]
        if cs:
            c += " | their comments: " + " / ".join(f"on {slug2name.get(sl, sl)[:40]}: \"{t[:160]}\"" for dt, sl, t in cs)
        return c
    pds = [(u, d) for u, d in sample() if u in pdict]
    return pds, make, {d: sorted(v) for d, v in lineups.items()}, names


def call(threads=48):
    pds, make, lineups, names = cards()
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            r = json.loads(l); done.add((r["kind"], r["model"], r["person"], r["key"]))
    jobs = []
    for u, d in pds:
        jobs += [("rate", "lite", u, d), ("pick3", "flash", u, d), ("pick3", "lite", u, d)]
    months = sorted({(u, d[:7] + "-01") for u, d in pds})
    jobs += [("summary", m, u, ms) for u, ms in months for m in ("flash", "lite")]
    jobs = [j for j in jobs if j not in done]
    print("calls to make:", len(jobs), flush=True)

    def one(j):
        kind, model, u, key = j
        if kind == "summary":
            txt, ti, to = gem(SUMMARY.format(card=make(u, key)), model); val = txt.strip()
        else:
            line = lineups[key]; lu = "\n".join(f"{k + 1}. {names[x]}" for k, x in enumerate(line))
            prompt = (RATE_PROMPT.format(card=make(u, key), lineup=lu, n=len(line)) if kind == "rate"
                      else PICK.format(card=make(u, key), lineup=lu))
            txt, ti, to = gem(prompt, model)
            try:
                js = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
                val = ({x: float(v) for x, v in zip(line, js["ratings"])} if kind == "rate"
                       else [line[int(k) - 1] for k in js["picks"] if 1 <= int(k) <= len(line)][:3])
            except Exception:  # noqa: BLE001
                val = None
        with lock, open(OUT, "a") as f:
            f.write(json.dumps({"kind": kind, "model": model, "person": u, "key": key, "value": val, "tin": ti, "tout": to}) + "\n")
    with ThreadPoolExecutor(threads) as ex:
        for k, _ in enumerate(ex.map(one, jobs)):
            if k % 1000 == 0:
                print("done", k, flush=True)


def score():
    from .push import FRAME, fit, CAT
    from .v2_compare import CF
    R = [json.loads(l) for l in open(OUT)]
    cost = {}
    for r in R:
        c = cost.setdefault((r["kind"], r["model"]), [0, 0, 0, 0])
        c[0] += 1; c[1] += r["tin"]; c[2] += r["tout"]; c[3] += r["value"] is None
    print("measured usage:")
    for (k, m), (n, ti, to, bad) in sorted(cost.items()):
        usd = ti / 1e6 * PRICE[m][0] + to / 1e6 * PRICE[m][1]
        print(f"  {k:8s} {m:6s} calls {n:5d}  failed {bad:4d}  tokens in/out per call {ti / n:6.0f} / {to / n:4.0f}  ${usd:.2f}")
    S = {f"{u}|{d}" for u, d in sample()}
    D = pd.read_parquet(FRAME); D = D[D.g.isin(S)].copy()
    Z = np.load(f"{store.RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}; EM = Z["launch"]
    from sentence_transformers import SentenceTransformer
    bge = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    feats = {}
    for kind, model in (("rate", "lite"), ("pick3", "flash"), ("pick3", "lite"), ("summary", "flash"), ("summary", "lite")):
        name = f"{kind}_{model}"; rows = [r for r in R if r["kind"] == kind and r["model"] == model and r["value"]]
        if kind == "rate":
            m = {(r["person"], r["key"]): r["value"] for r in rows}
            D[name] = [m.get((u, d), {}).get(x, np.nan) for u, d, x in zip(D.person, D.day, D.id)]
        elif kind == "pick3":
            m = {(r["person"], r["key"]): r["value"] for r in rows}
            D[name] = [(3 - m[(u, d)].index(x)) if (u, d) in m and x in m[(u, d)] else (0 if (u, d) in m else np.nan)
                       for u, d, x in zip(D.person, D.day, D.id)]
        else:
            keys = [(r["person"], r["key"]) for r in rows]
            V = bge.encode([r["value"] for r in rows], normalize_embeddings=True, batch_size=64)
            vm = dict(zip(keys, V))
            D[name] = [float(vm[(u, d[:7] + "-01")] @ EM[li[x]]) if (u, d[:7] + "-01") in vm and x in li else np.nan
                       for u, d, x in zip(D.person, D.day, D.id)]
        D[name] = D.groupby("g")[name].rank(pct=True); feats[name] = name
    SEQ = ["seq_last10", "seq_decay", "seq_nn", "team_recent"]
    base = ["backed", "topic", "meaning"] + CF + SEQ + [c for c in CAT if c != "cat_rank"]
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy(); te = te[te.g.isin(te[te.y == 1].g)]
    rng = np.random.default_rng(0)

    def hits(cols):
        t = te.assign(p=fit(tr, te, cols)); t["r"] = t.groupby("g").p.rank(ascending=False, method="first")
        return t[t.r <= 3].groupby("g").y.max().reindex(t.g.unique(), fill_value=0)
    h0 = hits(base); res = {"simcore choice inputs": round(float(h0.mean()), 3)}
    print(f"\ntest person-days {te.g.nunique()}; simcore choice inputs: top3 {h0.mean():.3f}")
    for name in ["p3"] + list(feats):
        h = hits(base + [name]); d = (h - h0.reindex(h.index)).values
        ci = np.percentile([d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)], [2.5, 97.5]) * 100
        label = {"p3": "rate_flash (existing)"}.get(name, name)
        print(f"  + {label:22s} top3 {h.mean():.3f}  gain {100 * d.mean():+.1f} pts (95% {ci[0]:+.1f} to {ci[1]:+.1f})")
        res[label] = {"top3": round(float(h.mean()), 3), "gain": round(100 * float(d.mean()), 1), "ci": [round(float(x), 1) for x in ci]}
    json.dump({"cost": {f"{k}|{m}": v for (k, m), v in cost.items()}, "scores": res},
              open(os.path.join(os.path.dirname(CACHE), "reports", "persona_lab.json"), "w"), indent=1)


if __name__ == "__main__":
    call(int(sys.argv[2]) if len(sys.argv) > 2 else 48) if sys.argv[1] == "call" else score()
