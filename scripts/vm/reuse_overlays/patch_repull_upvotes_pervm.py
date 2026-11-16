#!/usr/bin/env python3
"""repullupvotes: per-VM list repull_upvotes_list.{VM}.txt (fleet partition)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
if not p.exists():
    print("ph_batch.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "REPULL_UPVOTES_PERVM_PATCH" in src:
    print("repull_upvotes_pervm already patched")
    sys.exit(0)
old = "        sh('gsutil', '-q', 'cp', f'{B}/repull_upvotes_list.txt', 'repull_upvotes_list.txt'); handles = [l.strip() for l in open('repull_upvotes_list.txt') if l.strip()]"
new = """        # REPULL_UPVOTES_PERVM_PATCH
        (gexists(f'repull_upvotes_list.{VM}.txt') and sh('gsutil', '-q', 'cp', f'{B}/repull_upvotes_list.{VM}.txt', 'repull_upvotes_list.txt')) or sh('gsutil', '-q', 'cp', f'{B}/repull_upvotes_list.txt', 'repull_upvotes_list.txt')
        handles = [l.strip().split()[0].lower().lstrip('@') for l in open('repull_upvotes_list.txt') if l.strip() and not l.lstrip().startswith('#')]"""
if old not in src:
    print("repullupvotes block not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(old, new, 1))
print("patched repull_upvotes_pervm")