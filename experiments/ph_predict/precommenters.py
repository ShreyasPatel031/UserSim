"""WHO the pre-launch commenters are (orchestrator 01:47Z Nov 13; backtest Apr-Oct, counts only, no usernames in outputs).
Pre-launch commenters = distinct non-hunter commenters of comments created <= 00:05 PT of the launch day (comment dumps,
read after the day; only comments timestamped before 00:05 PT are used). Per launch:
  a  n_complete     of them, people with a complete pull (raw/_babysitter/quality/latest_complete.txt, keyed by PH user id)
  b  med_foll       log1p median PH follower count (warehouse people.ph_followers; profile read later, not at launch)
  c  past_top10     share who had commented before launch on an earlier daily top-10 launch (strictly earlier days)
  d  newish         share with account joined < 30 days before the day or upvotes_total == 0 (people table; joined is
                    blank for most rows, so this is mostly the zero-upvote share)
  e  hunter_reply   the hunter replied (depth > 0) before 00:05 PT
Leave-one-day-out ridge (alpha 3) on within-day z features -> z(-log final rank): base [clean_nosite, th_n_pre] vs base + each.
Coverage = share of pre-launch commenters found in the people table. usage: python precommenters.py -> results/precommenters.md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from early_forecast import B
from sklearn.linear_model import Ridge


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    P = W.query("SELECT lower(person) person, joined, ph_followers, upvotes_total FROM people", do_sync=False).drop_duplicates("person")
    P = P.set_index("person")
    p = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")) + "/c.txt"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/_babysitter/quality/latest_complete.txt", p], check=True)
    complete = {l.strip().lower() for l in open(p) if l.strip()}
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    K, _ = CF.load_comments()
    K = K.merge(L[["slug", "id", "day", "poster", "daily_rank"]], on="slug")
    K["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    pre = K[K.ts <= K.t5]
    top10_pre = pre[pre.daily_rank <= 10].groupby("user").day.min()   # first day a user pre-commented on a top-10 launch
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    rows, found, tot = [], 0, 0
    G = pre.groupby("id")
    for i, d, hp in zip(X.id, X.day, X.poster):
        g = G.get_group(i) if i in G.groups else pre.iloc[0:0]
        us = [u for u in g[g.user != hp].user.unique() if u]
        tot += len(us); fu = [u for u in us if u in P.index]; found += len(fu)
        fol = [P.ph_followers[u] for u in fu if pd.notna(P.ph_followers[u])]
        new = []
        for u in fu:
            j = pd.to_datetime(P.joined[u], errors="coerce", utc=True)
            new.append(float((pd.notna(j) and (pd.Timestamp(d, tz="UTC") - j).days < 30) or (P.upvotes_total[u] == 0)))
        uids = {str(x) for x in g[g.user != hp].uid.unique() if x}   # the complete list is keyed by PH user id
        rows.append({"id": i, "npre": len(us), "n_complete": sum(1 for u in uids if u in complete),
                     "med_foll": np.log1p(np.median(fol)) if fol else 0.0,
                     "past_top10": np.mean([1.0 if (u in top10_pre.index and top10_pre[u] < d) else 0.0 for u in us]) if us else 0.0,
                     "newish": np.mean(new) if new else 0.0,
                     "hunter_reply": float(((g.user == hp) & (g.depth > 0)).any()) if hp else 0.0})
    X = X.merge(pd.DataFrame(rows), on="id")
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    F = ["clean", "npre", "n_complete", "med_foll", "past_top10", "newish", "hunter_reply"]
    for c in F:
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    def lodo(cols):
        out = []
        for d in days:
            te = X[X.day == d]; tr = X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(out)
    base = lodo(["z_clean", "z_npre"]); clean = lodo(["z_clean"])
    md = [f"# Who the pre-launch commenters are ({len(days)} days Apr-Oct; LODO ridge; backtest)", "",
          f"Coverage: {found} of {tot} pre-launch commenters found in the people table ({found / max(tot, 1):.1%}); dumps read after the day, "
          "comments <= 00:05 PT only; follower counts and join dates come from later profile reads.", "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 vs base | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite only | {clean[:,0].mean():.1f} | {clean[:,1].mean():.1f} | {clean[:,2].mean():.1f} | | | |",
          f"| base: clean + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for c in F[2:]:
        Pp = lodo(["z_clean", "z_npre", "z_" + c]); dP = Pp - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| + {c} | {Pp[:,0].mean():.1f} | {Pp[:,1].mean():.1f} | {Pp[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    open(os.path.join(HERE, "results", "precommenters.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
