"""Launch-specific promotion before launch, from Google results via Gemini with Google Search grounding (Vertex).
For each Sep–Oct launch: posts by the founders / company on LinkedIn and X (and elsewhere) about the product or its
Product Hunt launch, dated BEFORE launch day; founders' and company's LinkedIn/X follower counts as shown; earlier
coverage (press, Hacker News, Reddit, newsletters). Only items with a date before launch day count as pre-launch.
usage: python promo_search.py [max_launches] [threads] -> appends data/promo_search.jsonl (skips done)
       TODAY=YYYY-MM-DD python promo_search.py   (live: today's launches at forecast time; 1,500 searches/day are free)"""
import json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/promo_search.jsonl"
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
       "models/gemini-2.5-flash:generateContent")
PROMPT = """Use Google Search to find how this product was promoted BEFORE its Product Hunt launch.
Product: {name} — {tagline}
Website: {site}
Founders/makers: {makers}
Company X: {cx}   Founders' X: {mx}
Product Hunt launch day: {day}

Search for: LinkedIn posts and X posts by the founders or the company about this product or its launch; the founders'
and company's LinkedIn/X follower counts; earlier press, Hacker News, Reddit, newsletter or blog coverage; funding.
Report only what search results show. Give dates as YYYY-MM-DD when shown (null if not shown). Do not guess numbers.
Reply with JSON only:
{{"posts": [{{"platform": "linkedin|x|other", "author": "...", "author_role": "founder|company|other", "date": "...",
   "about_launch": true|false, "reactions": n|null, "comments": n|null, "snippet": "..."}}],
 "founder_linkedin_followers": n|null, "company_linkedin_followers": n|null, "founder_x_followers": n|null,
 "coverage": [{{"source": "...", "type": "press|hackernews|reddit|newsletter|blog|other", "date": "...", "title": "..."}}],
 "funding": "...|null", "company_founded": "YYYY|null", "notes": "..."}}"""
lock = threading.Lock()
TOK = {}


def token(refresh=False):
    with lock:   # threads start together: one gcloud call, not eight racing ones
        return _token(refresh)


def _token(refresh):
    if refresh or "v" not in TOK:
        TOK["v"] = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    return TOK["v"]


def launches():
    makers = {}
    for f in os.listdir(f"{D}/days"):
        if f >= "2026-09":
            for p in json.load(open(f"{D}/days/{f}")):
                makers[p["id"]] = [m.get("name") or m["username"] for m in p.get("makers") or []]
                makers[p["id"] + "_t"] = p["tagline"]
    for h in json.load(open(f"{D}/sepoct_handles.json")):
        yield {"id": h["id"], "day": h["day"], "name": h["name"], "tagline": makers.get(h["id"] + "_t", ""),
               "site": (h.get("site_url") or "").split("?")[0], "makers": ", ".join(makers.get(h["id"], [])[:5]),
               "cx": h.get("company_x") or "", "mx": ", ".join(h.get("makers_x") or [])}


def launches_today(day):
    """Today's launches at forecast time (live): site from sites_today.jsonl, X handles from the makers' profiles."""
    site = {}
    if os.path.exists(f"{D}/sites_today.jsonl"):
        for l in open(f"{D}/sites_today.jsonl"):
            r = json.loads(l)
            site[str(r.get("id"))] = r.get("domain") or r.get("url") or ""
    for p in json.load(open(f"{D}/today/{day}.json")):
        mk = p.get("makers") or []
        yield {"id": p["id"], "day": day, "name": p["name"], "tagline": p["tagline"], "site": site.get(str(p["id"]), ""),
               "makers": ", ".join((m.get("name") or m["username"]) for m in mk[:5]), "cx": "",
               "mx": ", ".join(m["twitterUsername"] for m in mk[:5] if m.get("twitterUsername"))}


def launches_range(a, b):
    """Launches between days a..b from the PH day files; site = resolved domain from the backtest table."""
    import pandas as pd
    dom = pd.read_csv(f"{os.path.dirname(D)}/results/predictions.csv", usecols=["id", "domain"])
    dom = dict(zip(dom.id.astype(str), dom.domain.fillna("")))
    for f in sorted(os.listdir(f"{D}/days")):
        if a <= f[:10] <= b:
            for p in json.load(open(f"{D}/days/{f}")):
                yield {"id": p["id"], "day": f[:10], "name": p["name"], "tagline": p["tagline"], "site": dom.get(p["id"], ""),
                       "makers": ", ".join((m.get("name") or m["username"]) for m in (p.get("makers") or [])[:5]),
                       "cx": "", "mx": ""}


def one(x):
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(**x)}]}], "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0}}
    r = None
    for a in range(5):
        try:
            r = requests.post(URL, json=body, headers={"Authorization": f"Bearer {token(a > 0)}"}, timeout=150)
            if r.status_code == 200 and (r.json().get("candidates") or [{}])[0].get("content"):
                break
            print("status", r.status_code, r.text[:120].replace("\n", " "), flush=True)
        except requests.RequestException:
            pass
        time.sleep(5 * (a + 1))
    else:
        return
    c = r.json()["candidates"][0]
    txt = "".join(p.get("text", "") for p in c["content"]["parts"])
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        res = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        res = {"parse_error": txt[:500]}
    g = c.get("groundingMetadata") or {}
    rec = {"id": x["id"], "day": x["day"], "name": x["name"], "result": res, "queries": g.get("webSearchQueries"),
           "sources": [(s.get("web") or {}).get("uri") for s in g.get("groundingChunks") or []][:20]}
    with lock, open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    th = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    src = (launches_today(os.environ["TODAY"]) if os.environ.get("TODAY") else
           launches_range(*os.environ["RANGE"].split(":")) if os.environ.get("RANGE") else launches())
    todo = [x for x in src if x["id"] not in done][:n]
    print("launches", len(todo), flush=True)
    with ThreadPoolExecutor(th) as ex:
        list(ex.map(one, todo))


if __name__ == "__main__":
    main()
