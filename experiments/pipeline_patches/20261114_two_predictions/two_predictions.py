"""The two published predictions as web files, written on the VM (bundle 12a; Shreyas via orchestrator 00:52Z Nov 14). No session needed.
  midnight <d>   results/web/predictions/<d>_0005.json from the pipeline's 00:05 forecast parquet (published order = pred_arm2; the parquet's
                 own fallback to clean_nosite is named when pred_arm2 is missing)
  prereveal <d>  results/web/predictions/<d>_prereveal.json at 03:45 PT. Model "hybrid_vm": hidden rank top 5 as is, slots 6+ by the frozen
                 ridge results/frozen/hybrid_vmonly_P345_20261114.json on z(log hidden pos), z(move since 01:00), z(log1p recorder comments),
                 z(00:05 clean_nosite pred). Inputs only from this VM: the hourly recorder file data/vote_snapshots/<d>.jsonl (03:45 read, else
                 the 03:00 read) and the 00:05 forecast parquet. Fallback order, named in the file:
                   1 hybrid_vm   2 hybrid_vm without the clean term (parquet missing)   3 plain hidden rank (weights file missing)
                   4 the 00:05 midnight order (no recorder read within 65 min of 03:45)
Also writes <kind>_latest.json pointers. Counts and launch names only (no people). usage: python3 two_predictions.py midnight|prereveal [YYYY-MM-DD]"""
import datetime as dt, json, os, subprocess, sys
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
PH = "/home/agent/w/experiments/ph_predict"; TW = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
PT = ZoneInfo("America/Los_Angeles"); ACC0 = "60.7 / 68.4 / 75.7 top 3 / 5 / 10 on 214 backtest days (Apr-Oct 2026)"
ACC1 = "72.7 / 74.5 / 77.3 top 3 / 5 / 10 on 11 days (Nov 2-12, recorder reads; top 3 and top 5 equal the plain hidden rank, top 10 +4.5)"
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0


def forecast(d):
    p = f"{PH}/results/forecast_{d}.parquet"
    if not os.path.exists(p):
        p = f"/tmp/forecast_{d}.parquet"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], capture_output=True)
    return pd.read_parquet(p) if os.path.exists(p) else None


def names(d):
    p = f"{PH}/data/vote_snapshots/{d}.jsonl"; V = pd.DataFrame([json.loads(l) for l in open(p)]) if os.path.exists(p) else pd.DataFrame()
    return (V, dict(zip(V.launch_id.astype(str), V.name))) if len(V) else (V, {})


def put(d, kind, out):
    os.makedirs(f"{TW}/out", exist_ok=True); p = f"{TW}/out/{d}_{kind}.json"; json.dump(out, open(p, "w"), indent=1)
    if os.environ.get("DRY") == "1":
        print("DRY: not uploaded", p); print(json.dumps({k: out[k] for k in ("day", "kind", "model", "fallback_used", "inputs")})); return
    for nm in (f"{d}_{kind}.json", f"{kind}_latest.json"):
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/predictions/{nm}"], check=True)
    print(json.dumps({k: out[k] for k in ("day", "kind", "model", "fallback_used", "inputs")}))


def midnight(d):
    F = forecast(d); _, nm = names(d); now = dt.datetime.now(dt.timezone.utc).isoformat()
    if F is None or not len(F):
        put(d, "0005", {"day": d, "kind": "0005", "time": "00:05 PT", "model": None, "fallback_used": "none available", "inputs": {"forecast_parquet": "missing"},
                        "written_at": now, "backtest": ACC0, "ranking": []}); return
    F["id"] = F.id.astype(str); arm2 = "pred_arm2" in F and F.pred_arm2.notna().all(); col = "pred_arm2" if arm2 else "pred"
    F = F.sort_values([col, "id"], ascending=[False, True]).reset_index(drop=True)
    put(d, "0005", {"day": d, "kind": "0005", "time": "00:05 PT", "model": "arm2" if arm2 else "clean_nosite", "fallback_used": None if arm2 else "clean_nosite (arm 2 missing)",
                    "inputs": {"forecast_parquet": "present", "pred_arm2": "present" if arm2 else "missing"}, "written_at": now, "backtest": ACC0,
                    "ranking": [{"rank": k + 1, "id": r.id, "name": nm.get(r.id), "score": round(float(r[col]), 4)} for k, r in F.iterrows()]})


def prereveal(d):
    now = dt.datetime.now(dt.timezone.utc); t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC"); T = t0 + pd.Timedelta(hours=3.75)
    V, nm = names(d); inp = {}; fb = None
    if len(V):
        V["launch_id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True); V = V.drop_duplicates(["launch_id", "at"]).dropna(subset=["rank_now"])
    def at(h):
        Tt = t0 + pd.Timedelta(hours=h)
        s = V[(V.a <= Tt) & (V.a >= Tt - pd.Timedelta(minutes=65)) & (V.a >= t0 - pd.Timedelta(minutes=5))] if len(V) else V
        return s.sort_values("a").groupby("launch_id").last() if len(s) else None
    sT, s1 = at(3.75), at(1.0)
    inp["recorder_T"] = f"present ({sT.a.max():%H:%MZ})" if sT is not None else "missing"; inp["recorder_0100"] = "present" if s1 is not None else "missing"
    F = forecast(d); inp["forecast_parquet"] = "present" if F is not None and len(F) else "missing"
    fz = f"{TW}/hybrid_vmonly_P345_20261114.json"; inp["weights"] = "present" if os.path.exists(fz) else "missing"
    if sT is None:
        if F is None or not len(F):
            put(d, "prereveal", {"day": d, "kind": "prereveal", "time": "03:45 PT", "model": None, "fallback_used": "none available", "inputs": inp,
                                 "written_at": now.isoformat(), "backtest": ACC1, "ranking": []}); return
        F["id"] = F.id.astype(str); col = "pred_arm2" if "pred_arm2" in F and F.pred_arm2.notna().all() else "pred"
        order = F.sort_values([col, "id"], ascending=[False, True]).id.tolist(); model = "midnight order"; fb = "4: no recorder read within 65 min of 03:45 PT"
    else:
        ids = list(sT.index); pos = sT.rank_now.rank(method="first")
        hid = sorted(ids, key=lambda i: (pos[i], i))
        if inp["weights"] == "missing":
            order = hid; model = "plain hidden rank"; fb = "3: weights file missing"
        else:
            W = json.load(open(fz))["coef"]; pos1 = (s1.rank_now.reindex(ids).fillna(999) if s1 is not None else pd.Series(999, index=ids)).rank(method="first")
            Z = pd.DataFrame({"lpos": np.log(pos), "move": np.log(pos1) - np.log(pos), "nc_rec": np.log1p(sT.comments.fillna(0).astype(float))}, index=ids)
            if inp["forecast_parquet"] == "present":
                F["id"] = F.id.astype(str); Z["clean"] = Z.index.map(dict(zip(F.id, F.pred))).astype(float); Z["clean"] = Z.clean.fillna(Z.clean.min() - 0.1)
            else:
                Z["clean"] = 0.0; fb = "2: forecast parquet missing, clean term dropped"
            sc = sum(zf(Z[f.replace("z_", "")]) * c for f, c in W.items())
            rest = [i for i in sc.sort_values(ascending=False).index if i not in set(hid[:5])]
            order = hid[:5] + rest; model = "hybrid_vm (hidden rank top 5 + ridge 6+)"
    put(d, "prereveal", {"day": d, "kind": "prereveal", "time": "03:45 PT", "model": model, "fallback_used": fb, "inputs": inp, "written_at": now.isoformat(),
                         "backtest": ACC1, "ranking": [{"rank": k + 1, "id": i, "name": nm.get(i)} for k, i in enumerate(order)]})


if __name__ == "__main__":
    d = sys.argv[2] if len(sys.argv) > 2 else dt.datetime.now(PT).strftime("%Y-%m-%d")
    {"midnight": midnight, "prereveal": prereveal}[sys.argv[1]](d)
