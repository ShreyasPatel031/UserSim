#!/usr/bin/env python3
"""Allow ph_batch --mode repullupvotes under full7 write gate (fleet upvote_refresh)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "REPULL_WRITE_PATCH" in src:
    print("repallow_upvotes_write already patched")
    sys.exit(0)

old = """if __name__ == "__main__" and not ("--mode" in sys.argv and sys.argv[sys.argv.index("--mode") + 1] == "pdeep"):  # full7: only pdeep PDEEP_MODE=full may write
    print("only pdeep PDEEP_MODE=full may write"); sys.exit(5)"""

new = """if __name__ == "__main__":  # REPULL_WRITE_PATCH: repullupvotes may write to SB like pdeep
    _mi = sys.argv.index("--mode") + 1 if "--mode" in sys.argv else -1
    _md = sys.argv[_mi] if 0 < _mi < len(sys.argv) else ""
    if _md not in ("pdeep", "repullupvotes"):
        print("only pdeep or repullupvotes PDEEP_MODE=full may write"); sys.exit(5)"""

if old not in src:
    print("full7 write gate not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old, new, 1)
p.write_text(src)
print("patched repallow_upvotes_write")