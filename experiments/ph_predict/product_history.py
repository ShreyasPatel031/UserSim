"""PRODUCT history at 00:05 (orchestrator 05:46Z Nov 13; counts only). Built in time order from the 2025 lists (raw/ph_history/2025,
Data Feeder) + the 2026 warehouse launches. A launch's product = same slug stem (trailing -N removed) OR same name stem (lowercased,
version / year tokens removed: v2, 2.0, 3, 2025, ...); domain matching is not used (no held domain for 2025 rows).
Per launch, prior launches of the same product on strictly earlier days: pr_n (log1p count), pr_best (best prior daily rank,
-log), pr_last (last prior daily rank, -log), pr_votes (log1p best prior votes), pr_gap (log1p days since the last one);
flags: name_ver (name carries a version number or year), hunter_new (the hunter has no ranked launch before the day in the lists),
self_hunted (hunter among the makers; makers from the warehouse / 2025 lists = later reads, LEAK-PRONE, reported separately).
Evaluation on the 214 days: bases = history_retrain DECOMP 5-seed predictions (pure, both) + th_n_pre; LODO ridge vs + product
features; overall, on final top-3 launches whose hunter is new (hit rate in the predicted top 3), and on busy days (30+ launches).
usage: python product_history.py <2025 lists dir> -> results/product_history.md"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
VER = re.compile(r"\b(v?\d+(\.\d+)*|20\d\d|ii|iii|iv|pro|max|plus|new)\b")


def stem_name(n):
    n = re.sub(r"[^a-z0-9 .]", " ", str(n).lower()); n = VER.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def main(src):
    from pipeline import warehouse as W
    rows = []
    for fn in sorted(glob.glob(f"{src}/*.json")):
        for p in json.load(open(fn)):
            rows.append({"id": str(p["id"]), "day": os.path.basename(fn)[:10], "slug": p.get("slug") or "", "name": p.get("name") or "",
                         "rank": p.get("dailyRank"), "votes": p.get("votesCount"), "hunter": str((p.get("user") or {}).get("username") or "").lower(),
                         "makers": [str(m.get("username") or "").lower() for m in (p.get("makers") or []) if m.get("username") and m.get("username") != "[REDACTED]"]})
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, slug, name, daily_rank, votes, poster, makers FROM launches", do_sync=False)
    for i, d, sl, nm, r, v, po, mk in zip(L.id, L.day, L.slug, L.name, L.daily_rank, L.votes, L.poster, L.makers):
        ms = json.loads(mk) if isinstance(mk, str) and mk.startswith("[") else []
        rows.append({"id": i, "day": d, "slug": sl or "", "name": nm or "", "rank": r, "votes": v, "hunter": str(po or "").lower(), "makers": [str(m).lower() for m in ms]})
    X = pd.DataFrame(rows).drop_duplicates("id").sort_values("day").reset_index(drop=True)
    X["rank"] = pd.to_numeric(X["rank"], errors="coerce").astype(float); X["votes"] = pd.to_numeric(X["votes"], errors="coerce").astype(float)
    X["s_stem"] = X.slug.str.replace(r"-\d+$", "", regex=True); X["n_stem"] = X.name.map(stem_name)
    X["name_ver"] = X.name.str.lower().str.contains(r"\b(?:v\d+|\d+\.\d+|20\d\d)\b", regex=True).astype(float)
    X["self_hunted"] = [float(bool(h) and h in set(m)) for h, m in zip(X.hunter, X.makers)]
    hist_s, hist_n, hunt = {}, {}, {}
    F = []
    for d, g in X.groupby("day", sort=True):
        for r in g.itertuples():
            prev = {p[0]: p for p in hist_s.get(r.s_stem, []) + (hist_n.get(r.n_stem, []) if len(r.n_stem) >= 3 else [])}.values()
            ranks = [p[2] for p in prev if p[2] == p[2] and p[2] is not None]; vs = [p[3] for p in prev if p[3] == p[3] and p[3] is not None]
            last = max(prev, key=lambda p: p[1]) if prev else None
            F.append({"id": r.id, "pr_n": np.log1p(len(prev)), "pr_best": -np.log(min(ranks)) if ranks else np.nan,
                      "pr_last": -np.log(last[2]) if last and last[2] == last[2] and last[2] is not None else np.nan,
                      "pr_votes": np.log1p(max(vs)) if vs else np.nan,
                      "pr_gap": np.log1p((pd.Timestamp(d) - pd.Timestamp(last[1])).days) if last else np.nan,
                      "hunter_new": float(r.hunter == "" or hunt.get(r.hunter, 0) == 0)})
        for r in g.itertuples():   # add the day's results only after the whole day is featurised
            rec = (r.id, r.day, float(r.rank) if r.rank == r.rank and r.rank is not None else np.nan, float(r.votes) if r.votes == r.votes and r.votes is not None else np.nan)
            hist_s.setdefault(r.s_stem, []).append(rec)
            if len(r.n_stem) >= 3:
                hist_n.setdefault(r.n_stem, []).append(rec)
            if r.rank == r.rank and r.rank is not None and r.hunter:
                hunt[r.hunter] = hunt.get(r.hunter, 0) + 1
    Fd = pd.DataFrame(F).set_index("id")
    A = pd.read_parquet(os.path.join(HERE, "results", "history_retrain_decomp_preds.parquet")); A["id"] = A.id.astype(str)
    A = A.dropna(subset=["dailyRank", "pure", "both"]).join(Fd, on="id").join(X.set_index("id")[["name_ver", "self_hunted"]], on="id")
    Lp = L[["id", "slug", "day", "poster"]].copy(); Lp["poster"] = Lp.poster.fillna("").str.lower()
    K, _ = CF.load_comments(); K = K.merge(Lp, on="slug")
    K["t5"] = [(pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(minutes=5)).tz_convert("UTC") for d in K.day]
    A["npre"] = A.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    A["has_prior"] = (A.pr_n > 0).astype(float)
    for c in ("pr_best", "pr_last", "pr_votes", "pr_gap"):
        A[c] = A[c].fillna(A[c].min() - 0.5 if c != "pr_gap" else A[c].max() + 0.5)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    PF = ["pr_n", "pr_best", "pr_last", "pr_votes", "pr_gap", "has_prior", "name_ver", "hunter_new"]
    for c in ["pure", "both", "npre", "self_hunted"] + PF:
        A["z_" + c] = A.groupby("day")[c].transform(zf)
    A["y"] = A.groupby("day").dailyRank.transform(lambda s: zf(-np.log(s)))
    A["n_day"] = A.groupby("day").id.transform("size")
    days = sorted(A.day.unique()); rng = np.random.default_rng(0); t3 = A[A.dailyRank <= 3]
    md = [f"# Product history at 00:05 ({len(days)} days Apr-Oct; {len(A)} launches; 2025 lists: {len(glob.glob(src + '/*.json'))} days)", "",
          f"Coverage: launches with a prior launch of the same product {A.has_prior.mean():.1%} (final top 3: {t3.has_prior.mean():.1%}); "
          f"name carries a version/year {A.name_ver.mean():.1%} (top 3: {t3.name_ver.mean():.1%}); hunter new {A.hunter_new.mean():.1%} "
          f"(top 3: {t3.hunter_new.mean():.1%}); self-hunted (leak-prone makers) {A.self_hunted.mean():.1%} (top 3: {t3.self_hunted.mean():.1%}); "
          f"busy days (30+ launches) {A[A.n_day >= 30].day.nunique()}", ""]
    def run(cols):
        P, sub_new, busy = [], [], []
        for d in days:
            te, tr = A[A.day == d], A[A.day != d]; t = te.sort_values("dailyRank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            h = [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]; P.append(h)
            nn = te[(te.dailyRank <= 3) & (te.hunter_new == 1)].id
            sub_new += [float(i in set(o[:3])) for i in nn]
            if len(te) >= 30:
                busy.append(h)
        return np.array(P), np.array(sub_new), np.array(busy)
    md += ["| model | top 3 | top 5 | top 10 | diff vs base (95%) | new-hunter top-3 launches caught | busy days t3/t5/t10 |", "|---|---|---|---|---|---|---|"]
    for base in ("pure", "both"):
        B0 = ["z_" + base, "z_npre"]; b0, n0, y0 = run(B0)
        md.append(f"| {base} + th_n_pre | {b0[:,0].mean():.1f} | {b0[:,1].mean():.1f} | {b0[:,2].mean():.1f} | - | {n0.sum():.0f} of {len(n0)} | "
                  f"{y0[:,0].mean():.1f} / {y0[:,1].mean():.1f} / {y0[:,2].mean():.1f} |")
        for nm, cols in (("+ product history", ["z_pr_n", "z_pr_best", "z_pr_last", "z_pr_votes", "z_pr_gap", "z_has_prior"]),
                         ("+ product history + flags (name_ver, hunter_new)", ["z_pr_n", "z_pr_best", "z_pr_last", "z_pr_votes", "z_pr_gap", "z_has_prior", "z_name_ver", "z_hunter_new"]),
                         ("+ flags only", ["z_name_ver", "z_hunter_new"]), ("+ self-hunted (LEAK-PRONE)", ["z_self_hunted"])):
            P, nw, by = run(B0 + cols); dP = P - b0; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
            md.append(f"| {base} {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                      " / ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) +
                      f" | {nw.sum():.0f} of {len(nw)} | {by[:,0].mean():.1f} / {by[:,1].mean():.1f} / {by[:,2].mean():.1f} |")
    open(os.path.join(HERE, "results", "product_history.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1])
