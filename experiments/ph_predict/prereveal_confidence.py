"""Per-pick confidence before the reveal (orchestrator 02:30Z Nov 12, item 2). Replay of pred_rank_best (api_depth.md:
weighted mean of the hidden API rank position and the 00:05 LM position, w_api 0.5 at P1, 0.75 at P2-P4) at P1..P4 on the
days with pre-reveal API ranks in the hourly recorder (vote_snapshots rank_now, reads <= 00:00 PT + h; P4 uses the last
read before 04:00 PT). For our pick #j: is it in the final daily top 3 (j <= 3) / top 5 (j <= 5)?
Conditioned on
  agree   |hidden-rank position - LM position| of the pick: <= 2 "agree", else "disagree"
  gap     est_votes of the pick / est_votes of our next pick (estvotes.py; days with 15-min weekly ranks, not Mondays):
          >= 1.5 "clear lead", else "close"
Intervals: Wilson 95% on launch-level hit rates (picks are not independent within a day; read them as rough).
usage: python prereveal_confidence.py -> results/web/prereveal_confidence.json + results/prereveal_confidence.md"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores


def wilson(k, n):
    if n == 0:
        return None
    p = k / n; z = 1.96; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def cell(g, col):
    k, n = int(g[col].sum()), int(g[col].notna().sum())
    return {"rate": round(100 * k / n, 1) if n else None, "hits": k, "n": n, "ci95": wilson(k, n)}


def main():
    from pipeline import warehouse as W
    import estvotes as EV
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    rows = []
    for d, g in V[V.d < today].groupby("d"):
        truth = R[R.day == d].sort_values("daily_rank").id.tolist()
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        if len(truth) < 10 or g[g.a <= t0 + pd.Timedelta(hours=1)].empty:
            continue
        lm = lm_scores(d)
        if not lm:
            continue
        lm_pos = pd.Series({i: -lm.get(i, -99) for i in sorted(truth)}).rank(method="first")
        E, _ = EV.earlier_votes(d)
        for h in (1, 2, 3, 4):
            T = t0 + pd.Timedelta(hours=h) - (pd.Timedelta(minutes=1) if h == 4 else pd.Timedelta(0))
            S = g[g.a <= T].sort_values("a").groupby("id").rank_now.last()
            if S.empty:
                continue
            api_pos = pd.Series({i: S.get(i, 999) for i in sorted(truth)}).rank(method="first")
            w = 0.5 if h == 1 else 0.75
            best = (w * api_pos + (1 - w) * lm_pos + 1e-6 * lm_pos).sort_values().index.tolist()
            ev = pd.Series(dtype=float)
            if not E.empty:
                X = EV.est_votes(d, T, E)
                if len(X):
                    ev = X.set_index("id").est_votes
            for j in range(5):
                i = best[j]; nxt = best[j + 1]
                gap = ev.get(i, np.nan) / ev.get(nxt, np.nan) if len(ev) and ev.get(nxt, 0) else np.nan
                rows.append({"day": d, "point": f"P{h}", "pick": j + 1, "id": i, "final_rank": truth.index(i) + 1,
                             "in_top3": float(truth.index(i) < 3) if j < 3 else np.nan, "in_top5": float(truth.index(i) < 5),
                             "agree": "agree" if abs(api_pos[i] - lm_pos[i]) <= 2 else "disagree",
                             "gap": np.nan if gap != gap else ("clear lead" if gap >= 1.5 else "close")})
    X = pd.DataFrame(rows); days = sorted(X.day.unique())
    out = {"replay": True, "n_days": len(days), "days": days, "method": "pred_rank_best (0.5 hidden API rank + 0.5 LM at P1; 0.75 / 0.25 at P2-P4)",
           "note": "Replay on past days, not live-scored; picks within a day are not independent, so intervals are rough.",
           "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "by_point": {}, "pooled_P1_P4": {}, "by_agreement": {}, "by_est_gap": {}}
    for p, g in X.groupby("point"):
        out["by_point"][p] = {f"pick{j}": {"in_top3": cell(gg, "in_top3") if j <= 3 else None, "in_top5": cell(gg, "in_top5")} for j, gg in g.groupby("pick")}
    for j, gg in X.groupby("pick"):
        out["pooled_P1_P4"][f"pick{j}"] = {"in_top3": cell(gg, "in_top3") if j <= 3 else None, "in_top5": cell(gg, "in_top5")}
    for a, gg in X.groupby("agree"):
        out["by_agreement"][a] = {"picks1_3_in_top3": cell(gg[gg.pick <= 3], "in_top3"), "picks1_5_in_top5": cell(gg, "in_top5")}
    Xg = X.dropna(subset=["gap"])
    out["by_est_gap"]["days"] = sorted(Xg.day.unique())
    for a, gg in Xg.groupby("gap"):
        out["by_est_gap"][a] = {"picks1_3_in_top3": cell(gg[gg.pick <= 3], "in_top3"), "picks1_5_in_top5": cell(gg, "in_top5")}
    os.makedirs(os.path.join(HERE, "results", "web"), exist_ok=True)
    p = os.path.join(HERE, "results", "web", "prereveal_confidence.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/prereveal_confidence.json"], check=True)
    f = lambda c: f"{c['rate']:.0f}% ({c['hits']}/{c['n']}) [{c['ci95'][0]:.0f}-{c['ci95'][1]:.0f}]" if c and c["n"] else "-"
    md = [f"# Per-pick confidence before the reveal (replay, {len(days)} days: {', '.join(days)})", "", out["method"] + ". " + out["note"], "",
          "## Hit rate of our pick #j", "", "| point | pick | in final top 3 | in final top 5 |", "|---|---|---|---|"]
    for p_, v in list(out["by_point"].items()) + [("P1-P4 pooled", out["pooled_P1_P4"])]:
        for k, c in v.items():
            md.append(f"| {p_} | {k[4:]} | {f(c['in_top3'])} | {f(c['in_top5'])} |")
    md += ["", "## By hidden-rank / LM agreement (|position difference| <= 2), P1-P4 pooled", "", "| | picks 1-3 in top 3 | picks 1-5 in top 5 |", "|---|---|---|"]
    md += [f"| {a} | {f(v['picks1_3_in_top3'])} | {f(v['picks1_5_in_top5'])} |" for a, v in out["by_agreement"].items()]
    md += ["", f"## By est_votes gap to our next pick (>= 1.5x = clear lead), P1-P4 pooled, days {', '.join(out['by_est_gap']['days'])}", "",
           "| | picks 1-3 in top 3 | picks 1-5 in top 5 |", "|---|---|---|"]
    md += [f"| {a} | {f(v['picks1_3_in_top3'])} | {f(v['picks1_5_in_top5'])} |" for a, v in out["by_est_gap"].items() if a != "days"]
    open(os.path.join(HERE, "results", "prereveal_confidence.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
