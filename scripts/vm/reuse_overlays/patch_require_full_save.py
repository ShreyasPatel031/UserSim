#!/usr/bin/env python3
"""Do not upload out/<h>.json unless coverage passes whole-person gate (fleet rule)."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "REQUIRE_FULL_SAVE_PATCH" in src:
    print("require_full_save already patched")
    sys.exit(0)

helper = '''
def _full_enough_for_save(cv, res):
    # REQUIRE_FULL_SAVE_PATCH
    if os.environ.get("PH_REQUIRE_FULL_SAVE", "1").strip().lower() in ("0", "false", "no"):
        return True
    min_hdr = float(os.environ.get("PH_MIN_HEADER_PCT", "98") or 98)
    min_tab = float(os.environ.get("PH_MIN_TAB_PCT", "95") or 95)
    if float((cv or {}).get("header_pct") or 0) < min_hdr:
        return False
    if (res or {}).get("truncated_budget"):
        return False
    for k, tab in ((cv or {}).get("tabs") or {}).items():
        if not isinstance(tab, dict):
            continue
        st = tab.get("status") or ""
        if st == "partial":
            return False
        pct = tab.get("pct")
        if pct is not None and float(pct) < min_tab and st != "complete_not_visible":
            return False
        hdr, got = tab.get("header"), tab.get("got")
        if hdr and got is not None and float(got) < 0.95 * float(hdr) and st != "complete_not_visible":
            return False
    return True
'''

needle = """            cv = coverage(res); json.dump(res, open(f'out/{h}.json', 'w'), indent=1, ensure_ascii=False)
            row = dict(handle=h, rc=0, method="reuse_browser_v1", secs=secs, bytes=b, mb=round(b / 1e6, 2), gql=res["run"]["gql_calls"], html=res["run"]["html_fetches"], navs=res["run"]["thread_navs"],
                       header_pct=cv["header_pct"], header_items=cv["header_items"], coverage=cv["tabs"], fill=cv["field_fill_pct"], block_lines=0, port=int(os.environ.get('PROXY_PORT', 0)))
            sh('gsutil', '-q', 'cp', f'out/{h}.json', f'{B}/{h}.json'); sh('gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')"""

repl = """            cv = coverage(res); json.dump(res, open(f'out/{h}.json', 'w'), indent=1, ensure_ascii=False)
            # REQUIRE_FULL_SAVE_PATCH
            if not _full_enough_for_save(cv, res):
                S.put(handle=h, event="incomplete_skip_upload", header_pct=cv.get("header_pct"), coverage=cv.get("tabs"), note="whole-person gate: no gs:// upload", port=int(os.environ.get('PROXY_PORT', 0)))
                deep_add(h, 'incomplete_coverage', list((cv.get("tabs") or {}).keys()), {}, {})
                sh('gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log'); sh('gsutil', '-q', 'rm', f'{B}/claims/{h}')
                i += 1; consec_err = 0; continue
            row = dict(handle=h, rc=0, method="reuse_browser_v1", secs=secs, bytes=b, mb=round(b / 1e6, 2), gql=res["run"]["gql_calls"], html=res["run"]["html_fetches"], navs=res["run"]["thread_navs"],
                       header_pct=cv["header_pct"], header_items=cv["header_items"], coverage=cv["tabs"], fill=cv["field_fill_pct"], block_lines=0, port=int(os.environ.get('PROXY_PORT', 0)))
            sh('gsutil', '-q', 'cp', f'out/{h}.json', f'{B}/{h}.json'); sh('gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')"""

if needle not in src:
    print("save/upload block not found", file=sys.stderr)
    sys.exit(1)

# Insert helper before async def pull or before coverage(
if "def _full_enough_for_save" not in src:
    anchor = "def coverage(res):"
    if anchor not in src:
        print("coverage() anchor missing", file=sys.stderr)
        sys.exit(1)
    src = src.replace(anchor, helper + "\n" + anchor, 1)

src = src.replace(needle, repl, 1)
p.write_text(src)
print("patched require_full_save")
