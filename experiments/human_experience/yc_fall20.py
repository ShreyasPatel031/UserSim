"""Agent mode for NET-NEW products: the next 20 YC startups (Fall 2026 B2B, picked by hash), production path only.

  python yc_fall20.py plan                  # competitors (planner + model-named, review-site names) -> results/yc_fall20/plan.json
  python yc_fall20.py scrape-list           # every product name that needs a live scrape (startups + rivals)
  python yc_fall20.py run --cache DIR       # full agent mode on live scrapes in DIR (mvp.review_context cache format,
                                            # aio-<slug>.json): identity gate, competitors kept, likely users, use
                                            # cases, what users value / dislike, rating level; flags startups without
                                            # usable competitor data -> results/yc_fall20/report.json + REPORT.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from mvp import agent_mode as A  # noqa: E402
from mvp import review_context as RC  # noqa: E402

OUT = HERE / "results/yc_fall20"
BATCH = "https://yc-oss.github.io/api/batches/fall-2026.json"


def companies() -> list[dict]:
    with urllib.request.urlopen(BATCH, timeout=30) as r:
        d = json.load(r)
    b2b = [c for c in d if "B2B" in (c.get("industries") or []) and c.get("website")]
    b2b.sort(key=lambda c: hashlib.sha256(f"42|ycf26|{c['slug']}".encode()).hexdigest())
    return [{"name": c["name"], "website": c["website"], "one_liner": c.get("one_liner") or "",
             "subindustry": c.get("subindustry") or ""} for c in b2b[:20]]


async def plan() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cs = companies()
    rivals = await asyncio.gather(*(A.discover_rivals(c["website"], about=f"{c['name']}: {c['one_liner']}") for c in cs))
    for c, r in zip(cs, rivals):
        c["rivals"] = r
    (OUT / "plan.json").write_text(json.dumps(cs, indent=1))
    for c in cs:
        print(f"{c['name']:28s} {c['one_liner'][:50]:50s} -> {c['rivals']}")


async def run(cache: Path) -> None:
    cs = json.loads((OUT / "plan.json").read_text())
    RC._APIFY_CACHE = cache
    RC.apify_token = lambda: "from-cache"
    RC.prefetch = lambda names: None

    async def no_words(prompt):
        return {}
    report = []
    for c in cs:
        out = await A.predict_experience(product=c["name"], url=c["website"], persona={"role": "typical buyer"},
                                         competitors=c["rivals"], wait_s=0, llm=no_words)
        ev = out.get("evidence") or {}
        checks = ev.get("rivals_check") or out.get("rivals_check") or {}
        prof = out.get("product_profile") or {}
        used = ev.get("rivals_used") or []
        n_used = sum((prof.get("competitor_ratings") or {}).get(n, {}).get("reviews", 0) for n in used)
        row = {"name": c["name"], "website": c["website"], "one_liner": c["one_liner"], "status": out.get("status"),
               "rivals_named": c["rivals"],
               "rivals_with_reviews": [n for n in c["rivals"] if (RC.cached_live_reviews(n) or {}).get("reviews")],
               "rivals_kept": used, "rivals_rejected": {n: v for n, v in checks.items() if not v.get("ok")},
               "competitor_reviews_used": n_used, "own_reviews_check": ev.get("own_reviews_check") or out.get("own_reviews_check"),
               "own_reviews_used": ev.get("own_reviews", 0), "likely_users": prof.get("likely_users"),
               "use_cases": prof.get("use_cases"), "what_users_value": prof.get("what_users_value"),
               "what_frustrates_users": prof.get("what_frustrates_users"),
               "competitor_ratings": prof.get("competitor_ratings"),
               "overall_rating_level": ((out.get("ratings") or {}).get("overall_rating") or {}).get("estimate"),
               "usable": bool(used) and n_used >= 20}
        report.append(row)
        print(f"{c['name']:28s} kept {used} ({n_used} reviews) usable={row['usable']}", flush=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=1, default=str))
    ok = [r for r in report if r["usable"]]
    lines = [f"# Agent mode on 20 net-new YC Fall 2026 B2B startups\n",
             f"Usable competitor data (>= 1 checked direct/partial competitor, >= 20 of its reviews): **{len(ok)} of {len(report)}**.\n",
             "| Startup | Rivals named | with reviews | kept by the check | reviews used | top roles | top use case |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in report:
        roles = ", ".join(f"{k} {v:.0%}" for k, v in list(((r["likely_users"] or {}).get("role_families") or {}).items())[:2])
        lines.append(f"| {r['name']} | {len(r['rivals_named'])} | {len(r['rivals_with_reviews'])} | {', '.join(r['rivals_kept']) or '—'} | "
                     f"{r['competitor_reviews_used']} | {roles or '—'} | {(r['use_cases'] or ['—'])[0]} |")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "scrape-list", "run"])
    ap.add_argument("--cache", type=Path)
    a = ap.parse_args()
    if a.cmd == "plan":
        asyncio.run(plan())
    elif a.cmd == "scrape-list":
        cs = json.loads((OUT / "plan.json").read_text())
        print("\n".join(sorted({n for c in cs for n in [c["name"]] + c["rivals"]})))
    else:
        asyncio.run(run(a.cache))


if __name__ == "__main__":
    main()
