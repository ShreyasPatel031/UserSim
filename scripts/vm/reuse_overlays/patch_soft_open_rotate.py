#!/usr/bin/env python3
"""Soft-rotate sticky port on browser_open_failed (CF clear 403) — not only mid-pull blocks.

Most fleet 403s hit open_browser/goto before pull(); the mid-pull soft patch never ran.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "SOFT_OPEN_ROTATE_PATCH" in src:
    print("soft_open_rotate already patched")
    sys.exit(0)

needle = """            try: cm, pages, cap = await open_browser(lr, a.tabs, h)
            except Exception as e:
                S.put(event="browser_open_failed", err=str(e)[:300], bytes=nic() - b0)
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'): S.put(event="stopped_on_block", handle=h, note="test2a: browser open/Cloudflare clear failed; no retry", **sess(None)); return 3
                if fresh_used: S.put(event="stopped_on_block", handle=h); return 3
                fresh_used = True; cm = None; await asyncio.sleep(120); continue"""

repl = """            try: cm, pages, cap = await open_browser(lr, a.tabs, h)
            except Exception as e:
                # SOFT_OPEN_ROTATE_PATCH
                S.put(event="browser_open_failed", err=str(e)[:300], bytes=nic() - b0)
                if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'): S.put(event="stopped_on_block", handle=h, note="test2a: browser open/Cloudflare clear failed; no retry", **sess(None)); return 3
                if os.environ.get("PH_STOP_ON_FIRST_BLOCK", "").strip() in ("1", "true", "yes"):
                    S.put(event="stopped_on_block", handle=h, note="PH_STOP_ON_FIRST_BLOCK on browser_open_failed", **sess(None)); return 3
                sess_blocks = int(getattr(lr, "_sess_blocks", 0)) + 1
                lr._sess_blocks = sess_blocks
                circuit = int(float(os.environ.get("PH_BLOCK_CIRCUIT", "5") or 5))
                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} open_failed >= PH_BLOCK_CIRCUIT={circuit}", **sess(None)); return 3
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0"
                    os.environ["PH_PORTSCREEN_MAX_TRY"] = os.environ.get("PH_PORTSCREEN_MAX_TRY_ON_BLOCK", "8")
                    import portscreen as _ps
                    home = int(os.environ.get("PROXY_PORT") or 0)
                    if home:
                        _ps.FAILED.add(home)
                        try: _ps._release(home, VM)
                        except Exception: pass
                    newp = _ps.prescreen(VM, lambda **kw: S.put(**kw))
                    S.put(event="block_port_rotate", handle=h, phase="browser_open", from_port=home, to_port=newp, sess_blocks=sess_blocks)
                except Exception as _e:
                    S.put(event="block_port_rotate_error", handle=h, phase="browser_open", err=str(_e)[:200], sess_blocks=sess_blocks)
                wait_s = float(os.environ.get("PH_BLOCK_ROTATE_SLEEP_SEC", "45") or 45)
                S.put(event="block_soft_retry", handle=h, phase="browser_open", note=f"sleep {wait_s}s then reopen", sess_blocks=sess_blocks)
                await asyncio.sleep(wait_s); continue"""

if needle not in src:
    print("browser_open_failed pattern not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched soft_open_rotate")
