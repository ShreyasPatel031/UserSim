"""Forward shadow table rebuilt on fixed inputs (orchestrator 17:34Z Nov 14). Scratch only; ids and scores, no names; nothing live is written.
For each night d (today/<d>.json exists, Oct 26 - Nov 13), as of that night: days/ <= d-2, and
  MODE=polluted: every today/ file dated <= d, features.py 981c5ded (what the shadows saw);  MODE=fixed: today/<d> only, 033d7bd7.
Runs the shadow scripts' own main(d) (makerfix_shadow: unfixed / makerfix / clean / clean_nosite / clean_avg; h25_shadow: h25 / h25llm = arm 2 /
pure; readable_shadow: readable v2) with F.D = the scratch root, RN.OUT = <out>/<MODE> and H25_DATA = a fresh scratch root, so every
write lands in scratch. F.build is memoised per (root, include_today) within a night (identical calls, copies returned).
usage (VM, cwd ~/w/experiments/ph_predict): MODE=fixed PYTHONPATH=<features dir>:$HOME/w/mk:.:$HOME/w/h25 H25_SRC=~/w/ph_history/2025 \
  python3 shadow_rebuild.py <scratch dir> <out dir> [first] [last]"""
import json, os, shutil, sys, time
import pandas as pd
import features as F, run as RN
MODE = os.environ["MODE"]; T, OUT = sys.argv[1], sys.argv[2]; first = sys.argv[3] if len(sys.argv) > 3 else "2026-10-26"
last = sys.argv[4] if len(sys.argv) > 4 else "2026-11-13"; REAL = os.path.realpath("data"); t0 = time.time()
print("features from", os.path.realpath(F.__file__), flush=True)
_b = F.build; _cache = {}
def build(include_today=False):
    k = (F.D, include_today)
    if k not in _cache: _cache[k] = _b(include_today=include_today)
    return _cache[k].copy()
F.build = build
import makerfix_shadow as MS, h25_shadow as HS, readable_shadow as RS
RN.OUT = f"{OUT}/{MODE}"; os.makedirs(RN.OUT, exist_ok=True)
for mod in (MS, HS, RS):
    if hasattr(mod, "RN"): mod.RN.OUT = RN.OUT
nights = sorted(f[:10] for f in os.listdir(f"{REAL}/today") if first <= f[:10] <= last)
for d in nights:
    cut = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d"); r = f"{T}/sr_{MODE}_{d}"; r2 = f"{T}/sr25_{MODE}_{d}"
    for x in (r, r2): shutil.rmtree(x, ignore_errors=True)
    os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(os.path.realpath(f"{REAL}/{e}"), f"{r}/{e}")
    for fn in os.listdir(f"{REAL}/days"):
        if fn[:10] <= cut: os.symlink(os.path.realpath(f"{REAL}/days/{fn}"), f"{r}/days/{fn}")
    for fn in os.listdir(f"{REAL}/today"):
        if (fn[:10] <= d) if MODE == "polluted" else (fn[:10] == d): os.symlink(os.path.realpath(f"{REAL}/today/{fn}"), f"{r}/today/{fn}")
    F.D = r; os.environ["H25_DATA"] = r2; _cache.clear(); st = {}
    for nm, mod in (("makerfix", MS), ("h25", HS), ("readable", RS)):
        F.D = r
        try: mod.main(d); st[nm] = "ok"
        except Exception as e: st[nm] = f"{type(e).__name__}: {str(e)[:120]}"
    F.D = REAL
    for x in (r, r2): shutil.rmtree(x, ignore_errors=True)
    print(json.dumps({"night": d, "mode": MODE, "status": st, "seconds": round(time.time() - t0)}), flush=True)
