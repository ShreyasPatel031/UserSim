"""Arm 2 of the 2025 retrain (orchestrator 04:39Z Nov 13): score llm_pitch and llm_brand on the 2025 rows with the exact 2026 prompts and
model (llm.py, Gemini 2.5 Flash, text only; brand gets site 'unknown' as for any launch without a resolved site). Cap: stops when
the estimated spend reaches CAP_USD (default 10). Never writes the pipeline's caches: in the private data dir (H25_DATA, built by
history_retrain.py) the llm_<mode>_gemini entries are replaced by real folders holding symlinks to the 2026 day files, and only the
new 2025 files are written there.
Then a leak check: Spearman of llm_pitch / llm_brand with final rank (within day, mean over days) on 2025 vs 2026 rows, and on
rows the model flags as known ("known": it recognises the product and how its launch went) vs not.
usage (VM, from ph_predict, after history_retrain.py has built H25_DATA): PYTHONPATH=~/w/mk:. python3 ~/w/h25/h25_llm.py [score|check]"""
import glob, json, os, sys
import numpy as np, pandas as pd
import features as F
ROOT = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data")); REAL = F.D
CAP = float(os.environ.get("CAP_USD", "10"))


def private_llm_dirs():
    for mode in ("pitch", "brand"):
        p = f"{ROOT}/llm_{mode}_gemini"
        if os.path.islink(p):
            os.unlink(p)
        os.makedirs(p, exist_ok=True)
        for fn in glob.glob(f"{REAL}/llm_{mode}_gemini/*.json"):
            dst = f"{p}/{os.path.basename(fn)}"
            if not os.path.exists(dst):
                os.symlink(fn, dst)


def score():
    private_llm_dirs(); F.D = ROOT
    import llm as L
    L.D = ROOT; assert os.path.realpath(f"{ROOT}/llm_pitch_gemini") != os.path.realpath(f"{REAL}/llm_pitch_gemini")
    df = F.build(); days = sorted(d for d in df.day.unique() if d < "2026-01-01")
    spent = lambda: L.USAGE["in"] / 1e6 * 0.30 + L.USAGE["out"] / 1e6 * 2.50
    for mode in ("pitch", "brand"):
        for d in days:
            if spent() >= CAP:
                print(json.dumps({"stopped": "cap", "usd": round(spent(), 3)}), flush=True); return
            L.run_day(d, df[df.day == d], mode)
    print(json.dumps({"done_days": len(days), "usd": round(spent(), 3), "tokens": L.USAGE}), flush=True)


def check():
    out = {}
    for mode in ("pitch", "brand"):
        S = {}
        for fn in glob.glob(f"{ROOT}/llm_{mode}_gemini/*.json"):
            for k, v in json.load(open(fn)).items():
                if isinstance(v, dict):
                    S[str(k)] = (v.get("score"), bool(v.get("known")))
        out[mode] = S
    F.D = ROOT; df = F.build(); df["id"] = df.id.astype(str); df = df[df.dailyRank.notna()]
    for mode in ("pitch", "brand"):
        df[mode] = df.id.map({k: v[0] for k, v in out[mode].items()}); df[mode + "_known"] = df.id.map({k: v[1] for k, v in out["pitch"].items()})
    res = {}
    for mode in ("pitch", "brand"):
        for nm, g in (("2025", df[df.day < "2026-01-01"]), ("2026", df[df.day >= "2026-01-01"])):
            for kn in (None, True, False):
                h = g if kn is None else g[g.pitch_known == kn]
                r = [x.dropna()[mode].corr(-x.dropna().dailyRank, method="spearman") for _, x in h[[mode, "dailyRank", "day"]].groupby("day") if x[mode].notna().sum() >= 4]
                res[f"{mode}|{nm}|{'all' if kn is None else ('known' if kn else 'not_known')}"] = {"rho": round(float(np.nanmean(r)), 3) if r else None,
                                                                                                    "days": len(r), "rows": int(h[mode].notna().sum())}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    score() if sys.argv[1:] == ["score"] else check()
