"""Check discovery's data sources with real credentials, without the LLM.

Runs the agent's own user-collection step (mvp/discovery.py DiscoveryAgent.users_for) for a product and its
competitors: Google searches (site:g2.com / site:capterra.com / site:producthunt.com), then the exact
review page found on each site, scraped by URL. Prints every trace step and the counts; never
prints credentials.

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


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--competitors", nargs="*", default=[])
    a = ap.parse_args()
    run = D.new_run("https://example.invalid")
    agent = D.DiscoveryAgent(run, llm=lambda _m: None)
    users = await agent.users_for([a.product, *a.competitors])
    for st in run.steps:
        print(f"[{st.kind:11}] {st.status:7} {st.title}\n              {st.summary}")
    per: dict[str, dict[str, int]] = {}
    for u in users:
        row = per.setdefault(u["product"], {})
        row[u["source"]] = row.get(u["source"], 0) + 1
        if u.get("role"):
            row["with_job_title"] = row.get("with_job_title", 0) + 1
    print(json.dumps({"credentials": {"apify": bool(D.apify_token()), "producthunt": D.ph_configured()},
                      "users_per_product": per, "total_users": len(users),
                      "samples": [u for u in users if u.get("role")][:3] + [u for u in users if u["source"] == "producthunt"][:2]},
                     indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
