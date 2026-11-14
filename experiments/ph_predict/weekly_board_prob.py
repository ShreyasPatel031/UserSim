"""Probabilistic insertion for the running weekly / monthly board (orchestrator 14:33Z Nov 14). Held data only; counts only.

Same boards and truth as weekly_board_pred.py (b1e4f767). For each board day D (right after D's 00:05 forecast):
  (a)  votes-only: launches of days < D by stored votes
  (b)  point insertion: + D's line-up at month-forward calibrated arm-2 predicted votes (the adopted rule)
  (p)  probabilistic: simulate final period votes N times: days < D at their stored votes; D's launches at calibrated prediction + a
       residual drawn from the AS-OF residual pool (calibrated residuals of months < D's month, by within-day predicted-rank band
       1-3 / 4-10 / 11+; empirical, so heavy tails are kept); order candidates by P(in final top k), a separate order per k
  (pf) as (p) plus the period's not-yet-launched days: for each remaining day, a phantom line-up = the votes of a random earlier day
       (< D, same weekday, as-of) - they compete for top-k slots but can never be picked
Scored on weeks from May 4 (April has no earlier month for residuals): hits = |board top k ∩ true top k| / k by weekday of D, paired
week bootstrap 95% of (p)-(b), (pf)-(b). Calibration of P(top k) for D's launches: reliability table vs actual weekly top k.
usage: python3 weekly_board_prob.py <X.parquet> <L.parquet> <out.md> [N sims]"""
import json, sys
import numpy as np, pandas as pd

X = pd.read_parquet(sys.argv[1])[["id", "both"]]; X["id"] = X.id.astype(str)
L = pd.read_parquet(sys.argv[2]); L["id"] = L.id.astype(str); OUT = sys.argv[3]; NS = int(sys.argv[4]) if len(sys.argv) > 4 else 400
L = L.merge(X, on="id", how="left"); L["mon"] = L.day.str[:7]
for c in ("votes", "weekly_rank", "monthly_rank"): L[c] = pd.to_numeric(L[c], errors="coerce")
L["lv"] = np.log1p(L.votes)
L["cal"] = np.nan; RES = {}
for m in sorted(L.mon.unique()):
    prev = L[(L.mon < m) & L.both.notna() & (L.mon >= "2026-04")]
    if len(prev) >= 200:
        b, a = np.polyfit(prev.both, prev.lv, 1)
        k = L.mon == m; L.loc[k, "cal"] = a + b * L.loc[k, "both"]
        P = prev.assign(c=a + b * prev.both); P["r"] = P.lv - P.c
        P["band"] = pd.cut(P.groupby("day").c.rank(ascending=False, method="first"), [0, 3, 10, 999], labels=[0, 1, 2]).astype(float).fillna(2).astype(int)
        RES[m] = {bd: P[P.band == bd].r.values for bd in (0, 1, 2)}
L["cal"] = L.cal.fillna(L.groupby("day").cal.transform("median"))
L["band"] = pd.cut(L.groupby("day").cal.rank(ascending=False, method="first"), [0, 3, 10, 999], labels=[0, 1, 2]).astype(float).fillna(2).astype(int)
L["pv"] = np.expm1(L.cal)
L["wk"] = pd.to_datetime(L.day).dt.to_period("W-SUN").apply(lambda p: str(p.start_time.date()))
L["dow"] = pd.to_datetime(L.day).dt.dayofweek
KS = (3, 5, 10); rng = np.random.default_rng(0)
DAYV = {d: g.votes.astype(float).values for d, g in L.groupby("day")}
DOW = {d: pd.Timestamp(d).dayofweek for d in DAYV}


def run(pcol, rcol, periods, pos_fn, end_fn):
    R, CAL = [], []
    for p in periods:
        Z = L[L[pcol] == p]; truth = {k: set(Z[Z[rcol] <= k].id) for k in KS}
        for D in sorted(Z.day.unique()):
            m = D[:7]
            if m not in RES: continue
            prev = Z[Z.day < D]; tod = Z[Z.day == D]
            pv0 = prev.votes.astype(float).values
            cand_ids = list(prev.id) + list(tod.id)
            # simulations of today's votes
            eps = np.column_stack([rng.choice(RES[m][bd], NS) for bd in tod.band.values]) if len(tod) else np.zeros((NS, 0))
            tv = np.expm1(tod.cal.values[None, :] + eps)
            # phantom future days (as-of: random earlier day with the same weekday)
            fut = [str(x.date()) for x in pd.date_range(pd.Timestamp(D) + pd.Timedelta(days=1), end_fn(p, D))]
            pool = {w: [d for d in DAYV if d < D and DOW[d] == w] for w in range(7)}
            out = {"period": p, "day": D, "pos": pos_fn(D)}
            for k in KS:
                pts = {"a": prev.assign(v=pv0).nlargest(k, "v").id.tolist(),
                       "b": pd.concat([prev.assign(v=pv0), tod.assign(v=tod.pv)]).nlargest(k, "v").id.tolist()}
                for var in ("p", "pf"):
                    cnt = np.zeros(len(cand_ids))
                    for s in range(NS):
                        allv = np.concatenate([pv0, tv[s]])
                        if var == "pf" and fut:
                            ph = np.concatenate([DAYV[rng.choice(pool[pd.Timestamp(f).dayofweek])] for f in fut if pool[pd.Timestamp(f).dayofweek]] or [np.array([])])
                            thr = np.sort(np.concatenate([allv, ph]))[::-1][k - 1] if len(allv) + len(ph) >= k else -1
                        else:
                            thr = np.sort(allv)[::-1][k - 1] if len(allv) >= k else -1
                        cnt += allv >= thr
                    pr = cnt / NS
                    order = [cand_ids[i] for i in np.lexsort((-np.r_[pv0, tod.pv.values], -pr))][:k]
                    pts[var] = order
                    if var == "pf":
                        CAL += [{"k": k, "p": float(pr[len(pv0) + j]), "y": float(i in truth[k]), "pos": pos_fn(D)} for j, i in enumerate(tod.id)]
                for n, o in pts.items():
                    out[f"{n}_{k}"] = len(set(o) & truth[k]) / k
            R.append(out)
    return pd.DataFrame(R), pd.DataFrame(CAL)


def boot(R, x, y, B_=4000):
    d = (R[x] - R[y]); dm = d.groupby(R.period).mean(); ps = dm.index.values
    bs = [dm.loc[rng.choice(ps, len(ps))].mean() for _ in range(B_)]
    return round(100 * d.mean(), 1), [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]


weeks = [w for w in sorted(L.wk.unique()) if "2026-05-04" <= w <= "2026-10-19"]
RW, CW = run("wk", "weekly_rank", weeks, lambda d: pd.Timestamp(d).day_name()[:3], lambda p, D: pd.Timestamp(p) + pd.Timedelta(days=6))
months = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
RM, CM = run("mon", "monthly_rank", months, lambda d: f"days {7 * ((int(d[8:]) - 1) // 7) + 1}-{min(7 * ((int(d[8:]) - 1) // 7) + 7, 31)}",
             lambda p, D: pd.Timestamp(p + "-01") + pd.offsets.MonthEnd(0))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
L_ = ["# Weekly / monthly board: probabilistic insertion vs point insertion (held data)", "",
      f"{len(weeks)} weeks (May 4 - Oct 25; April has no earlier month for residuals), {len(RW)} board days, {NS} simulations per day. "
      "(a) votes only, (b) point insertion (adopted), (p) order by P(final top k) with as-of residuals by predicted-rank band, (pf) (p) + "
      "phantom future days. Paired week bootstrap 95%.", "",
      "| D | k | (a) | (b) | (p) | (pf) | (p)-(b) | (pf)-(b) |", "|---|---|---|---|---|---|---|---|"]
dec = {}
for dn in DAYS + ["all"]:
    R = RW if dn == "all" else RW[RW.pos == dn]
    for k in KS:
        m = {n: round(100 * R[f"{n}_{k}"].mean(), 1) for n in ("a", "b", "p", "pf")}
        d1, c1 = boot(R, f"p_{k}", f"b_{k}"); d2, c2 = boot(R, f"pf_{k}", f"b_{k}"); dec[(dn, k)] = (d1, c1, d2, c2)
        L_.append(f"| {dn} | {k} | {m['a']} | {m['b']} | {m['p']} | {m['pf']} | {d1:+} [{c1[0]:+}, {c1[1]:+}] | {d2:+} [{c2[0]:+}, {c2[1]:+}] |")
L_ += ["", "## Calibration of P(final weekly top k) for D's launches ((pf) model)", "", "| k | P bin | n | mean P | actual rate |", "|---|---|---|---|---|"]
for k in KS:
    c = CW[CW.k == k].copy(); c["bin"] = pd.cut(c.p, [-0.01, 0.02, 0.1, 0.25, 0.5, 0.75, 1.0])
    for b, g in c.groupby("bin", observed=True):
        L_.append(f"| {k} | {b} | {len(g)} | {g.p.mean():.3f} | {g.y.mean():.3f} |")
    L_.append(f"| {k} | Brier | {len(c)} | | {((c.p - c.y) ** 2).mean():.4f} |")
L_ += ["", "## Monthly (6 months, indicative)", "", "| D in month | k | (a) | (b) | (p) | (pf) | (pf)-(b) |", "|---|---|---|---|---|---|---|"]
for pn in sorted(RM.pos.unique(), key=lambda s: int(s.split()[1].split("-")[0])) + ["all"]:
    R = RM if pn == "all" else RM[RM.pos == pn]
    for k in KS:
        m = {n: round(100 * R[f"{n}_{k}"].mean(), 1) for n in ("a", "b", "p", "pf")}
        d2, c2 = boot(R, f"pf_{k}", f"b_{k}")
        L_.append(f"| {pn} | {k} | {m['a']} | {m['b']} | {m['p']} | {m['pf']} | {d2:+} [{c2[0]:+}, {c2[1]:+}] |")
clear = [f"{dn} top {k}: (p) {v[0]:+} [{v[1][0]:+}, {v[1][1]:+}]" for (dn, k), v in dec.items() if v[1][0] > 0] + \
        [f"{dn} top {k}: (pf) {v[2]:+} [{v[3][0]:+}, {v[3][1]:+}]" for (dn, k), v in dec.items() if v[3][0] > 0]
worse = [f"{dn} top {k}: (p) {v[0]:+} [{v[1][0]:+}, {v[1][1]:+}]" for (dn, k), v in dec.items() if v[1][1] < 0] + \
        [f"{dn} top {k}: (pf) {v[2]:+} [{v[3][0]:+}, {v[3][1]:+}]" for (dn, k), v in dec.items() if v[3][1] < 0]
L_ += ["", "## Readout", "", "Better than (b) clear of 0: " + ("; ".join(clear) or "none"), "", "Worse than (b) clear of 0: " + ("; ".join(worse) or "none"),
       "", "Leak notes: calibration and residual pools use months < D's month only; phantom future days use days < D; earlier days use stored "
       "final votes (as b1e4f767; the official weekly rank is votes at week close, so this mildly mis-orders earlier days for all variants equally)."]
open(OUT, "w").write("\n".join(L_) + "\n"); RW.to_csv(OUT.replace(".md", "_days.csv"), index=False)
print("\n".join(L_[-6:]))
