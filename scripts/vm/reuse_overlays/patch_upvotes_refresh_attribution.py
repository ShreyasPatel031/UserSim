#!/usr/bin/env python3
"""Stamp VM + exit IP on upvote refresh staging saves (Population audit)."""
from __future__ import annotations

import pathlib
import sys

MARK = "UPVOTES_REFRESH_ATTRIBUTION_PATCH"
p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ph/reuse") / "ph_batch.py"
src = p.read_text()
if MARK in src:
    print("upvotes_refresh_attribution already applied")
    sys.exit(0)

needle = 'res["upvotes_refreshed_at"] = now()  # REPULL_UPVOTES_STAGING_PATCH'
if needle not in src:
    print("upvotes_refreshed_at stamp not found", file=sys.stderr)
    sys.exit(1)

block = f"""res["upvotes_refreshed_at"] = now()  # REPULL_UPVOTES_STAGING_PATCH
    res["upvotes_refreshed_by"] = VM  # {MARK}
    try:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("_eiu", "/opt/ph/overlays/exit_ip_util.py")
        _mod = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_mod)
        res["upvotes_refreshed_exit_ip"] = (_mod.exit_info() or {{}}).get("exit_ip")
    except Exception:
        res["upvotes_refreshed_exit_ip"] = None"""

src = src.replace(needle, block, 1)
p.write_text(src)
print("patched upvotes_refresh_attribution")