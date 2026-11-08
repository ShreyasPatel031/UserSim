#!/usr/bin/env python3
"""Cloudflare wall: give up on a port in ~2-3 min instead of ~10 min.

Stock on_block: 60 s challenge wait, 120 s backoff, retry, 120 s backoff, retry, raise on the 3rd block (7-10 min).
PH_CF_BACKOFF_SEC / PH_CF_MAX_BLOCKS make that configurable so the supervisor can move to a fresh port quickly.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_person.py")
if not p.exists():
    print("ph_person.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "CF_FAST_FAIL_PATCH" in src:
    print("cf_fast_fail already patched")
    sys.exit(0)

needle = (
    '        if len(s.blocks) >= 3: s.stop = True; raise Blocked(what)\n'
    '        s.tier = max(0, s.tier - 1); s.log("backoff 120s, drop to", s.ramp[s.tier]); await asyncio.sleep(120)'
)
repl = (
    '        # CF_FAST_FAIL_PATCH\n'
    '        _mb = int(os.environ.get("PH_CF_MAX_BLOCKS", "3") or 3); _bo = float(os.environ.get("PH_CF_BACKOFF_SEC", "120") or 120)\n'
    '        if len(s.blocks) >= _mb: s.stop = True; raise Blocked(what)\n'
    '        s.tier = max(0, s.tier - 1); s.log(f"backoff {_bo:.0f}s, drop to", s.ramp[s.tier]); await asyncio.sleep(_bo)'
)
if needle not in src:
    print("on_block backoff not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(needle, repl, 1)
if "\nimport os" not in src and not src.startswith("import os"):
    src = "import os\n" + src
p.write_text(src)
print("patched cf_fast_fail")
