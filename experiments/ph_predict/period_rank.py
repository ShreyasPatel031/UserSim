"""What are Product Hunt's weekly / monthly ranks made of beyond votes? (orchestrator 22:40Z Nov 11)
Finding so far: PH's period ranks follow votes almost exactly (Nov 11 read: monthlyRank vs votes Spearman 0.9993) but are
FROZEN / LAGGED: the final monthly rank orders launches by their votes around the period end, while our warehouse votes
were read later (most on Oct 28), so launches late in a period have extra post-period votes. Late-in-month launches are the
ones out-ranked despite more votes (day-of-month 17.3 vs 12.9 among inverted top-15 pairs).

This script learns a period-rank score month-forward from held data and scores the period-end call:
  votes      rank by final (warehouse) votes
  learned    ridge on [log votes, days from launch to period end, days from period end to the votes read (updated_at),
             log votes x those two, log daily rank, weekly-rank percentile within its week] trained on earlier months to
             predict -log(period rank); month-forward
Periods: calendar months (monthly_rank, Jan-Oct) and Mon-Sun weeks (weekly_rank, 44 complete weeks; trained on weeks of
earlier months). Top 3/5/10 vs the final period rank, period-bootstrap 95% intervals.
usage: python period_rank.py -> results/period_rank.json + results/period_rank.md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))


def load():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, votes, daily_rank, weekly_rank, monthly_rank, updated_at FROM launches "
                "WHERE daily_rank IS NOT NULL AND votes IS NOT NULL AND day >= '2026-01-01' AND day < '2026-11-01'", do_sync=False)
    L["d"] = pd.to_datetime(L.day); L["mon"] = L.day.str[:7]; L["wk"] = L.d.dt.to_period("W-SUN").astype(str)
    L["read"] = pd.to_datetime(L.updated_at.str[:10])
    return L


def feats(g, period_end):
    lv = np.log1p(g.votes.astype(float))
    to_end = (period_end - g.d).dt.days.clip(lower=0).astype(float)
    after = (g.read - period_end).dt.days.clip(lower=0).astype(float)
    wpct = g.groupby("wk").weekly_rank.rank(pct=True).fillna(0.5)
    return pd.DataFrame({"lv": lv, "to_end": to_end, "after": np.log1p(after), "lv_to_end": lv * to_end / 30, "lv_after": lv * np.log1p(after),
                         "ldr": np.log(g.daily_rank.astype(float)), "wpct": wpct}, index=g.index)


def run(L, kind):
    from sklearn.linear_model import Ridge
    rk = "monthly_rank" if kind == "month" else "weekly_rank"
    key = "mon" if kind == "month" else "wk"
    X = L.dropna(subset=[rk]).copy()
    if kind == "week":
        X = X[X.groupby("wk").day.transform("nunique") == 7]
        X["end"] = X.d.dt.to_period("W-SUN").dt.end_time.dt.normalize()
    else:
        X["end"] = X.d.dt.to_period("M").dt.end_time.dt.normalize()
    parts = []
    for k_, g in X.groupby(key):
        F = feats(g, g.end.iloc[0]); parts.append(F)
    F = pd.concat(parts).loc[X.index]
    X["y"] = -np.log(X[rk].astype(float)); X["pred"] = np.nan
    mons = sorted(X.mon.unique())
    for m in mons[1:]:
        tr, te = X.mon < m, X.mon == m
        mu, sd = F[tr].mean(), F[tr].std() + 1e-9
        X.loc[te, "pred"] = Ridge(alpha=1.0).fit((F[tr] - mu) / sd, X.y[tr]).predict((F[te] - mu) / sd)
    S = X.dropna(subset=["pred"])
    rows = []
    for k_, g in S.groupby(key):
        truth = g.sort_values(rk).id.tolist()
        r = {"period": k_}
        for nm, c in (("votes", "votes"), ("learned", "pred")):
            o = g.sort_values(c, ascending=False).id.tolist()
            for k in (3, 5, 10):
                r[f"{nm}{k}"] = len(set(o[:k]) & set(truth[:k])) / k * 100
        rows.append(r)
    return pd.DataFrame(rows), X


def boot(v, rng, n=4000):
    v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)]
    return [round(float(v.mean()), 1), round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]


def main():
    rng = np.random.default_rng(0)
    L = load(); res = {}; md = ["# Product Hunt's weekly / monthly rank: votes, frozen at the period end", ""]
    for kind in ("month", "week"):
        R, _ = run(L, kind)
        r = {"periods": int(len(R))}
        for nm in ("votes", "learned"):
            r[nm] = {f"top{k}": boot(R[f"{nm}{k}"], rng) for k in (3, 5, 10)}
        r["learned_minus_votes"] = {f"top{k}": boot(R[f"learned{k}"] - R[f"votes{k}"], rng) for k in (3, 5, 10)}
        res[kind] = r
        md += [f"## {kind} ({len(R)} periods, month-forward)", "", "| scorer | top 3 | top 5 | top 10 |", "|---|---|---|---|"]
        for nm in ("votes", "learned", "learned_minus_votes"):
            md.append(f"| {nm} | " + " | ".join(f"{r[nm][f'top{k}'][0]:+.1f} [{r[nm][f'top{k}'][1]:+.0f}, {r[nm][f'top{k}'][2]:+.0f}]" if nm.endswith("votes") and "minus" in nm
                                                 else f"{r[nm][f'top{k}'][0]:.1f} [{r[nm][f'top{k}'][1]:.0f}, {r[nm][f'top{k}'][2]:.0f}]" for k in (3, 5, 10)) + " |")
        md.append("")
    json.dump(res, open(os.path.join(HERE, "results", "period_rank.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "period_rank.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
