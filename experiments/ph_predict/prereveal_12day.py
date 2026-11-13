"""Pre-reveal lines on every replay day with hidden ranks (orchestrator 21:00Z Nov 13). Points P1 / P2 / P3 / P345 (01:00 / 02:00 / 03:00 /
03:45 PT). Hidden rank at T = latest read <= T (live posts_ts daily_rank_at_fetch, else warehouse vote_snapshots rank_now); comments from live
comments_ts (created <= T). Lines (frozen weights where they exist: results/frozen/prereveal_hr_clean_20261113.json, P345 its own file):
  hr            hidden order as is
  hr_clean      frozen ridge z(log pos), z(move since 01:00), z(log1p comments), z(log1p commenters), z(prior)   [published P1, P2]
  best_cnosite  w x hidden pos + (1-w) x prior pos (w 0.5 at P1, 0.75 after; as live)
  hybrid        hidden top 5 + hr_clean order for 6+                                                             [published P3, P345]
Prior = clean_nosite 00:05 score (clean_live_rows_nosite + shadow_makerfix pred_clean_nosite) or arm 2 (history_retrain_decomp_preds_nov_arm2
'both', month-fold; built from final-read inputs, so a mild advantage vs a live 00:05 read). The frozen weights were fit on the 7 old days, so the
5 new days are out-of-sample. Label = dailyRank. Paired day bootstrap vs the published line at each point.
usage: python prereveal_12day.py -> results/prereveal_12day.md"""
import json, os, subprocess, sys, tempfile, glob
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
TMP = os.environ.get("TMPDIR", "/tmp")
HS = {"P1": 1, "P2": 2, "P3": 3, "P345": 3.75}
OLD = {"2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"}
PUB = {"P1": "hr_clean", "P2": "hr_clean", "P3": "hybrid", "P345": "hybrid"}


def get(path):
    p = tempfile.mkdtemp(dir=TMP) + "/" + os.path.basename(path)
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    # raw recorder files (E5 23:45Z Nov 13): the warehouse vote_snapshots table misses the pre-reveal rows of Nov 5-7; dedup (launch, at)
    VR = []
    for d_ in pd.date_range("2026-10-25", "2026-11-13").strftime("%Y-%m-%d"):
        f_ = get(f"{B}/raw/vote_snapshots/{d_}.jsonl")
        if f_:
            VR += [json.loads(l) for l in open(f_)]
    V = pd.DataFrame(VR).dropna(subset=["rank_now"]).rename(columns={"day": "d", "at": "a", "launch_id": "id"})[["d", "a", "id", "rank_now"]]
    V["id"] = V.id.astype(str); V["a"] = pd.to_datetime(V.a, utc=True); V = V.drop_duplicates(["id", "a"])
    CL = pd.read_parquet(f"{HERE}/results/clean_live_rows_nosite.parquet"); CL["id"] = CL.id.astype(str)
    clean = {d: dict(zip(g.id, g.clean_v3_nosite)) for d, g in CL.groupby("day")}; CLSUB = set()
    for f in glob.glob(f"{HERE}/results/shadow_makerfix/*.json"):
        d = os.path.basename(f)[:10]
        if d not in clean:
            S = pd.DataFrame(json.load(open(f))["forecast"])
            col = "pred_clean_nosite" if "pred_clean_nosite" in S else "pred_clean" if "pred_clean" in S else None   # Nov 12 file predates the nosite column
            if col:
                clean[d] = dict(zip(S.id.astype(str), S[col])); CLSUB.add(d) if col == "pred_clean" else None
    TWn = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); TWn["id"] = TWn.id.astype(str)   # month-fold clean_nosite stand-in (Nov 5-7)
    for d_, g_ in TWn.dropna(subset=["clean_v3_nosite"]).groupby("day"):
        if d_ >= "2026-10-25" and d_ not in clean:
            clean[d_] = dict(zip(g_.id, g_.clean_v3_nosite)); CLSUB.add(d_)
    A2 = pd.read_parquet(f"{HERE}/results/history_retrain_decomp_preds_nov_arm2.parquet"); A2["id"] = A2.id.astype(str)
    arm2 = {d: dict(zip(g.id, g.both)) for d, g in A2.groupby("day")}
    FZ = json.load(open(f"{HERE}/results/frozen/prereveal_hr_clean_20261113.json"))["points"]
    FZ.update(json.load(open(f"{HERE}/results/frozen/prereveal_hr_clean_P345_20261113.json"))["points"])
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    res, info = {}, {}
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
        H = pd.DataFrame(H, columns=["a", "id", "r"]); G = V[V.d == d].rename(columns={"rank_now": "r"})[["a", "id", "r"]]
        cp = get(f"{B}/raw/ph_at_launch/{d}/live/comments_ts.jsonl"); C = pd.DataFrame(columns=["id", "u", "ts"])
        if cp:
            C = pd.DataFrame([json.loads(l) for l in open(cp)]).drop_duplicates("comment_id")
            C = pd.DataFrame({"id": C.launch_id.astype(str), "u": C.commenter_user_id.fillna(C.get("user_id")).astype(str),
                              "ts": pd.to_datetime(C.created_at, utc=True, errors="coerce")})
        pos, src = {}, {}
        for p, h in [("P0", 1)] + list(HS.items()):
            S = H[H.a <= t0 + pd.Timedelta(hours=h)].sort_values("a").groupby("id").r.last(); src[p] = "posts_ts"
            if S.empty:
                S = G[G.a <= t0 + pd.Timedelta(hours=h)].sort_values("a").groupby("id").r.last(); src[p] = "vote_snapshots"
            if not S.empty:
                pos[p] = pd.Series({i: S.get(i, 999) for i in ids}).rank(method="first")
        if "P3" not in pos or "P1" not in pos:
            continue
        info[d] = {"src": src.get("P3"), "comments": bool(cp), "clean": d in clean, "arm2": d in arm2, "new": d not in OLD}
        t = truth.id.tolist()
        for p, h in HS.items():
            if p not in pos:
                continue
            T = t0 + pd.Timedelta(hours=h); Ch = C[C.ts <= T]
            posT = pos[p]; cC = Ch.groupby("id").size(); cU = Ch.groupby("id").u.nunique()
            base = pd.DataFrame({"lpos": np.log(posT), "move": np.log(pos["P1"]) - np.log(posT),
                                 "nc": np.log1p(pd.Series(ids, index=ids).map(cC).fillna(0)), "nu": np.log1p(pd.Series(ids, index=ids).map(cU).fillna(0))}, index=ids)
            o_hr = posT.sort_values(kind="stable").index.tolist()
            res.setdefault((p, "hr"), {})[d] = hits(o_hr, t)
            w = 0.5 if p == "P1" else 0.75
            for pn, prior in (("clean", clean), ("arm2", arm2)):
                if d not in prior:
                    continue
                Z = base.copy(); Z["clean"] = pd.Series(ids, index=ids).map(prior.get(d, {})).astype(float); Z["clean"] = Z.clean.fillna(Z.clean.mean() if Z.clean.notna().any() else 0)
                sc = sum(zf(Z[f.replace("z_", "")]) * c for f, c in FZ[p]["coef"].items())
                o_hc = sc.sort_values(ascending=False, kind="stable").index.tolist()
                cpos = Z.clean.rank(ascending=False, method="first")
                o_bc = (w * posT + (1 - w) * cpos + 1e-6 * cpos).sort_values(kind="stable").index.tolist()
                o_hy = o_hr[:5] + [i for i in o_hc if i not in set(o_hr[:5])]
                suf = "" if pn == "clean" else "_arm2"
                for nm, o in (("hr_clean", o_hc), ("best_cnosite", o_bc), ("hybrid", o_hy)):
                    res.setdefault((p, nm + suf), {})[d] = hits(o, t)
    rng = np.random.default_rng(0); days = sorted(info); new = [d for d in days if info[d]["new"]]
    md = ["# Pre-reveal lines on every replay day with hidden ranks (orchestrator 21:00Z Nov 13)", "",
          f"Days ({len(days)}): {', '.join(d[5:] for d in days)}; new vs the 7-day freeze ({len(new)}): {', '.join(d[5:] for d in new)}. "
          "Frozen weights (fit on the 7 old days) -> the new days are out-of-sample. Label = dailyRank. Diff = shadow minus the published line at that point, paired, day bootstrap 95%.", "",
          "Day sources: " + "; ".join(f"{d[5:]} {info[d]['src']}{'' if info[d]['comments'] else ' no-comments'}{'' if info[d]['clean'] else ' no-clean'}{' clean stand-in (clean-with-site 00:05 or month-fold clean_nosite)' if d in CLSUB else ''}{'' if info[d]['arm2'] else ' no-arm2'}" for d in days), "",
          "| point | line | days | top 3 | top 5 | top 10 | diff vs published, all days (t3 / t5 / t10) | new days only: diff (t3 / t5 / t10) |", "|---|---|---|---|---|---|---|---|"]
    def ci(a, b):
        dd = a - b; bs = np.array([dd[rng.integers(0, len(dd), len(dd))].mean(0) for _ in range(4000)])
        return dd.mean(0), np.percentile(bs, 2.5, 0), np.percentile(bs, 97.5, 0)
    verdict = []
    for p in HS:
        pub = res.get((p, PUB[p]), {})
        for nm in ("hr", "hr_clean", "best_cnosite", "hybrid", "hr_clean_arm2", "best_cnosite_arm2", "hybrid_arm2"):
            r = res.get((p, nm), {}); dd = [d for d in days if d in r and d in pub]
            if not dd:
                continue
            X = np.array([r[d] for d in dd]); P = np.array([pub[d] for d in dd])
            m, lo, hi = ci(X, P); dn = [i for i, d in enumerate(dd) if d in new]
            mn = (X[dn] - P[dn]).mean(0) if dn else [np.nan] * 3
            tag = " (published)" if nm == PUB[p] else ""
            md.append(f"| {p} | {nm}{tag} | {len(dd)} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | " +
                      ("-" if tag else " / ".join(f"{m[k]:+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3))) + f" | {'-' if tag else ' / '.join(f'{v:+.1f}' for v in mn)} ({len(dn)}) |")
            if not tag:
                for k, kn in ((0, "top 3"), (1, "top 5"), (2, "top 10")):
                    if lo[k] > 0 and mn[k] > 0 and (k == 0 or m[0] >= 0):
                        verdict.append(f"{p} {nm} {kn}: {m[k]:+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}] on {len(dd)} days, new days {mn[k]:+.1f} -> QUALIFIES")
                    elif m[k] > 0:
                        se = (hi[k] - lo[k]) / 3.92
                        need = int(np.ceil(len(dd) * (1.96 * se / m[k]) ** 2)) if m[k] > 0 else None
                        verdict.append(f"{p} {nm} {kn}: {m[k]:+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]; at this effect ~{need} days total for the interval to clear 0 (~{max(0, need - len(dd))} more)")
    md += ["", "## Rule-5 check (all days interval > 0 AND same sign on the new days; top 3 not worse)", ""] + [f"- {v}" for v in verdict]
    open(f"{HERE}/results/prereveal_12day.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
