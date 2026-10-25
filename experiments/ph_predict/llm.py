"""LLM judges each day's launches together (listwise), blind to votes. Two modes:
  pitch — name, tagline, description, topics          -> llm_pitch
  site  — the same + launch-day homepage text excerpt  -> llm_site
Also asks whether it recognises the product (memorisation check) -> llm_known.
Claude Sonnet 4.5 on Vertex (training data predates every launch here). Cached per day in data/llm_<mode>/."""
import json, os, re, subprocess, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import features as F

D = F.D
MODEL = "claude-sonnet-4-5"
URL = (f"https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/"
       f"anthropic/models/{MODEL}:rawPredict")
_tok = {"t": "", "at": 0}
_lk = threading.Lock()


def token():
    with _lk:
        if time.time() - _tok["at"] > 1800:
            _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            _tok["at"] = time.time()
        return _tok["t"]


def call(prompt, max_tokens=4000):
    body = {"anthropic_version": "vertex-2023-10-16", "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(),
                                         {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["content"][0]["text"]
        except Exception as e:  # noqa: BLE001
            print("llm retry", i, str(e)[:120], flush=True); time.sleep(5 * (i + 1))
    return ""


PROMPT = """You are predicting Product Hunt launch-day results. Below are all {n} products featured on Product Hunt on {day}.
Predict how each will do on the daily leaderboard (upvotes). Judge from {basis} only.

For EVERY product return a score 0-100 = your estimated probability (in %) that it finishes in the day's top 5, and
"known": true only if you specifically recognise this exact product and remember how its launch went.

Products:
{items}

Reply with JSON only: {{"<id>": {{"score": <0-100>, "known": <true|false>}}, ...}}"""


BRAND = """Below are products launched on Product Hunt on {day}. For each, rate how well known the company or brand
behind it already was BEFORE this launch, from what you know: 0 = never heard of it, 1 = niche/small, 2 = well known
in its niche, 3 = widely known brand (e.g. Notion, Figma, OpenAI). Judge the company, not this exact product.

{items}

Reply with JSON only: {{"<id>": <0-3>, ...}}"""


def item(r, mode):
    s = f"[{r.id}] {r['name']} — {r.tagline}\n  topics: {', '.join(r.topics)}\n  description: {r.description[:400]}"
    if mode == "site":
        s += f"\n  homepage ({'launch-day snapshot' if r.web_src_wayback else 'current site' if r.web_src_live else 'unavailable'}): {(r.web_text or '')[:700]}"
    return s


def run_day(day, g, mode):
    out = f"{D}/llm_{mode}/{day}.json"
    if os.path.exists(out):
        return
    if mode == "brand":
        items = "\n".join(f"[{r.id}] {r['name']} — {r.tagline} (site: {r.domain or 'unknown'})" for _, r in g.iterrows())
        txt = call(BRAND.format(day=day, items=items), max_tokens=20 * len(g) + 300)
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            res = {k: {"score": v} for k, v in json.loads(m.group(0)).items()}
        except Exception:  # noqa: BLE001
            print("bad json", day, txt[:200], flush=True); return
        json.dump(res, open(out, "w")); print(mode, day, len(res), flush=True); return
    basis = "the pitch (name, tagline, description, topics)" if mode == "pitch" else "the pitch and the homepage text"
    txt = call(PROMPT.format(n=len(g), day=day, basis=basis, items="\n".join(item(r, mode) for _, r in g.iterrows())),
               max_tokens=60 * len(g) + 500)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        res = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        print("bad json", day, txt[:200], flush=True); return
    json.dump(res, open(out, "w"))
    print(mode, day, len(res), flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    os.makedirs(f"{D}/llm_{mode}", exist_ok=True)
    df = F.build()
    days = sorted(df.day.unique(), reverse=True)
    if mode in ("site", "brand"):  # only days whose websites have been resolved (unresolved counts as resolved-without-site)
        seen = set(F._jl("sites.jsonl", "id"))
        days = [d for d in days if df[df.day == d].id.isin(seen).mean() > 0.95]
    with ThreadPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 4) as ex:
        list(ex.map(lambda d: run_day(d, df[df.day == d], mode), days))
