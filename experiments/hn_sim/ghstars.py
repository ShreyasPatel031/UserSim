"""Live GitHub star velocity for HN-relevant repos, recorded hourly (runs on hn-sim-1; github.com is blocked from the
dev container). Repos: github.com links in HN stories of the last 48 h (Algolia) and on github.com/trending (daily).
For each, the star count from the repo page (no API token needed), so star velocity before / after an HN post can be
learned once enough days are recorded. -> <cache>/ghstars/<day>.jsonl {read_at, repo, stars, from_hn, from_trending},
pushed to the bucket.

    python ghstars.py [once]
"""
import json
import os
import re
import sys
import time

import requests

import store as S

UA = {"User-Agent": "atelier-research (GitHub star counts for HN repos, hourly)"}
OUT = os.path.join(S.LOCAL, "ghstars")
REPO = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
SKIP = {"orgs", "sponsors", "features", "topics", "collections", "marketplace", "settings", "about", "login"}


def hn_repos() -> set:
    since = int(time.time()) - 48 * 3600
    r = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30,
                     params={"tags": "story", "hitsPerPage": 1000, "query": "github.com",
                             "restrictSearchableAttributes": "url", "numericFilters": f"created_at_i>{since}"}).json()
    out = set()
    for h in r.get("hits", []):
        m = REPO.search(h.get("url") or "")
        if m and m.group(1).lower() not in SKIP:
            out.add(f"{m.group(1)}/{m.group(2).removesuffix('.git')}")
    return out


def trending() -> set:
    h = requests.get("https://github.com/trending", headers=UA, timeout=30).text
    return {f"{a}/{b}" for a, b in re.findall(r'<h2 class="h3 lh-condensed"[^>]*>\s*<a[^>]*href="/([^/"]+)/([^/"]+)"', h)}


def stars(repo: str):
    r = requests.get(f"https://github.com/{repo}", headers=UA, timeout=30)
    if r.status_code != 200:
        return None, r.status_code
    m = re.search(r'"stargazerCount":(\d+)', r.text)
    return (int(m.group(1)) if m else None), 200


def once():
    a, b = hn_repos(), trending()
    at, rows = int(time.time()), []
    for repo in sorted(a | b):
        n, status = stars(repo)
        rows.append({"read_at": at, "repo": repo, "stars": n, "status": status, "from_hn": repo in a, "from_trending": repo in b})
        time.sleep(1.5)
    day = time.strftime("%Y-%m-%d", time.gmtime(at))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{day}.jsonl")
    with open(path, "a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    S._bucket().blob(f"usersim_sim/hn_jobs/cache/ghstars/{day}.jsonl").upload_from_filename(path)
    print(time.strftime("%H:%M", time.gmtime()), len(rows), "repos;", sum(r["stars"] is not None for r in rows), "with stars;",
          len(a), "from HN,", len(b), "trending", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["once"]:
        once()
    else:
        while True:
            try:
                once()
            except Exception as exc:  # noqa: BLE001
                print("ghstars error:", exc, flush=True)
            time.sleep(3600 - time.time() % 3600 + 900)       # a quarter past each hour
