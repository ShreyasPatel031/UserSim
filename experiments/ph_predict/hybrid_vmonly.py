"""VM-only 03:45 hybrid (orchestrator 00:52Z Nov 14: two published predictions; the before-reveal one must depend ONLY on what the VM produces).
Inputs, all from usersim-pipeline itself:
  hidden rank   recorder rank_now (raw/vote_snapshots/<d>.jsonl, pipeline/hourly.py) at the latest read <= T (E5's rule: within 65 min, after 23:55 PT)
  move          log rank-position at 01:00 minus at T (same recorder)
  nc_rec        log1p commentsCount from the same recorder row (public before the reveal; replies included; no distinct-commenter count)
  clean         the 00:05 forecast parquet's `pred` (clean_nosite; raw/daily/<d>/forecast_<d>.parquet), month-fold clean_nosite as stand-in where absent
Line: hidden top 5 as is, slots 6+ by a ridge on z(lpos), z(move), z(nc_rec), z(clean). Weights: leave-one-day-out here (backtest); the live
version freezes the all-day fit. Compared with the plain hidden rank and the published hybrid (feed comments, frozen P345 weights).
usage: python hybrid_vmonly.py -> results/hybrid_vmonly.md (+ results/frozen/hybrid_vmonly_P345_20261114.json)"""
import json, os, subprocess, tempfile, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [os.path.dirname(HERE), HERE]
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; TMP = os.environ.get("TMPDIR", "/tmp")
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True)
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
PTS = {"P3": 3.0, "P345": 3.0}   # 03:45 uses the 03:00 read in the backtest (no 03:45 recorder read existed); live adds one


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    TWn = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); TWn["id"] = TWn.id.astype(str); twc = dict(zip(TWn.id, TWn.clean_v3_nosite))
    rows = []; src = {}
    for d in pd.date_range("2026-11-02", "2026-11-12").strftime("%Y-%m-%d"):
        V = pd.DataFrame([json.loads(l) for l in gcat(f"{B}/raw/vote_snapshots/{d}.jsonl").stdout.splitlines() if l.strip()])
        V["launch_id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True); V = V.drop_duplicates(["launch_id", "at"]).dropna(subset=["rank_now"])
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC"); truth = R[R.day == d].sort_values("daily_rank")
        fc = tempfile.mkdtemp(dir=TMP) + "/f.parquet"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", fc], capture_output=True)
        cp = {}
        if os.path.exists(fc):
            F_ = pd.read_parquet(fc)
            if len(F_):
                cp = dict(zip(F_.id.astype(str), F_.pred))
        src[d] = "forecast parquet pred" if cp else "month-fold clean_nosite stand-in"
        def at(h):
            T = t0 + pd.Timedelta(hours=h); s = V[(V.a <= T) & (V.a >= T - pd.Timedelta(minutes=65)) & (V.a >= t0 - pd.Timedelta(minutes=5))]
            return s.sort_values("a").groupby("launch_id").last()
        s1 = at(1.0)
        for p, h in PTS.items():
            sT = at(h); ids = [i for i in truth.id if i in sT.index]
            if len(ids) < 10:
                continue
            posT = sT.rank_now.reindex(ids).rank(method="first"); pos1 = s1.rank_now.reindex(ids).fillna(999).rank(method="first")
            for i in ids:
                rows.append({"day": d, "point": p, "id": i, "final": int(truth.set_index("id").daily_rank[i]), "pos": posT[i], "lpos": np.log(posT[i]),
                             "move": np.log(pos1[i]) - np.log(posT[i]), "nc_rec": np.log1p(sT.comments.get(i, 0) or 0), "clean": cp.get(i, twc.get(i, np.nan))})
    X = pd.DataFrame(rows); X["clean"] = X.groupby("day").clean.transform(lambda s: s.fillna(s.min() - 0.1) if s.notna().any() else s.fillna(0))
    F = ["lpos", "move", "nc_rec", "clean"]
    for c in F:
        X["z_" + c] = X.groupby(["day", "point"])[c].transform(zf)
    X["y"] = X.groupby(["day", "point"]).final.transform(lambda s: zf(-np.log(s)))
    rng = np.random.default_rng(0); md = ["# VM-only before-reveal hybrid (recorder rank + recorder comment count + 00:05 forecast), 11 days Nov 2-12", "",
          "Recorder reads only (E5's rule: latest rank_now <= T, within 65 min, after 23:55 PT); 03:45 = the 03:00 read (no 03:45 read existed). Label = official dailyRank, all featured launches. "
          "Weights leave-one-day-out. Clean prior per day: " + "; ".join(f"{d[5:]} {s}" for d, s in src.items()), "",
          "| point | line | top 3 | top 5 | top 10 | minus plain hidden rank (t3 / t5 / t10) |", "|---|---|---|---|---|---|"]
    out = {}
    for p in PTS:
        Xp = X[X.point == p]; dd = sorted(Xp.day.unique()); H, Y, O = [], [], []
        for d in dd:
            tr, te = Xp[Xp.day != d], Xp[Xp.day == d]; t = te.sort_values("final").id.tolist()
            sc = Ridge(alpha=3.0).fit(tr[["z_" + f for f in F]], tr.y).predict(te[["z_" + f for f in F]])
            oh = te.sort_values(["pos", "id"]).id.tolist(); ol = te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            H.append(hits(oh, t)); Y.append(hits(oh[:5] + [i for i in ol if i not in set(oh[:5])], t))
            fz = te.sort_values(["clean", "id"], ascending=[False, True]).id.tolist(); O.append(hits(fz, t))
        H, Y, O = map(np.array, (H, Y, O))
        def ci(A):
            dl = A - H; b = np.array([dl[rng.integers(0, len(dl), len(dl))].mean(0) for _ in range(4000)])
            return " / ".join(f"{dl[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3))
        lab = "03:00" if p == "P3" else "03:45"
        md += [f"| {lab} | plain hidden rank | {H[:,0].mean():.1f} | {H[:,1].mean():.1f} | {H[:,2].mean():.1f} | - |",
               f"| {lab} | VM-only hybrid (hidden top 5 + ridge 6+) | {Y[:,0].mean():.1f} | {Y[:,1].mean():.1f} | {Y[:,2].mean():.1f} | {ci(Y)} |",
               f"| {lab} | 00:05 clean prior alone (reference) | {O[:,0].mean():.1f} | {O[:,1].mean():.1f} | {O[:,2].mean():.1f} | {ci(O)} |"]
        out[p] = (len(dd), Y.mean(0))
        if p == "P345" and os.environ.get("HV_DUMP"):   # per-day hits of the line that will be published (orchestrator 01:36Z Nov 14)
            json.dump({"line": "hybrid_vm (bundle 12a), 03:45 PT", "label": "official dailyRank, all featured launches", "read_rule": "recorder rank_now latest <= T within 65 min, after 23:55 PT; 03:45 = 03:00 read",
                       "weights": "leave-one-day-out", "days": [{"day": d, "hits_top3": int(round(y[0] * 3 / 100)), "hits_top5": int(round(y[1] * 5 / 100)), "hits_top10": int(round(y[2] * 10 / 100))} for d, y in zip(dd, Y)],
                       "mean_top3_5_10": [round(float(v), 1) for v in Y.mean(0)]}, open(os.environ["HV_DUMP"], "w"), indent=1)
    md += ["", "Published 03:45 hybrid (feed comments + distinct commenters, frozen P345 weights), recorder-only reads, 11 days: 72.7 / 74.5 / 77.3 (prereveal_12day_recorder_only.md)."]
    Xp = X[X.point == "P345"]; m = Ridge(alpha=3.0).fit(Xp[["z_" + f for f in F]], Xp.y)
    fz = f"{HERE}/results/frozen/hybrid_vmonly_P345_20261114.json"
    if not os.path.exists(fz):
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": "2026-11-02..2026-11-12 (11)", "alpha": 3.0, "features": ["z_" + f for f in F],
                   "coef": dict(zip(["z_" + f for f in F], map(float, m.coef_))), "intercept": float(m.intercept_),
                   "note": "z within day; lpos = log hidden-rank position (recorder rank_now), move = log pos at 01:00 - log pos at T, nc_rec = log1p recorder commentsCount at T, clean = 00:05 forecast parquet pred; target z(-log final rank); slots 6+ only (top 5 = hidden rank)"},
                  open(fz, "w"), indent=1)
        md.append(f"Frozen all-day fit -> {os.path.relpath(fz, HERE)}: " + ", ".join(f"{f} {c:+.3f}" for f, c in zip(F, m.coef_)))
    open(f"{HERE}/results/hybrid_vmonly.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
