"""Gemini's read of each launch (listing + homepage), as features. Vertex AI, gemini-2.5-flash-lite, JSON output.

The model sees only what a visitor would see before voting: name, tagline, description, topics and the homepage
text with Product Hunt badges removed. Never votes, ranks or comments. Appends to cache/llm.jsonl; ids already
there are skipped.

    GOOGLE_APPLICATION_CREDENTIALS=... python experiments/ph_longitudinal/llm_scores.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

OUT = F.CACHE / "llm.jsonl"
MODEL = "gemini-2.5-flash-lite"
URL = ("https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/"
       f"publishers/google/models/{MODEL}:generateContent")
KEYS = ["novelty", "broad_appeal", "clarity", "polish", "demo_wow", "dev_audience", "maker_credibility",
        "brand_known", "p_top5"]
PROMPT = """You are a seasoned Product Hunt voter. Judge this product launch from what a visitor sees.

Name: {name}
Tagline: {tagline}
Topics: {topics}
Description: {description}
Homepage ({url}):
{site}

Return JSON with integer scores:
- novelty (1-10): how new/different vs existing tools
- broad_appeal (1-10): share of Product Hunt's audience (makers, developers, designers, founders) who would want it
- clarity (1-10): how quickly you understand what it does
- polish (1-10): how finished and credible the product and site look
- demo_wow (1-10): how impressive a quick demo would be
- dev_audience (1-10): how developer/technical the audience is
- maker_credibility (1-10): signs of an established team or company (customers, funding, known brand)
- brand_known (0 or 1): you recognise the company or product from before
- p_top5 (0-100): chance it finishes in the top 5 products of its launch day
"""
_tok = {"v": "", "t": 0.0}
_lock = threading.Lock()


def token() -> str:
    with _lock:
        if time.time() - _tok["t"] > 1800:
            _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            _tok["t"] = time.time()
        return _tok["v"]


def score(row: dict, site: dict) -> dict | None:
    text = F.PH_LEAK.sub(" ", site.get("text") or "")[:4000] or "(could not load)"
    prompt = PROMPT.format(name=row["name"], tagline=row["tagline"], topics=", ".join(row["topics"]),
                           description=row["description"][:1500], url=site.get("loaded_url") or "", site=text)
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 300}}
    for attempt in range(4):
        try:
            r = requests.post(URL, json=body, timeout=60, headers={"Authorization": f"Bearer {token()}"})
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            got = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            got = got[0] if isinstance(got, list) else got
            return {"id": row["id"], **{k: got.get(k) for k in KEYS}, "had_site": int(bool(site.get("text")))}
        except Exception:
            time.sleep(2 ** attempt)
    return None


def main(require_site: bool = True) -> None:
    df = F.load_posts()
    done = {json.loads(l)["id"] for l in OUT.read_text().splitlines()} if OUT.exists() else set()
    web = {p.stem: json.loads(p.read_text()) for p in (F.CACHE / "web").glob("*.json")}
    todo = [r for r in df.to_dict("records") if r["id"] not in done and (r["id"] in web or not require_site)]
    print(f"{len(todo)} launches to score", flush=True)
    lock = threading.Lock()
    n = [0]

    def one(r):
        got = score(r, web.get(r["id"], {}))
        if got:
            with lock:
                with OUT.open("a") as f:
                    f.write(json.dumps(got) + "\n")
                n[0] += 1
                if n[0] % 200 == 0:
                    print(n[0], flush=True)

    with ThreadPoolExecutor(24) as ex:
        list(ex.map(one, todo))
    print("done", n[0], flush=True)


if __name__ == "__main__":
    main(require_site="--no-site" not in sys.argv)
