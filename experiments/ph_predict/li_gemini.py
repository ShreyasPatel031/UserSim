"""LinkedIn headline/role/company/location for people who link their LinkedIn on Product Hunt, read from Google
search results through Gemini with Google Search grounding (Vertex, our GCP project). 10 people per request.
usage: python li_gemini.py [max_people] [threads]   -> appends to data/li_search.jsonl (skips people already done)"""
import ast, gzip, json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RETRY = os.environ.get("RETRY") == "1"  # second pass: people not found, smaller batches
OUT = f"{D}/li_search_retry.jsonl" if RETRY else f"{D}/li_search.jsonl"
BS = 3 if RETRY else 10
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
       "models/gemini-2.5-flash:generateContent")
PROMPT = ("Search Google for each LinkedIn profile below. Report only what the search results show (the LinkedIn result "
          "title is usually 'Name - Headline'; snippets may show location, current company, education). Do not guess.\n"
          "Return one JSON object per line, no other text: {\"id\":n, \"name\":..., \"headline\":<LinkedIn headline as shown>, "
          "\"role\":..., \"company\":..., \"location\":..., \"education\":..., \"found\":true|false}\n")
lock = threading.Lock()
tok = {"v": None}


def token(refresh=False):
    if refresh or not tok["v"]:
        tok["v"] = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    return tok["v"]


def people():
    for fn in (f"{D}/ph_profiles2.jsonl.gz", f"{D}/ph_profiles_rest.jsonl.gz"):
        for l in gzip.open(fn, "rt"):
            p = json.loads(l)
            links = p.get("links") or []
            links = ast.literal_eval(links) if isinstance(links, str) else links
            li = [x.get("url") if isinstance(x, dict) else str(x) for x in links]
            li = [u for u in li if u and "linkedin.com/in/" in u]
            if li:
                yield {"username": p["username"], "ph_name": p.get("name"), "url": li[0].split("?")[0]}


def batch(b):
    text = PROMPT + "\n".join(f"{i}. {x['url']} (name on Product Hunt: {x['ph_name']})" for i, x in enumerate(b))
    body = {"contents": [{"role": "user", "parts": [{"text": text}]}], "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0}}
    for attempt in range(5):
        try:
            r = requests.post(URL, json=body, headers={"Authorization": f"Bearer {token(attempt > 0)}"}, timeout=120)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            break
        print("status", r.status_code, r.text[:150].replace("\n", " "), flush=True)
        time.sleep(10 * (attempt + 1))
    else:
        return
    if not ((r.json().get("candidates") or [{}])[0].get("content")):
        return  # empty answer: leave these people for a retry run
    d = r.json(); c = (d.get("candidates") or [{}])[0]
    txt = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
    got = {}
    for m in re.finditer(r"\{[^{}]*\}", txt):
        try:
            o = json.loads(m.group(0)); got[int(o.pop("id"))] = o
        except Exception:  # noqa: BLE001
            pass
    q = (c.get("groundingMetadata") or {}).get("webSearchQueries") or []
    with lock, open(OUT, "a") as f:
        for i, x in enumerate(b):
            f.write(json.dumps({**x, **got.get(i, {"found": None}), "n_queries_batch": len(q)}) + "\n")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    th = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    done = {json.loads(l)["username"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [p for p in people() if p["username"] not in done]
    if RETRY:
        miss = {json.loads(l)["username"] for l in open(f"{D}/li_search.jsonl") if not json.loads(l).get("found")}
        todo = [p for p in todo if p["username"] in miss]
    todo = todo[:n]
    bs = [todo[i:i + BS] for i in range(0, len(todo), BS)]
    print("people", len(todo), "requests", len(bs), flush=True)
    with ThreadPoolExecutor(th) as ex:
        list(ex.map(batch, bs))


if __name__ == "__main__":
    main()
