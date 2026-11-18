"""Pre-launch comment votes (orchestrator 02:14Z Nov 13; counts only). Live comment feed raw/ph_at_launch/<d>/live/comments_ts.jsonl
(field votes_at_fetch). Per launch: comments created <= 00:05 PT of the day by non-hunters (is_hunter false); each comment's votes =
its latest votes_at_fetch with fetched_at <= CUT (default 01:00 PT, the orchestrator's 11-day read; live column uses the P point T).
Features: pcv_sum = log1p(sum votes), pcv_max = log1p(max votes), pcv_n2 = number of pre-launch comments with 2+ votes.
Days used = days whose feed has at least one fetch <= CUT. Base = ridge on z(clean_v3_nosite live OOF) + z(th_n_pre).
LODO top 3/5/10 vs base with paired day bootstrap; then freeze weights on all used days ->
results/frozen/clean_nosite_pcv_20261113.json (labelled THIN). usage: python precomment_votes.py [cut_hhmm]"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
import prior_blend as PB
from sklearn.linear_model import Ridge
FEATS = ["pcv_sum", "pcv_max", "pcv_n2"]


def feats(day, rows, cut):
    """rows: comment dicts of one day; cut: UTC Timestamp. Returns {launch_id: {pcv_*}} using reads fetched <= cut."""
    t5 = (pd.Timestamp(day, tz="America/Los_Angeles") + pd.Timedelta(minutes=5)).tz_convert("UTC")
    best = {}
    for r in rows:
        if r.get("is_hunter") or r.get("votes_at_fetch") is None:
            continue
        try:
            fa = pd.Timestamp(r["fetched_at"]); ca = pd.Timestamp(r["created_at"])
        except Exception:
            continue
        fa = fa.tz_localize("UTC") if fa.tzinfo is None else fa.tz_convert("UTC"); ca = ca.tz_localize("UTC") if ca.tzinfo is None else ca.tz_convert("UTC")
        if fa > cut or ca > t5:
            continue
        k = (str(r["launch_id"]), str(r["comment_id"]))
        if k not in best or fa >= best[k][0]:
            best[k] = (fa, float(r["votes_at_fetch"]))
    out = {}
    for (lid, _), (_, v) in best.items():
        o = out.setdefault(lid, [])
        o.append(v)
    return {lid: {"pcv_sum": float(np.log1p(sum(v))), "pcv_max": float(np.log1p(max(v))), "pcv_n2": float(sum(x >= 2 for x in v))} for lid, v in out.items()}


def load(day):
    p = subprocess.run(["gsutil", "-q", "cat", f"{B}/raw/ph_at_launch/{day}/live/comments_ts.jsonl"], capture_output=True, text=True)
    return [json.loads(l) for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else []


def main():
    from pipeline import warehouse as W
    hh = sys.argv[1] if len(sys.argv) > 1 else "01:00"
    Q = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-26' AND day <= '2026-11-12'", do_sync=False)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    X = Q.merge(CL[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    F, used, nrows = {}, [], {}
    for d in sorted(X.day.unique()):
        rows = load(d); cut = (pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(hours=int(hh[:2]), minutes=int(hh[3:]))).tz_convert("UTC")
        if not any(pd.Timestamp(r["fetched_at"]).tz_convert("UTC") <= cut for r in rows if r.get("fetched_at")):
            continue
        used.append(d); f = feats(d, rows, cut); F.update(f); nrows[d] = len(f)
    X = X[X.day.isin(used)].copy()
    for c in FEATS:
        X[c] = X.id.map({k: v[c] for k, v in F.items()}).fillna(0.0)
    npre = {}
    for d in used:
        E, _, _ = PB.thread(d, X[X.day == d].id.tolist()); npre.update(E.th_n_pre.to_dict())
    X["npre"] = X.id.map(npre).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ["clean", "npre"] + FEATS:
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    def lodo(cols):
        o_ = []
        for d in days:
            te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(o_)
    BASE = ["z_clean", "z_npre"]; base = lodo(BASE)
    res = X.y - Ridge(alpha=3.0).fit(X[BASE], X.y).predict(X[BASE])
    md = [f"# Pre-launch comment votes (live feed, reads <= {hh} PT; {len(days)} days {days[0]}..{days[-1]}; {len(X)} ranked launches; THIN)", "",
          f"Launches with any pre-launch non-hunter comment read: {int((X.pcv_sum > 0).sum() + ((X.pcv_sum == 0) & X.id.isin(F.keys())).sum())}; "
          "residual Spearman vs base (in-sample): " + ", ".join(f"{c} {pd.Series(X[c]).rank().corr(res.rank()):+.2f}" for c in FEATS), "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for nm, cols in (("+ pcv_sum", ["z_pcv_sum"]), ("+ pcv_max", ["z_pcv_max"]), ("+ pcv_n2", ["z_pcv_n2"]), ("+ all three", ["z_pcv_sum", "z_pcv_max", "z_pcv_n2"])):
        P = lodo(BASE + cols); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    fp = os.path.join(HERE, "results", "frozen", "clean_nosite_pcv_20261113.json")
    if hh == "01:00" and not os.path.exists(fp):
        cols = BASE + ["z_" + c for c in FEATS]; m = Ridge(alpha=3.0).fit(X[cols], X.y)
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "label": "THIN", "days": days, "cut": "reads <= 01:00 PT",
                   "coef": dict(zip(cols, map(float, m.coef_))), "features": "z within day; pcv_* from comments created <= 00:05 PT by non-hunters"},
                  open(fp, "w"), indent=1)
        md += ["", f"Frozen weights -> {os.path.relpath(fp, HERE)}"]
    out = os.path.join(HERE, "results", f"precomment_votes{'' if hh == '01:00' else '_' + hh.replace(':', '')}.md")
    open(out, "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
