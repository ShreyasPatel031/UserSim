#!/usr/bin/env python3
"""repullupvotes: read/write complete person from SB; stamp refresh metadata for Population merge."""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "REPULL_UPVOTES_STAGING_PATCH" in src:
    print("repull_upvotes_staging already patched")
    sys.exit(0)

# Load existing complete person from staging (Population merge path), not VM root.
old_read = "p0 = pages[0]; res = json.loads(sh('gsutil', 'cat', f'{B}/{handle}.json').stdout)"
new_read = "p0 = pages[0]; _src = f'{SB}/{handle}.json' if gexists(f'{SB}/{handle}.json') else f'{B}/{handle}.json'; res = json.loads(sh('gsutil', 'cat', _src).stdout)  # REPULL_UPVOTES_STAGING_PATCH"
idx = src.find("async def pull_upvotes")
if idx < 0:
    print("pull_upvotes not found", file=sys.stderr)
    sys.exit(1)
sub = src[idx:]
if old_read not in sub:
    print("pull_upvotes read line not found", file=sys.stderr)
    sys.exit(1)
sub = sub.replace(old_read, new_read, 1)
src = src[:idx] + sub

# Backups and list bootstrap: use SB for person JSON.
old_bak = "            if not gexists(f'{h}.json.bak_preupvotesrepull'): sh('gsutil', '-q', 'cp', f'{B}/{h}.json', f'{B}/{h}.json.bak_preupvotesrepull')"
new_bak = """            if not gexists(f'{h}.json.bak_preupvotesrepull'):
                _from = f'{SB}/{h}.json' if gexists(f'{SB}/{h}.json') else f'{B}/{h}.json'
                sh('gsutil', '-q', 'cp', _from, f'{SB}/{h}.json.bak_preupvotesrepull')  # REPULL_UPVOTES_STAGING_PATCH"""
if old_bak not in src:
    print("repullupvotes backup block not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_bak, new_bak, 1)

stamp = """    res["upvotes_refreshed_at"] = now()  # REPULL_UPVOTES_STAGING_PATCH
    res["upvotes_refreshed_by"] = VM  # UPVOTES_REFRESH_ATTRIBUTION_PATCH
    try:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("_eiu", "/opt/ph/overlays/exit_ip_util.py")
        _mod = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_mod)
        res["upvotes_refreshed_exit_ip"] = (_mod.exit_info() or {}).get("exit_ip")
    except Exception:
        res["upvotes_refreshed_exit_ip"] = None
    _items_added = max(0, len(ups) - len(old))
    res.setdefault("upvotes", {})["refresh"] = {"read_utc": now(), "delta": {"items_before": len(old), "items_after": len(ups), "items_added": _items_added}}
    _prior_fin = (res.get("run") or {}).get("finished_utc")
    res.setdefault("run", {})["finished_utc"] = now()
    if _prior_fin and _prior_fin != res["run"]["finished_utc"]:
        res["run"]["finished_utc_prior_pull"] = _prior_fin"""
needle = '    res.setdefault("run", {})["timing"] = timing; res["run"]["upvotes_repulled"] = {"utc": now(), "requests": R.reqs, "ended": ended}'
if needle not in src:
    print("upvotes_repulled line not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(needle, needle + "\n" + stamp, 1)

# Whole-person gate: upvote-only refresh must upload merged complete JSON.
helper_needle = "def _full_enough_for_save(cv, res):"
if helper_needle in src and "REPULL_UPVOTES_STAGING_PATCH" not in src.split(helper_needle, 1)[1][:400]:
    src = src.replace(
        helper_needle,
        helper_needle + """
    # REPULL_UPVOTES_STAGING_PATCH
    if (res or {}).get("run", {}).get("upvotes_repulled"):
        return True
""",
        1,
    )

p.write_text(src)
print("patched repull_upvotes_staging")