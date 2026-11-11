#!/usr/bin/env python3
"""Open 1 tab through CF clear; spawn extra tabs in background (full 32-tab capacity)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "LAZY_TABS_PATCH" in src:
    print("lazy_tabs already patched")
    sys.exit(0)

old = """    await R.goto(pages[0], f"/@{first_handle}", 150)  # the one Cloudflare clear for this browser
    for _ in range(n_tabs - 1):
        pg = await ctx.new_page(); await R.goto(pg, f"/@{first_handle}/stacks"); pages.append(pg)"""

new = """    await R.goto(pages[0], f"/@{first_handle}", 150)  # the one Cloudflare clear for this browser
    # LAZY_TABS_PATCH: start pulling sooner — extra tabs warm in background.
    for _ in range(n_tabs - 1):
        pages.append(await ctx.new_page())
    async def _lazy_fill_tabs():
        h = first_handle
        for i in range(1, len(pages)):
            try:
                await R.goto(pages[i], f"/@{h}/stacks", 90)
            except Exception:
                pass
    asyncio.create_task(_lazy_fill_tabs())"""

if old not in src:
  # slightly different spacing
  old2 = "    await R.goto(pages[0], f\"/@{first_handle}\", 150)"
  if old2 not in src:
    print("open_browser tab loop not found", file=sys.stderr)
    sys.exit(1)
  # fallback: regex replace multiline
  import re
  pat = re.compile(
    r"    await R\.goto\(pages\[0\], f\"/@\{first_handle\}\", 150\).*?"
    r"pages\.append\(pg\)",
    re.S,
  )
  if not pat.search(src):
    print("open_browser tab loop not found (regex)", file=sys.stderr)
    sys.exit(1)
  src = pat.sub(new.strip().replace("\n", "\n"), src, count=1)
else:
  src = src.replace(old, new, 1)

p.write_text(src)
print("patched lazy_tabs")
