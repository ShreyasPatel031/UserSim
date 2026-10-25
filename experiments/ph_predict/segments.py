"""Detailed segments for Product Hunt commenters, from their profile headline + bio (Claude on Vertex), plus their
Product Hunt activity. Output data/segments.jsonl: one row per person with the LLM labels and activity fields.
Usernames are kept during research; reduce to segment counts before any ongoing pipeline."""
import gzip, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/segments.jsonl"
PROMPT = """Classify each Product Hunt user from their profile headline and bio. Use only what the text says; use "unknown"
when it doesn't say.

Fields:
- role: founder_exec | engineer | data_ml | designer | product | marketing_growth | sales_bd | investor | creator |
  student | operations | other | unknown
- seniority: founder_c_level | senior_lead | mid | junior | student | unknown
- company_type: own_startup | startup_employee | big_tech | enterprise | agency_consulting | freelancer | academic |
  unknown
- domain: the field they work in, one of: ai_ml | developer_tools | saas_b2b | marketing | design | fintech | ecommerce |
  health | education | media_content | crypto_web3 | hardware | gaming | consumer_apps | other | unknown
- builder: true if they build/ship software products themselves, else false
- region: country or region if stated, else "unknown"

Users:
{items}

Reply with JSON only: {{"<username>": {{"role": "...", "seniority": "...", "company_type": "...", "domain": "...",
"builder": true, "region": "..."}}, ...}}"""


def batch(rows):
    items = "\n".join(f"[{r['username']}] headline: {(r.get('headline') or '')[:160]} | bio: {(r.get('about') or '')[:240]}"
                      for r in rows)
    txt = llm.call(PROMPT.format(items=items), max_tokens=90 * len(rows) + 400)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    P = [json.loads(l) for l in gzip.open(f"{D}/ph_profiles.jsonl.gz", "rt")]
    done = {json.loads(l)["username"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [p for p in P if p["username"] not in done]
    has_text = [p for p in todo if p.get("headline") or p.get("about")]
    chunks = [has_text[i:i + 40] for i in range(0, len(has_text), 40)]
    print("todo", len(todo), "with text", len(has_text), "batches", len(chunks), flush=True)
    by_user = {p["username"]: p for p in todo}
    with open(OUT, "a") as f:
        for p in todo:  # people with no headline/bio: activity only
            if not (p.get("headline") or p.get("about")):
                f.write(json.dumps({"username": p["username"], "labels": None}) + "\n")
        with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 5) as ex:
            for i, res in enumerate(ex.map(batch, chunks)):
                for u, lab in res.items():
                    if u in by_user:
                        f.write(json.dumps({"username": u, "labels": lab}) + "\n")
                f.flush()
                if i % 10 == 0:
                    print(i, flush=True)
    print("done")
