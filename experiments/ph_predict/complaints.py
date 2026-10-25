"""Competitor reviews -> complaints -> does the new launch fix them? (Claude on Vertex, blind to launch results)

  step 1  per competitor: top complaints, top praise, who reviews it      -> data/competitor_summaries.json
  step 2  per launch: pitch + homepage + its competitors' summaries ->
          fixes_complaints (0-10), differentiation (0-10), demand (0-10)  -> data/complaint_fit.json"""
import gzip, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

S1 = """Below are Product Hunt reviews of several products. For EACH product, summarise what its users complain about
and what they love, and who reviews it (roles). Be concrete (missing features, pricing, speed, reliability, UX...).

{items}

Reply with JSON only: {{"<product>": {{"complaints": ["...", "...", "..."], "praise": ["...", "..."],
"reviewers": "one short phrase"}}, ...}}"""

S2 = """You are judging new products launched on Product Hunt against their established competitors.
For each new product: its pitch, homepage text, and what users of its competitors complain about and love.

Score each (0-10):
- fixes_complaints: how directly the new product addresses the competitors' users' main complaints
- differentiation: how clearly it is different from (not a clone of) the competitors
- demand: how strong the evident demand is for what it offers, given what competitors' users ask for

{items}

Reply with JSON only: {{"<id>": {{"fixes_complaints": n, "differentiation": n, "demand": n}}, ...}}"""


def call_json(prompt, max_tokens):
    txt = llm.call(prompt, max_tokens=max_tokens)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


def step1(workers):
    out_f = f"{D}/competitor_summaries.json"
    out = json.load(open(out_f)) if os.path.exists(out_f) else {}
    R = [json.loads(l) for l in gzip.open(f"{D}/competitor_reviews.jsonl.gz", "rt")]
    R = [r for r in R if r["reviews"] and r["competitor"] not in out]

    def block(r):
        rev = "\n".join(f"  - ({x.get('rating')}/5, {x.get('role') or 'user'}) {(x.get('text') or '')[:220]}" for x in r["reviews"][:25])
        return f"## {r['competitor']}\n{rev}"
    chunks = [R[i:i + 5] for i in range(0, len(R), 5)]
    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(lambda ch: call_json(S1.format(items="\n\n".join(block(r) for r in ch)), 1600), chunks):
            out.update(res)
            json.dump(out, open(out_f, "w"))
    print("competitor summaries:", len(out))
    return out


def step2(summ, workers):
    out_f = f"{D}/complaint_fit.json"
    out = json.load(open(out_f)) if os.path.exists(out_f) else {}
    H = json.load(open(f"{D}/sepoct_handles.json"))
    C = json.load(open(f"{D}/competitors.json"))
    import glob
    meta = {p["id"]: p for f in glob.glob(f"{D}/days/2026-09-*.json") + glob.glob(f"{D}/days/2026-10-*.json") for p in json.load(open(f))}
    low = {k.lower(): v for k, v in summ.items()}
    todo = []
    for x in H:
        comps = [(c["name"], low.get(c["name"].strip().lower())) for c in C.get(x["id"], [])]
        comps = [(n, s) for n, s in comps if s]
        if comps and x["id"] not in out:
            todo.append((x, comps))

    def block(item):
        x, comps = item
        p = meta.get(x["id"], {})
        cs = "\n".join(f"    {n}: complaints={s.get('complaints')}; praise={s.get('praise')}" for n, s in comps)
        return (f"[{x['id']}] {x['name']} — {p.get('tagline', '')}\n  description: {(p.get('description') or '')[:300]}\n"
                f"  homepage: {(x.get('site_text') or '')[:600]}\n  competitors:\n{cs}")
    chunks = [todo[i:i + 8] for i in range(0, len(todo), 8)]
    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(lambda ch: call_json(S2.format(items="\n\n".join(block(i) for i in ch)), 700), chunks):
            out.update(res)
            json.dump(out, open(out_f, "w"))
    print("launches scored:", len(out))


if __name__ == "__main__":
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    step2(step1(w), w)
