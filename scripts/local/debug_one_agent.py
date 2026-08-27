"""Run one MVP browser agent and report trace + bbox screenshot coverage."""

import asyncio
import sys

from mvp.browser_agent import run_browser_agent


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://useagency.dev/"
    run = await run_browser_agent(
        study_id="debug",
        agent_id="one",
        url=url,
        task_prompt=(
            "Read the Blog and Use cases pages to judge whether this team has real "
            "engineering depth. Report what you found."
        ),
        persona={"id": "p1", "name": "Technical founder", "bio": "Bay Area, evaluates vendors fast."},
        segment="Startup founder, technical, 20-45",
        max_steps=6,
    )
    trace = run["trace"]
    shots = [s for s in trace if s.get("screenshot_url")]
    print()
    print("steps       :", len(trace))
    print("screenshots :", len(shots))
    print("visited     :", run["visited_urls"])
    print("session     :", run["browserbase_session_url"])
    print("run_dir     :", run["run_dir"])


asyncio.run(main())
