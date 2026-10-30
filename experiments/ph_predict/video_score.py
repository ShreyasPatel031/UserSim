"""Launch video, watched by Gemini: the actual video content (YouTube / Loom links from the Product Hunt API), scored
as launch inputs (vs_*) to test against real outcomes like every other page element.
Scores 1-10: hook (first 5 seconds), problem shown, product shown working, clarity, pacing, production quality,
voiceover / captions, length fit, call to action, wow; plus length in seconds, shows real UI (0/1), founder on camera (0/1).
usage: python video_score.py [limit] [threads] -> data/video_scores.jsonl ; python video_score.py features -> data/vs_features.json"""
import json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/video_scores.jsonl"
URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/"
       "gemini-2.5-flash:generateContent")
USE = {"in": 0, "out": 0}; LK = threading.Lock()
SCORES = ["hook", "problem_shown", "product_working", "clarity", "pacing", "production", "voice_or_captions", "length_fit", "call_to_action", "wow"]
PROMPT = """This is the launch video of "{name}" ({tagline}) on Product Hunt. Watch it as a Product Hunt visitor deciding whether
to try and upvote. Score 1-10: {scores}. Also give length_seconds, shows_real_ui (0/1), founder_on_camera (0/1), and one
sentence on what would most improve it.
Reply with JSON only: {{"scores": {{...}}, "length_seconds": n, "shows_real_ui": 0 or 1, "founder_on_camera": 0 or 1, "improve": "..."}}"""


def call(video, prompt):
    body = {"contents": [{"role": "user", "parts": [{"fileData": {"mimeType": "video/*", "fileUri": video}}, {"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 800, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    for a in range(4):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r); u = j.get("usageMetadata", {})
                with LK:
                    USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if e.code == 400:                     # private / removed / unsupported video: record and move on
                return json.dumps({"error": msg})
            if e.code == 401:
                llm.token(refresh=True)
            print("retry", a, e.code, msg, flush=True); time.sleep(5 * (a + 1))
        except Exception as e:  # noqa: BLE001
            print("retry", a, str(e)[:120], flush=True); time.sleep(5 * (a + 1))
    return ""


def youtube(u):
    m = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([\w-]{11})", u or "")
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def main(limit, threads):
    names = {}
    import glob
    for f in sorted(glob.glob(f"{D}/days/*.json")) + sorted(glob.glob(f"{D}/today/*.json")):
        for p in json.load(open(f)):
            names[str(p["id"])] = (p["name"], p.get("tagline") or "")
    vids = {}
    for l in open(f"{D}/page_media.jsonl"):
        r = json.loads(l)
        for m in r.get("media") or []:
            v = youtube(m.get("videoUrl"))
            if m.get("type") == "video" and v:
                vids[str(r["id"])] = v; break
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [x for x in vids if x not in done and x in names][:limit]
    print("videos", len(todo), "of", len(vids), "launches with a YouTube video", flush=True)
    lock = threading.Lock()

    def one(x):
        txt = call(vids[x], PROMPT.format(name=names[x][0], tagline=names[x][1], scores=", ".join(SCORES)))
        try:
            res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        except Exception:  # noqa: BLE001
            return
        with lock, open(OUT, "a") as f:
            f.write(json.dumps({"id": x, "video": vids[x], "result": res}) + "\n")
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    print("tokens", USE, "usd", round(USE["in"] / 1e6 * 0.30 + USE["out"] / 1e6 * 2.50, 4), flush=True)


def features():
    out = {}
    for l in open(OUT):
        r = json.loads(l); res = r["result"]
        if "error" in res:
            out[r["id"]] = {"vs_unwatchable": 1.0}; continue
        f = {f"vs_{k}": float(v) for k, v in (res.get("scores") or {}).items() if isinstance(v, (int, float))}
        for k in ("length_seconds", "shows_real_ui", "founder_on_camera"):
            if isinstance(res.get(k), (int, float)):
                f[f"vs_{k}"] = float(res[k])
        f["vs_unwatchable"] = 0.0
        out[r["id"]] = f
    json.dump(out, open(f"{D}/vs_features.json", "w"))
    print("video features for", len(out), "launches")


if __name__ == "__main__":
    if sys.argv[1:2] == ["features"]:
        features()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**9, int(sys.argv[2]) if len(sys.argv) > 2 else 8)
