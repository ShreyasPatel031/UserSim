"""Typed concerns / questions, step 2-3 (orchestrator 00:47Z Nov 14). Scratch-only texts; counts only in commits.
(a) taxonomy: gemini-2.5-pro reads a random sample of 700 non-team comments from Jan-Feb launches only and proposes 15-25 CONCERN types
    (critical / sceptical points) and 10-15 QUESTION types, each with a short id, name and one-line definition. Frozen to taxonomy.json.
(b) labels: gemini-2.5-flash-lite, one call per launch with >= 5 non-team comments (first 25 by order): each comment -> kind (concern /
    question / other) and one type id from the frozen taxonomy (or 'other'). Written to labels.jsonl (launch id, comment index, kind, type).
    python typed_label.py <scratchpad> taxonomy|label
"""
import asyncio, json, os, re, sys
import numpy as np, pandas as pd
SP, STEP = sys.argv[1:3]; TD = f"{SP}/typed"
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); sys.path[:0] = [os.path.join(SP, "phweb"), os.path.join(SP, "phweb", "src")]
from capability import gemini_config as GC  # noqa: E402
B = pd.read_parquet(f"{TD}/bank.parquet"); USD = {"usd": 0.0}
async def call(p, model, tok, pin, pout, **kw):
    try:
        r = await GC.gemini_chat([{"role": "user", "content": p}], model=model, temperature=0.0, max_retries=3, max_output_tokens=tok, **kw)
        USD["usd"] += len(p) / 4 / 1e6 * pin + len(r) / 4 / 1e6 * pout; return GC.extract_json(r) or {}
    except Exception: return {}
if STEP == "taxonomy":
    S = B[B.day < "2026-03-01"].sample(700, random_state=0)
    p = ("Below are 700 user comments from product launches on Product Hunt (makers' own comments removed). Induce a taxonomy of what users "
         "raise. Return JSON {\"concern_types\": [{\"id\": \"c_<short>\", \"name\": ..., \"definition\": one line}], \"question_types\": [same with q_]} "
         "with 15-25 concern types (critical or sceptical points: pricing, privacy/data, already exists / vs a named alternative, platform support, "
         "onboarding friction, trust / who is behind it, AI wrapper, performance, missing integration, etc. - use what the comments show) and 10-15 "
         "question types (what users ask). Types must be general across products, mutually distinct, and cover most critical comments and questions.\n\n"
         + "\n".join(f"- {t[:300]}" for t in S.text))
    T = asyncio.run(call(p, "gemini-2.5-pro", 12000, 1.25, 10.0, thinking_budget=2048)); json.dump(T, open(f"{TD}/taxonomy.json", "w"), indent=1)
    print(len(T.get("concern_types", [])), len(T.get("question_types", [])), "usd", round(USD["usd"], 3)); print([c["id"] for c in T.get("concern_types", [])]); print([c["id"] for c in T.get("question_types", [])])
else:
    T = json.load(open(f"{TD}/taxonomy.json")); ty = "\n".join(f"{c['id']}: {c['name']} - {c['definition']}" for c in T["concern_types"] + T["question_types"])
    n = B.groupby("id").size(); ids = n[n >= 5].index; OUT = f"{TD}/labels.jsonl"; done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    P = ("Classify each user comment on a product launch. For each numbered comment return kind: 'concern' (critical, sceptical, objection, "
         "complaint or request implying a gap), 'question' (asks something), or 'other' (praise, congratulations, generic); and type: the single best "
         "id from the list for that kind (c_* for concerns, q_* for questions) or 'other'. Return JSON {{\"labels\": [{{\"i\": n, \"kind\": ..., \"type\": ...}}, ...]}}.\n\nTYPES:\n{ty}\n\nCOMMENTS:\n{cm}")
    async def run():
        sem = asyncio.Semaphore(16); f = open(OUT, "a")
        async def one(i):
            g = B[B.id == i].head(25)
            async with sem:
                a = await call(P.format(ty=ty, cm="\n".join(f"{k+1}. {t[:400]}" for k, t in enumerate(g.text))), "gemini-2.5-flash-lite", 2500, 0.10, 0.40)
            for x in a.get("labels") or []:
                try: f.write(json.dumps({"id": i, "i": int(x.get("i")), "kind": x.get("kind"), "type": x.get("type")}) + "\n")
                except Exception: pass
            f.flush()
        await asyncio.gather(*[one(i) for i in ids if i not in done]); f.close()
    asyncio.run(run()); print("labelled launches", len({json.loads(l)["id"] for l in open(OUT)}), "of", len(ids), "usd", round(USD["usd"], 3))
