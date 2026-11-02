"""C1: the product's existing user base before launch, from dated public records (Data Feeder's raw/github_stargazers/
and raw/pkg_downloads/), as a pre-launch input.
Expected inputs (JSON lines or CSV, any file names under each folder; the script fails loudly on a missing column):
  stars:      repo ("owner/name"), date (YYYY-MM-DD), stars   (new stars that day; daily star history)
  downloads:  package, registry (npm | pypi), date (YYYY-MM-DD), downloads   (that day)
Launch -> repos / packages: tmp/ph_ops/c1_repos.json ({launch_id: {day, repos, npm, pypi}}).
Per launch, counting only days strictly before the launch's Pacific day (launch-day counts excluded):
  c1_stars        log1p(max over the launch's repos of stars accumulated up to day-1)
  c1_stars_30     log1p(max over repos of new stars in the 30 days before)
  c1_repo_age     days from the repo's first star-history date to day-1 (largest repo)
  c1_dl_7 / c1_dl_30 / c1_dl_90   log1p(max over packages of downloads in the 7 / 30 / 90 days before)
Missing (no repo / package, or no history before the day) stays NaN.
Then userbase_eval: residual-Spearman gate vs the honest model, and daily / weekly / monthly top 3/5/10 vs the honest
day-calibrated control.
usage: SIMLAB_DATA=data_v2 python c1_user_base.py <c1_repos.json> <stars dir> [downloads dir] -> results/c1_user_base.json"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd
import userbase_eval as UE

COLS = ["c1_stars", "c1_stars_30", "c1_repo_age", "c1_dl_7", "c1_dl_30", "c1_dl_90"]


def read_any(path, what):
    files = [path] if os.path.isfile(path) else sorted(glob.glob(os.path.join(path, "**", "*"), recursive=True))
    files = [f for f in files if os.path.isfile(f) and f.endswith((".jsonl", ".jsonl.gz", ".json", ".csv", ".csv.gz"))
             and "README" not in os.path.basename(f).upper()]
    if not files:
        raise SystemExit(f"{what}: no .jsonl / .json / .csv files under {path}")
    out = []
    for f in files:
        if ".csv" in f:
            out.append(pd.read_csv(f))
        elif f.endswith(".json"):
            j = json.load(open(f)); out.append(pd.DataFrame(j if isinstance(j, list) else j.get("rows", [])))
        else:
            op = gzip.open if f.endswith(".gz") else open
            with op(f, "rt") as h:
                out.append(pd.DataFrame([json.loads(l) for l in h if l.strip()]))
    return pd.concat(out, ignore_index=True)


def star_feats(S, L):
    UE.need(S, ["repo", "date", "stars"], "github_stargazers")
    S = S.assign(repo=S.repo.str.lower().str.strip("/"), date=S.date.astype(str).str[:10], stars=pd.to_numeric(S.stars, errors="coerce").fillna(0))
    S = S.groupby(["repo", "date"]).stars.sum().reset_index().sort_values(["repo", "date"])
    S["cum"] = S.groupby("repo").stars.cumsum()
    by = {r: g for r, g in S.groupby("repo")}
    rows = []
    for lid, v in L.items():
        d = v["day"]; best = None
        for r in v.get("repos", []):
            g = by.get(r.lower())
            if g is None:
                continue
            pre = g[g.date < d]
            if not len(pre):
                continue
            tot = float(pre.cum.iloc[-1]); new30 = float(pre[pre.date >= str((pd.Timestamp(d) - pd.Timedelta(days=30)).date())].stars.sum())
            age = float((pd.Timestamp(d) - pd.Timestamp(g.date.iloc[0])).days - 1)
            if best is None or tot > best[0]:
                best = (tot, new30, age)
        if best:
            rows.append({"id": lid, "c1_stars": np.log1p(best[0]), "c1_stars_30": np.log1p(best[1]), "c1_repo_age": best[2]})
    return pd.DataFrame(rows, columns=["id", "c1_stars", "c1_stars_30", "c1_repo_age"])


def dl_feats(Dl, L):
    UE.need(Dl, ["package", "registry", "date", "downloads"], "pkg_downloads")
    Dl = Dl.assign(key=Dl.registry.str.lower() + ":" + Dl.package.str.lower(), date=Dl.date.astype(str).str[:10],
                   downloads=pd.to_numeric(Dl.downloads, errors="coerce").fillna(0))
    by = {k: g for k, g in Dl.groupby("key")}
    rows = []
    for lid, v in L.items():
        d = v["day"]; keys = [f"npm:{p.lower()}" for p in v.get("npm", [])] + [f"pypi:{p.lower()}" for p in v.get("pypi", [])]
        vals = {w: [] for w in (7, 30, 90)}
        for k in keys:
            g = by.get(k)
            if g is None:
                continue
            for w in vals:
                lo = str((pd.Timestamp(d) - pd.Timedelta(days=w)).date())
                vals[w].append(float(g[(g.date >= lo) & (g.date < d)].downloads.sum()))
        if vals[7]:   # at least one package with history (zeros count: a package nobody downloaded is a real 0)
            rows.append({"id": lid, **{f"c1_dl_{w}": np.log1p(max(x)) for w, x in vals.items()}})
    return pd.DataFrame(rows, columns=["id", "c1_dl_7", "c1_dl_30", "c1_dl_90"])


def main(repos_json, stars_dir, dl_dir=None):
    L = {str(k): v for k, v in json.load(open(repos_json)).items()}
    UE.need(pd.DataFrame(list(L.values())), ["day", "repos"], "c1_repos.json")
    F = star_feats(read_any(stars_dir, "github_stargazers"), L)
    if dl_dir:
        F = F.merge(dl_feats(read_any(dl_dir, "pkg_downloads"), L), on="id", how="outer")
    for c in COLS:
        if c not in F:
            F[c] = np.nan
    print(f"launches with stars before launch {int(F.c1_stars.notna().sum())}, with downloads {int(F.c1_dl_30.notna().sum())}", flush=True)
    cols = [c for c in COLS if F[c].notna().any()]
    return UE.evaluate(F, "c1", cols, os.environ.get("OUT", "results/c1_user_base.json"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
