#!/usr/bin/env python3
"""Patch ph_batch.week_bytes to cache + parallel-cat (cuts launch→browser tax)."""
from __future__ import annotations
import pathlib, re, sys
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "WEEK_BYTES_CACHE" in src:
    print("week_bytes already patched")
    sys.exit(0)
old = '''def week_bytes():
    """2045Z: the 29e9 weekly stop counts EVERY feeder-* VM: all vm/status/feeder-*.jsonl 'bytes' (phpeople, pgql, phtest, dy, ...)
    (feeder-dy-* write their own status files there, so each VM is counted once)."""
    tot = 0; per = {}
    for u in sh('gsutil', 'ls', f'{B}/status/feeder-*.jsonl').stdout.split():
        if u.endswith('.supervisor.jsonl'): continue
        s = 0
        for l in sh('gsutil', 'cat', u).stdout.splitlines():
            try: j = json.loads(l)
            except Exception: continue
            if j.get('utc', '') >= WEEK_START and isinstance(j.get('bytes'), int): s += j['bytes']
        per[u.rsplit('/', 1)[-1][:-6]] = s; tot += s
    return tot, per'''
new = '''_WEEK_BYTES_CACHE = {"t": 0.0, "v": None}
def week_bytes():
    """2045Z weekly stop — cached 10m; ceiling strat skips (CAP unused for probe)."""
    import time as _t
    if (os.environ.get("PH_STRATEGY") or "").strip() == "ceiling":
        return 0, {}
    now = _t.time()
    if _WEEK_BYTES_CACHE["v"] is not None and now - _WEEK_BYTES_CACHE["t"] < 600:
        return _WEEK_BYTES_CACHE["v"]
    tot = 0; per = {}
    urls = [u for u in sh("gsutil", "ls", f"{B}/status/feeder-*.jsonl").stdout.split() if not u.endswith(".supervisor.jsonl")]
    # One process per file is the tax; batch via gsutil -m cp to /tmp then read.
    import tempfile, pathlib as _pl
    td = tempfile.mkdtemp(prefix="week_bytes_")
    try:
        if urls:
            sh("gsutil", "-m", "-q", "cp", *urls, td + "/")
        for fp in _pl.Path(td).glob("*.jsonl"):
            s = 0
            for l in fp.read_text(errors="ignore").splitlines():
                try: j = json.loads(l)
                except Exception: continue
                if j.get("utc", "") >= WEEK_START and isinstance(j.get("bytes"), int): s += j["bytes"]
            per[fp.name[:-6]] = s; tot += s
    finally:
        import shutil as _sh; _sh.rmtree(td, ignore_errors=True)
    _WEEK_BYTES_CACHE["t"] = now; _WEEK_BYTES_CACHE["v"] = (tot, per)
    return tot, per'''
if old not in src:
    print("week_bytes pattern not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(old, new, 1))
print("patched week_bytes")
