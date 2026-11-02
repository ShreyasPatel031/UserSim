"""Launch-day forecast backtest from real early comments (proxy for early votes until the hourly snapshots are long
enough). For each launch and hour h after 00:00 PT of its day (h = 1, 2, 4, 8, 12), using only comments posted
before then:
  c_h     comments by people outside the team (makers + hunter), log
  u_h     distinct such commenters, log
  t_h     comments by the team, log
  past_h  how established the commenters are: mean log count of their actions before the day (store events)
  c_h_dayr / c_h_share   standing and share of the day's comments so far (within-day)
Prior: the pre-launch launch model (ctrl.py, out of sample, `all`). Model per hour: LightGBM on final log votes from
the prior plus the hour's readings, rolling monthly (train on earlier months, from Apr), 3 seeds.
Columns saved: h0 (the prior alone), h1 .. h12 (prior + readings), and cmt_h4 (readings only, no prior, at hour 4).
Score with lists_score.py on all three boards.
usage: SIMLAB_DATA=data_v2 python launchday.py -> results/launchday_preds.parquet"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import ph_comments as PC

D = "data"; HOURS = (1, 2, 4, 8, 12)


def comments():
    slug2 = {}
    for f in glob.glob(f"{D}/days/*.json"):
        for p in json.load(open(f)):
            slug2[p["slug"]] = (str(p["id"]), f[-15:-5], {m["username"] for m in p.get("makers") or [] if isinstance(m, dict)} | {(p.get("user") or {}).get("username")})
    rows, seen = [], set()
    for fn in sorted(glob.glob(f"{D}/comments/page*.jsonl.gz")) + sorted(glob.glob(f"{D}/comments/daily/*.jsonl.gz")):
        try:
            for l in gzip.open(fn, "rt"):
                try:
                    r = json.loads(l)
                    if r.get("status") != 200:
                        continue
                    info, cs = PC.parse(json.loads(r["html"]))
                except Exception:  # noqa: BLE001
                    continue
                s = slug2.get(info.get("slug"))
                if not s:
                    continue
                for c in cs:
                    if c.get("comment_id") and c["comment_id"] not in seen and c.get("username") and c.get("created"):
                        seen.add(c["comment_id"]); rows.append((s[0], s[1], c["username"], c["created"], c["username"] in s[2]))
        except (EOFError, OSError):
            pass
    T = pd.DataFrame(rows, columns=["id", "day", "person", "created", "team"])
    t = pd.to_datetime(T.created, utc=True, errors="coerce")
    start = pd.to_datetime(T.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")
    T["h"] = (t - start).dt.total_seconds() / 3600
    return T[T.h.notna()]


def main():
    T = comments()
    P, I, E = store.load()
    E = E.sort_values("date")
    first = {}   # person -> sorted action dates, for "how established" before the day
    for u, g in E.groupby("person"):
        first[u] = g.date.values
    def past(u, d):
        a = first.get(u)
        return np.log1p(np.searchsorted(a, d)) if a is not None else 0.0
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
    A = C[["id", "day", "dailyRank", "logv", "all"]].copy()
    feats = {}
    for h in HOURS:
        S = T[(T.h >= -24) & (T.h < h)]
        out = S[~S.team].groupby("id").agg(c=("person", "size"), u=("person", "nunique"))
        tm = S[S.team].groupby("id").size().rename("t")
        ps = S[~S.team].drop_duplicates(["id", "person"]).assign(p=lambda x: [past(u, d) for u, d in zip(x.person, x.day)]).groupby("id").p.mean()
        F = out.join(tm, how="outer").join(ps, how="outer").fillna(0).rename(columns=lambda c: f"{c}_{h}")
        A = A.merge(F, left_on="id", right_index=True, how="left")
        for c in (f"c_{h}", f"u_{h}", f"t_{h}", f"p_{h}"):
            A[c] = A[c].fillna(0)
            if c[0] != "p":
                A[c] = np.log1p(A[c])
        A[f"c_{h}_dayr"] = A.groupby("day")[f"c_{h}"].rank(pct=True)
        A[f"c_{h}_share"] = np.expm1(A[f"c_{h}"]) / A.groupby("day")[f"c_{h}"].transform(lambda s: np.expm1(s).sum() + 1)
        feats[h] = [f"c_{h}", f"u_{h}", f"t_{h}", f"p_{h}", f"c_{h}_dayr", f"c_{h}_share"]
    A["mon"] = A.day.str[:7]; out = []
    fit = lambda tr, te, cols: np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8,
                                                          subsample_freq=1, colsample_bytree=0.7, random_state=s, verbose=-1, n_jobs=8)
                                        .fit(tr[cols], tr.logv).predict(te[cols]) for s in range(3)], 0)
    for m in sorted(A.mon.unique()):
        if m < "2026-05":
            continue
        tr, te = A[(A.mon < m) & (A.mon >= "2026-03")], A[A.mon == m].copy()
        te["h0"] = te["all"]
        for h in HOURS:
            te[f"h{h}"] = fit(tr, te, ["all"] + feats[h])
        te["cmt_h4"] = fit(tr, te, feats[4])
        out.append(te)
    R = pd.concat(out)
    R[["id", "day", "dailyRank", "logv", "h0"] + [f"h{h}" for h in HOURS] + ["cmt_h4"] + sum(feats.values(), [])].to_parquet("results/launchday_preds.parquet")
    cover = {h: round(float((np.expm1(R[f"c_{h}"]) > 0).mean()), 3) for h in HOURS}
    print(json.dumps({"launches": len(R), "timed_comments": len(T), "share_of_launches_with_a_comment_by_hour": cover}))


if __name__ == "__main__":
    main()
