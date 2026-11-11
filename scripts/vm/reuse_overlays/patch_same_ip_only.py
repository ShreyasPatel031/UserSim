#!/usr/bin/env python3
"""When PH_BLOCK_NEW_PORT=0, mid-pull blocks use same-port backoff (no prescreen rotate)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
if not p.exists():
    print("ph_batch.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "SAME_IP_ONLY_PATCH" in src:
    print("same_ip_only already patched")
    sys.exit(0)

needle = """                # Close browser, claim a new sticky port (same VM), short backoff, reopen warm.
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0\""""
repl = """                # SAME_IP_ONLY_PATCH
                if os.environ.get("PH_BLOCK_NEW_PORT", "1").strip() not in ("1", "true", "yes"):
                    try:
                        await cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                    cm = None
                    wait_s = float(os.environ.get("PH_BLOCK_SAME_PORT_SLEEP_SEC", "20") or 20)
                    S.put(event="block_same_ip_backoff", handle=h, note=f"PH_BLOCK_NEW_PORT=0; sleep {wait_s}s same port", sess_blocks=sess_blocks, **sess(R))
                    await asyncio.sleep(wait_s)
                    continue
                # Close browser, claim a new sticky port (same VM), short backoff, reopen warm.
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0\""""
if needle not in src:
    print("soft block rotate anchor not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched same_ip_only")
