"""Smoke test: browser-use Agent driven by Gemini 2.5 Flash on Vertex AI.

Uses this repo's existing GCP auth (src/auth.py, src/config.py) instead of a
raw Gemini API key. Default task is browser-use's own quickstart example
("Find the number of stars of the browser-use repo"), which opens GitHub.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL

from browser_use import Agent
from browser_use.llm.google import ChatGoogle

DEFAULT_TASK = "Find the number of stars of the browser-use repo"


async def main(task: str = DEFAULT_TASK) -> None:
    llm = ChatGoogle(
        model=MODEL,
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
    )
    agent = Agent(task=task, llm=llm)
    history = await agent.run()
    print("\n=== DONE ===")
    print("final result:", history.final_result())
    print("is_successful:", history.is_successful())
    print("steps taken:", history.number_of_steps())


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    asyncio.run(main(task))
