#!/usr/bin/env python3
"""Population RR-only: one rerun_whole file in file order, no cold need_list pulls."""
from __future__ import annotations

import pathlib
import re
import sys

p = pathlib.Path("/opt/ph/reuse/pdeep.py")
if not p.exists():
    print("pdeep.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "PDEEP_RR_ONLY_PATCH" in src:
    print("pdeep_rr_only already patched")
    sys.exit(0)

if "PDEEP_RR_ONLY_SKIP" not in src:
    m = re.search(
        r"    PB\.sh\('gsutil', '-q', 'cp', '([^']+need_list\.jsonl)', 'need_list\.jsonl'\)\n"
        r"(    for l in open\('need_list\.jsonl'\):\n"
        r"        try: rows\.append\(json\.loads\(l\)\)\n"
        r"        except Exception: pass\n"
        r"    _tr = \{'likely': 0, 'active_rest': 1, 'other': 2\}\n"
        r"    rows\.sort\(key=lambda x: \(_tr\.get\(x\.get\('tier'\), 3\), x\.get\('rank'\) or 1e9\)\)\n"
        r"    nl = \[h for h in dict\.fromkeys\(\(x\.get\('handle'\) or ''\)\.lower\(\) for x in rows\) if h\]\n)",
        src,
    )
    if m:
        inner = m.group(2)
        repl = (
            "    # PDEEP_RR_ONLY_SKIP\n"
            "    if os.environ.get('PH_FLEET_RR_ONLY', '').strip() in ('1', 'true', 'yes'):\n"
            "        rows, nl = [], []\n"
            "    else:\n"
            f"    PB.sh('gsutil', '-q', 'cp', '{m.group(1)}', 'need_list.jsonl')\n"
            + inner
        )
        src = src[: m.start()] + repl + src[m.end() :]

pat = re.compile(
    r"    RR\.clear\(\)\n"
    r"    for u in sorted\(x for x in PB\.sh\('gsutil', 'ls', '([^']+rerun_whole_\*\.txt)'\)\.stdout\.split\(\) if x\.endswith\('\.txt'\)\):\n"
    r"        tag = u\.rsplit\('/', 1\)\[-1\]\[:-4\]\n"
    r"        for h in _names\(u\): RR\.setdefault\(h, tag\)\n"
    r"    pl = _names\('([^']+priority_lastweek\.txt)'\)\n"
    r"    rest = \[h for h in dict\.fromkeys\(pl \+ nl\) if h not in have and h not in dq and h not in RR\]",
    re.M,
)
m = pat.search(src)
if not m:
    print("pdeep RR queue block not found", file=sys.stderr)
    sys.exit(1)
_rr_ls, _pl_path = m.group(1), m.group(2)
repl = f"""    RR.clear()
    # PDEEP_RR_ONLY_PATCH
    _rr_glob = '{_rr_ls}'
    _pl_path = '{_pl_path}'
    _rr_only = os.environ.get('PH_FLEET_RR_ONLY', '').strip() in ('1', 'true', 'yes')
    # PDEEP_COVERAGE_QUEUE
    _req_root = _rr_glob.split('rerun_whole_')[0]
    _cursor_root = (os.environ.get('PH_RR_CURSOR_GCS') or '').strip() or _req_root.replace('/population/requests/', '/_cursor/').replace('population/requests/', '_cursor/')
    _specs = [x.strip() for x in (os.environ.get('PH_RR_FILES') or os.environ.get('PH_RR_FILE') or '').split(',') if x.strip()]
    _flagged = set()
    _vmfl = (os.environ.get('PH_VM_FLAGGED_GCS') or '').strip() or (_cursor_root.rstrip('/') + '/vm_flagged.txt')
    _fr = PB.sh('gsutil', 'cat', _vmfl)
    if _fr.returncode == 0:
        _flagged = {{t.strip() for t in _fr.stdout.splitlines() if t.strip() and not t.lstrip().startswith('#')}}
    _vm_flagged = VM in _flagged
    _urls = []
    if _rr_only and _specs:
        for _spec in _specs:
            _fn = _spec.split('/')[-1]
            if _fn.startswith('fix_vmgate') and _vm_flagged:
                continue
            if _fn.startswith('fix_'):
                _urls.append(_cursor_root.rstrip('/') + '/' + _fn)
            elif _fn.endswith('.txt'):
                _urls.append(_req_root + _fn)
    elif _rr_only:
        _all = sorted(x for x in PB.sh('gsutil', 'ls', _rr_glob).stdout.split() if x.endswith('.txt'))
        _urls = [_all[-1]] if _all else []
    else:
        _urls = sorted(x for x in PB.sh('gsutil', 'ls', _rr_glob).stdout.split() if x.endswith('.txt'))
    for u in _urls:
        tag = u.rsplit('/', 1)[-1][:-4]
        for h in _names(u): RR.setdefault(h, tag)
    if _rr_only:
        rest = []
    else:
        pl = _names(_pl_path)
        rest = [h for h in dict.fromkeys(pl + nl) if h not in have and h not in dq and h not in RR]"""
src = pat.sub(repl, src, count=1)

# Do not merge new need_list rows mid-run while draining RR-only queue.
src = src.replace(
    "            if FULL and st[\"qi\"] and st[\"qi\"] % 500 == 0 and not st.get(\"rb_\" + str(st[\"qi\"])):  # 0225Z audit: pick up new need_list rows every 500 people\n"
    "                st[\"rb_\" + str(st[\"qi\"])] = 1; queue[st[\"qi\"]:] = [x for x in dict.fromkeys(queue[st[\"qi\"]:] + await asyncio.to_thread(_full_queue))]",
    "            if FULL and st[\"qi\"] and st[\"qi\"] % 500 == 0 and not st.get(\"rb_\" + str(st[\"qi\"])) and os.environ.get('PH_FLEET_RR_ONLY', '').strip() not in ('1', 'true', 'yes'):  # 0225Z audit: pick up new need_list rows every 500 people\n"
    "                st[\"rb_\" + str(st[\"qi\"])] = 1; queue[st[\"qi\"]:] = [x for x in dict.fromkeys(queue[st[\"qi\"]:] + await asyncio.to_thread(_full_queue))]",
    1,
)

p.write_text(src)
print("patched pdeep_rr_only")
