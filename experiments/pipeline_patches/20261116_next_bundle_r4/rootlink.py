"""One shared builder for the private data roots (~/w/h25/data, ~/w/h25/data_arm3) used by arm 2, arm 3 and the 2025 shadows
(stale-input audit, orchestrator 01:37Z Nov 15). Every root-builder calls link_root(real, root, extra_day_files) on every run:
  - a top-level entry of the real data dir that the root lacks -> symlink (as before)
  - a REAL directory in the root (e.g. llm_*_gemini, made by h25_llm.py to hold 2025 scores) -> every file of the matching real
    directory that it lacks is linked in, so a new day's file is visible (the llm_pitch / llm_brand bug of Nov 14)
  - a broken symlink (target gone) is replaced when the target exists again, else left alone and counted (never crashes the run)
  - days/: every real day file and every extra day file (2025 / 2024 / 2023 lists) is linked if missing or broken
Returns counts; never deletes a real file."""
import glob, os


def _link(src, dst, n):
    if os.path.islink(dst) and not os.path.exists(dst):
        if os.path.exists(src):
            os.unlink(dst); os.symlink(src, dst); n["relinked_broken"] += 1
        else:
            n["broken_left"] += 1
    elif not os.path.lexists(dst):
        os.symlink(src, dst); n["linked"] += 1


def link_root(real, root, extra_day_files=()):
    n = {"linked": 0, "relinked_broken": 0, "broken_left": 0, "files_into_real_dirs": 0}
    os.makedirs(f"{root}/days", exist_ok=True)
    for e in os.listdir(real):
        if e == "days" or e.startswith("build_cache"):
            continue
        rp, dp = f"{real}/{e}", f"{root}/{e}"
        if os.path.isdir(dp) and not os.path.islink(dp) and os.path.isdir(rp):
            before = n["linked"]
            for fn in os.listdir(rp):
                _link(f"{rp}/{fn}", f"{dp}/{fn}", n)
            n["files_into_real_dirs"] += n["linked"] - before
        else:
            _link(rp, dp, n)
    for fn in glob.glob(f"{real}/days/*.json") + list(extra_day_files):
        _link(os.path.abspath(fn), f"{root}/days/{os.path.basename(fn)}", n)
    return n
