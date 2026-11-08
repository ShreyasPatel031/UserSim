#!/usr/bin/env python3
"""When PH_STOP_ON_FIRST_BLOCK=1, exit the batch on the first 403/challenge (no fresh-browser retry)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "STOP_ON_FIRST_BLOCK_PATCH" in src:
    print("stop_on_first_block already patched")
    sys.exit(0)

needle = """            if err[0] == "block":
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'):
                    S.put(event="stopped_on_block", handle=h, note="test2a: stop at first block; no fresh browser, no recycle, no port/IP change", **sess(R)); return 3
                if fresh_used: S.put(event="stopped_on_block", handle=h, note="second block after the one fresh browser"); return 3
                fresh_used = True; S.put(event="block_fresh_browser", handle=h, note="closing browser, waiting 300s, one fresh browser, retry same person")
                try: await cm.__aexit__(None, None, None)
                except Exception: pass
                cm = None; await asyncio.sleep(300); continue"""

repl = """            if err[0] == "block":
                # STOP_ON_FIRST_BLOCK_PATCH
                if os.environ.get("PH_STOP_ON_FIRST_BLOCK", "").strip() in ("1", "true", "yes"):
                    S.put(event="stopped_on_block", handle=h, note="PH_STOP_ON_FIRST_BLOCK: ding stop at first 403", **sess(R)); return 3
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'):
                    S.put(event="stopped_on_block", handle=h, note="test2a: stop at first block; no fresh browser, no recycle, no port/IP change", **sess(R)); return 3
                if fresh_used: S.put(event="stopped_on_block", handle=h, note="second block after the one fresh browser"); return 3
                fresh_used = True; S.put(event="block_fresh_browser", handle=h, note="closing browser, waiting 300s, one fresh browser, retry same person")
                try: await cm.__aexit__(None, None, None)
                except Exception: pass
                cm = None; await asyncio.sleep(300); continue"""

if needle not in src:
    print("block-handler pattern not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched stop_on_first_block")
