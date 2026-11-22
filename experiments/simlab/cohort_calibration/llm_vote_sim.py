"""PREREG addendum 4: Gemini 2.5 Flash simulates which of the day's launches an active person upvotes; scored against real upvotes.
Key from env GEMINI_API_KEY (never written to disk). Aggregates only: no person ids or names in the output.
    GEMINI_API_KEY=... python llm_vote_sim.py <store dir> <backtest_v1 dir> <out json> <day> [<day> ...]"""
import concurrent.futures as cf, io, json, os, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); import period_parts as PP
ST, BT, OUT = sys.argv[1:4]; DAYS = sys.argv[4:]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; KEY = os.environ["GEMINI_API_KEY"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"; USE = {"in": 0, "out": 0}
def gem(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 4000, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    for a in range(4):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": KEY})
            with urllib.request.urlopen(req, timeout=120) as r: d = json.load(r)
            u = d.get("usageMetadata", {}); USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
            return json.loads(d["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:
            err = str(e); time.sleep(2 ** a)
    print("call failed:", err[:200], file=sys.stderr); return None
L = {r["launch_id"]: r for r in map(json.loads, open(f"{BT}/launches.jsonl"))}
PR = {r["launch_id"]: r for r in map(json.loads, open(f"{BT}/predictions.jsonl"))}
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)))); from pipeline import warehouse
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
INFO = {i: (n, t, tp) for i, n, t, tp in zip(W.id, W.name, W.tagline, W.topics)}; U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
first = U.groupby("person_id").ft.min(); last = U.groupby("person_id").ft.max()
topics = lambda i: set(json.loads(INFO[i][2]) if isinstance(INFO.get(i, (0, 0, None))[2], str) and str(INFO[i][2]).startswith("[") else [])
line = lambda i: f"{INFO[i][0]} - {INFO[i][1]} [{', '.join(sorted(topics(i)))}]" if i in INFO else None
PROMPT = """You are simulating one specific Product Hunt user. Below are the launches this person upvoted most recently (newest first), which show their taste.
{hist}

Today's launches:
{today}

{extra}For EACH of today's launches, estimate the likelihood (0-100) that this person upvotes it today. Most people upvote only a few launches per day.
JSON only: {{"likelihood": [{{"n": <launch number>, "p": <0-100>}}, ...]}}"""
rng = np.random.default_rng(0); rows = []
for D in DAYS:
    ids = [l for l, r in L.items() if r["day"] == D and l in INFO]
    close = PP.close_utc(D); start = close - pd.Timedelta(days=1); d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    past = U[(U.lday < D) & (U.lday >= d30) & (U.ft < start)]; act = past.person_id.value_counts()
    pool = [p for p in act[act >= 20].index if p in COMPLETE and last.get(p) > close and first.get(p) < start]
    pick = list(rng.choice(sorted(pool), min(60, len(pool)), replace=False))
    raw = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/backer_pred/{D}.parquet"], capture_output=True).stdout
    CFp = {}
    if raw:
        C = pd.read_parquet(io.BytesIO(raw)); CFp = {(str(l), p): v for l, p, v in zip(C.launch_id, C.person_id, C.p)}
    voted = set(zip(U[U.lday == D].person_id, U[U.lday == D].target_id))
    pop = {l: (PR.get(l, {}).get("forecast_prereveal_0345") or {}).get("predicted_rank") for l in ids}
    def one(p):
        h = U[(U.person_id == p) & (U.lday < D) & (U.ft < start)].sort_values("lday", ascending=False).target_id.drop_duplicates().head(40)
        hl = [line(i) for i in h if line(i)]; ht = [topics(i) for i in h]
        V2 = os.environ.get("PROMPT_V") == "2"; ph = past[past.person_id == p]; rate = len(ph) / max(1, ph.lday.nunique())
        tm = {i: float(np.mean([len(topics(i) & t) > 0 for t in ht])) if ht else 0.0 for i in ids}
        lab = (lambda k, i: f"{k + 1}. {line(i)} | forecast rank today: {'#' + str(pop[i]) if pop[i] else 'unranked'} of {len(ids)} | topic match with this person's history: {round(100 * tm[i])}%") if V2 else (lambda k, i: f"{k + 1}. {line(i)}")
        extra = (f"On days this person votes, they upvote about {rate:.1f} launches on average. The forecast rank is a model's prediction of how popular each launch "
                 f"will be today (popular launches get far more votes); topic match is how much of this person's history shares a topic with the launch. "
                 f"Make the likelihoods realistic: they should add up to roughly {100 * rate:.0f} in total.\n") if V2 else ""
        j = gem(PROMPT.format(hist="\n".join(f"- {x}" for x in hl), today="\n".join(lab(k, i) for k, i in enumerate(ids)), extra=extra))
        lk = {int(x["n"]) - 1: float(x["p"]) for x in ((j or {}).get("likelihood") or []) if isinstance(x, dict) and "n" in x and "p" in x}
        out = []
        for k, i in enumerate(ids):
            tp = topics(i)
            out.append({"day": D, "pi": pick.index(p), "y": int((p, i) in voted), "llm": lk.get(k, np.nan), "cf": CFp.get((i, p), 0.0),
                        "pop": -(pop[i] if pop[i] is not None else 99), "topic": float(np.mean([len(tp & t) > 0 for t in ht])) if ht else 0.0})
        return out
    with cf.ThreadPoolExecutor(8) as ex:
        for o in ex.map(one, pick): rows += o
    print(D, len(ids), "launches", len(pick), "people", flush=True)
R = pd.DataFrame(rows).dropna(subset=["llm"]); R["key"] = R.day + "_" + R.pi.astype(str)
R["ens"] = R.groupby("key").llm.rank(pct=True) + R.groupby("key")["pop"].rank(pct=True)
ARMS = ["llm", "cf", "pop", "topic", "ens"]; rng = np.random.default_rng(1)
def per_person(df, a):
    v = [roc_auc_score(g.y, g[a]) for _, g in df.groupby("key") if 0 < g.y.sum() < len(g)]; return float(np.mean(v)) if v else np.nan
def rec5(df, a):
    v = [g.nlargest(5, a).y.sum() / g.y.sum() for _, g in df.groupby("key") if g.y.sum() > 0]; return float(np.mean(v)) if v else np.nan
def boot(f):
    d = sorted(R.day.unique()); bs = [f(pd.concat([R[R.day == z] for z in rng.choice(d, len(d))])) for _ in range(500)]
    return [round(f(R), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]
out = {"prereg": "PREREG.md addendum 4" + ("b" if os.environ.get("PROMPT_V") == "2" else ""), "ens": "rank average of LLM and POP per person", "days": DAYS, "people": int(R.key.nunique()), "cells": int(len(R)), "votes": int(R.y.sum()),
       "people with >= 1 vote": int((R.groupby("key").y.sum() > 0).sum()), "base rate": round(float(R.y.mean()), 4),
       "pooled AUC": {a: boot(lambda x, a=a: roc_auc_score(x.y, x[a])) for a in ARMS},
       "mean per-person AUC": {a: boot(lambda x, a=a: per_person(x, a)) for a in ARMS},
       "recall@5 (people with a vote)": {a: boot(lambda x, a=a: rec5(x, a)) for a in ARMS},
       "LLM minus CF pooled AUC": boot(lambda x: roc_auc_score(x.y, x.llm) - roc_auc_score(x.y, x.cf)),
       "ENS (rank avg LLM+POP) minus POP pooled AUC": boot(lambda x: roc_auc_score(x.y, x.ens) - roc_auc_score(x.y, x["pop"])),
       "LLM minus best baseline (POP) pooled AUC": boot(lambda x: roc_auc_score(x.y, x.llm) - roc_auc_score(x.y, x["pop"])),
       "count: predicted sum(p)/100 vs real votes per person": [round(float(R.llm.sum() / 100 / R.key.nunique()), 2), round(float(R.y.sum() / R.key.nunique()), 2)],
       "usd": round(USE["in"] / 1e6 * 0.30 + USE["out"] / 1e6 * 2.50, 4), "note": "[value, day-bootstrap 2.5%, 97.5%]; 3 days so intervals are wide"}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": "llm_vote_sim", "provider": "gemini_api", "usd": out["usd"]}) + "\n")
