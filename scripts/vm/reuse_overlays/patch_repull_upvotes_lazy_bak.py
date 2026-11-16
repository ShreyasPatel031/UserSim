#!/usr/bin/env python3
"""repullupvotes: drop O(n) pre-run gsutil backup loop; backup lazily per person + skip vm-wide have scan."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "REPULL_LAZY_BAK_PATCH" in src:
    print("repull_upvotes_lazy_bak already patched")
    sys.exit(0)

old_have = "    have = set(x.rsplit('/', 1)[-1][:-5] for x in sh('gsutil', 'ls', f'{B}/*.json').stdout.split() if x.endswith('.json'))"
new_have = """    have = set()
    if a.mode != 'repullupvotes':  # REPULL_LAZY_BAK_PATCH
        have = set(x.rsplit('/', 1)[-1][:-5] for x in sh('gsutil', 'ls', f'{B}/*.json').stdout.split() if x.endswith('.json'))"""
if old_have not in src:
    print("have scan line not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_have, new_have, 1)

old_bulk = """        for h in handles:
            if not gexists(f'{h}.json.bak_preupvotesrepull'):
                _from = f'{SB}/{h}.json' if gexists(f'{SB}/{h}.json') else f'{B}/{h}.json'
                sh('gsutil', '-q', 'cp', _from, f'{SB}/{h}.json.bak_preupvotesrepull')  # REPULL_UPVOTES_STAGING_PATCH"""
new_bulk = "        # REPULL_LAZY_BAK_PATCH: backup per handle in main loop (not 27k gsutil calls before start)"
if old_bulk not in src:
    # Unpatched staging backup block
    old_bulk2 = """        for h in handles:
            if not gexists(f'{h}.json.bak_preupvotesrepull'): sh('gsutil', '-q', 'cp', f'{B}/{h}.json', f'{B}/{h}.json.bak_preupvotesrepull')"""
    if old_bulk2 in src:
        src = src.replace(old_bulk2, new_bulk, 1)
    else:
        print("repullupvotes bulk backup block not found", file=sys.stderr)
        sys.exit(1)
else:
    src = src.replace(old_bulk, new_bulk, 1)

needle = "        h = handles[i]\n        if a.mode.startswith('half')"
lazy = """        h = handles[i]
        if a.mode == 'repullupvotes' and not gexists(f'{h}.json.bak_preupvotesrepull'):  # REPULL_LAZY_BAK_PATCH
            _from = f'{SB}/{h}.json' if gexists(f'{SB}/{h}.json') else f'{B}/{h}.json'
            sh('gsutil', '-q', 'cp', _from, f'{SB}/{h}.json.bak_preupvotesrepull')
        if a.mode.startswith('half')"""
if needle not in src:
    print("main loop handle line not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(needle, lazy, 1)

p.write_text(src)
print("patched repull_upvotes_lazy_bak")