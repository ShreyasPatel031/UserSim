"""Concrete, checkable facts about each launch page (not taste judgments), extracted by Gemini Flash-Lite from the name,
tagline, description, topics, media types and the maker's first comment. Every fact becomes a model input (pf_*) and
is tested against real outcomes like the rest (ctrl.py, matched pairs). Gemini's head-to-head taste judgments did no
better than a coin flip (pairjudge.py), so here it only reads facts off the page.
usage: python page_facts.py [limit] [threads] -> data/page_facts.jsonl ; python page_facts.py features -> data/pf_features.json"""
import json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import llm
from page_score import first_comments, launches

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/page_facts.jsonl"
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/"
       "gemini-2.5-flash-lite:generateContent")
USE = {"in": 0, "out": 0}; LK = threading.Lock()
BOOL = ["open_source", "free_plan", "free_trial", "paid_only", "launch_discount", "number_in_tagline", "ai_in_tagline",
        "problem_stated", "who_its_for_stated", "how_it_works_steps", "social_proof", "founder_story", "asks_for_feedback",
        "asks_for_upvotes", "emoji_in_first_comment", "mentions_competitor", "claims_speed", "claims_privacy", "integrations_listed",
        "relaunch_or_new_version", "waitlist_or_beta", "no_signup_needed", "mobile_app", "browser_extension", "mac_app",
        "developer_tool", "api_or_sdk", "agent", "consumer_product", "b2b_product", "hardware", "games_or_fun"]
CAT = {"tagline_style": ["benefit", "feature", "category", "clever", "question", "other"],
       "audience": ["developers", "designers", "marketers", "founders", "sales", "consumers", "students", "creators", "teams", "other"],
       "price_point": ["free", "under_10", "10_to_50", "over_50", "not_stated"]}
PROMPT = """Read this Product Hunt launch page and report facts only (not opinions).
Name: {name}
Tagline: {tagline}
Topics: {topics}
Media: {media}
Description: {description}
Maker's first comment: {first}

Give true/false for each: {bools}.
Pick one for each: {cats}.
Also: tagline_words (count), first_comment_words (count, 0 if none), features_listed (count).
Reply with JSON only: {{"bool": {{...}}, "cat": {{...}}, "tagline_words": n, "first_comment_words": n, "features_listed": n}}"""


def call(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 1200, "responseMimeType": "application/json"}}
    for a in range(4):
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


def main(limit, threads):
    rows = launches()
    teams = {p["slug"]: {m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")} for p in rows.values()}
    first = first_comments(teams)
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [x for x in rows if x not in done][:limit]
    print("launches", len(todo), flush=True)
    lock = threading.Lock()

    def one(x):
        p = rows[x]; media = p.get("media") or []
        txt = call(PROMPT.format(name=p["name"], tagline=p.get("tagline") or "", topics=", ".join(e["node"]["name"] for e in p["topics"]["edges"]),
                                 media=f"{len(media)} items ({sum(m.get('type') == 'video' for m in media)} video)",
                                 description=(p.get("description") or "")[:1200], first=(first.get(p["slug"]) or "none")[:1500],
                                 bools=", ".join(BOOL), cats="; ".join(f"{k}: {'/'.join(v)}" for k, v in CAT.items())))
        try:
            res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        except Exception:  # noqa: BLE001
            return
        with lock, open(OUT, "a") as f:
            f.write(json.dumps({"id": x, "result": res}) + "\n")
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    print("tokens", USE, "usd", round(USE["in"] / 1e6 * 0.10 + USE["out"] / 1e6 * 0.40, 4), flush=True)


def features():
    out = {}
    for l in open(OUT):
        r = json.loads(l); res = r["result"]; f = {}
        for k in BOOL:
            v = (res.get("bool") or {}).get(k)
            f[f"pf_{k}"] = 1.0 if v is True else 0.0 if v is False else None
        for k, opts in CAT.items():
            v = (res.get("cat") or {}).get(k)
            for o in opts:
                f[f"pf_{k}_{o}"] = 1.0 if v == o else 0.0
        for k in ("tagline_words", "first_comment_words", "features_listed"):
            f[f"pf_{k}"] = float(res[k]) if isinstance(res.get(k), (int, float)) else None
        out[r["id"]] = f
    json.dump(out, open(f"{D}/pf_features.json", "w"))
    print("page facts for", len(out), "launches")


if __name__ == "__main__":
    if sys.argv[1:2] == ["features"]:
        features()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**9, int(sys.argv[2]) if len(sys.argv) > 2 else 32)
