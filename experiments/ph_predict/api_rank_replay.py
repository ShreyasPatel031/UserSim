"""Pre-reveal API rank (orchestrator 21:05Z Nov 11): the official API's post.dailyRank (live/posts_ts.jsonl
daily_rank_at_fetch, raw snapshots .dailyRank) is populated while votes are still hidden. Replay on every day whose
capture starts before 01:00 PT: at each 15-min cut 00:15..04:00 PT, rank by the latest daily_rank_at_fetch at or before T
(official API rows only, fetch 200; launches without a rank go last, LM breaks ties), vs final daily rank (warehouse), next
to the 00:05 LM and, at whole hours, the comment ridge (dry-run P files, CF_DRY dir) and the blend (mean of rank
positions of API rank and comment ridge). Also per day: first cut with ranks, share of line-up ranked, rank changes.
usage: CF_DRY=<dir with <day>_P*.json> python api_rank_replay.py -> results/api_rank_replay.json + .md"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores


def topk(g, col, k):
    return len(set(g.nsmallest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    days = sorted({p.split("/")[-3] for p in subprocess.run(["gsutil", "ls", f"{B}/raw/ph_at_launch/*/live/posts_ts.jsonl"], capture_output=True, text=True).stdout.split()})
    tmp = tempfile.mkdtemp(prefix="ar_"); dry = os.environ.get("CF_DRY")
    rows, info = [], {}
    for d in days:
        rk = R[R.day == d].set_index("id").daily_rank
        if len(rk) < 10:
            continue
        p = f"{tmp}/{d}.jsonl"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl", p], check=True)
        P = []
        for l in open(p):
            r = json.loads(l)
            if r.get("fetch_status") == 200 and str(r.get("source", "")).startswith("ph_api_v2") and str(r.get("day", d)) == d:
                P.append((pd.Timestamp(r["snapshot_ts"]), pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]),
                          r.get("daily_rank_at_fetch"), r.get("votes_at_fetch")))
        P = pd.DataFrame(P, columns=["ts", "fa", "id", "drank", "v"])
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        if P.empty or P.ts.min() > t0 + pd.Timedelta(hours=1):
            info[d] = {"first_snapshot": None if P.empty else str(P.ts.min()), "used": False}; continue
        lm = lm_scores(d); ids = list(rk.index)
        first_rank = P[P.drank.notna()].ts.min()
        info[d] = {"first_snapshot": str(P.ts.min()), "first_api_rank": str(first_rank), "launches": len(ids), "lm": bool(lm), "used": True}
        for m in range(15, 241, 15):
            T = t0 + pd.Timedelta(minutes=m)
            Q = P[(P.fa <= T) & P.drank.notna()]   # fetched by T (no look-ahead)
            Q = Q.sort_values("ts").groupby("id").last()
            G = pd.DataFrame({"id": ids, "rank": rk.values})
            G["lm"] = [lm.get(i, -99) for i in G.id]
            G["api"] = G.id.map(Q.drank).fillna(999) - 1e-6 * G.lm
            G["lmr"] = -G.lm
            stale = float((T - Q.fa.max()).total_seconds() / 60) if len(Q) else None
            r = {"day": d, "min": m, "ranked_share": round(float(G.id.isin(Q.index).mean()), 3), "minutes_since_last_fetch": stale,
                 "votes_visible": bool((P[(P.fa <= T)].v.fillna(0) > 0).mean() > 0.5) if len(P[P.fa <= T]) else False}
            for nm, c in (("api", "api"), ("LM", "lmr")):
                for k in (3, 5, 10):
                    r[f"{nm}_{k}"] = topk(G, c, k)
            if dry and m % 60 == 0 and os.path.exists(f"{dry}/{d}_P{m // 60}.json"):
                F = pd.DataFrame(json.load(open(f"{dry}/{d}_P{m // 60}.json"))["forecast"]).set_index("id")
                G["cr"] = G.id.map(F.pred_rank).fillna(999)
                G["blend"] = (G.api.rank() + G.cr.rank()) / 2 - 1e-6 * G.lm
                for nm in ("cr", "blend"):
                    for k in (3, 5, 10):
                        r[f"{nm}_{k}"] = topk(G, nm, k)
            rows.append(r)
    X = pd.DataFrame(rows)
    json.dump({"days": info, "rows": X.to_dict("records")}, open(os.path.join(HERE, "results", "api_rank_replay.json"), "w"), indent=1, default=str)
    print(json.dumps(info, indent=0))
    pd.set_option("display.width", 250)
    print(X.drop(columns=["day"]).groupby("min").mean(numeric_only=True).round(1).to_string())
    print(X[X["min"].isin([60, 120, 180, 240])][["day", "min", "ranked_share", "minutes_since_last_fetch", "votes_visible", "api_3", "api_5", "api_10", "LM_3", "LM_5", "LM_10"]].to_string())
    return X, info


if __name__ == "__main__":
    main()
