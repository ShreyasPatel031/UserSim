"""Why is our reveal-time (R0) forecast ~10 points below E5's Wayback 04:00-05:00 PT buckets? (orchestrator 22:55Z Nov 11)
On every day whose live/posts_ts.jsonl (15-min official API snapshots) covers the reveal:
  timing   per snapshot around the reveal: share of launches showing votes > 0, share with hide_votes_count, R0 (first
           snapshot with >= half showing votes, as early_forecast.reveal), and the first snapshot with >= 90% showing votes
  scores   rank by raw votes at R0 + 0/15/30/45/60 min (latest fetched_at <= cut), also dropping zero-vote rows to the
           bottom by LM, vs (a) final daily rank and (b) final votes; top 3/5/10
  line-up  ranked launches absent from the API rows at R0 (or with fetch errors), and how many finished top 10
usage: python reveal_gap.py -> results/reveal_gap.json + .md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores


def load(day):
    p = f"{tempfile.mkdtemp(prefix='rg_')}/p.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/posts_ts.jsonl", p]).returncode:
        return None
    rows = []
    for l in open(p):
        r = json.loads(l)
        if str(r.get("day", day)) != day or not str(r.get("source", "")).startswith("ph_api_v2"):
            continue
        rows.append((pd.Timestamp(r["snapshot_ts"]), pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]), r.get("fetch_status"),
                     r.get("votes_at_fetch"), bool(r.get("hide_votes_count"))))
    return pd.DataFrame(rows, columns=["ts", "fa", "id", "st", "v", "hid"])


def topk(order, truth, k):
    return len(set(order[:k]) & set(truth[:k])) / k * 100


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-25'", do_sync=False)
    out, md = [], ["# Reveal-time gap (live 15-min API snapshots)", ""]
    for day in sorted(R.day.unique()):
        P = load(day)
        if P is None or P.empty:
            continue
        P = P[P.st == 200]
        t0 = pd.Timestamp(day + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        if P.ts.min() > t0 + pd.Timedelta(hours=3.5):
            continue
        g = P.groupby("ts").agg(n=("id", "nunique"), nz=("v", lambda x: float((pd.to_numeric(x, errors="coerce").fillna(0) > 0).mean())),
                                hid=("hid", "mean")).sort_index()
        r0s = g[g.nz >= 0.5]; r90 = g[g.nz >= 0.9]
        if r0s.empty:
            continue
        R0 = r0s.index.min(); R90 = r90.index.min() if len(r90) else None
        f = R[R.day == day]; truth_rank = f.sort_values("daily_rank").id.tolist(); truth_votes = f.sort_values("votes", ascending=False).id.tolist()
        lm = lm_scores(day)
        row = {"day": day, "R0": str(R0), "R0_PT": R0.tz_convert("America/Los_Angeles").strftime("%H:%M"), "R90": str(R90),
               "nz_at_R0": round(float(g.loc[R0, "nz"]), 3), "hid_at_R0": round(float(g.loc[R0, "hid"]), 3),
               "rank_vs_votes_truth_top3": topk(truth_votes, truth_rank, 3), "rank_vs_votes_truth_top5": topk(truth_votes, truth_rank, 5),
               "rank_vs_votes_truth_top10": topk(truth_votes, truth_rank, 10)}
        seen_R0 = set(P[(P.fa <= R0 + pd.Timedelta(minutes=5))].id)
        miss = f[~f.id.isin(seen_R0)]
        row["missing_at_R0"] = int(len(miss)); row["missing_top10"] = int((miss.daily_rank <= 10).sum())
        for off in (0, 15, 30, 45, 60, 120):
            T = R0 + pd.Timedelta(minutes=off)
            S = P[P.fa <= T + pd.Timedelta(minutes=5)].sort_values("fa").groupby("id").v.last()
            S = pd.to_numeric(S, errors="coerce").fillna(0)
            G = pd.DataFrame({"id": f.id}); G["v"] = G.id.map(S).fillna(0); G["lm"] = [lm.get(i, -99) for i in G.id]
            o = (G.v + 1e-6 * G.lm).sort_values(ascending=False).index; order = G.loc[o].id.tolist()
            row[f"+{off}"] = {"vs_rank": [topk(order, truth_rank, k) for k in (3, 5, 10)], "vs_votes": [topk(order, truth_votes, k) for k in (3, 5, 10)],
                              "share_zero": round(float((G.v == 0).mean()), 3)}
        out.append(row); print(json.dumps({k: v for k, v in row.items() if not k.startswith("+")}), json.dumps(row["+0"]), json.dumps(row["+30"]))
    X = out
    md += [f"Days: {', '.join(r['day'] for r in X)}.", "", "| day | R0 (PT) | shown >0 at R0 | hide flag at R0 | missing at R0 (top-10 among them) | votes-order vs final rank, top 3/5/10 |", "|---|---|---|---|---|---|"]
    for r in X:
        md.append(f"| {r['day']} | {r['R0_PT']} | {r['nz_at_R0']:.2f} | {r['hid_at_R0']:.2f} | {r['missing_at_R0']} ({r['missing_top10']}) | {r['rank_vs_votes_truth_top3']:.0f} / {r['rank_vs_votes_truth_top5']:.0f} / {r['rank_vs_votes_truth_top10']:.0f} |")
    md += ["", "Raw votes at R0 + offset, mean over the days, top 3 / 5 / 10 (vs final daily rank; vs final votes):", "", "| offset | vs final rank | vs final votes | share of line-up still at 0 |", "|---|---|---|---|"]
    for off in (0, 15, 30, 45, 60, 120):
        a = np.mean([r[f"+{off}"]["vs_rank"] for r in X], axis=0); b = np.mean([r[f"+{off}"]["vs_votes"] for r in X], axis=0)
        z = np.mean([r[f"+{off}"]["share_zero"] for r in X])
        md.append(f"| +{off} min | {a[0]:.1f} / {a[1]:.1f} / {a[2]:.1f} | {b[0]:.1f} / {b[1]:.1f} / {b[2]:.1f} | {z:.2f} |")
    json.dump(X, open(os.path.join(HERE, "results", "reveal_gap.json"), "w"), indent=1, default=str)
    open(os.path.join(HERE, "results", "reveal_gap.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
