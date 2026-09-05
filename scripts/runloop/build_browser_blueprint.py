"""Build the reusable Chromium + Playwright Runloop Blueprint."""

from __future__ import annotations

import asyncio
import getpass

from runloop_api_client import AsyncRunloopSDK


NAME = "usersim-browser-v2"


async def main() -> None:
    sdk = AsyncRunloopSDK(bearer_token=getpass.getpass("Runloop API key: "))
    blueprint = await sdk.blueprint.create(
        name=NAME,
        launch_parameters={
            "launch_commands": [
                "python3 -m venv $HOME/.usersim-browser",
                "$HOME/.usersim-browser/bin/pip -q install playwright",
                "$HOME/.usersim-browser/bin/playwright install --with-deps chromium",
            ]
        },
    )
    print(f"blueprint_id={blueprint.id} name={NAME}")
    while True:
        info = await blueprint.get_info()
        print(f"status={info.status}", flush=True)
        if info.status == "build_complete":
            return
        if info.status == "build_failed":
            logs = await blueprint.logs()
            for row in logs.logs[-30:]:
                print(f"{row.level}: {row.message}")
            raise SystemExit(2)
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
