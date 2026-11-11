#!/usr/bin/env python3
"""Retry same sticky port once or twice before expensive port prescreen + new fingerprint."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "SAME_PORT_RETRY_PATCH" in src:
    print("same_port_retry already patched")
    sys.exit(0)

inject = '''                # SAME_PORT_RETRY_PATCH
                max_same = int(float(os.environ.get("PH_BLOCK_SAME_PORT_RETRIES", "2") or 2))
                same_n = int(getattr(lr, "_same_port_retries", 0)) + 1
                lr._same_port_retries = same_n
                if same_n <= max_same:
                    wait_s = float(os.environ.get("PH_BLOCK_SAME_PORT_SLEEP_SEC", "20") or 20)
                    S.put(event="block_same_port_retry", handle=h, attempt=same_n, max_same=max_same, note=f"sleep {wait_s}s reopen same port", **sess(R) if err[0]=='block' else {})
                    try:
                        if cm is not None:
                            await cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                    cm = None
                    await asyncio.sleep(wait_s)
                    continue
                lr._same_port_retries = 0'''

# Mid-pull block path (after sess_blocks increment, before close browser rotate)
needle_block = """                sess_blocks = int(getattr(lr, "_sess_blocks", 0)) + 1
                lr._sess_blocks = sess_blocks
                circuit = int(float(os.environ.get("PH_BLOCK_CIRCUIT", "5") or 5))
                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} blocks >= PH_BLOCK_CIRCUIT={circuit}", **sess(R)); return 3
                # Close browser, claim a new sticky port (same VM), short backoff, reopen warm."""

if needle_block in src:
    src = src.replace(needle_block, needle_block.replace(
        "# Close browser, claim a new sticky port",
        inject + "\n                # Close browser, claim a new sticky port",
    ), 1)
else:
    print("block rotate anchor not found", file=sys.stderr)
    sys.exit(1)

needle_open = """                sess_blocks = int(getattr(lr, "_sess_blocks", 0)) + 1
                lr._sess_blocks = sess_blocks
                circuit = int(float(os.environ.get("PH_BLOCK_CIRCUIT", "5") or 5))
                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} open_failed >= PH_BLOCK_CIRCUIT={circuit}", **sess(None)); return 3
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0"
                    os.environ["PH_PORTSCREEN_MAX_TRY"] = os.environ.get("PH_PORTSCREEN_MAX_TRY_ON_BLOCK", "8")
                    import portscreen as _ps"""

if needle_open in src:
    src = src.replace(
        """                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} open_failed >= PH_BLOCK_CIRCUIT={circuit}", **sess(None)); return 3
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0"
                    os.environ["PH_PORTSCREEN_MAX_TRY"] = os.environ.get("PH_PORTSCREEN_MAX_TRY_ON_BLOCK", "8")
                    import portscreen as _ps""",
        """                if sess_blocks >= circuit:
                    S.put(event="stopped_on_block", handle=h, note=f"circuit: {sess_blocks} open_failed >= PH_BLOCK_CIRCUIT={circuit}", **sess(None)); return 3
""" + inject.replace("err[0]=='block'", "False").replace("**sess(R)", "**sess(None)") + """
                cm = None
                try:
                    os.environ["PH_PORTSCREEN_HOME_ONLY"] = "0"
                    os.environ["PH_PORTSCREEN_MAX_TRY"] = os.environ.get("PH_PORTSCREEN_MAX_TRY_ON_BLOCK", "8")
                    import portscreen as _ps""",
        1,
    )
else:
    print("open rotate anchor not found", file=sys.stderr)
    sys.exit(1)

# Reset same-port counter on successful browser open
needle_ok = 'S.put(event="browser_open", bytes=nic() - b0, note="Cloudflare clear + tabs; counted in week bytes")'
if needle_ok in src:
    src = src.replace(needle_ok, 'lr._same_port_retries = 0\n            ' + needle_ok, 1)

p.write_text(src)
print("patched same_port_retry")
