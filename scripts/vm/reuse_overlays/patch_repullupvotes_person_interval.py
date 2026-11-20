#!/usr/bin/env python3
"""repullupvotes: respect --person-interval 0 (do not force default 180s gap)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ph/reuse") / "ph_batch.py"
src = p.read_text()
mark = "REPULL_PERSON_INTERVAL_PATCH"
if mark in src:
    print("repullupvotes person_interval already patched")
    sys.exit(0)

old = "    if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'): a.person_interval = a.person_interval or (int(os.environ.get('DEEP_INTERVAL', 60)) if a.mode == 'deep' else 180); a.cap = min(a.cap, CAP)  # 2052Z proposal: deep gap 60 s (180 s was half-pace pacing, not a PH limit)"
new = """    if a.mode in ('test2a', 'repull', 'repulltabs', 'repullstacks', 'repullupvotes', 'half', 'headers', 'deep'):
        if a.mode == 'repullupvotes' and (a.person_interval is None or a.person_interval == 0):
            a.person_interval = float(os.environ.get('PH_PERSON_INTERVAL') or os.environ.get('DEEP_INTERVAL') or 0)
        elif not a.person_interval:
            a.person_interval = int(os.environ.get('DEEP_INTERVAL', 60)) if a.mode == 'deep' else 180
        a.cap = min(a.cap, CAP)  # REPULL_PERSON_INTERVAL_PATCH; 2052Z deep gap"""

if old not in src:
    print("person_interval default block not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(old, new, 1))
print("patched repullupvotes person_interval")