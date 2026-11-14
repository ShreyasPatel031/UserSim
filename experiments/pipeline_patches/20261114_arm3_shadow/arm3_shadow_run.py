"""Arm 3 SHADOW write (undeployed; bundle 13). Runs E5's arm3_live.predict(<d>) on the 00:05 line-up after 01:00 PT and writes
~/w/arm3_live/results/<d>.json (+ gs://.../results/shadow_arm3/<d>.json): per launch pred_arm3 and its rank, next to the published arm-2 rank
from the 00:05 parquet. Never touches the published file or the parquet. Any failure writes the file with status "failed: <reason>" and
empty ranking (so the miss is visible), exit 0.
mode "prewarm": embeds every finished day's launches into the cache (ARM3_CACHE) so the 00:05 run only embeds today's line-up.
usage (VM, cwd ~/w/experiments/ph_predict, PYTHONPATH=~/w/experiments/ph_predict, HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1):
  python3 ~/w/arm3_live/arm3_shadow_run.py <d>          shadow write
  python3 ~/w/arm3_live/arm3_shadow_run.py prewarm <d>  cache finished days (<= d-1)"""
import datetime as dt, json, os, subprocess, sys, time
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def prewarm(d):
    import numpy as np, glob
    import features as F, run as RN
    import arm3_live as AL
    root = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data"))
    real = F.D; F.D = root
    try:
        df = RN.load_llm(F.build(include_today=False))
    finally:
        F.D = real
    df["id"] = df.id.astype(str); df = df[df.day < d].reset_index(drop=True)
    t = time.time(); _, info = AL._cache_embed(df, np.zeros(len(df), bool))
    print(json.dumps({"prewarm_through": str(df.day.max()), "rows": len(df), **info, "seconds": round(time.time() - t)}))


def shadow(d):
    t0 = time.time(); out = {"day": d, "kind": "arm3_shadow", "status": "ok", "published": False}
    try:
        import arm3_live as AL
        PA, info = AL.predict(d)
        PA = PA.sort_values(["pred_arm3", "id"], ascending=[False, True]).reset_index(drop=True)
        rk2 = {}
        fp = f"/tmp/arm3_fc_{d}.parquet"
        if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", fp], capture_output=True).returncode == 0:
            import pandas as pd
            Fq = pd.read_parquet(fp); os.remove(fp); Fq["id"] = Fq.id.astype(str)
            col = "pred_arm2" if "pred_arm2" in Fq and Fq.pred_arm2.notna().all() else "pred"
            rk2 = dict(zip(Fq.sort_values([col, "id"], ascending=[False, True]).id, range(1, len(Fq) + 1))); out["compare_to"] = col
        out.update({"info": info, "ranking": [{"rank": k + 1, "id": r.id, "pred_arm3": round(float(r.pred_arm3), 4), "rank_published": rk2.get(r.id)}
                                              for k, r in PA.iterrows()]})
    except Exception as e:   # noqa: BLE001
        out.update({"status": f"failed: {type(e).__name__}: {str(e)[:200]}", "ranking": []})
    out["seconds"] = round(time.time() - t0); out["written_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    od = os.path.expanduser(os.environ.get("ARM3_OUT", "~/w/arm3_live/results")); os.makedirs(od, exist_ok=True)   # own dir, never the pipeline's results
    p = f"{od}/{d}.json"; json.dump(out, open(p, "w"), indent=1)
    if os.environ.get("DRY") != "1":
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/shadow_arm3/{d}.json"], check=False)
    print(json.dumps({k: out[k] for k in ("day", "status", "seconds")} | {"launches": len(out["ranking"])}))


if __name__ == "__main__":
    (prewarm(sys.argv[2]) if sys.argv[1] == "prewarm" else shadow(sys.argv[1]))
