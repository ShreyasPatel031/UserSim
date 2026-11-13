"""Hunter X-handle feature, 214-day backtest (Apr-Oct; counts only). Prompted by the X pilot: in the 00:05 API read the hunter's
user object is never redacted and carries twitterUsername; within the read, 0.78 of final top-10 hunters had an X handle vs 0.26.
Backtest source: warehouse people row of the hunter (98% coverage for both top-10 and other launches, so no coverage leak).
DRIFT CAVEAT: the people row is read later, so 'has X handle' and PH follower count are as of the profile read, not launch day;
the handle link changes slowly, follower counts can grow after a strong launch (reported separately, labelled).
Base = LODO ridge on z(clean_nosite) + z(th_n_pre); + hunter_x (has handle), + log1p hunter PH followers, + both.
usage: python hunter_x.py -> results/hunter_x.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    P = W.query("SELECT lower(person) p, twitter, ph_followers, joined, updated_at FROM people", do_sync=False).drop_duplicates("p").set_index("p")
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    X["npre"] = X.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    X["hx"] = X.poster.map(P.twitter).fillna("").astype(str).str.strip().ne("").astype(float)
    X["hf"] = np.log1p(X.poster.map(P.ph_followers).astype(float).fillna(0))
    jn = pd.to_datetime(X.poster.map(P.joined), errors="coerce", utc=True).dt.tz_convert(None)
    X["hage"] = np.log1p((pd.to_datetime(X.day) - jn).dt.days.clip(lower=0)); X["has_age"] = X.hage.notna().astype(float)
    X["hage"] = X.groupby("day").hage.transform(lambda s: s.fillna(s.median() if s.notna().any() else 0.0))
    ua = pd.to_datetime(X.poster.map(P.updated_at), errors="coerce", utc=True).dt.tz_convert(None)
    read_note = (f"Hunter object read time (people.updated_at): before the launch day {int((ua < pd.to_datetime(X.day)).sum())}, "
                 f"after {int((ua >= pd.to_datetime(X.day)).sum())}, missing {int(ua.isna().sum())} (of {len(X)})")
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean", "npre", "hx", "hf", "hage", "has_age"):
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
    base = lodo(["z_clean", "z_npre"])
    md = [f"# Hunter X handle ({len(days)} days Apr-Oct, LODO; hunter people rows read later, see drift caveat)", "",
          read_note, "", f"Hunter has X handle: final top 10 {X[X.daily_rank <= 10].hx.mean():.2f} vs 11+ {X[X.daily_rank > 10].hx.mean():.2f}", "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for nm, cols in (("+ hunter has X handle", ["z_hx"]), ("+ hunter PH followers (drift-prone)", ["z_hf"]), ("+ both", ["z_hx", "z_hf"]),
                     ("+ hunter account age (log days)", ["z_hage", "z_has_age"]), ("+ X handle + account age", ["z_hx", "z_hage", "z_has_age"])):
        Pp = lodo(["z_clean", "z_npre"] + cols); dP = Pp - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {Pp[:,0].mean():.1f} | {Pp[:,1].mean():.1f} | {Pp[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    # climber band: days with a hidden read (vote_snapshots), hidden rank 11-19 at 03:00 PT; hunter features from the same people rows
    Q = L[(L.day >= "2026-10-31") & (L.day <= "2026-11-12")].copy()
    Q["hx"] = Q.poster.map(P.twitter).fillna("").astype(str).str.strip().ne("").astype(float)
    jq = pd.to_datetime(Q.poster.map(P.joined), errors="coerce", utc=True).dt.tz_convert(None); Q["hage"] = (pd.to_datetime(Q.day) - jq).dt.days
    uq = pd.to_datetime(Q.poster.map(P.updated_at), errors="coerce", utc=True).dt.tz_convert(None); Q["after"] = (uq >= pd.to_datetime(Q.day)).astype(float)
    QI = Q.set_index("id"); V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots WHERE rank_now IS NOT NULL', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True); cl = []
    for d, g in V.groupby("d"):
        t3 = (pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(hours=3)).tz_convert("UTC")
        for i, r in g[g.a <= t3].sort_values("a").groupby("id").rank_now.last().items():
            if 11 <= r <= 19 and i in QI.index:
                cl.append({"c": int(QI.daily_rank[i] <= 10), "hx": QI.hx[i], "hage": QI.hage[i], "after": QI.after[i]})
    C = pd.DataFrame(cl)
    if len(C):
        from sklearn.metrics import roc_auc_score
        md += ["", f"Climber band ({V.d.nunique()} days with a hidden read, Oct 31 - Nov 12; hidden rank 11-19 at 03:00 PT; {len(C)} launches, "
               f"{int(C.c.sum())} ended top 10): hunter has X handle {C[C.c == 1].hx.mean():.2f} vs {C[C.c == 0].hx.mean():.2f}; "
               f"median hunter account age (days) {C[C.c == 1].hage.median():.0f} vs {C[C.c == 0].hage.median():.0f}; "
               f"hunter row read after launch day {int(C.after.sum())} of {len(C)}"
               + (f"; AUC has-handle {roc_auc_score(C.c, C.hx):.2f}, AUC account age {roc_auc_score(C[C.hage.notna()].c, C[C.hage.notna()].hage):.2f}" if C.c.nunique() == 2 else "")]
    open(os.path.join(HERE, "results", "hunter_x.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
