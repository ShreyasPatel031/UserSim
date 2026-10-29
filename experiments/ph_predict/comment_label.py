"""Label every real Product Hunt comment (warehouse `comments`, makers' own comments excluded) with Gemini Flash-Lite:
kind (question, bug, pricing, comparison, privacy, confusion, praise, other) and products named in it. The ground truth
for checking predicted comment mix, questions and competitors (page_score.py).
usage: python comment_label.py [limit] [threads] -> data/comment_labels.jsonl"""
import json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import llm
from pipeline import warehouse as W

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/comment_labels.jsonl"
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/"
       "gemini-2.5-flash-lite:generateContent")
USE = {"in": 0, "out": 0}; LK = threading.Lock()
KINDS = ["question", "bug", "pricing", "comparison", "privacy", "confusion", "praise", "other"]
PROMPT = """Comments on the Product Hunt launch of "{name}" ({tagline}). For each comment give:
kind = the ONE main kind: question (asks something), bug (something broken), pricing (price, plans, free tier),
comparison (compares to another product), privacy (privacy, security, data), confusion (unclear what it does or how),
praise (congratulations, support, compliments), other;
named = other products or companies it names (not "{name}").
Comments:
{items}
Reply with JSON only: {{"<n>": {{"kind": "...", "named": [...]}}, ...}}"""


def call(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 4000, "responseMimeType": "application/json"}}
    for a in range(5):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r); u = j.get("usageMetadata", {})
                with LK:
                    USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            print("retry", a, str(e)[:100], flush=True); time.sleep(5 * (a + 1))
    return ""


def one(batch, name, tagline, lock):
    txt = call(PROMPT.format(name=name, tagline=tagline, items="\n".join(f"[{i}] {t[:400]}" for i, (_, t) in enumerate(batch))))
    try:
        res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception:  # noqa: BLE001
        return
    with lock, open(OUT, "a") as f:
        for i, (key, _) in enumerate(batch):
            v = res.get(str(i)) or {}
            if v.get("kind") in KINDS:
                f.write(json.dumps({"key": key, "kind": v["kind"], "named": v.get("named") or []}) + "\n")


def main(limit, threads):
    con = W.connect(do_sync=False)
    C = con.execute("""SELECT c.launch_id, c.person, c.date, c.text, l.name, l.tagline FROM comments c JOIN launches l ON l.id = c.launch_id
                       WHERE c.text IS NOT NULL AND length(c.text) > 0""").df()
    C["key"] = C.launch_id + "|" + C.person + "|" + C.text.str[:40]
    done = {json.loads(l)["key"] for l in open(OUT)} if os.path.exists(OUT) else set()
    C = C[~C.key.isin(done)].drop_duplicates("key").head(limit)
    jobs = []
    for (lid, name, tagline), g in C.groupby(["launch_id", "name", "tagline"]):
        items = list(zip(g.key, g.text))
        jobs += [(items[k:k + 25], name, tagline) for k in range(0, len(items), 25)]
    print("comments", len(C), "calls", len(jobs), flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(lambda j: one(*j, lock), jobs))
    print("tokens", USE, "usd", round(USE["in"] / 1e6 * 0.10 + USE["out"] / 1e6 * 0.40, 4), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**9, int(sys.argv[2]) if len(sys.argv) > 2 else 16)
