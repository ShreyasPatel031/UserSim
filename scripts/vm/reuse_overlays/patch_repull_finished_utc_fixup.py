#!/usr/bin/env python3
"""repullupvotes: stamp run.finished_utc=now() so Population sees today's pulls."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ph/reuse") / "ph_batch.py"
src = p.read_text()
if "REPULL_FINISHED_UTC_FIXUP" in src:
    print("finished_utc fixup already applied")
    sys.exit(0)

old = 'res["run"]["finished_utc"] = res.get("run", {}).get("finished_utc") or now()'
new = """_pf = res.get("run", {}).get("finished_utc")
    res.setdefault("run", {})["finished_utc"] = now()
    if _pf:
        res["run"]["finished_utc_prior_pull"] = _pf  # REPULL_FINISHED_UTC_FIXUP"""

if old not in src:
    print("preserve finished_utc line not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old, new, 1)
p.write_text(src)
print("patched finished_utc fixup")