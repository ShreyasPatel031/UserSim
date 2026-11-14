"""Input guards for the 00:05 forecast (UNDEPLOYED; next bundle, deploy only on Shreyas's direct word).

Why (orchestrator 12:17Z Nov 14, measured on the 214-day arm-2 backtest with inputs blanked at inference, top 3):
  hunter history missing -6.7 [-9.3, -4.0]; llm_pitch/llm_brand missing -3.0 [-5.1, -0.8]; promo -1.9; busy -1.7; site -0.6.

What it does (all called from forecast.py; nothing here changes the model):
  1. store_check(day)   the day store (data/days) must hold the normal lag: files through day-2 (the ranks step writes
                        day-1 only AFTER the forecast). If day files are missing in the last LOOKBACK days, it builds an
                        overlay store (symlinks to the real files + missing day files copied from the bucket's daily store
                        copy, else the newest arm-2 inputs backup) and points features.D at it, so hunters do not look new.
                        It never writes into the real store.
  2. llm_check(day, g)  every launch must have llm_pitch and llm_brand. Missing launches (file absent, bad JSON, id absent,
                        NaN) are re-scored for the missing subset only, with backoff, until the deadline; the result is
                        merged into the day file. Launches still missing are recorded.
  3. coverage(te)       alert-only: share of today's launches with any promo_ / busy_ / site input.
  finish(day)           writes results/forecast_inputs_<day>.json (the published file's inputs block reads it), prints
                        "INPUT ALERT ..." lines, uploads the alert file to <BUCKET>/alerts/ when there is an alert.
No handles or names are written: counts and launch ids only.
"""
import datetime as dt
import glob
import json
import math
import os
import shutil
import subprocess
import tempfile
import time

import features as F

BUCKET = os.environ.get("USERSIM_BUCKET", "gs://usersim-bakeoff-347838016394/usersim_sim")
STORE_COPY = os.environ.get("GUARD_STORE_COPY", f"{BUCKET}/raw/store/days")            # written daily by the raw step (this bundle)
ARM2_BACKUPS = os.environ.get("GUARD_ARM2_BACKUPS", f"{BUCKET}/raw/model_inputs/arm2")  # <yyyymmdd>/ph_predict_data/days/
LOOKBACK = int(os.environ.get("GUARD_LOOKBACK_DAYS", "14"))
LLM_BACKOFF = [int(x) for x in os.environ.get("GUARD_LLM_BACKOFF", "20,60,180").split(",")]
LLM_BUDGET_S = int(os.environ.get("GUARD_LLM_BUDGET_S", "420"))   # the published file must not slip past ~00:20 PT
COVER_MIN = float(os.environ.get("GUARD_COVER_MIN", "0.5"))
# persistent (not /tmp): h25_live.py symlinks F.D/days/* into ~/w/h25/data/days and keeps those links across runs, so a
# restored file must outlive this run or the next arm-2 run hits a dangling link (os.symlink FileExistsError)
RESTORE = os.path.expanduser(os.environ.get("GUARD_RESTORE_DIR", "~/w/guard_restore"))
LLM_MODES = ("pitch", "brand")   # arm-2 inputs; site/full keep their old behaviour

STATE = {"store": {}, "llm": {}, "coverage": {}, "alerts": []}


def _alert(kind, msg):
    STATE["alerts"].append({"kind": kind, "msg": msg})
    print(f"INPUT ALERT [{kind}] {msg}", flush=True)


def _gs_cp(src, dst):
    return subprocess.run(["gsutil", "-q", "cp", src, dst], capture_output=True, timeout=120).returncode == 0


def _latest_arm2_backup():
    r = subprocess.run(["gsutil", "ls", f"{ARM2_BACKUPS}/"], capture_output=True, text=True, timeout=60)
    dirs = sorted(l.rstrip("/").rsplit("/", 1)[-1] for l in r.stdout.split() if l.endswith("/"))
    dirs = [x for x in dirs if x.isdigit()]
    return f"{ARM2_BACKUPS}/{dirs[-1]}/ph_predict_data/days" if dirs else None


def store_check(day):
    """Expected: every calendar day in [day-LOOKBACK, day-2] has a file in F.D/days (PH has launches every day)."""
    real = F.D
    d0 = dt.date.fromisoformat(day)
    want = [str(d0 - dt.timedelta(days=k)) for k in range(2, LOOKBACK + 1)]
    have = {os.path.basename(f)[:-5] for f in glob.glob(f"{real}/days/*.json")}
    missing = [x for x in want if x not in have]
    latest = max(have) if have else None
    STATE["store"] = {"latest_day": latest, "expected_through": want[0], "missing_days": len(missing), "fallback": None}
    if not missing:
        return real
    _alert("store", f"day store missing {len(missing)} of the last {len(want)} days (latest {latest}); restoring from bucket copy")
    ov = f"{RESTORE}/overlay_{day}"
    shutil.rmtree(ov, ignore_errors=True); os.makedirs(f"{RESTORE}/days", exist_ok=True); os.makedirs(ov)
    for e in os.listdir(real):
        if e != "days":
            os.symlink(f"{real}/{e}", f"{ov}/{e}")
    os.makedirs(f"{ov}/days")
    for f in glob.glob(f"{real}/days/*.json"):
        os.symlink(os.path.abspath(f), f"{ov}/days/{os.path.basename(f)}")
    src_used, restored, arm2 = set(), [], None
    for x in missing:
        dst = f"{RESTORE}/days/{x}.json"
        ok = _gs_cp(f"{STORE_COPY}/{x}.json", dst)
        if ok:
            src_used.add("store_copy")
        else:
            arm2 = arm2 or _latest_arm2_backup()
            ok = bool(arm2) and _gs_cp(f"{arm2}/{x}.json", dst)
            if ok:
                src_used.add(arm2.rsplit("/", 3)[-3])
        if ok:
            os.symlink(dst, f"{ov}/days/{x}.json"); restored.append(x)
    still = [x for x in missing if x not in restored]
    STATE["store"].update({"fallback": "bucket:" + "+".join(sorted(src_used)) if restored else "none_found",
                           "restored_days": len(restored), "still_missing_days": len(still), "overlay": True})
    if still:
        _alert("store", f"{len(still)} days still missing after restore ({', '.join(still[:5])}); hunter history is short for them")
    if not restored:
        shutil.rmtree(ov, ignore_errors=True)
        STATE["store"]["overlay"] = False
        return real
    F.D = ov
    return ov


def _bad(v):
    if isinstance(v, dict):
        v = v.get("score")
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


def _missing(path, ids):
    try:
        x = json.load(open(path))
    except (OSError, ValueError):
        return list(ids), {}
    return [i for i in ids if i not in x or _bad(x[i])], x


def llm_check(day, g):
    """g = today's rows (df0[df0.day == day]). Calls llm.run_day on the missing subset with backoff; merges results."""
    import llm
    ids = [str(i) for i in g.id]
    t_end = time.time() + LLM_BUDGET_S
    for mode in LLM_MODES:
        path = f"{llm.D}/llm_{mode}{llm.SUFFIX}/{day}.json"
        miss, have = _missing(path, ids)
        tries = 0
        while miss and tries < len(LLM_BACKOFF) and time.time() < t_end:
            time.sleep(min(LLM_BACKOFF[tries], max(0, t_end - time.time())))
            tries += 1
            tmp = tempfile.mkdtemp(prefix="guard_llm_")
            saved = llm.D
            try:   # run_day writes <D>/llm_<mode><SUFFIX>/<day>.json and skips an existing file: score into a scratch dir
                os.makedirs(f"{tmp}/llm_{mode}{llm.SUFFIX}")
                llm.D = tmp
                llm.run_day(day, g[g.id.astype(str).isin(miss)], mode)
                _, new = _missing(f"{tmp}/llm_{mode}{llm.SUFFIX}/{day}.json", miss)
            except Exception as e:   # noqa: BLE001  (network, quota, bad JSON: retry)
                print(f"guard llm {mode} retry {tries} error {type(e).__name__}", flush=True); new = {}
            finally:
                llm.D = saved
                shutil.rmtree(tmp, ignore_errors=True)
            good = {k: v for k, v in new.items() if k in miss and not _bad(v)}
            if good:
                have.update(good)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".tmp", "w") as f:
                    json.dump(have, f)
                os.replace(path + ".tmp", path)
            miss = [i for i in miss if i not in good]
        STATE["llm"][mode] = {"launches": len(ids), "missing": len(miss), "retries": tries, "missing_ids": miss}
        if miss:
            _alert("llm", f"llm_{mode}: {len(miss)} of {len(ids)} launches still unscored after {tries} retries")


def coverage(te):
    """Alert-only. Share of today's launches with at least one non-null input per group."""
    for name, pre in (("promo", ("promo",)), ("busy", ("busy",)), ("site", ("web", "dom", "llm_site"))):
        cols = [c for c in te.columns if (c.split("_")[0] in pre or c in pre) and te[c].dtype != object]
        share = float(te[cols].notna().any(axis=1).mean()) if cols and len(te) else 0.0
        STATE["coverage"][name] = {"columns": len(cols), "share_with_input": round(share, 3)}
        if share < COVER_MIN:
            _alert(name, f"{name}: only {share:.0%} of {len(te)} launches have any {name} input ({len(cols)} columns)")


def finish(day, out_dir):
    p = f"{out_dir}/forecast_inputs_{day}.json"
    STATE["written_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(p, "w") as f:
        json.dump(STATE, f, indent=1)
    if STATE["alerts"] and os.environ.get("GUARD_NO_UPLOAD") != "1":
        _gs_cp(p, f"{BUCKET}/alerts/forecast_inputs_{day}.json")
    return p
