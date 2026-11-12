"""More days for the pre-reveal API rank (orchestrator 01:45Z Nov 12). Sources found (see api_rank_replay.md):
  A  warehouse vote_snapshots (the deployed pipeline's hourly recorder, Oct 31 on): rank_now = the official API's
     dailyRank, also before the reveal (votes 0). Pre-reveal reads at ~00:07, 01:07, 02:07, 03:07 PT on Nov 2, 3, 4, 8,
     9, 10, 11.
  B  raw/daily/<d>/<d>.json: the pipeline's 00:05 pull, dailyRank per post (votes 0), Oct 28 - Nov 11 (no Nov 7).
  C  live/posts_ts.jsonl (15-min, Nov 4, 8, 9, 10, 11), already in api_rank_replay.py.
Scores each read time vs the final daily rank (top 3/5/10), next to the 00:05 LM, the comment ridge (replay P files) and
the blend (mean rank of API rank and comment ridge), per day; pooled with day-bootstrap CIs.
Also the 00:05 API rank on every day (source B), and the earliest 15-min cut where the API rank beats the LM (source C).
usage: python api_rank_more.py -> results/api_rank_more.json, appends to results/api_rank_replay.md"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores


def tk(order, truth, k):
    return len(set(order[:k]) & set(truth[:k])) / k * 100


def boot(v, rng):
    v = np.asarray(v, float)
    if len(v) < 5:
        return None
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]


def main():
    from pipeline import warehouse as W
    rng = np.random.default_rng(0)
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    V = W.query('SELECT "day" d, "at" a, hours_since_start h, CAST(launch_id AS VARCHAR) id, votes, rank_now FROM vote_snapshots', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    rows = []
    # A: hourly reads before the reveal
    for d, g in V[(V.h < 4) & (V.d < today)].groupby("d"):
        truth = R[R.day == d].sort_values("daily_rank").id.tolist()
        if len(truth) < 10:
            continue
        lm = lm_scores(d); ids = truth
        lmo = sorted(ids, key=lambda i: -lm.get(i, -99))
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        for cut in (1, 2, 3, 4):
            T = t0 + pd.Timedelta(hours=cut)
            S = g[g.a <= T].sort_values("a").groupby("id").rank_now.last()
            if S.empty:
                continue
            api = sorted(ids, key=lambda i: (S.get(i, 999), -lm.get(i, -99)))
            r = {"day": d, "cut": f"P{cut}", "source": "hourly", "read_at": str(g[g.a <= T].a.max()), "LM": [tk(lmo, truth, k) for k in (3, 5, 10)],
                 "api": [tk(api, truth, k) for k in (3, 5, 10)]}
            for pf in (os.path.join(HERE, "results", "early_forecast", f"{d}_P{cut}.json"), os.path.join(HERE, "results", "early_forecast_replay_P", f"{d}_P{cut}.json")):
                if os.path.exists(pf):
                    F = pd.DataFrame(json.load(open(pf))["forecast"]); F["id"] = F.id.astype(str)
                    cr = dict(zip(F.id, F.pred_rank))
                    rid = sorted(ids, key=lambda i: cr.get(i, 999))
                    ar = {i: n for n, i in enumerate(api)}; rr = {i: n for n, i in enumerate(rid)}
                    bl = sorted(ids, key=lambda i: ((ar[i] + rr[i]) / 2, -lm.get(i, -99)))
                    r["ridge"] = [tk(rid, truth, k) for k in (3, 5, 10)]; r["blend"] = [tk(bl, truth, k) for k in (3, 5, 10)]
                    break
            rows.append(r)
    # B: the 00:05 pull
    zero = []
    for d in sorted({p.split("/")[-2] for p in subprocess.run(["gsutil", "ls", f"{B}/raw/daily/*/"], capture_output=True, text=True).stdout.split() if p.endswith(".json")}):
        if d >= today:
            continue
        p = f"{tempfile.mkdtemp(prefix='ar_')}/d.json"
        if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/{d}.json", p]).returncode:
            continue
        P = json.load(open(p)); truth = R[R.day == d].sort_values("daily_rank").id.tolist()
        if len(truth) < 10:
            continue
        rk = {str(x["id"]): x.get("dailyRank") for x in P}
        lm = lm_scores(d)
        api = sorted(truth, key=lambda i: (rk.get(i) or 999, -lm.get(i, -99)))
        lmo = sorted(truth, key=lambda i: -lm.get(i, -99))
        zero.append({"day": d, "ranked_share": round(float(np.mean([rk.get(i) is not None for i in truth])), 2),
                     "votes_visible": int(sum((x.get("votesCount") or 0) > 0 for x in P)), "api_0005": [tk(api, truth, k) for k in (3, 5, 10)],
                     "LM": [tk(lmo, truth, k) for k in (3, 5, 10)] if lm else None})
    X = pd.DataFrame(rows)
    res = {"hourly_rows": rows, "pull_0005": zero}
    md = ["", "## More days: the pipeline's own hourly reads and the 00:05 pull (Nov 12)", "",
          "Sources checked:",
          "- raw/ph_at_launch/<day>/snapshots: each folder's pre-reveal files are the PREVIOUS PT day's launches continuing (the folder is the UTC date), so Nov 3 / Nov 7 add nothing new.",
          "- api_hourly / api_detail: start 00:01-01:31 PT only on days already covered (Nov 4, 8, 10, 11).",
          "- warehouse vote_snapshots: rank_now = the official API dailyRank, read hourly from ~00:07 PT, also before the reveal.",
          "- raw/daily/<d>/<d>.json: the pipeline's 00:05 pull with dailyRank.",
          "Nothing else in the bucket carries a per-post rank read before 04:00 PT on its launch day.", "",
          "### A. Hourly pre-reveal API rank (vote_snapshots), per day, top 3 / 5 / 10", "", "| day | cut | read at (UTC) | API rank | LM | comment ridge | blend |", "|---|---|---|---|---|---|---|"]
    f = lambda v: " / ".join(f"{x:.0f}" for x in v) if isinstance(v, list) else "-"
    for r in rows:
        md.append(f"| {r['day']} | {r['cut']} | {r['read_at'][11:16]} | {f(r['api'])} | {f(r['LM'])} | {f(r.get('ridge'))} | {f(r.get('blend'))} |")
    md += ["", "Pooled over days (mean, 95% day bootstrap when n >= 5):", "", "| cut | days | API rank | LM | API - LM top 3 | blend (days) |", "|---|---|---|---|---|---|"]
    for cut, g in X.groupby("cut"):
        a = np.array(g.api.tolist()); l = np.array(g.LM.tolist())
        cia = [boot(a[:, j], rng) for j in range(3)]; d3 = boot(a[:, 0] - l[:, 0], rng)
        bl = g.dropna(subset=["blend"]) if "blend" in g else g.iloc[:0]
        bs = " / ".join(f"{x:.1f}" for x in np.mean(bl.blend.tolist(), axis=0)) + f" ({len(bl)})" if len(bl) else "-"
        md.append(f"| {cut} | {len(g)} | " + " / ".join(f"{a[:, j].mean():.1f}" + (f" [{cia[j][0]:.0f}, {cia[j][1]:.0f}]" if cia[j] else "") for j in range(3))
                  + f" | {' / '.join(f'{x:.1f}' for x in l.mean(0))} | {(a[:, 0] - l[:, 0]).mean():+.1f}" + (f" [{d3[0]:+.0f}, {d3[1]:+.0f}]" if d3 else "") + f" | {bs} |")
    md += ["", "### B. The 00:05 pull's API dailyRank vs final, per day", "", "| day | share ranked | votes visible | API rank at 00:05 | LM |", "|---|---|---|---|---|"]
    for z in zero:
        md.append(f"| {z['day']} | {z['ranked_share']} | {z['votes_visible']} | {f(z['api_0005'])} | {f(z['LM'])} |")
    if zero:
        a = np.array([z["api_0005"] for z in zero]); md.append(f"| mean ({len(zero)} days) | | | {' / '.join(f'{x:.1f}' for x in a.mean(0))} | |")
    json.dump(res, open(os.path.join(HERE, "results", "api_rank_more.json"), "w"), indent=1, default=str)
    open(os.path.join(HERE, "results", "api_rank_replay.md"), "a").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
