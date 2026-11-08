#!/usr/bin/env python3
"""pdeep FULL queue: drop handles already claimed fleet-wide and give each VM its own stride of the queue.

Without this every VM walks the same need_list order and spends ~2.4 s of gsutil per handle that another VM already
claimed, so a fleet of N VMs mostly waits on claim collisions (minutes of silence between people).
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/pdeep.py")
if not p.exists():
    print("pdeep.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "PDEEP_PARTITION_PATCH" in src:
    print("pdeep_partition already patched")
    sys.exit(0)

needle = "    return list(RR) + rest\nRR = {}"
repl = '''    # PDEEP_PARTITION_PATCH
    try:
        _cl = set(x.rstrip('/').rsplit('/', 1)[-1].lower() for x in PB.sh('gsutil', 'ls', f'{SB}/claims/').stdout.split())
        rest = [h for h in rest if h not in _cl]
    except Exception:
        pass
    import re as _re, zlib as _z
    _n = int(os.environ.get('PH_FLEET_N', '0') or 0)
    if _n > 1:
        _m = _re.search(r'-(\\d+)$', VM)
        _k = (int(_m.group(1)) if _m else _z.crc32(VM.encode())) % _n
        rest = [h for j, h in enumerate(rest) if j % _n == _k] + [h for j, h in enumerate(rest) if j % _n != _k]
    return list(RR) + rest
RR = {}'''

if needle not in src:
    print("pdeep _full_queue return not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched pdeep_partition")
