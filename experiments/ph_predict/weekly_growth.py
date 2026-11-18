"""Weekly 'running_g' shadow (orchestrator 09:45Z Nov 12). Weekly rank = order by total votes at the week's close (Sunday
23:59 PT), frozen after. At the end of day D of a week:
  running      PH's running order = votes at the nightly full-refresh read just after D (warehouse launch parts, ~00:20 PT)
  running_g    running votes x expected growth still to come to the close: per-day growth factor by launch age (days since
               launch, 1..6) x final-daily-rank band (1-3, 4-10, 11+), median of (v_t2/v_t1)^(24h/dt) over consecutive
               nightly reads ~1 day apart; leave-one-week-out (pairs of the held week's launches dropped)
  running_g_e  running_g + expected entrants: for each remaining day of the week, three placeholder launches with that
               weekday's typical final votes of daily #1-#3 (Jan-Oct table) x growth to the close; a placeholder in our
               top k counts as a miss (we cannot name it); reports how many current top-10 members it displaces
Truth: weekly_rank in the first full-refresh part after the week's close (fallback: the latest table). Weeks held: those
with a close read. usage: python weekly_growth.py -> results/weekly_growth.md + .json"""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
TZ = "America/Los_Angeles"
L = os.path.expanduser(os.environ.get("USERSIM_CACHE", "~/.usersim_sim")) + "/launches"


def parts():
    out = []
    for f in sorted(glob.glob(L + "/*.parquet")):
        p = pd.read_parquet(f)
        if "weekly_rank" not in p or pd.to_numeric(p.weekly_rank, errors="coerce").notna().sum() < 100:
            continue
        p = p[["id", "day", "daily_rank", "weekly_rank", "votes"]].copy(); p["id"] = p.id.astype(str)
        for c in ("daily_rank", "weekly_rank", "votes"):
            p[c] = pd.to_numeric(p[c], errors="coerce")
        out.append((pd.to_datetime(pd.read_parquet(f, columns=["updated_at"]).updated_at, utc=True).max(), p.drop_duplicates("id")))
    return sorted(out, key=lambda x: x[0])


def end(d):
    return pd.Timestamp(d + " 23:59:59", tz=TZ).tz_convert("UTC")


def band(r):
    return "1-3" if r <= 3 else ("4-10" if r <= 10 else "11+")


def main():
    P = parts()
    # daily growth pairs (consecutive full-refresh reads 18-30 h apart)
    pairs = []
    for (t1, a), (t2, b) in zip(P[:-1], P[1:]):
        dh = (t2 - t1).total_seconds() / 3600
        if not 18 <= dh <= 30:
            continue
        m = a.merge(b[["id", "votes"]], on="id", suffixes=("1", "2")).dropna(subset=["votes1", "votes2", "daily_rank"])
        m = m[m.votes1 > 0]
        m["age"] = [(t1.tz_convert(TZ).normalize().tz_localize(None) - pd.Timestamp(d)).days for d in m.day]
        m = m[(m.age >= 0) & (m.age <= 7)]
        m["g"] = (m.votes2 / m.votes1) ** (24 / dh); m["band"] = m.daily_rank.map(band)
        m["week"] = [(pd.Timestamp(d) - pd.Timedelta(days=pd.Timestamp(d).dayofweek)).strftime("%Y-%m-%d") for d in m.day]
        pairs.append(m[["id", "age", "band", "g", "week"]])
    G = pd.concat(pairs)
    # weekday x daily-rank table of final log votes (Jan-Oct), for entrants
    lat = P[0][1]
    for _, p in P[1:]:
        lat = pd.concat([lat, p]).drop_duplicates("id", keep="last")
    H = lat[lat.daily_rank.notna() & (lat.day < "2026-11-01")].copy(); H["wd"] = pd.to_datetime(H.day).dt.dayofweek
    TAB = H[H.daily_rank <= 3].groupby(["wd", "daily_rank"]).votes.median()
    weeks = []
    for t, p in P:
        tp = t.tz_convert(TZ)
        if tp.dayofweek == 0 and tp.hour < 8:   # first read after a Sunday close
            mon = (tp.normalize() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
            weeks.append((mon, p))
    res = []
    for mon, close in weeks:
        days = pd.date_range(mon, periods=7).strftime("%Y-%m-%d").tolist()
        truth = close[close.day.isin(days)].dropna(subset=["weekly_rank"]).sort_values("weekly_rank").id.tolist()
        Gt = G[G.week != mon]
        f = Gt.groupby(["age", "band"]).g.median(); fa = Gt.groupby("age").g.median()
        fac = lambda age, b: float(f.get((age, b), fa.get(age, 1.0))) if age <= 7 else 1.0
        for D in days[:-1]:
            rd = [(t, p) for t, p in P if end(D) <= t <= end(D) + pd.Timedelta(hours=8)]
            if not rd:
                continue
            t, p = rd[0]; S = p[p.day.isin([d for d in days if d <= D]) & p.daily_rank.notna()].dropna(subset=["votes"]).copy()
            left = (pd.Timestamp(days[-1]) - pd.Timestamp(D)).days
            S["age"] = [(pd.Timestamp(D) - pd.Timestamp(d)).days for d in S.day]
            S["mult"] = [np.prod([fac(a + k, band(r)) for k in range(1, left + 1)]) for a, r in zip(S.age, S.daily_rank)]
            S["est"] = S.votes * S.mult
            ent = []
            for k, d in enumerate(days[days.index(D) + 1:]):
                wd = pd.Timestamp(d).dayofweek; rem = (pd.Timestamp(days[-1]) - pd.Timestamp(d)).days
                for r in (1, 2, 3):
                    v = float(TAB.get((wd, r), np.nan))
                    if v == v:   # final votes already include growth to about the close; no extra factor
                        ent.append({"id": f"_new_{d}_{r}", "est": v})
            E = pd.concat([S[["id", "est"]], pd.DataFrame(ent)]) if ent else S[["id", "est"]]
            lists = {"running": S.sort_values("votes", ascending=False).id.tolist(),
                     "running_g": S.sort_values("est", ascending=False).id.tolist(),
                     "running_g_e": E.sort_values("est", ascending=False).id.tolist()}
            r_ = {"week": mon, "asof": D, "weekday": pd.Timestamp(D).day_name()[:3], "days_left": left, "read_pt": t.tz_convert(TZ).strftime("%m-%d %H:%M")}
            for nm, o in lists.items():
                for k in (3, 5, 10):
                    r_[f"{nm}_top{k}"] = len(set(o[:k]) & set(truth[:k]))
            r_["entrants_in_top10"] = sum(1 for i in lists["running_g_e"][:10] if i.startswith("_new_"))
            r_["reach10"] = len(set(truth[:10]) & set(S.id))
            res.append(r_)
    X = pd.DataFrame(res)
    md = ["# Weekly running rank vs growth-adjusted running votes (leave-one-week-out)", "",
          f"Weeks with a close read: {', '.join(w for w, _ in weeks)}; growth pairs: {len(G)} launch-days from {len(pairs)} consecutive nightly reads.",
          "Truth = weekly_rank at the first full-refresh read after Sunday's close. Hits out of 3 / 5 / 10. reach10 = final top 10 already launched.", "",
          X.to_string(index=False), "",
          "Totals (sum of hits over as-of points): " + ", ".join(f"{nm} {int(X[f'{nm}_top3'].sum())}/{int(X[f'{nm}_top5'].sum())}/{int(X[f'{nm}_top10'].sum())}"
                                                             for nm in ("running", "running_g", "running_g_e")),
          "", "Median daily growth by age (all pairs): " + ", ".join(f"{a}: x{v:.3f}" for a, v in G.groupby("age").g.median().items())]
    open(os.path.join(HERE, "results", "weekly_growth.md"), "w").write("\n".join(md) + "\n")
    json.dump({"rows": res, "growth_by_age": G.groupby("age").g.median().round(4).to_dict()}, open(os.path.join(HERE, "results", "weekly_growth.json"), "w"), indent=1)
    print("\n".join(md))


if __name__ == "__main__":
    main()
