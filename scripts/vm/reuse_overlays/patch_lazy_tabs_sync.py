#!/usr/bin/env python3
"""Fix post-browser_open hang: await tab warmup instead of fire-and-forget lazy task."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "LAZY_TABS_AWAIT" in src:
    print("lazy_tabs await already patched")
    sys.exit(0)
if "LAZY_TABS_PATCH" not in src:
    print("lazy_tabs patch missing; run patch_lazy_tabs.py first", file=sys.stderr)
    sys.exit(1)
old = "    asyncio.create_task(_lazy_fill_tabs())"
new = "    await _lazy_fill_tabs()  # LAZY_TABS_AWAIT: workers must not start on blank tabs"
if old not in src:
    print("lazy_tabs create_task not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(old, new, 1))
print("patched lazy_tabs await")