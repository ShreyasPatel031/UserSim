"""A1: each team's full Product Hunt launch history as a pre-launch input (Data Feeder's raw/ph_team_history/).
Expected input: JSON lines (*.jsonl, *.jsonl.gz) with at least
  username, post_id, role (maker | hunter), votesCount, and featuredAt or createdAt (ISO time); dailyRank optional.
The script fails loudly if a required column is missing.
Per launch (makers + hunter from data/days/ and data/today/), using only the team's OTHER posts dated strictly before
the launch's Pacific day:
  a1_n         distinct earlier posts (any team member, made or hunted)
  a1_n_made    distinct earlier posts the makers made
  a1_max_rel   max of log1p(votes) minus the median log1p(votes) of that post's month (all fetched posts), so old and
               new launches compare
  a1_mean_rel  mean of the same
  a1_top5      share of earlier posts with dailyRank <= 5 (NaN if no rank is known)
  a1_days_since days since the most recent earlier post
  a1_first     1 if the team has no earlier post at all (first-time team), else 0 (only for launches whose team was
               fetched)
  a1_team      team size (makers + hunter): a reference column. Counts and maxima grow with team size, so an
               a1_ input only adds information if it beats a1_team in the gate (synthetic random histories pass on
               team size alone).
Then userbase_eval: residual-Spearman gate vs the honest model, and daily / weekly / monthly top 3/5/10 vs the honest
day-calibrated control.
usage: SIMLAB_DATA=data_v2 python a1_team_history.py <dir or file of raw/ph_team_history> [days_dir]
  -> results/a1_team_history.json"""
import glob, gzip, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
import userbase_eval as UE

COLS = ["a1_n", "a1_n_made", "a1_max_rel", "a1_mean_rel", "a1_top5", "a1_days_since", "a1_first", "a1_team"]


def read_jsonl(path):
    files = [path] if os.path.isfile(path) else sorted(glob.glob(os.path.join(path, "**", "*.jsonl*"), recursive=True))
    if not files:
        raise SystemExit(f"no *.jsonl / *.jsonl.gz under {path}")
    rows = []
    for f in files:
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as h:
            rows += [json.loads(l) for l in h if l.strip()]
    return pd.DataFrame(rows)


def pacific_day(ts):
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    return t.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")


def teams(days_dir):
    T = {}
    for f in sorted(glob.glob(os.path.join(days_dir, "days", "*.json"))) + sorted(glob.glob(os.path.join(days_dir, "today", "*.json"))):
        d = os.path.basename(f)[:10]
        for p in json.load(open(f)):
            if str(p["id"]) in T:
                continue
            mk = {(m.get("username") or "").lower() for m in (p.get("makers") or []) if isinstance(m, dict)} - {""}
            hu = ((p.get("user") or {}).get("username") or "").lower()
            T[str(p["id"])] = (d, mk, hu)
    return T


def features(H, T):
    UE.need(H, ["username", "post_id", "role", "votesCount"], "ph_team_history")
    if "featuredAt" not in H and "createdAt" not in H:
        raise SystemExit("ph_team_history: needs featuredAt or createdAt")
    H = H.copy()
    ts = H["featuredAt"] if "featuredAt" in H else pd.Series(np.nan, index=H.index)
    if "createdAt" in H:
        ts = ts.fillna(H["createdAt"])
    H["pday"] = pacific_day(ts); H = H[H.pday.notna()]
    H["username"] = H.username.str.lower(); H["post_id"] = H.post_id.astype(str)
    H["lv"] = np.log1p(pd.to_numeric(H.votesCount, errors="coerce").fillna(0))
    H["rel"] = H.lv - H.groupby(H.pday.str[:7]).lv.transform("median")
    H["top5"] = (pd.to_numeric(H["dailyRank"], errors="coerce") <= 5).astype(float).where(pd.to_numeric(H["dailyRank"], errors="coerce").notna()) if "dailyRank" in H else np.nan
    fetched = set(H.username)
    by_user = {u: g.drop_duplicates("post_id") for u, g in H.groupby("username")}
    rows = []
    for lid, (d, mk, hu) in T.items():
        members = (mk | {hu}) - {""}
        if not members & fetched:
            continue
        P = pd.concat([by_user[u] for u in members if u in by_user]) if members & set(by_user) else H.iloc[:0]
        P = P[(P.pday < d) & (P.post_id != lid)].drop_duplicates("post_id")
        made = P[(P.role == "maker") & P.username.isin(mk)].post_id.nunique() if len(P) else 0
        rows.append({"id": lid, "a1_n": float(len(P)), "a1_n_made": float(made),
                     "a1_max_rel": float(P.rel.max()) if len(P) else np.nan, "a1_mean_rel": float(P.rel.mean()) if len(P) else np.nan,
                     "a1_top5": float(P.top5.mean()) if len(P) and P.top5.notna().any() else np.nan,
                     "a1_days_since": float((pd.Timestamp(d) - pd.to_datetime(P.pday).max()).days) if len(P) else np.nan,
                     "a1_first": float(len(P) == 0), "a1_team": float(len(members))})
    return pd.DataFrame(rows, columns=["id"] + COLS)


def own_days(days_dir):
    """Our own launch files (Jan 2026 on) as history rows in the same schema, so a team's history covers the crawl
    (2024-2025) and our data alike. votesCount here is the final count of an earlier launch: known before a later one."""
    rows, seen = [], set()
    for f in sorted(glob.glob(os.path.join(days_dir, "days", "*.json"))):
        for p in json.load(open(f)):
            if str(p["id"]) in seen:
                continue
            seen.add(str(p["id"]))
            base = {"post_id": str(p["id"]), "featuredAt": p.get("featuredAt"), "createdAt": p.get("createdAt"),
                    "votesCount": p.get("votesCount"), "dailyRank": p.get("dailyRank")}
            for role, u in [("maker", m.get("username")) for m in (p.get("makers") or []) if isinstance(m, dict)] + [("hunter", (p.get("user") or {}).get("username"))]:
                if u and u != "[REDACTED]":
                    rows.append({"username": u, "role": role, **base})
    return pd.DataFrame(rows)


def main(path, days_dir="data"):
    H = read_jsonl(path)
    if os.environ.get("OWN_DAYS", "1") == "1":   # add our own Jan-Oct 2026 launches as history (dedup by post id)
        O = own_days(days_dir); H = pd.concat([H, O[~O.post_id.isin(set(H.post_id.astype(str)))]], ignore_index=True)
    print(f"history rows {len(H)}, users {H.username.nunique() if 'username' in H else '?'}", flush=True)
    F = features(H, teams(days_dir))
    print(f"launches with a fetched team {len(F)}; with earlier posts {int((F.a1_n > 0).sum())}", flush=True)
    return UE.evaluate(F, "a1", COLS, os.environ.get("OUT", "results/a1_team_history.json"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
