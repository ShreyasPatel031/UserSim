"""The linked page itself (what OpenPipe's HN reward model read besides the title): fetch each story's URL once and
keep its <title>, meta description, first ~1,500 characters of visible text, word count, status and final host.
Direct from the VM (free); 32 threads; 10 s timeout; 600 KB cap per page. Pages are read today, not on the post
day: most articles do not change, but treat this block as approximate. -> <cache>/pages.jsonl

    python pages.py 2026-01-01 2026-09-30
"""
import html as _h
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

import store as S

OUT = os.path.join(S.LOCAL, "pages.jsonl")
lock = threading.Lock()
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def text_of(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", _h.unescape(re.sub(r"(?s)<[^>]+>", " ", html))).strip()


def one(job):
    pid, url = job
    rec = {"post_id": pid}
    try:
        r = requests.get(url, headers=UA, timeout=10, stream=True, allow_redirects=True)
        raw = r.raw.read(600_000, decode_content=True)
        enc = r.encoding or "utf-8"
        html = raw.decode(enc, errors="ignore")
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        d = re.search(r"""(?is)<meta[^>]+(?:name|property)=["'](?:og:)?description["'][^>]+content=["']([^"']*)""", html)
        body = text_of(html)
        rec.update(status=r.status_code, host=urlparse(r.url).netloc.lower(), ctype=r.headers.get("content-type", "")[:40],
                   page_title=_h.unescape(m.group(1).strip())[:300] if m else "", desc=_h.unescape(d.group(1))[:500] if d else "",
                   words=len(body.split()), text=body[:1500])
    except Exception as exc:  # noqa: BLE001
        rec.update(status=-1, error=type(exc).__name__)
    with lock, open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main(a, b):
    import top100 as H
    p = H.stories()
    p = p[(p.day >= a) & (p.day <= b) & p.url.fillna("").str.startswith("http")].sort_values("created_at_i", ascending=False)
    done = {json.loads(l)["post_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [(int(r.post_id), r.url) for r in p.itertuples() if r.post_id not in done]
    print(len(todo), "pages", flush=True)
    with ThreadPoolExecutor(32) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if i % 10000 == 0:
                print(i, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
