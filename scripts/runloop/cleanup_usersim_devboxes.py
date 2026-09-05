"""Shut down temporary Runloop Devboxes created by UserSim."""

from __future__ import annotations

import asyncio
import argparse
import getpass

from runloop_api_client import AsyncRunloopSDK


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("devbox_ids", nargs="*")
    args = parser.parse_args()
    sdk = AsyncRunloopSDK(bearer_token=getpass.getpass("Runloop API key: "))
    boxes = await sdk.devbox.list()
    usersim = []
    for box in boxes:
        info = await box.get_info()
        if info.name.startswith("usersim-"):
            usersim.append((box, info))
            print(f"found={box.id} name={info.name} status={info.status}")
    if not args.devbox_ids:
        print(f"temporary_usersim_devboxes={len(usersim)} (read-only listing)")
        return
    wanted = set(args.devbox_ids)
    targets = [(box, info) for box, info in usersim if box.id in wanted]
    missing = wanted - {box.id for box, _ in targets}
    if missing:
        raise SystemExit(f"Requested IDs not found among usersim Devboxes: {sorted(missing)}")
    for box, info in targets:
        await box.shutdown()
        print(f"shutdown={box.id} name={info.name}")


if __name__ == "__main__":
    asyncio.run(main())
