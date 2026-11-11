#!/usr/bin/env python3
"""Soft 403 recovery: rotate sticky port + reopen browser; circuit-break after N blocks.

Does not stop the world on the first challenge. Still writes full out/<h>.json on success.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "SOFT_BLOCK_ROTATE_PATCH" in src:
    print("soft_block_rotate already patched")
    sys.exit(0)

needle = """            if err[0] == "block":
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'):
                    S.put(event="stopped_on_block", handle=h, note="test2a: stop at first block; no fresh browser, no recycle, no port/IP change", **sess(R)); return 3
                if fresh_used: S.put(event="stopped_on_block", handle=h, note="second block after the one fresh browser"); return 3
                fresh_used = True; S.put(event="block_fresh_browser", handle=h, note="closing browser, waiting 300s, one fresh browser, retry same person")
                try: await cm.__aexit__(None, None, None)
                except Exception: pass
                cm = None; await asyncio.sleep(300); continue"""

# Prefer patched stop-on-first form if that overlay already ran.
needle2 = """            if err[0] == "block":
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

repl = '''            if err[0] == "block":
                # SOFT_BLOCK_ROTATE_PATCH
                if os.environ.get("PH_STOP_ON_FIRST_BLOCK", "").strip() in ("1", "true", "yes"):
                    S.put(event="stopped_on_block", handle=h, note="PH_STOP_ON_FIRST_BLOCK: ding stop at first 403", **sess(R)); return 3
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'):
                    S.put(event="stopped_on_block", handle=h, note="test2a: stop at first block; no fresh browser, no recycle, no port/IP change", **sess(R)); return 3
                sess_blocks = int(getattr(lr, "_sess_blocks", 0)) + 1
                lr._sess_blocks = sess_blocks
                circuit = int(float(os.environ.get("PH_BLOCK_CIRCUIT", "5") or 5))
                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} blocks >= PH_BLOCK_CIRCUIT={circuit}", **sess(R)); return 3
                # Close browser, claim a new sticky port (same VM), short backoff, reopen warm.
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0"
                    os.environ["PH_PORTSCREEN_MAX_TRY"] = os.environ.get("PH_PORTSCREEN_MAX_TRY_ON_BLOCK", "8")
                    import portscreen as _ps
                    home = int(os.environ.get("PROXY_PORT") or 0)
                    if home:
                        _ps.FAILED.add(home)
                        try:
                            _ps._release(home, VM)
                        except Exception:
                            pass
                    newp = _ps.prescreen(VM, lambda **kw: S.put(**kw))
                    if newp:
                        S.put(event="block_port_rotate", handle=h, from_port=home, to_port=newp, sess_blocks=sess_blocks)
                    else:
                        S.put(event="block_port_rotate_failed", handle=h, from_port=home, sess_blocks=sess_blocks)
                except Exception as _e:
                    S.put(event="block_port_rotate_error", handle=h, err=str(_e)[:200], sess_blocks=sess_blocks)
                wait_s = float(os.environ.get("PH_BLOCK_ROTATE_SLEEP_SEC", "45") or 45)
                S.put(event="block_soft_retry", handle=h, note=f"soft rotate; sleep {wait_s}s; retry same person", sess_blocks=sess_blocks, **sess(R))
                await asyncio.sleep(wait_s)
                continue'''

if needle2 in src:
    src = src.replace(needle2, repl, 1)
elif needle in src:
    src = src.replace(needle, repl, 1)
else:
    print("block-handler pattern not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src)
print("patched soft_block_rotate")
