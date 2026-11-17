"""How optimistic is the backtest's view of day d? (orchestrator 12:44Z Nov 17). Counts and launch ids only.
For each day d with a held 00:05 line-up (data/today/<d>.json) and a re-read day file (data/days/<d>.json), a private data root holds the
2026 day files < d + the 2025 lists (training, identical in every view) and ONE test view of day d:
  V0 asof      today/<d>.json as captured at 00:05
  V1 +text     V0 records with name / tagline / description / topics taken from the re-read (launches present at 00:05 only)
  V2 +makers   V1 + makers from the re-read
  V3 +hunter   V2 + user (hunter profile) from the re-read
  V4 +rest     the re-read record for every launch present at 00:05 (media, website, counts ...); still the 00:05 line-up
  V5 reread    days/<d>.json as a test day (the backtest condition: final line-up incl. launches added after 00:05)
Steps V0->V4 change content only; V4->V5 is the line-up (added / removed launches) plus day-file vs today-file handling.
Models: arm 2 = h25_live (old-row rules, no named-maker inputs, no llm_site / ph_month, 5 seeds P_); arm 3 = arm 2 + arm3_feats A/B/C
(norm strong, A over the test view's line-up). Same training rows and seeds in every view. Score: top 3/5/10 vs the final daily rank of
the re-read day file; launches absent from a view cannot be picked.
    usage: python opt.py <out dir> <day> ...   env: H25_SRC, ROOTS, EMB, EMB_IDS"""
import glob, json, os, shutil, sys, time
os.environ.setdefault("LGB_THREADS", "2")
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN, history_retrain as HR, arm3_feats as A3
REAL = os.path.abspath(F.D); H25 = os.environ["H25_SRC"]; OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers"); ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
CE = np.load(os.environ["EMB"]); CI = list(pd.read_parquet(os.environ["EMB_IDS"]).id.astype(str)); CM = dict(zip(CI, range(len(CI))))
STEPS = {"V1_text": ("name", "tagline", "description", "topics"), "V2_makers": ("makers",), "V3_hunter": ("user",)}

def make_root(d, view, recs=None):
    r = f"{os.environ['ROOTS']}/{d}_{view}"; shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{REAL}/{e}", f"{r}/{e}")
    for fn in glob.glob(f"{REAL}/days/*.json"):
        b = os.path.basename(fn)[:10]
        if b < d or (view == "V5_reread" and b == d): os.symlink(fn, f"{r}/days/{os.path.basename(fn)}")
    for fn in glob.glob(f"{H25}/*.json"): os.symlink(os.path.abspath(fn), f"{r}/days/{os.path.basename(fn)}")
    if recs is not None: json.dump(recs, open(f"{r}/today/{d}.json", "w"))
    return r

def run_view(d, view, recs):
    F.D = make_root(d, view, recs)
    try: df = RN.load_llm(F.build(include_today=view != "V5_reread"))
    finally: F.D = REAL
    df["id"] = df.id.astype(str); old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    df = df[~df.known].reset_index(drop=True)
    tod = ((df.day == d) & (df.is_today if view != "V5_reread" else ~df.is_today)).values
    df = df[tod | ((df.day < d) & ~df.is_today).values].reset_index(drop=True); tod = (df.day == d).values
    E = np.zeros((len(df), 384), np.float32); have = np.array([(i in CM) and not t for i, t in zip(df.id, tod)])
    E[have] = CE[[CM[i] for i in df.id[have]]]; E[~have] = A3.embed(A3.text_of(df[~have]))
    X, NEW = A3.add_feats(df, E, norm="strong", line_up=tod)
    tr, te = X[~tod], X[tod].copy(); tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    base = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")]
    o = te[["id"]].copy(); o["day"], o["view"] = d, view
    for nm, cc in (("arm2", base), ("arm3", base + NEW)):
        o[nm] = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, **P_).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], axis=0)
    o["n_inputs_arm2"] = len(base); return o

for d in sys.argv[2:]:
    t0 = time.time(); fa, fb = f"{REAL}/today/{d}.json", f"{REAL}/days/{d}.json"
    if not (os.path.exists(fa) and os.path.exists(fb)): print(json.dumps({"day": d, "skipped": "missing view"})); continue
    A = json.load(open(fa)); Bm = {r["id"]: r for r in json.load(open(fb))}
    views = {"V0_asof": A}; cur = [dict(r) for r in A]
    for v, fields in STEPS.items():
        cur = [dict(r, **{f: Bm[r["id"]][f] for f in fields if f in Bm.get(r["id"], {})}) if r["id"] in Bm else dict(r) for r in cur]; views[v] = cur
    views["V4_rest"] = [Bm.get(r["id"], r) for r in A]; views["V5_reread"] = None
    outs = [run_view(d, v, recs) for v, recs in views.items()]
    P = pd.concat(outs); P.to_parquet(f"{OUT}/{d}.parquet")
    print(json.dumps({"day": d, "n_asof": len(A), "n_reread": len(Bm), "added": len(set(Bm) - {r["id"] for r in A}), "removed": len({r["id"] for r in A} - set(Bm)),
                      "seconds": round(time.time() - t0)}), flush=True)
