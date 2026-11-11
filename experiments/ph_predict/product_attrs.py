"""it9b product profile per launch (pre-registered with E5, Nov 11): Gemini 2.5 Flash-Lite, temperature 0, JSON schema,
one call per launch. Variant (a) prompt input = name, tagline, description[:1500], topics, number of makers (fields as of
launch; no votes, ranks, comments, badges, media URLs). Cached per launch id with timestamp, model id and prompt hash in
<OUT>/attrs_a.jsonl; frozen before scoring. The leak grep (digits next to upvote/vote/comment/rank/#) is run on every
prompt and counted.
usage: SIMBT=<dir> python product_attrs.py [threads]   -> <SIMBT>/product_attrs/attrs_a.jsonl + leak_grep.json"""
import hashlib, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import llm

WORK = os.environ["SIMBT"]; OUT = os.path.join(WORK, "product_attrs"); os.makedirs(OUT, exist_ok=True)
MODEL = "gemini-2.5-flash-lite"
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/"
       f"{MODEL}:generateContent")
CATS = ["developer_tools", "ai_assistant_or_agent", "productivity", "marketing_sales", "design_creative", "finance",
        "health_fitness", "education", "social_communication", "data_analytics", "security_privacy", "other"]
AUD = ["developers", "designers", "marketers", "founders", "sales", "consumers", "students", "creators", "teams", "enterprises"]
PLAT = ["web", "ios", "android", "mac", "windows", "browser_extension", "api_sdk", "cli", "hardware"]
SCORES = ["value_clarity", "novelty", "breadth_of_appeal", "problem_urgency", "specificity"]
SCHEMA = {"type": "OBJECT", "properties": {
    "category": {"type": "STRING", "enum": CATS},
    "audience": {"type": "ARRAY", "items": {"type": "STRING", "enum": AUD}},
    "market": {"type": "STRING", "enum": ["b2b", "b2c", "both"]},
    "platform": {"type": "ARRAY", "items": {"type": "STRING", "enum": PLAT}},
    "ai_native": {"type": "BOOLEAN"}, "open_source": {"type": "BOOLEAN"}, "agent": {"type": "BOOLEAN"}, "developer_tool": {"type": "BOOLEAN"},
    "pricing": {"type": "STRING", "enum": ["free", "freemium", "paid", "not_stated"]},
    "maturity": {"type": "STRING", "enum": ["new_product", "major_update", "feature_update", "relaunch"]},
    **{s: {"type": "INTEGER", "minimum": 1, "maximum": 5} for s in SCORES}},
    "required": ["category", "audience", "market", "platform", "ai_native", "open_source", "agent", "developer_tool", "pricing", "maturity"] + SCORES}
PROMPT = """Classify this product from its launch text only. Report what the text says; do not use outside knowledge of the
product or its reception. Scores are 1 (low) to 5 (high):
value_clarity = how clearly the text says what it does and for whom; novelty = how new the idea is versus common tools;
breadth_of_appeal = how many kinds of people could use it; problem_urgency = how painful the problem it solves is;
specificity = how concrete and specific the claims are.

Name: {name}
Tagline: {tagline}
Topics: {topics}
Number of makers: {n_makers}
Description: {description}"""
LEAK = re.compile(r"(\d[\d,.]*\s*(up)?votes?|\d[\d,.]*\s*comments?|#\s*\d|\brank(ed)?\s*#?\d|\d+(st|nd|rd|th)\s+product\s+of\s+the)", re.I)
LK = threading.Lock(); USE = {"in": 0, "out": 0, "leak_hits": 0, "prompts": 0}


def call(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 600, "responseMimeType": "application/json",
                                 "responseSchema": SCHEMA}}
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(refresh=i > 0),
                                                                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r)
            u = j.get("usageMetadata", {})
            with LK:
                USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
            return json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:  # noqa: BLE001
            time.sleep(3 * (i + 1)); err = str(e)[:200]
    raise RuntimeError(err)


def main(threads=8):
    I = pd.read_parquet(f"{WORK}/items.parquet")
    done = set()
    path = f"{OUT}/attrs_a.jsonl"
    if os.path.exists(path):
        done = {json.loads(l)["id"] for l in open(path)}
    todo = I[~I.id.astype(str).isin(done)]
    f = open(path, "a")

    def one(r):
        mk = len(json.loads(r.makers or "[]"))
        p = PROMPT.format(name=r.name, tagline=r.tagline, topics=", ".join(json.loads(r.topics or "[]")), n_makers=mk,
                          description=(r.description or "")[:1500])
        hit = len(LEAK.findall(p)); p = LEAK.sub("[n]", p)   # counted, then redacted before sending
        try:
            a = call(p)
        except Exception as e:  # noqa: BLE001
            return {"id": str(r.id), "error": str(e)[:200]}
        rec = {"id": str(r.id), "day": r.day, "attrs": a, "model": MODEL, "prompt_sha": hashlib.sha256(p.encode()).hexdigest()[:16],
               "leak_hits": hit, "at": pd.Timestamp.now(tz="UTC").isoformat()}
        with LK:
            USE["prompts"] += 1; USE["leak_hits"] += hit
            f.write(json.dumps(rec) + "\n"); f.flush()
        return rec
    with ThreadPoolExecutor(threads) as ex:
        errs = [x for x in ex.map(one, todo.itertuples()) if "error" in x]
    json.dump({**USE, "errors": len(errs), "todo": len(todo), "model": MODEL}, open(f"{OUT}/run_{int(time.time())}.json", "w"))
    print(json.dumps({**USE, "errors": len(errs), "todo": len(todo)}))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
