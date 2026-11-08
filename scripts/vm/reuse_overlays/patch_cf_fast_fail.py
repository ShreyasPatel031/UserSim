#!/usr/bin/env python3
"""Fast port swap after a Cloudflare wall (target: back pulling within ~3 min).

ph_person on_block: stock waits 60 s, backs off 120 s and retries up to 3 blocks (7-10 min).
PH_CF_BACKOFF_SEC / PH_CF_MAX_BLOCKS make that configurable.

pdeep (same file, because supervisor_strat.sh only re-applies a fixed list of patch names):
  - _full_queue result is cached in /tmp for PDEEP_QUEUE_CACHE_SEC so a relaunch after a block skips the
    ~2 min of bucket listings;
  - a failed browser open exits immediately (os._exit) instead of ~90 s of executor/browser teardown.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_person.py")
if p.exists():
    src = p.read_text()
    if "CF_FAST_FAIL_PATCH" not in src:
        needle = (
            '        if len(s.blocks) >= 3: s.stop = True; raise Blocked(what)\n'
            '        s.tier = max(0, s.tier - 1); s.log("backoff 120s, drop to", s.ramp[s.tier]); await asyncio.sleep(120)'
        )
        repl = (
            '        # CF_FAST_FAIL_PATCH\n'
            '        _mb = int(os.environ.get("PH_CF_MAX_BLOCKS", "3") or 3); _bo = float(os.environ.get("PH_CF_BACKOFF_SEC", "120") or 120)\n'
            '        if len(s.blocks) >= _mb: s.stop = True; raise Blocked(what)\n'
            '        s.tier = max(0, s.tier - 1); s.log(f"backoff {_bo:.0f}s, drop to", s.ramp[s.tier]); await asyncio.sleep(_bo)'
        )
        if needle in src:
            src = src.replace(needle, repl, 1)
            if "\nimport os" not in src and not src.startswith("import os"):
                src = "import os\n" + src
            p.write_text(src)
            print("patched cf_fast_fail")
        else:
            print("on_block backoff not found", file=sys.stderr)

q = pathlib.Path("/opt/ph/reuse/pdeep.py")
if q.exists():
    src = q.read_text()
    if "PDEEP_FASTCYCLE_PATCH" not in src:
        n1 = "    if FULL:\n        queue = _full_queue()\n"
        r1 = (
            "    if FULL:  # PDEEP_FASTCYCLE_PATCH\n"
            "        _qc = '/tmp/pdeep_queue_cache.json'\n"
            "        try:\n"
            "            _c = json.load(open(_qc))\n"
            "            if time.time() - _c['t'] > int(os.environ.get('PDEEP_QUEUE_CACHE_SEC', '1200')): raise ValueError('stale')\n"
            "            queue = _c['q']; RR.clear(); RR.update(_c['rr'])\n"
            "        except Exception:\n"
            "            queue = _full_queue()\n"
            "            try: json.dump({'t': time.time(), 'q': queue, 'rr': RR}, open(_qc, 'w'))\n"
            "            except Exception: pass\n"
        )
        n2 = '        S.put(event="stopped_on_block", note="pdeep: browser open/Cloudflare clear failed; no retry"); return 3\n'
        r2 = (
            '        S.put(event="stopped_on_block", note="pdeep: browser open/Cloudflare clear failed; no retry")\n'
            "        PB.sh('gsutil', '-q', 'cp', S.f, f'{B}/status/{VM}.jsonl'); os._exit(3)\n"
        )
        if n1 in src and n2 in src:
            q.write_text(src.replace(n1, r1, 1).replace(n2, r2, 1))
            print("patched pdeep_fastcycle")
        else:
            print(f"pdeep_fastcycle needles missing q={n1 in src} exit={n2 in src}", file=sys.stderr)
