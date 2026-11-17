#!/usr/bin/env python3
"""pdeep: skip done people with an in-memory have-set, not a gsutil stat per handle.

On 2-vCPU VMs the per-handle `gsutil stat` (x2) plus a failing claim for every already-complete person starved
camoufox (load 4+, browser ~5% CPU) and each relaunch re-spun the whole pdeep_list. Now:
  - complete handles come from people_live/have_complete.txt (built from have_index.jsonl), refreshed every
    PDEEP_HAVE_REFRESH_SEC;
  - the pdeep_list is filtered once at load; handles another VM already holds a claim on are remembered per list
    (pdeep_tried.json) so a relaunch does not retry them;
  - _full_queue uses the same set instead of `gsutil ls` over ~95k saved people.
"""
from __future__ import annotations

import pathlib
import sys

MARK = "PDEEP_HAVE_SET_PATCH"
p = pathlib.Path("/opt/ph/reuse/pdeep.py") if len(sys.argv) < 2 else pathlib.Path(sys.argv[1])
src = p.read_text()
if MARK in src:
    print("pdeep_have_set already patched")
    sys.exit(0)

helpers = '''_HAVE = {'t': 0.0, 's': set()}  # PDEEP_HAVE_SET_PATCH
def _have_done():
    if time.time() - _HAVE['t'] < float(os.environ.get('PDEEP_HAVE_REFRESH_SEC', '900')):
        return _HAVE['s']
    _HAVE['t'] = time.time()
    _f = f'/tmp/have_complete.{os.getpid()}.txt'
    if PB.sh('gsutil', '-q', 'cp', B.rsplit('/', 1)[0] + '/have_complete.txt', _f).returncode == 0:
        try:
            _HAVE['s'] = {l.strip().lower() for l in open(_f) if l.strip()}
        except Exception:
            pass
    return _HAVE['s']
_TRIED, _TRIED_K, _TRIED_F = set(), [''], '/opt/ph/reuse/pdeep_tried.json'
def _tried_load(key):
    import hashlib
    _TRIED_K[0] = hashlib.md5(key.encode()).hexdigest()
    try:
        d = json.load(open(_TRIED_F))
        if d.get('k') == _TRIED_K[0]: _TRIED.update(d.get('h') or [])
    except Exception:
        pass
def _tried_add(h):
    _TRIED.add(h)
    try: json.dump({'k': _TRIED_K[0], 'h': sorted(_TRIED)}, open(_TRIED_F, 'w'))
    except Exception: pass
'''

edits = [
    (
        "RR = {}  # full15:",
        helpers + "RR = {}  # full15:",
    ),
    (
        "    have = set(x.rsplit('/', 1)[-1][:-5].lower() for x in (PB.sh('gsutil', 'ls', f'{B}/*.json').stdout + ' ' + (PB.sh('gsutil', 'ls', f'{SB}/*.json').stdout if SB != B else '')).split() if x.endswith('.json'))",
        "    have = _have_done()  # PDEEP_HAVE_SET_PATCH",
    ),
    (
        "await asyncio.to_thread(lambda: PB.gexists(f'{h}.json') or (SB != B and PB.sh('gsutil', '-q', 'stat', f'{SB}/{h}.json').returncode == 0))",
        "(h in await asyncio.to_thread(_have_done) or h in _TRIED)",
    ),
    (
        "            if await asyncio.to_thread(PB.claim, h if FULL else f'deep_{h}'): return h",
        "            if await asyncio.to_thread(PB.claim, h if FULL else f'deep_{h}'): return h\n"
        "            _tried_add(h)",
    ),
    (
        '        S.put(event="pdeep_test_list", n=len(queue))',
        "        _tried_load(tl.stdout); _hd = _have_done(); _n0 = len(queue); queue = [h for h in queue if h not in _hd and h not in _TRIED]\n"
        '        S.put(event="pdeep_test_list", n=len(queue), skipped_done=_n0 - len(queue))',
    ),
]
for old, new in edits:
    if src.count(old) != 1:
        print(f"pdeep_have_set: anchor not found once: {old[:70]!r}", file=sys.stderr)
        sys.exit(1)
    src = src.replace(old, new, 1)
p.write_text(src)
print("patched pdeep_have_set")
