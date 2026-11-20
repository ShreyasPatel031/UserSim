#!/usr/bin/env python3
"""Attach exit_ip to block/resume status events (EXIT_IP_AUDIT_PATCH)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ph/reuse") / "ph_batch.py"
src = p.read_text()
mark = "EXIT_IP_AUDIT_PATCH"
if mark in src:
    print("exit_ip_audit already patched")
    sys.exit(0)

needle = '        o = {"vm": VM, **o, "utc": now()}'
if needle not in src:
    print("Status.put header not found", file=sys.stderr)
    sys.exit(1)

inject = """        o = {"vm": VM, **o, "utc": now()}
        # EXIT_IP_AUDIT_PATCH: exit_ip on block/resume for Population 60m no-rotation audit
        _eip_ev = o.get("event")
        _BLOCK_RESUME = frozenset({
            "stopped_on_block", "block_soft_retry", "block_port_rotate", "block_port_rotate_error",
            "browser_open_failed", "block_same_port_retry", "block_same_ip_backoff", "block_fresh_browser",
            "block_port_rotate", "browser_open", "supervisor_run_start",
        })
        if _eip_ev in _BLOCK_RESUME or _eip_ev == "supervisor_run_end":
            try:
                ei = exit_info()
                for _k in ("exit_ip", "exit_asn", "exit_org", "exit_country", "proxy_port", "exit_err"):
                    if ei.get(_k) is not None and _k not in o:
                        o[_k] = ei[_k]
                if ei.get("ts"):
                    o["exit_ip_probe_ts"] = ei["ts"]
            except Exception:
                pass"""

src = src.replace(needle, inject, 1)
p.write_text(src)
print("patched exit_ip_audit")