#!/usr/bin/env python3
"""Upload whole-person JSON to PH_SAVE_B (SB), not VM root B — matches pdeep staging path."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "PH_BATCH_SAVE_SB_PATCH" in src:
    print("ph_batch_save_sb already patched")
    sys.exit(0)

old = "sh('gsutil', '-q', 'cp', f'out/{h}.json', f'{B}/{h}.json'); sh('gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')"
new = """sh('gsutil', '-q', 'cp', f'out/{h}.json', f'{SB}/{h}.json'); sh('gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')  # PH_BATCH_SAVE_SB_PATCH: staging on SB"""
if old not in src:
    print("upload line not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old, new, 1)
p.write_text(src)
print("patched ph_batch_save_sb")