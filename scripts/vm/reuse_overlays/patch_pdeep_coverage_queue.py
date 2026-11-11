#!/usr/bin/env python3
"""RR-only multi-file queue: Population fix lists (_cursor) then overnight rerun file; vmgate on clean VMs."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/pdeep.py")
if not p.exists():
    print("pdeep.py missing; skip")
    sys.exit(0)
src = p.read_text()
if "PDEEP_COVERAGE_QUEUE" in src:
    print("coverage_queue already patched")
    sys.exit(0)
if "PDEEP_RR_ONLY_PATCH" not in src:
    print("run patch_pdeep_rr_only first", file=sys.stderr)
    sys.exit(1)

old = """    _rrf = (os.environ.get('PH_RR_FILE') or '').strip()
    if _rr_only and _rrf:
        _fn = _rrf.split('/')[-1]
        _base = _rr_glob.split('rerun_whole_')[0]
        _urls = [_base + _fn] if _fn.endswith('.txt') else []
    elif _rr_only:
        _all = sorted(x for x in PB.sh('gsutil', 'ls', _rr_glob).stdout.split() if x.endswith('.txt'))
        _urls = [_all[-1]] if _all else []
    else:
        _urls = sorted(x for x in PB.sh('gsutil', 'ls', _rr_glob).stdout.split() if x.endswith('.txt'))"""

new = """    # PDEEP_COVERAGE_QUEUE
    _req_root = _rr_glob.split('rerun_whole_')[0]
    _cursor_root = (os.environ.get('PH_RR_CURSOR_GCS') or '').strip() or _req_root.replace('/population/requests/', '/_cursor/').replace('population/requests/', '_cursor/')
    _specs = [x.strip() for x in (os.environ.get('PH_RR_FILES') or os.environ.get('PH_RR_FILE') or '').split(',') if x.strip()]
    _flagged = set()
    _vmfl = (os.environ.get('PH_VM_FLAGGED_GCS') or '').strip() or (_cursor_root.rstrip('/') + '/vm_flagged.txt')
    _fr = PB.sh('gsutil', 'cat', _vmfl)
    if _fr.returncode == 0:
        _flagged = {t.strip() for t in _fr.stdout.splitlines() if t.strip() and not t.lstrip().startswith('#')}
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
        _urls = sorted(x for x in PB.sh('gsutil', 'ls', _rr_glob).stdout.split() if x.endswith('.txt'))"""

if old not in src:
    print("RR url block not found for upgrade", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(old, new, 1))
print("patched coverage_queue")
