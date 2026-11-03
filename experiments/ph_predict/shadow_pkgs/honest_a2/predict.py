"""shadow_honest_a2, live. Run from this folder: python3 predict.py <day> -> JSON lines {"launch_id", "score"} (log
expected votes). Offset: the live launch model (../../../results/forecast_<day>.parquet `pred`). Day terms as daycal
(trailing totals from the warehouse and earlier forecast files, backtest totals in meta.json). A1 from team_history.jsonl
(2024-2025 crawl) + data/days (2026); A2 from the warehouse's dated comments: the team's comments on OTHER launches in
the 7 / 14 days strictly before the day. Team = makers + hunter from data/today/<day>.json."""
import datetime as dt, glob, json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.abspath(os.path.join(HERE, "..", "..", "..")); EXP = os.path.dirname(PH)
sys.path.insert(0, EXP)


def team_of(p):
    mk = {(m.get("username") or "").lower() for m in (p.get("makers") or []) if isinstance(m, dict)} - {"", "[redacted]"}
    hu = ((p.get("user") or {}).get("username") or "").lower()
    return mk, hu


def a1(day, launches):
    rows = [json.loads(l) for l in open(os.path.join(HERE, "team_history.jsonl"))]
    for f in sorted(glob.glob(os.path.join(PH, "data", "days", "*.json"))):
        for p in json.load(open(f)):
            for role, u in [("maker", m.get("username")) for m in (p.get("makers") or []) if isinstance(m, dict)] + [("hunter", (p.get("user") or {}).get("username"))]:
                if u and u != "[REDACTED]":
                    rows.append({"username": u, "role": role, "post_id": str(p["id"]), "featuredAt": p.get("featuredAt") or p.get("createdAt"),
                                 "votesCount": p.get("votesCount"), "dailyRank": p.get("dailyRank")})
    H = pd.DataFrame(rows); H["username"] = H.username.str.lower(); H["post_id"] = H.post_id.astype(str)
    H["pday"] = pd.to_datetime(H.featuredAt, utc=True, errors="coerce").dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    H = H[H.pday.notna() & (H.pday < day)].drop_duplicates(["username", "post_id"])
    H["lv"] = np.log1p(pd.to_numeric(H.votesCount, errors="coerce").fillna(0)); H["rel"] = H.lv - H.groupby(H.pday.str[:7]).lv.transform("median")
    r = pd.to_numeric(H.dailyRank, errors="coerce"); H["top5"] = (r <= 5).astype(float).where(r.notna())
    by = {u: g for u, g in H.groupby("username")}; out = {}
    for lid, (mk, hu) in launches.items():
        mem = [u for u in (mk | {hu}) - {""} if u in by]
        P = pd.concat([by[u] for u in mem]).drop_duplicates("post_id") if mem else H.iloc[:0]
        P = P[P.post_id != lid]
        out[lid] = {"a1_mean_rel": float(P.rel.mean()) if len(P) else np.nan, "a1_top5": float(P.top5.mean()) if len(P) and P.top5.notna().any() else np.nan,
                    "a1_n": float(len(P)), "a1_first": float(len(P) == 0)}
    return out


def a2(day, launches):
    from pipeline import warehouse as W
    lo = (dt.date.fromisoformat(day) - dt.timedelta(days=60)).isoformat()
    C = W.query(f"SELECT lower(person) AS person, launch_id::VARCHAR AS item, substr(date::VARCHAR, 1, 10) AS date FROM comments "
                f"WHERE substr(date::VARCHAR, 1, 10) >= '{lo}' AND substr(date::VARCHAR, 1, 10) < '{day}'")
    by = {u: g for u, g in C.groupby("person")}; out = {}
    lo14 = (dt.date.fromisoformat(day) - dt.timedelta(days=14)).isoformat(); lo7 = (dt.date.fromisoformat(day) - dt.timedelta(days=7)).isoformat()
    for lid, (mk, hu) in launches.items():
        mem = [u for u in (mk | {hu}) - {""} if u in by]
        G = pd.concat([by[u] for u in mem]) if mem else C.iloc[:0]
        G = G[G.item != lid]; g14 = G[G.date >= lo14]; g7 = G[G.date >= lo7]
        out[lid] = {"a2_act7": np.log1p(len(g7)), "a2_act14": np.log1p(len(g14)), "a2_launches14": np.log1p(g14.item.nunique()),
                    "a2_active_members14": float(g14.person.nunique()),
                    "a2_days_since": float((pd.Timestamp(day) - pd.Timestamp(G.date.max())).days) if len(G) else np.nan}
    return out


def main(day):
    meta = json.load(open(os.path.join(HERE, "meta.json")))
    F = pd.read_parquet(os.path.join(PH, "results", f"forecast_{day}.parquet")); F["id"] = F.id.astype(str)
    launches = {str(p["id"]): team_of(p) for p in json.load(open(os.path.join(PH, "data", "today", f"{day}.json")))}
    mu0 = np.expm1(F.pred.astype(float)).clip(lower=0.5)
    from pipeline import warehouse as W
    trail = [(dt.date.fromisoformat(day) - dt.timedelta(days=k)).isoformat() for k in range(2, 9)]
    real = dict(W.query(f"SELECT day::VARCHAR, sum(votes) FROM launches WHERE day::VARCHAR IN ({','.join(repr(t) for t in trail)}) AND votes IS NOT NULL GROUP BY 1").values.tolist())
    lm = dict(meta["day_lm"])
    for t in trail:
        f = os.path.join(PH, "results", f"forecast_{t}.parquet")
        if os.path.exists(f):
            lm[t] = float(np.expm1(pd.read_parquet(f).pred.astype(float)).clip(lower=0.5).sum())
    tr_real = [real[t] for t in trail if t in real]; tr_lm = [lm[t] for t in trail if t in lm]
    X = pd.DataFrame({"day_wd": dt.date.fromisoformat(day).weekday(), "day_n": len(F), "day_lm_sum": float(mu0.sum()),
                      "trail_real7": np.mean(tr_real) if len(tr_real) >= 3 else np.nan, "trail_lm7": np.mean(tr_lm) if len(tr_lm) >= 3 else np.nan}, index=F.index)
    f1, f2 = a1(day, launches), a2(day, launches)
    for c in ("a1_mean_rel", "a1_top5", "a1_n", "a1_first"):
        X[c] = F.id.map(lambda i: f1.get(i, {}).get(c, np.nan))
    for c in ("a2_act7", "a2_act14", "a2_launches14", "a2_active_members14", "a2_days_since"):
        X[c] = F.id.map(lambda i: f2.get(i, {}).get(c, np.nan))
    raw = np.mean([lgb.Booster(model_file=os.path.join(HERE, m)).predict(X[meta["features"]], raw_score=True) for m in meta["models"]], axis=0)
    for i, s in zip(F.id, raw + np.log(mu0)):
        print(json.dumps({"launch_id": str(i), "score": float(s)}))
    print(f"honest_a2: {len(F)} launches; A1 history for {int((X.a1_n > 0).sum())}; A2 team comments in 14 d for {int((X.a2_act14 > 0).sum())}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
