#!/usr/bin/env python3
"""Widen held-upvote match: post_id, url slug, items_earlier (Population union)."""
from __future__ import annotations

import pathlib
import sys

MARK = "REPULL_UPVOTES_HELD_KEYS_PATCH"
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if MARK in src:
    print("held_keys already patched")
    sys.exit(0)

old = """    old_ids = {u.get("post_id") for u in (res.get("upvotes") or {}).get("items") or [] if u.get("post_id")}  # {MARK}"""

new = """    _uv_store = res.get("upvotes") or {}  # {MARK}
    _held_items = list(_uv_store.get("items") or []) + list(_uv_store.get("items_earlier") or [])
    old_ids = set()
    for _u in _held_items:
        if _u.get("post_id"):
            old_ids.add(str(_u["post_id"]))
        _url = (_u.get("url") or "").rstrip("/")
        if _url:
            old_ids.add(_url.rsplit("/", 1)[-1])"""

if old not in src:
    # v1 patch may use literal {MARK} in comment
    alt = """    old_ids = {u.get("post_id") for u in (res.get("upvotes") or {}).get("items") or [] if u.get("post_id")}  # REPULL_UPVOTES_TO_HELD_PATCH"""
    if alt in src:
        old = alt
    else:
        print("old_ids anchor not found", file=sys.stderr)
        sys.exit(1)

src = src.replace(old, new, 1)

old_pid = """            pid = n.get("id")
            if pid and pid in old_ids:"""

new_pid = """            pid = n.get("id")
            _slug = (n.get("slug") or ((n.get("product") or {}).get("slug")) or "").strip()
            if pid and (str(pid) in old_ids or (_slug and _slug in old_ids)):"""

if old_pid not in src:
    print("pid check anchor not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_pid, new_pid, 1)
p.write_text(src)
print("patched held_keys")