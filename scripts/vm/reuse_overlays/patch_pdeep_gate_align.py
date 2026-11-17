#!/usr/bin/env python3
"""pdeep whole(): align with population's merge gate (quality.person_complete), 2026-11-17 02:35Z.

  - collection_items: a collection with products_count > 0 needs some items, not items == products_count
    (the stricter rule was rejecting people the merge gate accepts);
  - a rejected person whose upvotes stopped at PH's signed-out end still gets its signed-in upvotes queue entry,
    so upvotes:signed_out_end_not_queued_signed_in no longer blocks them.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

# Supervisors started before patch_upvotes_search_sweep.py joined their patch list still run this file every loop.
_sweep = pathlib.Path(__file__).with_name("patch_upvotes_search_sweep.py")
if _sweep.is_file() and len(sys.argv) < 2:
    subprocess.run([sys.executable, str(_sweep)], check=False)

MARK = "PDEEP_GATE_ALIGN_PATCH"
p = pathlib.Path("/opt/ph/reuse/pdeep.py") if len(sys.argv) < 2 else pathlib.Path(sys.argv[1])
src = p.read_text()
if MARK in src:
    print("pdeep_gate_align already patched")
    sys.exit(0)

edits = [
    (
        '        if not isinstance(it, list) or (c.get("products_count") and len(it) < c["products_count"]): why.append("collection_items"); break',
        '        if c.get("products_count") and not (isinstance(it, list) and it): why.append("collection_items"); break  # PDEEP_GATE_ALIGN_PATCH',
    ),
    (
        "                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.incomplete.json', f'{_Q}incomplete/{h}.json')\n",
        "                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.incomplete.json', f'{_Q}incomplete/{h}.json')\n"
        "                if (res.get('upvotes') or {}).get('upvotes_capped'):  # PDEEP_GATE_ALIGN_PATCH\n"
        "                    open(f'out/{h}.su', 'w').write(json.dumps({\"header\": (res.get(\"header\") or {}).get(\"upvotes\"), \"got\": res[\"upvotes\"].get(\"count\"), \"utc\": PB.now(), \"vm\": VM}))\n"
        "                    await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.su', f'{_Q}signedin_upvotes/{h}.json')\n",
    ),
]
for old, new in edits:
    if src.count(old) != 1:
        print(f"pdeep_gate_align: anchor not found once: {old[:70]!r}", file=sys.stderr)
        sys.exit(1)
    src = src.replace(old, new, 1)
p.write_text(src)
print("patched pdeep_gate_align")
