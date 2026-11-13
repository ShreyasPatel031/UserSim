"""Arm 2 of the 2025 retrain (orchestrator 04:39Z Nov 13): score llm_pitch and llm_brand on the 2025 rows with the exact 2026 prompts and
model (llm.py, Gemini 2.5 Flash, text only; brand gets site 'unknown' as for any launch without a resolved site). Cap: stops when
the estimated spend reaches CAP_USD (default 10). Never writes the pipeline's caches: in the private data dir (H25_DATA, built by
history_retrain.py) the llm_<mode>_gemini entries are replaced by real folders holding symlinks to the 2026 day files, and only the
new 2025 files are written there.
Then a leak check: Spearman of llm_pitch / llm_brand with final rank (within day, mean over days) on 2025 vs 2026 rows, and on
rows the model flags as known ("known": it recognises the product and how its launch went) vs not.
usage (VM, from ph_predict, after history_retrain.py has built H25_DATA): PYTHONPATH=~/w/mk:. python3 ~/w/h25/h25_llm.py [score|check|probe]
Arm 3 (ARM3=1, Nov 13): H25_DATA defaults to ~/w/h25/data_arm3 (built by ARM3=1 history_retrain.py --probe, which links the 2025, 2024
and 2023 lists); the private llm dirs there also link the 2025 scores already in the arm-2 dir (LLM_SEED, default ~/w/h25/data), so
only 2024 / 2023 days are new spend. score order: newest day first, pitch and brand per day, so a cap stop leaves whole recent days.
probe (memorisation check, run BEFORE the full score): scores PROBE_DAYS (default 12) evenly spaced days per old year (2025 days
come from the seed), then the leak check per year: within-day Spearman of llm_pitch / llm_brand with final rank on 2023 / 2024 /
2025 vs 2026 rows, day-bootstrap 95% interval of (old year - 2026). Flag LEAK if the lower bound of (year - 2026) is > PROBE_MARGIN
(default 0.05): the model ranks that year's launches better than it can rank unseen 2026 launches, i.e. it recalls outcomes; then do not
score that year (the arm-3 rows for it keep llm_* missing, as in arm 1)."""
import glob, json, os, sys
import numpy as np, pandas as pd
import features as F
ARM3 = os.environ.get("ARM3") == "1"
ROOT = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data_arm3" if ARM3 else "~/w/h25/data")); REAL = F.D
SEED = os.path.expanduser(os.environ.get("LLM_SEED", "~/w/h25/data" if ARM3 else ""))
CAP = float(os.environ.get("CAP_USD", "10"))


def private_llm_dirs():
    for mode in ("pitch", "brand"):
        p = f"{ROOT}/llm_{mode}_gemini"
        if os.path.islink(p):
            os.unlink(p)
        os.makedirs(p, exist_ok=True)
        seed = glob.glob(f"{SEED}/llm_{mode}_gemini/*.json") if SEED and os.path.realpath(SEED) != os.path.realpath(ROOT) else []
        for fn in glob.glob(f"{REAL}/llm_{mode}_gemini/*.json") + seed:
            dst = f"{p}/{os.path.basename(fn)}"
            if not os.path.exists(dst):
                os.symlink(os.path.realpath(fn), dst)


def score(only_days=None):
    private_llm_dirs(); F.D = ROOT
    import llm as L
    L.D = ROOT; assert os.path.realpath(f"{ROOT}/llm_pitch_gemini") != os.path.realpath(f"{REAL}/llm_pitch_gemini")
    df = F.build(); days = sorted((d for d in df.day.unique() if d < "2026-01-01"), reverse=True)
    if only_days is not None:
        days = [d for d in days if d in only_days]
    skip = {y for y in os.environ.get("SKIP_YEARS", "").split(",") if y}   # years the probe flagged LEAK
    days = [d for d in days if d[:4] not in skip]
    spent = lambda: L.USAGE["in"] / 1e6 * 0.30 + L.USAGE["out"] / 1e6 * 2.50
    for d in days:
        for mode in ("pitch", "brand"):
            if spent() >= CAP:
                print(json.dumps({"stopped": "cap", "usd": round(spent(), 3)}), flush=True); return
            L.run_day(d, df[df.day == d], mode)
    print(json.dumps({"done_days": len(days), "usd": round(spent(), 3), "tokens": L.USAGE}), flush=True)


def probe():
    """Memorisation probe: score PROBE_DAYS evenly spaced days per old year without a seed score, then the per-year leak check."""
    F.D = ROOT; df = F.build(); n = int(os.environ.get("PROBE_DAYS", "12")); pick = set()
    for y in sorted({d[:4] for d in df.day.unique() if d < "2026-01-01"}):
        dd = sorted(d for d in df.day.unique() if d[:4] == y)
        pick |= {dd[int(i)] for i in np.linspace(0, len(dd) - 1, min(n, len(dd)))}
    score(pick); check(probe=True)


def check(probe=False):
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
    res = {}; per = {}
    groups = [(y, df[df.day.str[:4] == y]) for y in sorted(set(df.day.str[:4]))]
    for mode in ("pitch", "brand"):
        for nm, g in groups:
            for kn in (None, True, False):
                h = g if kn is None else g[g.pitch_known == kn]
                r = [x.dropna()[mode].corr(-x.dropna().dailyRank, method="spearman") for _, x in h[[mode, "dailyRank", "day"]].groupby("day") if x[mode].notna().sum() >= 4]
                res[f"{mode}|{nm}|{'all' if kn is None else ('known' if kn else 'not_known')}"] = {"rho": round(float(np.nanmean(r)), 3) if r else None,
                                                                                                    "days": len(r), "rows": int(h[mode].notna().sum())}
                if kn is None:
                    per[(mode, nm)] = np.array(r)
    # memorisation probe: old year vs 2026, day-bootstrap interval of the difference in mean daily rho (unpaired: different days)
    rng = np.random.default_rng(0); margin = float(os.environ.get("PROBE_MARGIN", "0.05")); leak = {}
    for mode in ("pitch", "brand"):
        b26 = per.get((mode, "2026"))
        for nm, _ in groups:
            a = per.get((mode, nm))
            if nm >= "2026" or a is None or b26 is None or len(a) < 3 or len(b26) < 3:
                continue
            bs = [np.nanmean(a[rng.integers(0, len(a), len(a))]) - np.nanmean(b26[rng.integers(0, len(b26), len(b26))]) for _ in range(3000)]
            lo, hi = np.nanpercentile(bs, [2.5, 97.5]); flag = bool(lo > margin)
            res[f"probe|{mode}|{nm}-2026"] = {"diff": round(float(np.nanmean(a) - np.nanmean(b26)), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
                                              "days": len(a), "LEAK": flag}
            leak[nm] = leak.get(nm, False) or flag
    if leak:
        res["probe_verdict"] = {y: ("LEAK: do not score; SKIP_YEARS=" + y) if f else "ok" for y, f in sorted(leak.items())}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["check"])[0]
    {"score": score, "probe": probe, "check": check}[cmd]()
