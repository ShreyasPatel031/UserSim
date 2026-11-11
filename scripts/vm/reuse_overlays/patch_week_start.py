#!/usr/bin/env python3
"""Make ph_batch's weekly byte stop roll over every Monday 00:00 UTC instead of a hardcoded date."""
from __future__ import annotations
import pathlib, re, sys
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "_ROLLING_WEEK_START" in src:
    print("week_start already patched")
    sys.exit(0)
pat = re.compile(r'WEEK_START = "\d{4}-\d{2}-\d{2}T00:00:00Z"')
if not pat.search(src):
    print("WEEK_START pattern not found", file=sys.stderr)
    sys.exit(1)
new = ('_ROLLING_WEEK_START = 1; WEEK_START = (lambda _d: (_d - __import__("datetime").timedelta(days=_d.weekday()))'
       '.strftime("%Y-%m-%dT00:00:00Z"))(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))')
p.write_text(pat.sub(new, src, count=1))
print("patched week_start")
