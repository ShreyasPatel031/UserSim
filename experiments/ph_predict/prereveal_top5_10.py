"""Raise pre-reveal top 5 / top 10 (orchestrator 01:33Z Nov 13). REPLAY on every finished day with a hidden-window dailyRank
read: hidden rank at 01:00 / 02:00 / 03:00 PT = latest read <= the point from live posts_ts daily_rank_at_fetch (official API)
or, if absent, warehouse vote_snapshots rank_now. Features per launch (within-day z):
  a  hidden rank position (log)                         c  + comments / distinct commenters created <= the point (comments_ts,
  b  + movement: log position at 01:00 minus at the point     replies included; read after the fact = replay)
  d  + clean_nosite 00:05 score (clean_live_rows_nosite clean_v3_nosite; days without it use the day mean)
Model: ridge (alpha 3) on z features -> within-day z(-log final rank), leave-one-day-out; rank by prediction.
Constant: hidden rank at 03:00 PT as is. Scores: top 3/5/10 per day, day bootstrap 95%. Misses: for each final top-5/top-10
launch we missed at 03:00, its hidden rank then (near-tie 6-8 vs late climber).
usage: python prereveal_top5_10.py -> results/web/prereveal_top5_10.json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
from sklearn.linear_model import Ridge
TMP = os.environ.get("TMPDIR", "/tmp")
HS = (1, 2, 3, 3.75)   # 03:45 PT = last pre-reveal read (orchestrator 02:39Z Nov 13; reveal is 04:00 PT sharp)
LAB = lambda h: f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"
PN = lambda h: "P345" if h == 3.75 else f"P{int(h)}"


def get(path):
    p = tempfile.mkdtemp(dir=TMP) + "/" + os.path.basename(path)
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots WHERE rank_now IS NOT NULL', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    cl = {d: dict(zip(g.id, g.clean_v3_nosite)) for d, g in CL.groupby("day")}
    rows, info = [], {}
    for d in sorted(set(R.day) & set(pd.date_range("2026-10-25", "2026-11-12").strftime("%Y-%m-%d"))):
        truth = R[R.day == d].sort_values("daily_rank"); ids = truth.id.tolist()
        if len(ids) < 10:
            continue
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        H = []
        pp = get(f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl")
        if pp:
            for l in open(pp):
                r = json.loads(l)
                if r.get("fetch_status") == 200 and r.get("daily_rank_at_fetch") is not None and str(r.get("source", "")).startswith("ph_api_v2"):
                    H.append((pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]), float(r["daily_rank_at_fetch"])))
        H = pd.DataFrame(H, columns=["a", "id", "r"])
        G = V[V.d == d].rename(columns={"rank_now": "r"})[["a", "id", "r"]]
        srcs = []
        cp = get(f"{B}/raw/ph_at_launch/{d}/live/comments_ts.jsonl"); C = pd.DataFrame(columns=["id", "u", "ts"])
        if cp:
            C = pd.DataFrame([json.loads(l) for l in open(cp)]).drop_duplicates("comment_id")
            C = pd.DataFrame({"id": C.launch_id.astype(str), "u": C.commenter_user_id.fillna(C.get("user_id")).astype(str),
                              "ts": pd.to_datetime(C.created_at, utc=True, errors="coerce")})
        pos = {}
        for h in HS:
            S = H[H.a <= t0 + pd.Timedelta(hours=h)].sort_values("a").groupby("id").r.last(); srcs.append("posts_ts")
            if S.empty:   # per point: fall back to the warehouse hourly recorder
                S = G[G.a <= t0 + pd.Timedelta(hours=h)].sort_values("a").groupby("id").r.last(); srcs[-1] = "vote_snapshots"
            if S.empty:
                break
            pos[h] = pd.Series({i: S.get(i, 999) for i in ids}).rank(method="first")
        if 3 not in pos:
            continue
        info[d] = {"rank_source": srcs, "comments": bool(cp), "clean": d in cl, "launches": len(ids)}
        for h in [h_ for h_ in HS if h_ in pos]:
            T = t0 + pd.Timedelta(hours=h); Ch = C[C.ts <= T]
            for i in ids:
                c = Ch[Ch.id == i]
                rows.append({"day": d, "h": h, "id": i, "final": int(truth.set_index("id").daily_rank[i]), "lpos": np.log(pos[h][i]),
                             "move": np.log(pos[1][i]) - np.log(pos[h][i]), "nc": np.log1p(len(c)), "nu": np.log1p(c.u.nunique()),
                             "clean": cl.get(d, {}).get(i, np.nan)})
    X = pd.DataFrame(rows)
    X["clean"] = X.groupby("day").clean.transform(lambda s: s.fillna(s.mean()) if s.notna().any() else s.fillna(0.0))
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("lpos", "move", "nc", "nu", "clean"):
        X["z_" + c] = X.groupby(["day", "h"])[c].transform(zf)
    X["y"] = X.groupby(["day", "h"]).final.transform(lambda s: zf(-np.log(s)))
    VAR = {"a hidden rank": ["z_lpos"], "b + movement": ["z_lpos", "z_move"], "c + comments": ["z_lpos", "z_move", "z_nc", "z_nu"],
           "d + clean_nosite": ["z_lpos", "z_move", "z_nc", "z_nu", "z_clean"]}
    days = sorted(X.day.unique()); rng = np.random.default_rng(0); res = []; per = {}
    def hits(o, t):
        return [len(set(o[:k]) & set(t[:k])) for k in (3, 5, 10)]
    for h in HS:
        Xh = X[X.h == h]
        if Xh.empty:
            continue
        days = sorted(Xh.day.unique())
        for nm, F in [("constant: hidden rank at 03:00", None)] + list(VAR.items()) + [("e hybrid: hidden top 5 + hr_clean 6-10", "hybrid")]:
            if F is None and h != 3:
                continue
            pd_ = []
            for d in days:
                te = Xh[Xh.day == d]; tr = Xh[Xh.day != d]; t = te.sort_values("final").id.tolist()
                if F is None:
                    o = te.sort_values(["lpos", "id"]).id.tolist()
                elif F == "hybrid":   # orchestrator 02:39Z Nov 13: top 3 / top 5 from the plain hidden order, slots 6-10 from hr_clean
                    h5 = te.sort_values(["lpos", "id"]).id.tolist()[:5]
                    D_ = VAR["d + clean_nosite"]; sc = Ridge(alpha=3.0).fit(tr[D_], tr.y).predict(te[D_])
                    o = h5 + [i for i in te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id if i not in set(h5)]
                else:
                    sc = Ridge(alpha=3.0).fit(tr[F], tr.y).predict(te[F]); o = te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
                pd_.append(hits(o, t))
                if nm == "a hidden rank" and h == 3:
                    per.setdefault("misses_at_0300", {})[d] = {
                        f"top{k}": sorted(int(np.exp(te.set_index("id").lpos[i])) for i in set(t[:k]) - set(o[:k])) for k in (5, 10)}
            P = np.array(pd_, float) / np.array([3, 5, 10]) * 100
            b = np.array([P[rng.integers(0, len(P), len(P))].mean(0) for _ in range(3000)])
            res.append({"point": LAB(h), "variant": nm, "days": len(P),
                        **{f"top{k}": round(float(P[:, j].mean()), 1) for j, k in enumerate((3, 5, 10))},
                        **{f"top{k}_ci": [round(float(np.percentile(b[:, j], 2.5)), 1), round(float(np.percentile(b[:, j], 97.5)), 1)] for j, k in enumerate((3, 5, 10))}})
    # orchestrator 01:43Z Nov 13: freeze variant d's weights (full 7-day fit per point) for the forward shadow line hr_clean
    fz = {"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": days, "alpha": 3.0, "features": VAR["d + clean_nosite"],
          "note": "z within day; lpos = log hidden-rank position, move = log pos at 01:00 - log pos now, nc / nu = log1p comments / "
                  "distinct commenters created <= the point, clean = clean_nosite 00:05 score; target z(-log final rank)", "points": {}}
    for h in (1, 2, 3):
        Xh = X[X.h == h]; m = Ridge(alpha=3.0).fit(Xh[VAR["d + clean_nosite"]], Xh.y)
        fz["points"][f"P{h}"] = {"coef": dict(zip(VAR["d + clean_nosite"], map(float, m.coef_))), "intercept": float(m.intercept_)}
    os.makedirs(os.path.join(HERE, "results", "frozen"), exist_ok=True)
    fp = os.path.join(HERE, "results", "frozen", "prereveal_hr_clean_20261113.json")
    if not os.path.exists(fp):   # frozen once: never overwritten
        json.dump(fz, open(fp, "w"), indent=1)
    fp4 = os.path.join(HERE, "results", "frozen", "prereveal_hr_clean_P345_20261113.json")   # 03:45 PT point, frozen separately
    X4 = X[X.h == 3.75]
    if not os.path.exists(fp4) and len(X4):
        m = Ridge(alpha=3.0).fit(X4[VAR["d + clean_nosite"]], X4.y)
        json.dump({**{k: v for k, v in fz.items() if k != "points"}, "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": sorted(X4.day.unique()),
                   "points": {"P345": {"coef": dict(zip(VAR["d + clean_nosite"], map(float, m.coef_))), "intercept": float(m.intercept_)}}},
                  open(fp4, "w"), indent=1)
    out = {"replay": True, "method": __doc__.split("\n")[0], "days": info, "rows": res, **per, "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
    p = os.path.join(HERE, "results", "web", "prereveal_top5_10.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/prereveal_top5_10.json"], check=True)
    print(json.dumps(info)); print(pd.DataFrame(res)[["point", "variant", "days", "top3", "top5", "top10", "top3_ci", "top5_ci", "top10_ci"]].to_string(index=False))
    print(json.dumps(per.get("misses_at_0300")))


if __name__ == "__main__":
    main()
