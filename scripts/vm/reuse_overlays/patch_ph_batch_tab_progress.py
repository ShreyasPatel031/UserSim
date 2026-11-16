#!/usr/bin/env python3
"""Per-tab progress clock for fleet tab stall watchdog (orchestrator 2026-11-16).

Refresh R._tab_progress_t on every captured GraphQL op (not only first op_seen per name)
so PH_TAB_STALL_SECS / NO_PROGRESS_SECS can end a stuck tab and requeue the person.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "TAB_PROGRESS_PATCH" in src:
    print("tab_progress already patched")
    sys.exit(0)

needle = '''            if R_: R_.log("op_seen", name, (h or '')[:64], r.request.method)
    except Exception: pass'''

repl = '''            if R_:  # TAB_PROGRESS_PATCH
                R_._tab_progress_t = time.time()
                if name:
                    R_._tab_key = name
                R_.log("op_seen", name, (h or '')[:64], r.request.method)
    except Exception: pass'''

if needle not in src:
    print("op_seen log line not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched tab_progress")