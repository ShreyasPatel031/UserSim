"""STACK-1b forward backer line (orchestrator 16:38Z Nov 26, ledger DEC-ORCH-STACK-DEPLOY; PREREG addendum 14; ledger STACK-FWD-1).

For PT launch day D (run ~01:50 PT, freeze before 03:30 PT):
  1. bench  = the latest simharness build (bench_v0/builds/latest, built ~02:22 PT the day before) + D's 00:05 line-up as overlay
              items (item_id = launch id; title = name, summary = tagline, tags = topic names, all scrub()bed), if the build does
              not already hold them.
  2. pool   = people with an endorsement in the build's active_days (60) window before D. No `require_observed` filter: that
              filter needs reads after the close, so it cannot be used forward (the backtest pool was ~4.6k/day, this ~10k).
  3. prompts: choice_ft1.Histories prefix(p, D) + launch(i) for every pool person x line-up launch (CHOICE-FT-1 format;
              parity with the FT1 eval prompts checked on 40 Nov 20 rows: identical).
  4. GPU    : simharness/finetune/gcp/launch.sh + startup_choice.sh, score-only with the CHOICE-FT-1 500k adapter
              (ckpt_final_500000), 1x A100 a2-highgpu-1g, spot first then standard, us-central1-f then -a; the VM deletes itself.
  5. stack  : logistic on standardised [ln_rw, tm, ln_rw_x_tm, logit p] with the frozen STACK-1 validation fit
              (tmp/e5/private/stack/stack_coef.json; refit on the same val pairs reproduced STACK-1's coefficients to 1e-3).
  6. freeze : top 2000 per launch, same schema as backer_pred_v2 -> tmp/e5/private/backer_pred_stack/<D>.parquet (PRIVATE,
              person ids as in the build), plus <D>_meta.json with predicted_at / freeze_deadline / before_0330_pt / cost.
    python stack_nightly.py D [--dry] [--test]   (--dry: prompts + features only; --test: no deadline, test paths; STACK_BUILD pins a build)
"""
import glob, json, os, subprocess, sys, time
import numpy as np, pandas as pd

D = [a for a in sys.argv[1:] if not a.startswith("--")][0]; DRY = "--dry" in sys.argv; TEST = "--test" in sys.argv   # --test: no deadline, writes backer_pred_stack_test/
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PRIV = f"{B}/tmp/e5/private"; PREFIX = f"{PRIV}/stack/{D}{'_test' if TEST else ''}"
CV = os.environ.get("FRESH_SIMHARNESS") or os.environ.get("STACK_CV"); sys.path.insert(0, CV)
W = os.path.join(os.environ.get("PU_WORK", "/tmp/pu"), f"stack_{D}"); os.makedirs(W, exist_ok=True)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
DEADLINE = pd.Timestamp(f"{D} 03:25", tz="America/Los_Angeles").tz_convert("UTC")
ADAPTER = f"{B}/simharness/choice_ft1/runs/choice-ft1-b/adapters/ckpt_final_500000"; MODEL = "Qwen/Qwen2.5-7B-Instruct"
TOPN, NFILES = 2000, 4
t0 = time.time(); log = lambda *a: print(f"[{pd.Timestamp.now(tz='UTC'):%H:%M:%S}]", *a, flush=True)

from simharness.bench import Benchmark, day_ord, scrub  # noqa: E402
from simharness.bench import KIND_CODE, ENDORSE  # noqa: E402
from simharness.finetune.choice_ft1 import Histories  # noqa: E402
from simharness.finetune.stack1 import feats  # noqa: E402

# 1. bench + overlay
stamp = os.environ.get("STACK_BUILD") or gcat(f"{B}/simharness/bench_v0/builds/latest").decode().strip(); bd = os.path.join(W, "build", stamp); os.makedirs(bd, exist_ok=True)
subprocess.run(["gsutil", "-m", "-q", "rsync", "-r", f"{B}/simharness/bench_v0/builds/{stamp}", bd], check=True)
LU = json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json") or b"[]")
if not LU: sys.exit(f"no 00:05 line-up for {D}")
def tags(r):
    t = r.get("topics"); t = __import__("ast").literal_eval(t) if isinstance(t, str) else t
    return [e["node"]["name"] for e in (t or {}).get("edges", [])]
ov = os.path.join(W, "overlay", D); os.makedirs(ov, exist_ok=True)
pd.DataFrame({"item_id": [str(r["id"]) for r in LU], "day": D, "title": [scrub(str(r["name"])) for r in LU],
              "summary": [scrub(str(r.get("tagline") or "")) for r in LU], "description": [scrub(str(r.get("description") or "")) for r in LU],
              "tags": [tags(r) for r in LU]}).to_parquet(f"{ov}/items.parquet")
pd.DataFrame({"person_idx": pd.Series([], dtype="int32"), "item_id": pd.Series([], dtype="str"), "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
              "text": pd.Series([], dtype="str")}).to_parquet(f"{ov}/comments.parquet")
b = Benchmark(bd); b.add_overlays([ov])
key = dict(zip(b.items["item_id"].astype(str), b.items["item_idx"])); items = np.array([key[str(r["id"])] for r in LU], np.int64)
ID = dict(zip(b.items["item_idx"], b.items["item_id"].astype(str)))
# 2. pool
e = b.hist[b.hist["kind"] == KIND_CODE[ENDORSE]]; o = day_ord(D)
pool = np.unique(e.loc[(e.day_ord >= o - b.cfg.active_days) & (e.day_ord < o), "person_idx"].to_numpy()).astype(np.int64)
log("build", stamp, "line-up", len(items), "pool", len(pool))
# 3. prompts
H = Histories(b); suff = [H.launch(int(i)) for i in items]
files = [os.path.join(W, f"fwd_{k:02d}.jsonl") for k in range(NFILES)]; fh = [open(f, "w") for f in files]
for k, p in enumerate(pool):
    fh[k % NFILES].write(json.dumps({"prefix": H.prefix(int(p), D), "suffixes": suff, "meta": {"day": D, "person_idx": int(p), "items": [int(i) for i in items]}}, ensure_ascii=False) + "\n")
for f in fh: f.close()
rows = pd.DataFrame({"day": D, "item_idx": np.tile(items, len(pool)), "person_idx": np.repeat(pool, len(items))})
meta = {"day": D, "build": stamp, "launches": int(len(items)), "pool": int(len(pool)), "pairs": int(len(rows)), "model": "STACK-1b forward",
        "adapter": ADAPTER, "prompt_build_s": round(time.time() - t0)}
log("prompts", meta)
if DRY:
    X = feats(b, rows, np.full(len(rows), 0.5)); log("dry: features ok", X.shape, bool(np.isfinite(X[:, :3]).all())); sys.exit(0)

# 4a. live BACKER-v2 decision values for STACK-v2's 5th input (CPU, runs while the GPU scores; PREREG 15, DEC-ORCH-STACK-V2-DEPLOY)
SD = os.path.join(W, "store"); os.makedirs(SD, exist_ok=True)
subprocess.run(["gsutil", "-q", "-m", "cp", f"{B}/raw/population/store_v3/persons.parquet", f"{B}/raw/population/store_v3/events.parquet", SD + "/"], check=True)
V2F = os.path.join(W, f"v2_{D}.parquet"); V2P = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_v2_scores.py"), SD, D, V2F])
# 4. GPU scoring (score-only; each file uploaded on its own so a preemption keeps the rest)
subprocess.run(["gsutil", "-q", "cp", f"{B}/simharness/choice_ft1/code/choice_lora.py", f"{PREFIX}/code/choice_lora.py"], check=True)
subprocess.run(["gsutil", "-q", "-m", "cp", *files, f"{PREFIX}/data/"], check=True)
names = " ".join(os.path.basename(f) for f in files); GS = os.path.join(CV, "simharness", "finetune", "gcp")
def launch(tag, prov, zone):
    env = {**os.environ, "FT_PREFIX": PREFIX, "FT_STARTUP": f"{GS}/startup_choice.sh", "FT_PROVISIONING": prov,
           "FT_NETWORK": os.environ.get("STACK_NETWORK", "main-vpc"), "FT_SUBNET": os.environ.get("STACK_SUBNET", "primary-subnet"), "FT_ADAPTER": ADAPTER, "FT_EXTRA_METADATA": f",ft_eval_file={names}"}
    r = subprocess.run(["bash", f"{GS}/launch.sh", tag, MODEL, "a2-highgpu-1g", zone, "1h"], env=env, capture_output=True, text=True)
    log("launch", tag, prov, zone, "rc", r.returncode, (r.stderr or r.stdout)[-300:].replace("\n", " ")); return r.returncode == 0
done = lambda tag: {os.path.basename(p) for p in subprocess.run(["gsutil", "ls", f"{PREFIX}/runs/{tag}/"], capture_output=True, text=True).stdout.split()}
want = {f"scores_{os.path.basename(f)}" for f in files}; tag = os.environ.get("STACK_REUSE_TAG"); t_gpu = time.time()   # reuse: scores already in runs/<tag>
for k, (prov, zone) in ([] if tag else enumerate((("SPOT", "us-central1-f"), ("SPOT", "us-central1-a"), ("STANDARD", "us-central1-f"), ("STANDARD", "us-central1-a")))):
    t = f"stackfwd-{D.replace('-', '')}{'t' if TEST else ''}-{k}"
    if launch(t, prov, zone): tag = t; break
if not tag: sys.exit("GPU: no A100 VM could be created")
while True:
    got = done(tag)
    if want <= got: break
    if "STATUS" in got and gcat(f"{PREFIX}/runs/{tag}/STATUS").strip() == b"failed": sys.exit("GPU job failed; see " + f"{PREFIX}/runs/{tag}/job.log")
    if pd.Timestamp.now(tz="UTC") > DEADLINE and not TEST: sys.exit(f"GPU scores not in by 03:25 PT ({sorted(got & want)} of {sorted(want)})")
    time.sleep(60)
gpu_min = round((time.time() - t_gpu) / 60, 1)
for f in want: subprocess.run(["gsutil", "-q", "cp", f"{PREFIX}/runs/{tag}/{f}", W], check=True)
# 5. stack
key2 = {(int(p), int(i)): k for k, (p, i) in enumerate(zip(rows.person_idx, rows.item_idx))}; pyes = np.full(len(rows), np.nan)
for f in want:
    for line in open(os.path.join(W, f)):
        r = json.loads(line); m = r["meta"]
        for i, s in zip(m["items"], r["p"]): pyes[key2[(int(m["person_idx"]), int(i))]] = s
assert np.isfinite(pyes).all(), f"{int(np.isnan(pyes).sum())} pairs without a score"
C = json.loads(gcat(f"{PRIV}/stack/stack_coef.json")); X = feats(b, rows, pyes)
z = ((X - np.array(C["mu"])) / np.array(C["sd"])) @ np.array(C["coef"]) + C["intercept"]; rows["p"] = 1 / (1 + np.exp(-z))
PID = pd.read_parquet(f"{bd}/people.parquet", columns=["person_idx", "person_id"]).set_index("person_idx").person_id.astype(str)
out = []
for i, g in rows.groupby("item_idx"):
    g = g.nlargest(TOPN, "p"); out.append(pd.DataFrame({"launch_id": ID[i], "person_id": PID.reindex(g.person_idx).to_numpy(), "p": g.p.to_numpy(),
                                                        "rank": np.arange(1, len(g) + 1), "day": D, "model": "stack1b (BACKER-v2 feats + CHOICE-FT-1 logit)",
                                                        "coef": json.dumps([round(x, 4) for x in C["coef"]])}))
FR = pd.concat(out, ignore_index=True)
for c in ("launch_id", "person_id", "day", "model", "coef"): FR[c] = FR[c].astype("string")
# 6. freeze
now = pd.Timestamp.now(tz="UTC"); dl = pd.Timestamp(f"{D} 03:30", tz="America/Los_Angeles").tz_convert("UTC")
usd = round(gpu_min / 60 * (2.204 if "SPOT" in tag or tag.endswith(("-0", "-1")) else 3.673), 3)
meta.update(predicted_at=now.isoformat(), freeze_deadline=dl.isoformat(), before_0330_pt=bool(now < dl), gpu_tag=tag, gpu_wall_min=gpu_min,
            gpu_usd_est=usd, cost_basis="a2-highgpu-1g wall time incl. setup x list price (spot $2.204/h, standard $3.673/h)", total_min=round((time.time() - t0) / 60, 1),
            rows_frozen=int(len(FR)), launches_frozen=int(FR.launch_id.nunique()))
p = os.path.join(W, f"{D}.parquet"); FR.to_parquet(p, index=False); mp = os.path.join(W, f"{D}_meta.json"); json.dump(meta, open(mp, "w"), indent=1)
subprocess.run(["gsutil", "-q", "cp", p, mp, f"{PRIV}/backer_pred_stack{'_test' if TEST else ''}/"], check=True)
log("FROZEN", json.dumps(meta))
# 7. STACK-v2 (published from 2026-11-28): the same rows restricted to people held before D's start, + the live BACKER-v2 decision value
rc = V2P.wait()
if rc != 0: sys.exit(f"FAIL live BACKER-v2 scores rc={rc}: STACK-v2 not frozen (STACK-1b shadow frozen above)")
V2 = pd.read_parquet(V2F); V2["launch_id"] = V2.launch_id.astype(str); V2["person_id"] = V2.person_id.astype(str)
rows["launch_id"] = rows.item_idx.map(ID); rows["person_id"] = PID.reindex(rows.person_idx).to_numpy(); rows["pyes"] = pyes
R2 = rows.merge(V2, on=["launch_id", "person_id"], how="inner").reset_index(drop=True)
C2 = json.loads(gcat(f"{PRIV}/stack_v2/stack_v2_coef.json")); X2 = np.column_stack([feats(b, R2[["day", "item_idx", "person_idx"]], R2.pyes.to_numpy()), R2.s_v2.to_numpy()])
R2["p"] = 1 / (1 + np.exp(-(((X2 - np.array(C2["mu"])) / np.array(C2["sd"])) @ np.array(C2["coef"]) + C2["intercept"])))
F2 = pd.concat([g.nlargest(TOPN, "p").assign(rank=lambda x: np.arange(1, len(x) + 1)) for _, g in R2.groupby("launch_id")], ignore_index=True)
F2 = F2[["launch_id", "person_id", "p", "rank"]].assign(day=D, model="stack_v2 (STACK-1b inputs + live BACKER-v2 score)", coef=json.dumps([round(x, 4) for x in C2["coef"]]))
for c in ("launch_id", "person_id", "day", "model", "coef"): F2[c] = F2[c].astype("string")
now2 = pd.Timestamp.now(tz="UTC")
m2 = {**meta, "model": "STACK-v2", "pairs_held_before_D": int(len(R2)), "people_held_before_D": int(R2.person_id.nunique()), "predicted_at": now2.isoformat(),
      "before_0330_pt": bool(now2 < dl), "rows_frozen": int(len(F2)), "launches_frozen": int(F2.launch_id.nunique()), "total_min": round((time.time() - t0) / 60, 1)}
p2 = os.path.join(W, f"v2list_{D}.parquet"); F2.to_parquet(p2, index=False); mp2 = os.path.join(W, f"v2list_{D}_meta.json"); json.dump(m2, open(mp2, "w"), indent=1)
dest = f"{PRIV}/backer_pred_stack_v2{'_test' if TEST else ''}"
subprocess.run(["gsutil", "-q", "cp", p2, f"{dest}/{D}.parquet"], check=True); subprocess.run(["gsutil", "-q", "cp", mp2, f"{dest}/{D}_meta.json"], check=True)
log("FROZEN_V2", json.dumps(m2))
