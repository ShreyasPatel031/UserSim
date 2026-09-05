"""Create a reusable Runloop disk snapshot with Chromium preinstalled."""

from __future__ import annotations

import asyncio
import getpass

from runloop_api_client import AsyncRunloopSDK


async def main() -> None:
    sdk = AsyncRunloopSDK(bearer_token=getpass.getpass("Runloop API key: "))
    devbox = await sdk.devbox.create(
        name="usersim-browser-snapshot-builder",
        blueprint_name="runloop/universal-ubuntu-24.04-x86_64",
    )
    try:
        setup = await devbox.cmd.exec(
            command=(
                "python3 -m venv $HOME/.usersim-browser && "
                "$HOME/.usersim-browser/bin/pip -q install playwright && "
                "$HOME/.usersim-browser/bin/playwright install --with-deps chromium"
            )
        )
        if setup.exit_code != 0:
            print(await setup.stderr())
            raise SystemExit(2)
        snapshot = await devbox.snapshot_disk(
            name="usersim-browser-snapshot-v1",
            commit_message="Playwright and Chromium runtime for UserSim public-site studies",
            metadata={"purpose": "usersim-browser", "version": "1"},
        )
        print(f"snapshot_id={snapshot.id}")
    finally:
        await devbox.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
