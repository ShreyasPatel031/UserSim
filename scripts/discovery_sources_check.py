"""Check discovery's data sources with real credentials, without the LLM.

For one product and its competitors, calls the same functions mvp/discovery.py uses and prints what each returns:
web search (Google via Apify, else DuckDuckGo), Product Hunt (post, topics, similar launches, commenters) and
G2 / Capterra reviewers (Apify). Prints counts and a few samples; never prints credentials.

    python scripts/discovery_sources_check.py --product Linear --competitors Jira Shortcut
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mvp import discovery as D  # noqa: E402


async def ph_check(names: list[str]) -> dict:
    if not D.ph_configured():
        return {"status": "skipped", "why": "PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set"}
    out: dict = {"posts": {}, "topics": [], "similar_launches": []}
    topics: list[str] = []
    for name in names:
        try:
            node = await D.ph_post_by_slug(D._slug(name))
        except Exception as exc:  # noqa: BLE001
            out["posts"][name] = {"error": repr(exc)[:300]}
            continue
        if not node:
            out["posts"][name] = {"found": False, "slug": D._slug(name)}
            continue
        post, users = D._ph_post(node), D._ph_users(node, name)
        topics += [t for t in post["topics"] if t not in topics]
        out["posts"][name] = {"found": True, "tagline": post["tagline"], "votes": post["votesCount"],
                              "topics": post["topics"], "commenters": len(users),
                              "with_headline": sum(1 for u in users if u["role"]), "sample": users[:2]}
    if not topics:
        try:
            found = await D.ph_topics("productivity")
            out["topics_search_sample"] = found
            topics = [t["slug"] for t in found[:1]]
        except Exception as exc:  # noqa: BLE001
            out["topics_search_error"] = repr(exc)[:300]
    for t in topics[:2]:
        try:
            rows = await D.ph_topic_posts(t)
            out["similar_launches"].append({"topic": t, "count": len(rows), "names": [r["name"] for r in rows[:10]]})
        except Exception as exc:  # noqa: BLE001
            out["similar_launches"].append({"topic": t, "error": repr(exc)[:300]})
    return out


async def reviews_check(names: list[str]) -> dict:
    if not D.apify_token():
        return {"status": "skipped", "why": "APIFY_TOKEN is not set"}

    async def one(name: str) -> tuple[str, dict]:
        try:
            got = await asyncio.to_thread(D.fetch_reviews, name)
        except Exception as exc:  # noqa: BLE001
            return name, {"error": repr(exc)[:300]}
        rows = [D._reviewer(r) for r in got.get("reviews") or []]
        by: dict[str, int] = {}
        for r in rows:
            by[r["source"]] = by.get(r["source"], 0) + 1
        return name, {"reviews": len(rows), "by_source": by, "with_role": sum(1 for r in rows if r["role"]),
                      "errors": got.get("errors"), "sample": rows[:2]}
    return dict(await asyncio.gather(*(one(n) for n in names)))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--competitors", nargs="*", default=[])
    a = ap.parse_args()
    names = [a.product, *a.competitors]
    search = {}
    for q in (f"{a.product} alternatives", f"{a.product} competitors"):
        try:
            rows = await D.web_search(q)
            search[q] = {"count": len(rows), "engines": sorted({r["engine"] for r in rows}), "urls": [r["url"] for r in rows[:6]]}
        except Exception as exc:  # noqa: BLE001
            search[q] = {"error": repr(exc)[:300]}
    ph, reviews = await asyncio.gather(ph_check(names), reviews_check(names))
    print(json.dumps({"credentials": {"apify": bool(D.apify_token()), "producthunt": D.ph_configured()},
                      "web_search": search, "producthunt": ph, "g2_capterra": reviews}, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
