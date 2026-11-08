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

# First-page Cloudflare clear: fleet data 2026-11-08 had 93/119 clears within 60 s and none between 60 and 90 s,
# while every failure burned the full 150 s.
b = pathlib.Path("/opt/ph/reuse/ph_batch.py")
if b.exists():
    src = b.read_text()
    n = 'await R.goto(pages[0], f"/@{first_handle}", 150)'
    if "PH_CF_OPEN_SEC" not in src:
        if n in src:
            b.write_text(src.replace(n, 'await R.goto(pages[0], f"/@{first_handle}", int(os.environ.get("PH_CF_OPEN_SEC", "150")))', 1))
            print("patched cf_open_sec")
        else:
            print("open_browser goto not found", file=sys.stderr)

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
            "            if time.time() - _c['t'] > int(os.environ.get('PDEEP_QUEUE_CACHE_SEC', '1200')) or _c.get('m') != PB.PKG_MD5: raise ValueError('stale')\n"
            "            queue = _c['q']; RR.clear(); RR.update(_c['rr']); _qhit = True\n"
            "        except Exception:\n"
            "            queue = _full_queue(); _qhit = False\n"
            "            try: json.dump({'t': time.time(), 'm': PB.PKG_MD5, 'q': queue, 'rr': RR}, open(_qc, 'w'))\n"
            "            except Exception: pass\n"
        )
        n2 = '        S.put(event="stopped_on_block", note="pdeep: browser open/Cloudflare clear failed; no retry"); return 3\n'
        r2 = (
            '        S.put(event="stopped_on_block", note="pdeep: browser open/Cloudflare clear failed; no retry")\n'
            "        PB.sh('gsutil', '-q', 'cp', S.f, f'{B}/status/{VM}.jsonl'); _wake(); os._exit(3)\n"
        )
        # Mid-run block: stock code sets st["stop"] and gather() waits for every other worker to finish its current
        # full pull on the walled IP (10+ min observed). Exit now, releasing the other workers' claims so those
        # people return to the queue.
        n3 = '    st = {"stop": None, "done": 0, "rc": 0, "qi": 0}\n'
        r3 = n3 + "    _INF = _INFG\n"
        n6 = "    import signal; signal.signal(signal.SIGTERM, lambda *_: (PB.sh('gsutil', '-q', 'cp', S.f, f'{B}/status/{VM}.jsonl'), os._exit(143)))"
        r6 = (
            "    import signal; signal.signal(signal.SIGTERM, lambda *_: ((lambda r: r and PB.sh('gsutil', '-q', '-m', 'rm', *r))"
            "([f'{SB}/claims/{v}' for v in _INFG.values()]), PB.sh('gsutil', '-q', 'cp', S.f, f'{B}/status/{VM}.jsonl'), _wake(), os._exit(143)))"
        )
        n7 = "async def main(a):\n"
        r7 = (
            "_INFG = {}\n"
            "def _wake():  # supervisor polls its child with `sleep 120`; end that sleep just after we exit\n"
            "    import subprocess as _sp; _sp.Popen(['bash', '-c', 'sleep 1; pkill -x -f \"sleep 120\"'], start_new_session=True)\n"
            + n7
        )
        n4 = "            h = await next_handle()\n            if not h: break\n"
        r4 = (
            "            _INF.pop(wi, None)\n"
            "            h = await next_handle()\n            if not h: break\n"
            "            _INF[wi] = f'rerun_{RR[h]}_{h}' if h in RR else h\n"
        )
        n5 = '                    st["stop"] = "block"; st["rc"] = 3; S.put(event="stopped_on_block", handle=h, note="pdeep: first block stops every worker"); break\n'
        r5 = (
            '                    S.put(event="stopped_on_block", handle=h, note="pdeep: first block; fast exit, released in-flight claims", released=sorted(v for k, v in _INF.items() if k != wi))\n'
            "                    _rel = [f'{SB}/claims/{v}' for k, v in _INF.items() if k != wi]\n"
            "                    if _rel: PB.sh('gsutil', '-q', '-m', 'rm', *_rel)\n"
            "                    PB.sh('gsutil', '-q', 'cp', S.f, f'{B}/status/{VM}.jsonl'); _wake(); os._exit(3)\n"
        )
        # Requeue sweep reads every entry with its own gsutil cat (~1.5 s each, 91 entries = 2+ min). It only acts
        # on entries from another build, which the run that built the cached queue already handled.
        n8 = "        rq = [] if _has_tl else ["
        r8 = "        rq = [] if (_has_tl or _qhit) else ["
        pairs = [(n8, r8), (n1, r1), (n2, r2), (n3, r3), (n4, r4), (n5, r5), (n6, r6), (n7, r7)]
        miss = [i for i, (n, _) in enumerate(pairs, 1) if n not in src]
        if not miss:
            for n, r in pairs:
                src = src.replace(n, r, 1)
            q.write_text(src)
            print("patched pdeep_fastcycle")
        else:
            print(f"pdeep_fastcycle needles missing {miss}", file=sys.stderr)
