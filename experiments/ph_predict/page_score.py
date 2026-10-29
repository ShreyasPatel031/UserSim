"""Score every element of a Product Hunt launch page with Gemini (images + text in one call), as model inputs (ps_*),
plus predictions to check against the real comments: comment mix, likely questions, competitors named, audience.
Elements: name, tagline, description, topics/category, logo, gallery images, video (thumbnail + link), maker's first
comment, website text, product links. Everything is launch-time content (the first comment is posted at launch).
usage: python page_score.py [limit] [threads] -> data/page_scores.jsonl ; python page_score.py features -> data/ps_features.json"""
import base64, glob, gzip, html, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import llm   # token(), PRICE-free Gemini endpoint and usage counter live there

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/page_scores.jsonl"
MODEL = os.environ.get("PS_MODEL", "gemini-2.5-flash")
URL = f"https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{MODEL}:generateContent"
USD = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}[MODEL]
USE = {"in": 0, "out": 0}; LK = threading.Lock()
ELEMENTS = ["name", "tagline", "description", "category_fit", "logo", "gallery", "video", "first_comment", "website", "links"]
OVERALL = ["clarity", "novelty", "usefulness", "audience_breadth", "credibility", "visual_polish", "problem_urgency", "wow"]
KINDS = ["question", "bug", "pricing", "comparison", "privacy", "confusion", "praise", "other"]

PROMPT = """You are judging a Product Hunt launch page exactly as visitors see it on launch day. Images attached in order:
{imgs}

Name: {name}
Tagline: {tagline}
Description: {description}
Topics: {topics}
Video: {video}
Product links: {links}
Maker's first comment (posted at launch): {first}
Website text (excerpt): {web}

Score each element 1-10 for how well it makes a Product Hunt visitor want to try and upvote (0 if the element is missing):
{elements}
Score the product overall 1-10 on: {overall}.
Estimate top5_chance: 0-100, the chance it finishes in the day's top 5 on Product Hunt.
Predict the comments it will get: comment_mix = share of comments (summing to 1) of each kind: {kinds};
questions = the 3 questions visitors are most likely to ask; competitors = up to 5 products visitors will compare it to;
audience = who will care most, in under 12 words.
Reply with JSON only: {{"elements": {{...}}, "overall": {{...}}, "top5_chance": n, "comment_mix": {{...}}, "questions": [...], "competitors": [...], "audience": "..."}}"""


def text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def launches():
    rows = {}
    for f in sorted(glob.glob(f"{D}/days/*.json")) + sorted(glob.glob(f"{D}/today/*.json")):
        for p in json.load(open(f)):
            rows[str(p["id"])] = dict(p, day=os.path.basename(f)[:10])
    return rows


def first_comments(teams):
    """slug -> earliest comment by the team (the maker's launch comment), from the saved comment pages."""
    out = {}
    for fn in glob.glob(f"{D}/comments/page*.jsonl.gz"):
        for l in gzip.open(fn, "rt"):
            try:
                post = (json.loads(json.loads(l).get("html") or "{}").get("data") or {}).get("post") or {}
            except ValueError:
                continue
            slug, team = post.get("slug"), teams.get(post.get("slug"), set())
            for e in ((post.get("threads") or {}).get("edges") or []):
                n = e["node"]; u = (n.get("user") or {}).get("username")
                if u in team and (slug not in out or n["createdAt"] < out[slug][0]):
                    out[slug] = (n["createdAt"], text(n.get("body") or n.get("bodyHtml")))
    return {k: v[1] for k, v in out.items()}


def image(url):
    u = re.sub(r"\?.*$", "", url) + "?w=512&h=512&fit=max&fm=jpg&q=70"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "usersim-research"}), timeout=30) as r:
            return base64.b64encode(r.read()).decode()
    except Exception:  # noqa: BLE001
        return None


def call(parts):
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 1500, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for a in range(5):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.load(r); u = j.get("usageMetadata", {})
                with LK:
                    USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            print("retry", a, str(e)[:120], flush=True); time.sleep(5 * (a + 1))
    return ""


def one(x, p, media, first, web, lock):
    m = media.get(x, {})
    imgs, labels = [], []
    if (m.get("thumbnail") or {}).get("url"):
        imgs.append(image(m["thumbnail"]["url"])); labels.append("logo")
    for k, it in enumerate([i for i in m.get("media") or [] if i.get("url")][:5]):
        imgs.append(image(it["url"])); labels.append("video thumbnail" if it["type"] == "video" else f"gallery image {k + 1}")
    keep = [(b, l) for b, l in zip(imgs, labels) if b]
    vids = [i.get("videoUrl") for i in m.get("media") or [] if i.get("type") == "video"]
    prompt = PROMPT.format(imgs="; ".join(f"{i + 1}. {l}" for i, (_, l) in enumerate(keep)) or "none",
                           name=p["name"], tagline=p.get("tagline") or "", description=(p.get("description") or "")[:1200],
                           topics=", ".join(e["node"]["name"] for e in p["topics"]["edges"]),
                           video=f"yes ({len(vids)})" if vids else "none",
                           links=", ".join(sorted({l["type"] for l in m.get("productLinks") or []})) or "none",
                           first=(first.get(p["slug"]) or "none")[:1500], web=(web.get(x) or "none")[:800],
                           elements=", ".join(ELEMENTS), overall=", ".join(OVERALL), kinds=", ".join(KINDS))
    parts = [{"inlineData": {"mimeType": "image/jpeg", "data": b}} for b, _ in keep] + [{"text": prompt}]
    txt = call(parts)
    try:
        res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception:  # noqa: BLE001
        return
    rec = {"id": x, "day": p["day"], "n_images": len(keep), "has_first_comment": p["slug"] in first, "result": res}
    with lock, open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def features():
    """page_scores.jsonl -> ps_* inputs for the launch model (every element kept)."""
    out = {}
    for l in open(OUT):
        r = json.loads(l); res = r["result"]; f = {"ps_n_images": r["n_images"], "ps_has_first_comment": int(r["has_first_comment"])}
        for grp, keys in (("elements", ELEMENTS), ("overall", OVERALL)):
            for k in keys:
                v = (res.get(grp) or {}).get(k)
                f[f"ps_{k}"] = float(v) if isinstance(v, (int, float)) else None
        f["ps_top5_chance"] = float(res.get("top5_chance")) if isinstance(res.get("top5_chance"), (int, float)) else None
        for k in KINDS:
            v = (res.get("comment_mix") or {}).get(k)
            f[f"ps_mix_{k}"] = float(v) if isinstance(v, (int, float)) else None
        out[r["id"]] = f
    json.dump(out, open(f"{D}/ps_features.json", "w"))
    print("features for", len(out), "launches")


def main(limit, threads):
    rows = launches()
    media = {str(json.loads(l)["id"]): json.loads(l) for l in open(f"{D}/page_media.jsonl")}
    teams = {p["slug"]: {m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")} for p in rows.values()}
    first = first_comments(teams)
    web = {}
    if os.path.exists(f"{D}/sites.jsonl"):
        for l in open(f"{D}/sites.jsonl"):
            r = json.loads(l)
            if r.get("html"):
                web[str(r["id"])] = text(r["html"])[:2000]
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = sorted([x for x in rows if x not in done and x in media], key=lambda x: rows[x]["day"], reverse=True)[:limit]
    print("launches", len(todo), "with first comment", sum(rows[x]["slug"] in first for x in todo), flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(lambda x: one(x, rows[x], media, first, web, lock), todo))
    print("tokens", USE, "usd", round(USE["in"] / 1e6 * USD[0] + USE["out"] / 1e6 * USD[1], 4), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["features"]:
        features()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**9, int(sys.argv[2]) if len(sys.argv) > 2 else 16)
