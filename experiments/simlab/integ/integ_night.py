"""Full-night integration dry run (orchestrator 19:31Z Nov 14). Private root, fake bucket (gsutil_stub.py), no VM, no new LLM calls.
Chain for night D, in VM order:
  A  today/<D> line-up -> forecast.py + h25_live (PH ops today-rows patch: features 033d7bd7, forecast, h25_live) -> results/forecast_D.parquet
     (VM upload emulated: raw/daily/D/forecast_D.parquet + today_0005.json)            mode fallback: H25_SRC empty -> arm 2 fails
  B  12a.2 two_predictions.py midnight D, then prereveal D (stored recorder file data/vote_snapshots/D.jsonl)
  C  vm_writers 12.2 tarball run.sh: prob_0005 D, prob_prereveal D, period D-1 (predicted entrants from D's parquet), track_record,
     period_score D-1 (TZ=America/Los_Angeles, USERSIM_CACHE, HOME private: tw.sh-like env)
Then silent-reuse probes: decoys for D-1 (and *_latest pointers) are planted, each input is deleted in turn and the downstream steps re-run.
    python integ_night.py <D> <normal|fallback> <workdir>       -> <workdir>/report.json"""
import json, os, re, shutil, subprocess, sys, glob
import pandas as pd
D, MODE, W = sys.argv[1:4]; SP = "/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad"
P1 = (pd.Timestamp(D) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"); HERE = os.path.dirname(os.path.abspath(__file__))
R = f"{SP}/a2rb/ph_predict_data"; PHO = f"{SP}/phops/experiments"; TGZ = os.environ.get("TGZ", f"{SP}/e5_vm_writers_12_2.tgz")
KEEP = f"{W}.forecast_cache"   # REUSE_A=1: reuse a finished forecast step for this night/mode (it takes ~10 min)
if os.environ.get("REUSE_A") != "1": shutil.rmtree(KEEP, ignore_errors=True)
shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
FB, BIN = f"{W}/fb", f"{W}/bin"; os.makedirs(FB); os.makedirs(BIN)
REAL = shutil.which("gsutil"); shutil.copy(f"{HERE}/gsutil_stub.py", f"{BIN}/gsutil")
ENV = {**os.environ, "PATH": f"{BIN}:" + os.environ["PATH"], "FB": FB, "REAL_GSUTIL": REAL, "FB_LOG": f"{W}/gsutil.log", "TZ": "America/Los_Angeles", "REAL_HOME": os.environ["HOME"]}
ENV.pop("VERCEL", None)
REP = {"day": D, "mode": MODE, "handoffs": {}, "probes": {}, "notes": []}
def sh(cmd, env=None, cwd=None, t=2400):
    r = subprocess.run(cmd, shell=True, env=env or ENV, cwd=cwd, capture_output=True, text=True, timeout=t); return r.returncode, (r.stdout + r.stderr)
def jl(p): return json.load(open(p)) if os.path.exists(p) else None
fbp = lambda rel: f"{FB}/{rel}"
LINEUP = [str(x["id"]) for x in json.load(open(f"{R}/today/{D}.json"))]

# ---------- A: forecast ----------
A = f"{W}/A"; os.makedirs(f"{A}/root/days"); os.makedirs(f"{A}/root/today"); os.makedirs(f"{A}/home/w/arm2_live"); os.makedirs(f"{A}/h25data"); os.makedirs(f"{A}/h25empty")
os.makedirs(f"{A}/code")
for f in glob.glob(f"{PHO}/ph_predict/*.py") + glob.glob(f"{SP}/a2rb/code/*.py"): shutil.copy(f, f"{A}/code/")
for f in ("features.py", "forecast.py"): shutil.copy(f"{PHO}/pipeline_patches/20261114_today_rows/{f}", f"{A}/code/")
shutil.copy(f"{PHO}/pipeline_patches/20261114_today_rows/h25_live.py", f"{A}/home/w/arm2_live/"); shutil.copy(f"{SP}/a2rb/code/history_retrain.py", f"{A}/home/w/arm2_live/")
for e in os.listdir(R):
    if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{R}/{e}", f"{A}/root/{e}")
for f in glob.glob(f"{R}/days/*.json"):
    if os.path.basename(f)[:10] < D: os.symlink(f, f"{A}/root/days/{os.path.basename(f)}")
for f in glob.glob(f"{R}/today/*.json"):
    if os.path.basename(f)[:10] <= D: os.symlink(f, f"{A}/root/today/{os.path.basename(f)}")
os.symlink(f"{A}/root", f"{A}/code/data"); os.makedirs(f"{A}/code/results")
def run_forecast():
    h25 = f"{A}/h25empty" if MODE == "fallback" else f"{SP}/rb/h25src"
    return sh(f"HOME={A}/home H25_DATA={A}/h25data H25_SRC={h25} LGB_THREADS=4 HF_HUB_OFFLINE=1 python forecast.py {D}", cwd=f"{A}/code", t=2400)
PQ = f"{A}/code/results/forecast_{D}.parquet"
if os.environ.get("REUSE_A") == "1" and os.path.exists(f"{KEEP}/forecast.parquet"):
    shutil.copy(f"{KEEP}/forecast.parquet", PQ); rc = 0; out = open(f"{KEEP}/forecast.log").read()
else:
    rc, out = run_forecast()
    if os.path.exists(PQ): os.makedirs(KEEP, exist_ok=True); shutil.copy(PQ, f"{KEEP}/forecast.parquet"); open(f"{KEEP}/forecast.log", "w").write(out)
open(f"{W}/A_forecast.log", "w").write(out)
def upload_vm():   # what the VM pipeline publishes after the forecast
    os.makedirs(fbp(f"raw/daily/{D}"), exist_ok=True)
    if os.path.exists(PQ): shutil.copy(PQ, fbp(f"raw/daily/{D}/forecast_{D}.parquet"))
    if os.path.exists(f"{R}/today/{D}.json"): shutil.copy(f"{R}/today/{D}.json", fbp(f"raw/daily/{D}/today_0005.json"))
upload_vm()
F = pd.read_parquet(PQ) if os.path.exists(PQ) else None
arm_line = [l for l in out.splitlines() if "arm2" in l.lower() and ("publish" in l.lower() or "fallback" in l.lower())][-1:] 
REP["handoffs"]["A lineup -> forecast parquet"] = h = {"rc": rc, "exists": F is not None, "log arm2 line": arm_line}
if F is not None:
    ids = F.id.astype(str).tolist()
    h.update({"day all D": bool((F.day.astype(str).str[:10] == D).all()), "rows / lineup": [len(F), len(LINEUP)], "ids == lineup": sorted(ids) == sorted(LINEUP),
              "pred_arm2 present": int(F.pred_arm2.notna().sum()), "expected arm2": MODE == "normal"})
    h["PASS"] = h["day all D"] and h["ids == lineup"] and ((h["pred_arm2 present"] == len(F)) if MODE == "normal" else h["pred_arm2 present"] == 0)

# ---------- B: two_predictions 12a.2 ----------
B = f"{W}/B"; shutil.copytree(f"{PHO}/pipeline_patches/20261114_two_predictions_12a2", f"{B}/tw", ignore=shutil.ignore_patterns("__pycache__", "out"))
PHD = f"{B}/ph"; os.makedirs(f"{PHD}/results"); os.makedirs(f"{PHD}/data/vote_snapshots")
src = open(f"{B}/tw/two_predictions.py").read(); assert 'PH = "/home/agent/w/experiments/ph_predict"' in src
open(f"{B}/tw/two_predictions.py", "w").write(src.replace('PH = "/home/agent/w/experiments/ph_predict"', f'PH = "{PHD}"'))
def stage_b_inputs(pq=True, rec=True):
    for f in glob.glob(f"{PHD}/results/forecast_{D}*") + glob.glob(f"{PHD}/data/vote_snapshots/{D}*") + glob.glob(f"/tmp/forecast_{D}.parquet"): os.remove(f)
    if pq and os.path.exists(PQ): shutil.copy(PQ, f"{PHD}/results/forecast_{D}.parquet")
    if rec and os.path.exists(f"{R}/vote_snapshots/{D}.jsonl"): shutil.copy(f"{R}/vote_snapshots/{D}.jsonl", f"{PHD}/data/vote_snapshots/{D}.jsonl")
def run_b(kind): return sh(f"python3 two_predictions.py {kind} {D}", cwd=f"{B}/tw")
stage_b_inputs()
ACC = {"os": os, "__file__": f"{B}/tw/two_predictions.py", "ZoneInfo": __import__("zoneinfo").ZoneInfo}; exec(src.split("zf = lambda")[0].split("from zoneinfo import ZoneInfo")[1], ACC)
for kind, fn in (("midnight", "0005"), ("prereveal", "prereveal")):
    rc, out = run_b(kind); open(f"{W}/B_{kind}.log", "w").write(out); J = jl(fbp(f"results/web/predictions/{D}_{fn}.json")); L = jl(fbp(f"results/web/predictions/{fn}_latest.json"))
    h = REP["handoffs"][f"B forecast{' + recorder' if kind == 'prereveal' else ''} -> {D}_{fn}.json"] = {"rc": rc, "exists": J is not None}
    if J:
        rid = [str(r["id"]) for r in J["ranking"]]
        h.update({"day": J["day"], "model": J["model"], "fallback_used": J["fallback_used"], "label": J["backtest"][:120], "rows": len(rid),
                  "ids == lineup": sorted(rid) == sorted(LINEUP), "ids missing / extra vs lineup": [len(set(LINEUP) - set(rid)), len(set(rid) - set(LINEUP))],
                  "latest pointer == this file": L == J, "inputs": J.get("inputs")})
        if kind == "midnight":
            want = "arm2" if MODE == "normal" else "clean_nosite"; col = "pred_arm2" if want == "arm2" else "pred"
            Fo = F.assign(id=F.id.astype(str)).sort_values([col, "id"], ascending=[False, True]).id.tolist()
            h.update({"expected model": want, "label == ACC0_BY[model]": J["backtest"] == ACC["ACC0_BY"][J["model"]], "order == parquet sort": rid == Fo})
            h["PASS"] = J["day"] == D and J["model"] == want and h["label == ACC0_BY[model]"] and h["ids == lineup"] and h["order == parquet sort"] and h["latest pointer == this file"]
        else:
            h.update({"label == acc1(model, fb)": J["backtest"] == ACC["acc1"](J["model"], J["fallback_used"], "arm2" if MODE == "normal" else "clean_nosite"),
                      "recorder read (PT)": J["inputs"].get("recorder_T")})
            h["PASS"] = J["day"] == D and h["label == acc1(model, fb)"] and h["latest pointer == this file"] and h["ids missing / extra vs lineup"] == [0, 0]

# ---------- C: vm_writers 12.2 ----------
C = f"{W}/C"; os.makedirs(f"{C}/home"); sh(f"tar xzf {TGZ} -C {C}")
os.makedirs(f"{C}/assets"); os.symlink(f"{SP}/a2x", f"{C}/assets/a2x"); os.symlink(f"{SP}/ph2025", f"{C}/assets/ph2025")
CENV = {**ENV, "ASSETS": f"{C}/assets", "LOG": f"{C}/writers.log", "USERSIM_CACHE": f"{W}/cache", "HOME": f"{C}/home"}
AUTHSYNC = re.compile(r"^(tmp/e5/vm_writers/assets/a2x/|raw/ph_history/2025/)")
def run_c(job, day=""):
    rc, out = sh(f"bash {C}/vm_writers/run.sh {job} {day}", env=CENV, t=1800); return rc, out
def pfile(kind): return jl(fbp(f"tmp/e5/website/probabilities/{D}_{kind}.json"))
def chain_c(tag):
    res = {}
    for job, day in (("prob_0005", D), ("prob_prereveal", D), ("period", P1), ("track_record", ""), ("period_score", P1)):
        rc, out = run_c(job, day); res[job] = {"rc": rc, "last": out.strip().splitlines()[-1][:300] if out.strip() else ""}
    open(f"{W}/C_{tag}.log", "w").write(json.dumps(res, indent=1)); return res
cres = chain_c("normal")
P0 = pfile("0005"); J0 = jl(fbp(f"results/web/predictions/{D}_0005.json"))
h = REP["handoffs"][f"C {D}_0005.json -> probabilities/{D}_0005.json"] = {"rc": cres["prob_0005"]["rc"], "exists": P0 is not None}
if P0 and J0:
    pid = [str(x["id"]) for x in P0.get("launches", [])]; rid = [str(r["id"]) for r in J0["ranking"]]
    h.update({"day": P0["day"], "status": P0["status"], "source": P0.get("source"), "method": P0.get("method"), "basis": P0.get("basis"), "basis_n_days": P0.get("basis_n_days"),
              "ids/order == published ranking": pid == rid, "rows": len(pid), "input_note": "input_note" in P0})
    want_m = "frozen logistic on score position" if J0["model"] == "arm2" else "rank table by position (published model not arm 2, or no scores)"
    h["method matches published model"] = P0.get("method") == want_m
    h["PASS"] = P0["day"] == D and pid == rid and h["method matches published model"] and f"model {J0['model']}" in str(P0.get("source"))
P3 = pfile("prereveal"); J3 = jl(fbp(f"results/web/predictions/{D}_prereveal.json"))
h = REP["handoffs"][f"C {D}_prereveal.json -> probabilities/{D}_prereveal.json"] = {"rc": cres["prob_prereveal"]["rc"], "exists": P3 is not None}
if P3 and J3:
    pid = [str(x["id"]) for x in P3.get("launches", [])]; rid = [str(r["id"]) for r in J3["ranking"]]
    h.update({"day": P3["day"], "status": P3["status"], "source": P3.get("source"), "names producing model": J3["model"] in json.dumps(P3), "ids/order == published": pid == rid})
    h["PASS"] = P3["day"] == D and pid == rid
PW = jl(fbp(f"tmp/e5/website/probabilities/{P1}_weekly.json")); PM = jl(fbp(f"tmp/e5/website/probabilities/{P1}_monthly.json"))
h = REP["handoffs"][f"C raw/daily/{D}/forecast parquet -> period {P1} (predicted entrants)"] = {"rc": cres["period"]["rc"], "weekly exists": PW is not None, "monthly exists": PM is not None}
for nm, X in (("weekly", PW), ("monthly", PM)):
    if X:
        s = json.dumps(X); h[nm] = {"day": X.get("day"), "entrants": {k: v for k, v in X.items() if "entrant" in k.lower()} if isinstance(X, dict) else None,
                                    "reads D parquet": f"raw/daily/{D}/forecast_{D}.parquet" in s, "names col": ("pred_arm2" in s) or ("clean_nosite" in s)}
TR = jl(fbp("tmp/e5/website/track_record_v1.json"))
h = REP["handoffs"]["C published files -> track_record_v1.json"] = {"rc": cres["track_record"]["rc"], "exists": TR is not None}
if TR:
    s = json.dumps(TR); rows = [r for r in (TR.get("rows") or TR.get("days") or []) if isinstance(r, dict) and r.get("day") == D] if isinstance(TR, dict) else []
    h.update({"rows for D": rows[:4], "mentions D": D in s})
REP["handoffs"]["C period_score " + P1] = {"rc": cres["period_score"]["rc"], "last": cres["period_score"]["last"][:200]}
json.dump(REP, open(f"{W}/report_chain.json", "w"), indent=1, default=str)

# ---------- silent-reuse probes ----------
def plant_decoys():
    """D-1 files and *_latest pointers that carry ids no real launch has (DECOY_*) and day D-1."""
    dec = lambda J: {**J, "day": P1, "ranking": [{**r, "id": "DECOY_" + str(r["id"])} for r in J.get("ranking", [])]}
    for fn in ("0005", "prereveal"):
        J = jl(fbp(f"results/web/predictions/{D}_{fn}.json"))
        if J:
            for nm in (f"{P1}_{fn}.json", f"{fn}_latest.json"): json.dump(dec(J), open(fbp(f"results/web/predictions/{nm}"), "w"))
    if F is not None:
        Fd = F.assign(id="DECOY_" + F.id.astype(str), day=P1); os.makedirs(fbp(f"raw/daily/{P1}"), exist_ok=True)
        Fd.to_parquet(fbp(f"raw/daily/{P1}/forecast_{P1}.parquet")); Fd.to_parquet(f"{PHD}/results/forecast_{P1}.parquet"); Fd.to_parquet(f"/tmp/forecast_{P1}.parquet")
    for f in glob.glob(f"{R}/vote_snapshots/{P1}.jsonl"):
        open(f"{PHD}/data/vote_snapshots/{P1}.jsonl", "w").write("".join(l.replace('"launch_id": "', '"launch_id": "DECOY_') for l in open(f)))
def scan(paths):
    hits = {}
    for p in paths:
        if os.path.exists(p):
            s = open(p, errors="ignore").read()
            if "DECOY_" in s: hits[p.replace(FB + "/", "")] = "contains D-1 decoy ids"
    return hits
OUTS = lambda: [fbp(f"results/web/predictions/{D}_0005.json"), fbp(f"results/web/predictions/{D}_prereveal.json"), fbp(f"tmp/e5/website/probabilities/{D}_0005.json"),
                fbp(f"tmp/e5/website/probabilities/{D}_prereveal.json"), fbp(f"tmp/e5/website/probabilities/{P1}_weekly.json"), fbp(f"tmp/e5/website/probabilities/{P1}_monthly.json")]
def summary():
    o = {}
    for k, p in (("0005", f"results/web/predictions/{D}_0005.json"), ("prereveal", f"results/web/predictions/{D}_prereveal.json"),
                 ("prob_0005", f"tmp/e5/website/probabilities/{D}_0005.json"), ("prob_prereveal", f"tmp/e5/website/probabilities/{D}_prereveal.json")):
        J = jl(fbp(p)); o[k] = None if J is None else {kk: (str(J.get(kk))[:110]) for kk in ("day", "model", "fallback_used", "status", "source", "backtest") if kk in J} | {"n": len(J.get("ranking", J.get("launches", [])) or [])}
    for nm in ("weekly", "monthly"):
        J = jl(fbp(f"tmp/e5/website/probabilities/{P1}_{nm}.json"))
        if J: o[f"period_{nm}"] = {k: str(v)[:160] for k, v in J.items() if "entrant" in k.lower() or k in ("day", "status")}
    return o
def rm(*rels):
    for r in rels:
        for p in glob.glob(r):
            if os.path.isdir(p): shutil.rmtree(p)
            elif os.path.exists(p): os.remove(p)
def reset_outputs():
    rm(fbp(f"results/web/predictions/{D}_*.json"), fbp(f"tmp/e5/website/probabilities/{D}_*.json"), fbp(f"tmp/e5/website/probabilities/{P1}_*.json"))
def rerun(b=True, c=True):
    if b: run_b("midnight"); run_b("prereveal")
    if c:
        for job, day in (("prob_0005", D), ("prob_prereveal", D), ("period", P1)): run_c(job, day)
def probe(name, setup, b=True):
    plant_decoys(); reset_outputs(); upload_vm(); stage_b_inputs(); setup(); rerun(b=b)
    REP["probes"][name] = {"outputs": summary(), "decoy ids found in": scan(OUTS())}
    print(json.dumps({"probe": name, "decoys": REP["probes"][name]["decoy ids found in"]}), flush=True)
probe("baseline (all inputs, decoys planted)", lambda: None)
probe("forecast parquet missing (VM results + raw/daily)", lambda: (rm(f"{PHD}/results/forecast_{D}.parquet", fbp(f"raw/daily/{D}/forecast_{D}.parquet"), f"/tmp/forecast_{D}.parquet")))
probe("recorder file missing", lambda: rm(f"{PHD}/data/vote_snapshots/{D}.jsonl"))
probe("forecast + recorder missing", lambda: rm(f"{PHD}/results/forecast_{D}.parquet", fbp(f"raw/daily/{D}/forecast_{D}.parquet"), f"/tmp/forecast_{D}.parquet", f"{PHD}/data/vote_snapshots/{D}.jsonl"))
def no_pub():
    rm(fbp(f"results/web/predictions/{D}_*.json"))
    for job, day in (("prob_0005", D), ("prob_prereveal", D)): run_c(job, day)
plant_decoys(); reset_outputs(); upload_vm(); stage_b_inputs(); run_b("midnight"); run_b("prereveal"); no_pub()
REP["probes"]["published prediction files missing (writers only)"] = {"outputs": summary(), "decoy ids found in": scan(OUTS())}
plant_decoys(); reset_outputs(); upload_vm(); stage_b_inputs(); run_b("midnight"); run_b("prereveal"); rm(fbp(f"results/web/predictions/{D}_*.json"), fbp(f"raw/daily/{D}"))
for job, day in (("prob_0005", D), ("prob_prereveal", D), ("period", P1)): run_c(job, day)
REP["probes"]["published files + raw/daily/D missing (writers only)"] = {"outputs": summary(), "decoy ids found in": scan(OUTS())}
# A with the line-up missing (the forecast step itself); SKIP_A_PROBE=1 skips it (re-runs of the writer stage only)
if os.environ.get("SKIP_A_PROBE") == "1": REP["probes"]["line-up today/D missing -> forecast"] = "skipped (SKIP_A_PROBE)"
else:
    rm(PQ); os.remove(f"{A}/root/today/{D}.json"); rc, out = run_forecast(); open(f"{W}/A_nolineup.log", "w").write(out)
    REP["probes"]["line-up today/D missing -> forecast"] = {"rc": rc, "parquet written": os.path.exists(PQ), "last lines": out.strip().splitlines()[-3:]}
REP["gsutil reads served from real bucket (non-chain paths)"] = sorted({json.loads(l)["path"] for l in open(f"{W}/gsutil.log") if json.loads(l)["src"] in ("real", "real-rsync") and json.loads(l)["path"]})[:40]
json.dump(REP, open(f"{W}/report.json", "w"), indent=1, default=str); print("done", flush=True)
