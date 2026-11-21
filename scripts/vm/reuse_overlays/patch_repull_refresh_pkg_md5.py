#!/usr/bin/env python3
"""repullupvotes: stamp run.pkg_md5 from PKG_MD5 so Population build gate accepts refresh saves."""
from __future__ import annotations

import pathlib
import sys

MARK = "REPULL_REFRESH_PKG_MD5"
p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ph/reuse") / "ph_batch.py"
src = p.read_text()
if MARK in src:
    print("repull_refresh_pkg_md5 already applied")
    sys.exit(0)

needle = 'res["upvotes_refreshed_at"] = now()  # REPULL_UPVOTES_STAGING_PATCH'
if needle not in src:
    print("repull staging stamp not found", file=sys.stderr)
    sys.exit(1)

insert = f"""    _pmd5 = (os.environ.get("PKG_MD5") or os.environ.get("PH_PKG_MD5") or "").strip()
    if _pmd5:
        res.setdefault("run", {{}})["pkg_md5"] = _pmd5  # {MARK}
    if not (res.get("run") or {{}}).get("vm"):
        res.setdefault("run", {{}})["vm"] = VM"""

src = src.replace(needle, needle + "\n" + insert, 1)
p.write_text(src)
print("patched repull_refresh_pkg_md5")