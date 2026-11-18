"""Per-launch vote estimates at 03:45 PT (Shreyas: "why do the 03:45 votes not change"; orchestrator 23:47Z Nov 14). PRE-REGISTERED.

Days: every day Oct 25 - Nov 13 with a 03:45 hidden-order read (raw/vote_snapshots recorder, the writer's own source), >= 10 launches
with final votes. Per launch at T = 03:45 PT (latest recorder read in [02:40, 03:46]):
  pos      hidden daily order (rank_now) at T            nc   comments at T (recorder)
  prior    00:05 expected log votes (clean_nosite as-of-night rows, the prior prereveal_12day.py uses)
  wk       weekly-rank bracket estimate at T (estvotes.est_votes; needs posts_ts weekly ranks and a non-Monday; else missing)
Methods (all leave-one-day-out where anything is fitted):
  B0 slot   CURRENT: the 00:05 expected votes sorted high->low, handed out by the 03:45 hidden-order slot
  M1 ridge  log1p(votes) ~ log pos + log1p nc + prior (+ log wk and a has-wk flag), ridge alpha 1, fitted on the other days
  Mw        the weekly bracket estimate where present, else B0
Stated range: estimate x exp(10th..90th percentile of the method's own log errors on the other days) (an 80% range).
Truth: final votes (warehouse launches) and votes at the reveal (first recorder read at/after 04:00 PT where >= half the launches show votes).
Metrics per day: median absolute % error, within-day Spearman, share inside the stated range. PRIMARY: M1 - B0 median abs % error vs
FINAL votes, paired by day, day bootstrap 95% (4000); M1 wins if the interval is below 0 and within-day Spearman is not worse beyond noise.
usage: python prereveal_votes.py -> results/prereveal_votes.{json,md}"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
R = lambda p: os.path.join(HERE, "results", p)
TMP = tempfile.mkdtemp()


def get(path):
    p = f"{TMP}/{abs(hash(path))}_{os.path.basename(path)}"
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def priors():
    CL = pd.read_parquet(R("clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    clean = {d: dict(zip(g.id, g.clean_v3_nosite)) for d, g in CL.groupby("day")}
    for f in glob.glob(R("shadow_makerfix/*.json")):
        d = os.path.basename(f)[:10]
        if d not in clean:
            S = pd.DataFrame(json.load(open(f))["forecast"]); col = "pred_clean_nosite" if "pred_clean_nosite" in S else "pred_clean" if "pred_clean" in S else None
            if col: clean[d] = dict(zip(S.id.astype(str), S[col]))
    TWn = pd.read_parquet(R("tw_nosite.parquet")); TWn["id"] = TWn.id.astype(str)
    for d, g in TWn.dropna(subset=["clean_v3_nosite"]).groupby("day"):
        if d >= "2026-10-25" and d not in clean: clean[d] = dict(zip(g.id, g.clean_v3_nosite))
    return clean


def build():
    sys.path.insert(0, os.path.dirname(HERE)); from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, CAST(day AS VARCHAR) AS day, votes FROM launches WHERE votes IS NOT NULL AND CAST(day AS VARCHAR) >= '2026-10-25'", do_sync=False)
    L["day"] = L.day.str[:10]; clean = priors(); rows = []
    import estvotes as EV
    for d in pd.date_range("2026-10-25", "2026-11-13").strftime("%Y-%m-%d"):
        f = get(f"{B}/raw/vote_snapshots/{d}.jsonl")
        if not f: continue
        V = pd.DataFrame([json.loads(l) for l in open(f)]); V["id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True)
        V = V.drop_duplicates(["id", "a"])
        pt = lambda hm: pd.Timestamp(f"{d} {hm}", tz="America/Los_Angeles").tz_convert("UTC")
        S = V[(V.a >= pt("02:40")) & (V.a <= pt("03:46")) & V.rank_now.notna()].sort_values("a").groupby("id").last()
        if len(S) < 10: continue
        after = V[V.a >= pt("04:00")]; g = after.groupby("a").votes.apply(lambda x: (x.fillna(0) > 0).mean()).sort_index(); ok = g[g >= 0.5]
        rv = after[after.a == ok.index.min()].groupby("id").votes.last() if len(ok) else pd.Series(dtype=float)
        fin = L[L.day == d].set_index("id").votes.astype(float)
        try:
            wk = EV.est_votes(d, pt("03:46")); wk = dict(zip(wk.id.astype(str), wk.est_votes)) if len(wk) else {}
        except Exception:
            wk = {}
        pr = clean.get(d, {})
        for i, r in S.iterrows():
            rows.append({"day": d, "id": i, "pos": float(r.rank_now), "nc": float(r.comments or 0), "prior": pr.get(i, np.nan),
                         "wk": wk.get(i, np.nan), "final": fin.get(i, np.nan), "reveal": float(rv.get(i, np.nan)) if len(rv) else np.nan})
    X = pd.DataFrame(rows); X = X[X.final.notna()]
    X["pos"] = X.groupby("day").pos.rank(method="first")
    X["prior"] = X.prior.fillna(X.groupby("day").prior.transform("min") - 0.1)
    return X[X.groupby("day").id.transform("size") >= 10]


def methods(X):
    X = X.copy(); X["has_prior"] = X.prior.notna()
    # B0: 00:05 expected votes sorted, by hidden slot
    def slot(g):
        lv = np.sort(np.expm1(g.prior.values))[::-1]; return pd.Series(lv[(g.pos.values - 1).astype(int).clip(0, len(lv) - 1)], index=g.index)
    X["B0"] = X.groupby("day", group_keys=False).apply(slot)
    X["Mw"] = np.where(X.wk.notna(), X.wk, X.B0)
    feats = lambda Z: pd.DataFrame({"lpos": np.log(Z.pos), "lnc": np.log1p(Z.nc), "prior": Z.prior, "lwk": np.log1p(Z.wk.fillna(0)), "has_wk": Z.wk.notna().astype(float)})
    X["M1"] = np.nan
    for d in X.day.unique():
        tr, te = X[X.day != d], X[X.day == d]
        m = Ridge(alpha=1.0).fit(feats(tr), np.log1p(tr.final)); X.loc[te.index, "M1"] = np.expm1(m.predict(feats(te)))
    return X


def score(X, truth):
    out = {}; M = ["B0", "M1", "Mw"]; days = sorted(X.day.unique())
    # LODO 80% range from each method's log errors on the other days
    for m in M:
        X[f"le_{m}"] = np.log1p(X[truth]) - np.log1p(X[m])
    per = {m: [] for m in M}
    for d in days:
        g = X[(X.day == d) & X[truth].notna()]
        if len(g) < 5: continue
        oth = X[(X.day != d) & X[truth].notna()]
        for m in M:
            q10, q90 = np.percentile(oth[f"le_{m}"].dropna(), [10, 90])
            lo, hi = np.expm1(np.log1p(g[m]) + q10), np.expm1(np.log1p(g[m]) + q90)
            ape = float(np.median(np.abs(g[m] - g[truth]) / g[truth].clip(lower=1)) * 100)
            rho = float(g[m].rank().corr(g[truth].rank()))
            inr = float(((g[truth] >= lo) & (g[truth] <= hi)).mean() * 100)
            per[m].append((d, ape, rho, inr))
    rng = np.random.default_rng(0)
    for m in M:
        A = np.array([p[1:] for p in per[m]]); out[m] = {"n_days": len(A), "median_abs_pct_err": round(float(A[:, 0].mean()), 1),
                                                          "spearman": round(float(A[:, 1].mean()), 3), "in_range_pct": round(float(A[:, 2].mean()), 1)}
    for m in ("M1", "Mw"):
        A = np.array([p[1:] for p in per[m]]); B0 = np.array([p[1:] for p in per["B0"]]); D = A - B0; n = len(D)
        bs = np.array([D[rng.integers(0, n, n)].mean(0) for _ in range(4000)])
        out[f"{m}_minus_B0"] = {k: [round(float(D[:, j].mean()), 3), round(float(np.percentile(bs[:, j], 2.5)), 3), round(float(np.percentile(bs[:, j], 97.5)), 3)]
                                for j, k in enumerate(["median_abs_pct_err", "spearman", "in_range_pct"])}
    out["per_day"] = {m: {p[0]: [round(p[1], 1), round(p[2], 3), round(p[3], 1)] for p in per[m]} for m in M}
    return out


if __name__ == "__main__":
    X = methods(build())
    res = {"method": __doc__, "days": sorted(X.day.unique()), "launches": int(len(X)), "with_wk": int(X.wk.notna().sum()),
           "with_reveal": int(X.reveal.notna().sum()), "final": score(X, "final"), "reveal": score(X, "reveal")}
    m = Ridge(alpha=1.0).fit(pd.DataFrame({"lpos": np.log(X.pos), "lnc": np.log1p(X.nc), "prior": X.prior, "lwk": np.log1p(X.wk.fillna(0)), "has_wk": X.wk.notna().astype(float)}), np.log1p(X.final))
    res["M1_all_days_fit"] = {"coef": dict(zip(["lpos", "lnc", "prior", "lwk", "has_wk"], np.round(m.coef_, 4))), "intercept": round(float(m.intercept_), 4)}
    X.to_parquet(R("prereveal_votes_rows.parquet"))
    json.dump(res, open(R("prereveal_votes.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k not in ("method",)}, default=float, indent=1)[:5000])
