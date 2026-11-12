"""Pre-registered forward check of the thread signal (orchestrator 09:12Z Nov 12): day-clustered coefficient of z(th_n_pre)
controlling for z(clean 00:05 score) in a pooled OLS of z(-log final daily rank), z within day. Backtest +0.204 (se 0.015);
stop when the forward se <= 0.07 (~13+ days). Forward days = live days from 2026-11-12.
th_n_pre (exact live definition): t5 = launch day 00:05 America/Los_Angeles; all comments_ts rows with created_at <= t5,
replies included; hunter id = daily JSON post.user.id, else people_ts role=hunter, else warehouse poster -> id (dump map);
th_n_pre = distinct commenter_user_id that are not the hunter; MISSING (day mean) if the hunter id is unknown.
Clean score: results/shadow_makerfix/<d>.json pred_clean, else results/clean_live_rows.parquet clean_v3 (same model, live rows).
usage: python thread_coef.py -> results/web/thread_coef.json (+ bucket); scoreboard.py embeds it"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
FWD = "2026-11-12"
TMP = os.environ.get("TMPDIR", "/tmp")


def get(path):
    p = tempfile.mkdtemp(dir=TMP) + "/" + os.path.basename(path)
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def day_rows(d, rk, clean_fallback, name2id, wposter):
    cp = get(f"{B}/raw/ph_at_launch/{d}/live/comments_ts.jsonl")
    if not cp:
        return None, "no comments_ts"
    sp = os.path.join(HERE, "results", "shadow_makerfix", f"{d}.json"); sc = {}
    if os.path.exists(sp):
        SF = pd.DataFrame(json.load(open(sp))["forecast"])
        if "pred_clean" in SF:
            sc = dict(zip(SF.id.astype(str), SF.pred_clean))
    if not sc:
        sc = clean_fallback.get(d, {})
    if not sc:
        return None, "no clean score"
    dp = get(f"{B}/raw/daily/{d}/{d}.json"); hun = {}
    if dp:
        hun = {str(x["id"]): str((x.get("user") or {}).get("id") or "") for x in json.load(open(dp))}
    pp = get(f"{B}/raw/ph_at_launch/{d}/live/people_ts.jsonl"); phun = {}
    if pp:
        for l in open(pp):
            r = json.loads(l)
            if r.get("role") == "hunter" and r.get("user_id"):
                for i in r.get("launch_ids") or []:
                    phun[str(i)] = str(r["user_id"])
    t5 = pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC")
    C = pd.DataFrame([json.loads(l) for l in open(cp)]).drop_duplicates("comment_id")
    C["ts"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); C = C[C.ts <= t5]
    C["id"] = C.launch_id.astype(str); C["u"] = C.commenter_user_id.fillna(C.get("user_id")).astype(str)
    rows = []
    for i, r in rk.items():
        h = hun.get(i) or phun.get(i) or name2id.get(wposter.get(i, ""), "")
        g = C[C.id == i]
        rows.append({"day": d, "id": i, "rank": r, "clean": sc.get(i, np.nan), "th_n_pre": float(g[g.u != h].u.nunique()) if h else np.nan})
    X = pd.DataFrame(rows)
    return X, {"launches": len(X), "hunter_missing": int(X.th_n_pre.isna().sum()), "clean_missing": int(X.clean.isna().sum())}


def fit(X):
    days = X.day.unique()
    if len(days) < 2:
        return None
    z = lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0.0
    Z = pd.DataFrame({"day": X.day, "y": X.groupby("day")["rank"].transform(lambda s: z(-np.log(s))),
                      "c": X.groupby("day").clean.transform(z), "t": X.groupby("day").th_n_pre.transform(z)})
    A = np.c_[Z.c, Z.t]; y = Z.y.values
    XtX = np.linalg.inv(A.T @ A); b = XtX @ A.T @ y; e = y - A @ b
    meat = sum(np.outer(A[(Z.day == d).values].T @ e[(Z.day == d).values], A[(Z.day == d).values].T @ e[(Z.day == d).values]) for d in days)
    G = len(days); V = XtX @ meat @ XtX * G / (G - 1)
    return {"days": int(G), "launches": int(len(Z)), "coef_th_n_pre": round(float(b[1]), 3), "se": round(float(np.sqrt(V[1, 1])), 3),
            "coef_clean": round(float(b[0]), 3)}


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, lower(poster) p FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-29'", do_sync=False)
    wposter = dict(zip(R.id, R.p))
    import comment_forecast as CF
    K, _ = CF.load_comments(); name2id = dict(zip(K.user, K.uid))
    cf = {}
    lp = os.path.join(HERE, "results", "clean_live_rows.parquet")
    if os.path.exists(lp):
        CL = pd.read_parquet(lp)
        cf = {d: dict(zip(g.id.astype(str), g.clean_v3)) for d, g in CL.groupby("day")}
    parts, info = [], {}
    for d, g in R.groupby("day"):
        X, st = day_rows(d, g.set_index("id").daily_rank, cf, name2id, wposter)
        info[d] = st
        if X is not None:
            X["th_n_pre"] = X.th_n_pre.fillna(X.th_n_pre.mean()); parts.append(X.dropna(subset=["clean"]))
    A = pd.concat(parts) if parts else pd.DataFrame(columns=["day"])
    out = {"what": "day-clustered coefficient of z(th_n_pre) controlling for z(clean 00:05 score), pooled OLS of z(-log final rank), z within day",
           "backtest": {"coef": 0.204, "se": 0.015}, "stop_rule": "se <= 0.07 on forward days (from 2026-11-12)", "forward_from": FWD,
           "forward": fit(A[A.day >= FWD]) if len(A) else None, "all_live": fit(A) if len(A) else None, "per_day": info,
           "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
    if out["forward"]:
        out["forward"]["stop_reached"] = out["forward"]["se"] <= 0.07
    p = os.path.join(HERE, "results", "web", "thread_coef.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/thread_coef.json"], check=True)
    print(json.dumps({k: out[k] for k in ("forward", "all_live")}))


if __name__ == "__main__":
    main()
