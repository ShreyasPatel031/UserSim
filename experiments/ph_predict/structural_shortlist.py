"""STRUCT-SHORTLIST (orchestrator 23:02Z Nov 23; AGENTS.md "two models", docs/SOCIAL_SIM_PLAN.md Task R). Structural model = the frozen
launch model (arm 3 published, arm 2 shadow). Derived OUTSIDE the VM pipeline; nothing deployed changes.
  backtest   (a) ceiling: per day, share of the real top 3 / 5 / 10 inside the structural top 10 / 15 / 20, arm 3 and arm 2 side by side,
                 95% day bootstrap (10,000 draws, seed 0), on (i) the stored 2026 month-forward backtest (results/arm3_vs_arm2_preds.parquet,
                 leak-free: trained on months before the day's month) and (ii) the live frozen 00:05 days (raw/daily/<d>/forecast_<d>.parquet,
                 written before 03:45 PT; truth_daily ranks; launches featured after 00:05 are outside every shortlist, as they are live)
             (b) results/structural/backtest/<day>.json per day: every launch with id, name, structural score / rank (arm 3; arm 2 alongside),
                 and a separate "truth" block (final rank, votes) -> results/structural/ceiling_v1.json
  live <D>   results/structural/<D>/shortlist.json from the frozen 00:05 forecast parquet (no truth: the day is not over); uploads it.
Names come from the warehouse launches table (backtest) or the 00:05 line-up (live). Launch ids, names and numbers only; no people.
usage: python structural_shortlist.py backtest | live <YYYY-MM-DD>"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUT = os.path.join(HERE, "results", "structural"); KS = (3, 5, 10); MS = (10, 15, 20); NB = 10000
LIVE_DAYS = [f"2026-11-{d}" for d in range(10, 32)]


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)


def ranked(scores):
    """scores: Series id -> score (higher = better) -> rank 1..n (ties broken by id)."""
    s = scores.dropna(); o = sorted(s.index, key=lambda i: (-s[i], i)); return pd.Series(range(1, len(o) + 1), index=o, dtype=float)


def day_file(d, source, L, truth):
    """L: DataFrame id, name, score_arm3, score_arm2 (one row per launch in the model's line-up); truth: DataFrame id, final_rank, votes."""
    r3 = ranked(L.set_index("id").score_arm3) if L.score_arm3.notna().any() else pd.Series(dtype=float)
    r2 = ranked(L.set_index("id").score_arm2) if L.score_arm2.notna().any() else pd.Series(dtype=float)
    main = "arm3" if len(r3) else "arm2"; rk = r3 if len(r3) else r2
    rows = [{"id": i, "name": n, "structural_score": (None if pd.isna(s3 if main == "arm3" else s2) else round(float(s3 if main == "arm3" else s2), 5)),
             "structural_rank": (int(rk[i]) if i in rk.index else None),
             "score_arm3": (None if pd.isna(s3) else round(float(s3), 5)), "rank_arm3": (int(r3[i]) if i in r3.index else None),
             "score_arm2": (None if pd.isna(s2) else round(float(s2), 5)), "rank_arm2": (int(r2[i]) if i in r2.index else None)}
            for i, n, s3, s2 in zip(L.id, L.name, L.score_arm3, L.score_arm2)]
    rows.sort(key=lambda r: (r["structural_rank"] is None, r["structural_rank"] or 0))
    return {"day": d, "source": source, "structural_model": main, "n_launches": len(rows), "launches": rows,
            "truth": {"note": "final daily rank and votes; NEVER an input", "by_id": {str(i): {"final_rank": (None if pd.isna(fr) else int(fr)), "votes": (None if pd.isna(v) else int(v))}
                                                                                     for i, fr, v in zip(truth.id, truth.final_rank, truth.votes)}}}


def capture(rank, truth):
    """rank: Series id -> structural rank; truth: Series id -> final rank. {k: {m: share of the real top k inside the structural top m}}."""
    return {k: {m: len(set(truth.index[truth <= k]) & set(rank.index[rank <= m])) / k for m in MS} for k in KS}


def backtest():
    from pipeline import warehouse
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str); W = W.sort_values("updated_at").drop_duplicates("id", keep="last").set_index("id")
    A = pd.read_parquet(os.path.join(HERE, "results", "arm3_vs_arm2_preds.parquet")); A["id"] = A.id.astype(str); A = A[A.year.astype(str) == "2026"]
    TD = json.loads(sh("gsutil", "cat", f"{B}/results/web/truth_daily.json").stdout)["days"]
    os.makedirs(os.path.join(OUT, "backtest"), exist_ok=True); caps = {"backtest_2026": {}, "live": {}}; files = 0
    for d, g in A.groupby("day"):
        d = str(d)[:10]; tr = g.set_index("id").dailyRank.astype(float).dropna()
        if len(tr) < 10: continue
        L = pd.DataFrame({"id": g.id.values, "name": g.id.map(W.name).values, "score_arm3": g.arm3.values, "score_arm2": g.arm2.values})
        T = pd.DataFrame({"id": g.id.values, "final_rank": g.dailyRank.values, "votes": g.id.map(W.votes).values})
        json.dump(day_file(d, "backtest month-forward 2026 (arm3_vs_arm2_preds.parquet)", L, T), open(os.path.join(OUT, "backtest", f"{d}.json"), "w")); files += 1
        caps["backtest_2026"][d] = {"arm3": capture(ranked(g.set_index("id").arm3), tr), "arm2": capture(ranked(g.set_index("id").arm2), tr)}
    tmp = tempfile.mkdtemp()
    for d in LIVE_DAYS:
        if TD.get(d, {}).get("status") != "counts": continue
        p = os.path.join(tmp, f"f_{d}.parquet")
        if sh("gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p).returncode: continue
        F = pd.read_parquet(p); F["id"] = F.id.astype(str)
        lu = json.loads(sh("gsutil", "cat", f"{B}/raw/daily/{d}/today_0005.json").stdout or "[]"); lu = lu.get("posts", lu) if isinstance(lu, dict) else lu
        nm = {str(x["id"]): x.get("name") for x in lu if isinstance(x, dict)}
        s3 = F.pred_arm3 if "pred_arm3" in F and F.pred_arm3.notna().all() else pd.Series(np.nan, index=F.index)
        s2 = F.pred_arm2 if "pred_arm2" in F and F.pred_arm2.notna().all() else pd.Series(np.nan, index=F.index)
        if s3.isna().all() and s2.isna().all(): continue
        tr = pd.Series({str(k): float(v) for k, v in TD[d]["ranks"].items()})
        L = pd.DataFrame({"id": F.id.values, "name": F.id.map(nm).values, "score_arm3": s3.values, "score_arm2": s2.values})
        ids = sorted(set(F.id) | set(tr.index))
        T = pd.DataFrame({"id": ids, "final_rank": [tr.get(i) for i in ids], "votes": [W.votes.get(i) for i in ids]})
        json.dump(day_file(d, "live frozen 00:05 forecast parquet (written before 03:45 PT)", L, T), open(os.path.join(OUT, "backtest", f"{d}.json"), "w")); files += 1
        caps["live"][d] = {arm: capture(ranked(pd.Series(s.values, index=F.id.values)), tr) for arm, s in (("arm3", s3), ("arm2", s2)) if s.notna().all()}
    rng = np.random.default_rng(0); res = {"experiment": "STRUCT-SHORTLIST", "asked": "orchestrator 23:02Z Nov 23", "files_written": files,
                                           "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "sets": {}}
    for name, C in caps.items():
        S = {}
        for arm in ("arm3", "arm2"):
            ds = [d for d in C if arm in C[d]]
            if not ds: continue
            S[arm] = {"days": len(ds), "first": ds[0], "last": ds[-1]}
            for k in KS:
                for m in MS:
                    x = np.array([C[d][arm][k][m] for d in ds]) * 100; bs = x[rng.integers(0, len(x), (NB, len(x)))].mean(1)
                    S[arm][f"top{k}_in_top{m}"] = [round(float(x.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)]
        both = [d for d in C if "arm3" in C[d] and "arm2" in C[d]]
        if both:
            S["arm3_minus_arm2_paired"] = {"days": len(both)}
            for k in KS:
                for m in MS:
                    x = np.array([C[d]["arm3"][k][m] - C[d]["arm2"][k][m] for d in both]) * 100; bs = x[rng.integers(0, len(x), (NB, len(x)))].mean(1)
                    S["arm3_minus_arm2_paired"][f"top{k}_in_top{m}"] = [round(float(x.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)]
        res["sets"][name] = S
    res["leak_checks"] = ("backtest scores are month-forward (trained on months before the day's month; leak-free by the arm-3 decision's rules); live scores "
                          "are the frozen 00:05 parquets (written ~00:18 PT, before 03:45 PT); truth (final rank, votes) sits only in each file's truth block")
    res["notes"] = ["live: launches featured after the 00:05 forecast are in the truth but in no shortlist (as live); backtest: every featured launch is in the line-up",
                    "live arm 3 exists from Nov 17; arm 2 from Nov 15 (Nov 14 arm 2 empty); days before have neither and are skipped"]
    json.dump(res, open(os.path.join(OUT, "ceiling_v1.json"), "w"), indent=1)
    print(json.dumps(res["sets"], indent=0)[:5000])


def live(d):
    if os.environ.get("SKIP_DONE") == "1":   # VM job retry slot: an on-time file already in the bucket is left alone
        cur = sh("gsutil", "cat", f"{B}/results/structural/{d}/shortlist.json").stdout
        try:
            if cur and json.loads(cur).get("on_time"):
                print(json.dumps({"day": d, "status": "skipped: on-time shortlist already written"})); return
        except Exception:  # noqa: BLE001
            pass
    tmp = tempfile.mkdtemp(); p = os.path.join(tmp, "f.parquet")
    if sh("gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p).returncode:
        print(json.dumps({"day": d, "status": "missing input: no 00:05 parquet"})); return
    F = pd.read_parquet(p); F["id"] = F.id.astype(str)
    lu = json.loads(sh("gsutil", "cat", f"{B}/raw/daily/{d}/today_0005.json").stdout or "[]"); lu = lu.get("posts", lu) if isinstance(lu, dict) else lu
    nm = {str(x["id"]): x.get("name") for x in lu if isinstance(x, dict)}
    s3 = F.pred_arm3 if "pred_arm3" in F and F.pred_arm3.notna().all() else pd.Series(np.nan, index=F.index)
    s2 = F.pred_arm2 if "pred_arm2" in F and F.pred_arm2.notna().all() else pd.Series(np.nan, index=F.index)
    L = pd.DataFrame({"id": F.id.values, "name": F.id.map(nm).values, "score_arm3": s3.values, "score_arm2": s2.values})
    out = day_file(d, "live frozen 00:05 forecast parquet", L, pd.DataFrame({"id": [], "final_rank": [], "votes": []}))
    out["truth"] = {"note": "not available: the day is not over; truth for scoring comes from results/web/truth_daily.json after the close"}
    out["published_model"] = str(F.get("published_model", pd.Series(["?"])).iloc[0])
    ls = sh("gsutil", "ls", "-l", f"{B}/raw/daily/{d}/forecast_{d}.parquet").stdout.split()
    out["frozen_at"] = ls[1] if len(ls) > 1 else None          # write time of the frozen 00:05 forecast parquet (the scores' freeze)
    nj = sh("gsutil", "cat", f"{B}/raw/daily/{d}/arm3_input_nulls_{d}.json").stdout
    out["model_version"] = (f"arm3_live, {json.loads(nj).get('inputs')} inputs (00:05 forecast)" if nj else out["published_model"])
    out["shortlists"] = {f"top{m}": [r["id"] for r in out["launches"] if r["structural_rank"] and r["structural_rank"] <= m] for m in MS}
    out["written_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    out["on_time"] = bool(pd.Timestamp(out["written_at"]) < pd.Timestamp(f"{d} 03:45", tz="America/Los_Angeles"))
    out["backfill"] = os.environ.get("BACKFILL") == "1"            # written late from the same frozen scores (no refit)
    os.makedirs(os.path.join(OUT, d), exist_ok=True); f = os.path.join(OUT, d, "shortlist.json"); json.dump(out, open(f, "w"), indent=1)
    sh("gsutil", "-q", "cp", f, f"{B}/results/structural/{d}/shortlist.json")
    print(json.dumps({"day": d, "status": "ok", "launches": out["n_launches"], "structural_model": out["structural_model"], "on_time": out["on_time"]}))


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(HERE, ".."))
    backtest() if sys.argv[1] == "backtest" else live(sys.argv[2])
