"""Name each launch's top 3 established competitors (website, X handle, LinkedIn company slug) with Claude on Vertex.
Competitors are mostly older products the model knows; it is told not to guess handles it doesn't know.
Writes data/competitors.json {launch_id: [{name, domain, x, linkedin}, ...]}; resumable."""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/competitors.json"
PROMPT = """For each product below (all launched on Product Hunt in 2026), name its 3 closest ESTABLISHED competitors:
products people already use for the same job. Prefer well-known products. For each competitor give its main website
domain, its X/Twitter handle and its LinkedIn company slug (the part after linkedin.com/company/) ONLY if you are
confident; otherwise use "".

{items}

Reply with JSON only: {{"<id>": [{{"name": "...", "domain": "...", "x": "...", "linkedin": "..."}}, ...], ...}}"""


def batch(rows):
    items = "\n".join(f"[{r['id']}] {r['name']} — {r['tagline']} (topics: {', '.join(r['topics'])})" for r in rows)
    txt = llm.call(PROMPT.format(items=items), max_tokens=250 * len(rows) + 500)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    import glob
    want = {x["id"] for x in json.load(open(f"{D}/sepoct_handles.json"))}
    rows = [{"id": p["id"], "name": p["name"], "tagline": p["tagline"] or "",
             "topics": [e["node"]["name"] for e in p["topics"]["edges"]]}
            for f in sorted(glob.glob(f"{D}/days/2026-0[9]-*.json") + glob.glob(f"{D}/days/2026-10-*.json"))
            for p in json.load(open(f)) if p["id"] in want]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    rows = [r for r in rows if r["id"] not in out]
    chunks = [rows[i:i + 15] for i in range(0, len(rows), 15)]
    print("todo", len(rows), "batches", len(chunks), flush=True)
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as ex:
        for i, res in enumerate(ex.map(batch, chunks)):
            out.update(res)
            json.dump(out, open(OUT, "w"))
            if i % 10 == 0:
                print(i, len(out), flush=True)
    print("done", len(out))
