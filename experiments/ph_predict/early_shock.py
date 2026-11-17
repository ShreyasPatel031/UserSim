"""Early-vote shock correction: does a launch's first hours of real votes, read against the honest pre-launch prior,
move the daily top 3 / 5 / 10, and does popscore help by predicting how front-loaded a launch's votes are?

Why: E0 (simlab/reports/overnight_1030.md) puts 90.5% of the simulation's error in a per-launch shock shared by the
whole audience. Early votes reveal it, but they are not a random sample: they lean to the team's network. vote_snapshots
holds counts only (no voters), so popscore cannot weight voters. Instead its tie outputs predict the share of a
launch's votes that arrive early, and the shock is read against that.

Per cutoff H (hours since 00:00 Pacific), per launch:
  p = honest prior (results/forecast_<d>.parquet `pred`, log votes, made before results)
  e = log1p(votes in the latest snapshot at or before H)      only where votes are visible (see below)
  m = log1p(comments in the same snapshot)                     always (comment counts are public from hour 0)
  prior                 rank by p
  votes alone           rank by e
  shock                 e_hat = OLS(e ~ 1 + p); s = e - e_hat; score = p + c*s, c = OLS((log1p(final) - p) ~ 1 + s)
  shock + pop           e_hat = OLS(e ~ 1 + p + tie_share + log_reach + pmax) from sim_live/pnx_<d>.json; same c step
  comment shock         the shock model on m instead of e
  comment shock + pop   the same with popscore's inputs
Product Hunt hides vote counts for about the first 4 hours (every launch reads 0 votes until hour 4; Nov 3-10).
A cutoff's vote arms count on a day only if at least VISIBLE of its line-up shows non-zero votes there; the comment
arms cover the hidden hours. A launch missing from the snapshot gets s = 0 (its prior). Fits are leave-one-day-out over
the days where the arm's signal exists. Scored on daily top 3 / 5 / 10 (real top k = final daily_rank <= k); deltas
are paired over the days both arms cover, bootstrap over days.

Clean day: on or after EARLY_FROM (first honest live prior), ranks final for >= 95% of the line-up, prior and popscore
for >= 90%, and a snapshot within (H - 0.85, H + 0.25] covering >= 95% of the line-up for every H up to READY_H
(hour 5 is scored where present but does not decide this).
Waits (prints the status, exits 0) until MIN_DAYS clean days exist.
Inputs are read locally (pipeline VM) or from the bucket (raw/daily/<d>/, uploaded by pipeline.daily s_raw).

usage: python early_shock.py [--write] [--force]
  --write  also append the results to the warehouse table `backtests` (run_file early_shock_<today>)
  --force  run with fewer than MIN_DAYS clean days (for checking the code; numbers are not a result)
Outputs: results/early_shock/early_shock_<today>.json and .md"""
import datetime as dt, json, os, subprocess, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE)
sys.path.insert(0, EXP)
EARLY_FROM = os.environ.get("EARLY_FROM", "2026-11-03")   # first day of the honest live forecast (HONEST=1 deployed Nov 2)
MIN_DAYS = int(os.environ.get("EARLY_MIN_DAYS", "14"))
CUTOFFS = [1, 2, 3, 4, 5, 6, 8, 12]
READY_H = int(os.environ.get("EARLY_READY_H", "8"))          # a day counts as clean if usable at every cutoff up to this
READY_SKIP = {5}                                            # extra cutoffs that never decide whether a day is clean
KS = (3, 5, 10)
LATE, EARLY = 0.25, 0.85                                    # snapshot for cutoff H: hours_since_start in (H - EARLY, H + LATE]
COVER, INPUT_COVER, RANK_COVER = 0.95, 0.90, 0.95
VISIBLE = 0.5                                               # votes count as visible at H if >= this share of launches > 0
POP = ["tie_share", "log_reach", "pmax"]
ARMS = {   # model -> (signal column prefix, uses popscore); "prior" and "votes alone" are scored directly
    "shock": ("e", False), "shock + pop": ("e", True), "comment shock": ("m", False), "comment shock + pop": ("m", True)}
MODELS = ["prior", "votes alone"] + list(ARMS)
DELTAS = [("votes alone", "prior"), ("shock", "prior"), ("shock + pop", "prior"), ("shock + pop", "shock"),
          ("comment shock", "prior"), ("comment shock + pop", "prior"), ("comment shock + pop", "comment shock"),
          ("shock", "comment shock")]
OUT = os.path.join(HERE, "results", "early_shock")
CACHE = os.path.join(OUT, "inputs")
BUCKET = os.environ.get("USERSIM_BUCKET", "gs://usersim-bakeoff-347838016394/usersim_sim")


def _fetch(name, d, local):
    """A per-day input: the local file if present (pipeline VM), else the copy s_raw uploaded to the bucket."""
    if os.path.exists(local):
        return local
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, name)
    if not os.path.exists(dst):
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/daily/{d}/{name}", dst], capture_output=True)
    return dst if os.path.exists(dst) else None


def prior(d):
    f = _fetch(f"forecast_{d}.parquet", d, os.path.join(HERE, "results", f"forecast_{d}.parquet"))
    if not f:
        return None
    P = pd.read_parquet(f)
    return pd.Series(P.pred.values, index=P.id.astype(str))


def popscore(d):
    f = _fetch(f"pnx_{d}.json", d, os.path.join(HERE, "data", "sim_live", f"pnx_{d}.json"))
    if not f:
        return None
    J = json.load(open(f))
    X = pd.DataFrame.from_dict(J, orient="index")
    X.index = X.index.astype(str)
    ev = X.get("pnx_ev", pd.Series(np.nan, index=X.index)).astype(float)
    ties = X.get("pnx_ev_ties", pd.Series(np.nan, index=X.index)).astype(float)
    return pd.DataFrame({"tie_share": (ties / ev.where(ev > 0)).clip(0, 1),
                         "log_reach": np.log1p(X.get("pnx_reach", pd.Series(np.nan, index=X.index)).astype(float)),
                         "pmax": X.get("pnx_pmax", pd.Series(np.nan, index=X.index)).astype(float)})


def finals(day_from):
    from pipeline import warehouse as W
    L = W.query(f"SELECT id, day, daily_rank, votes, updated_at FROM launches WHERE day >= '{day_from}'")
    L["id"] = L.id.astype(str)
    return L.sort_values("updated_at").drop_duplicates("id", keep="last")   # snapshot table: newest row per launch


def snapshots(day_from):
    from pipeline import snapshots as SN
    return SN.load(day_from=day_from)


def snap_at(S_d, h):
    """Votes and comments per launch from the latest snapshot in (h - EARLY, h + LATE]; None if the day has none there."""
    w = S_d[(S_d.hours_since_start > h - EARLY) & (S_d.hours_since_start <= h + LATE)]
    if not len(w):
        return None
    last = w[w["at"] == w["at"].max()]
    return pd.DataFrame({"votes": last.votes.astype(float).values, "comments": last.comments.astype(float).values},
                        index=last.launch_id.astype(str))


def day_frame(d, L_d, S_d, P, X):
    """One row per ranked launch of day d with p, final votes, rank, popscore inputs, m_H per usable cutoff and e_H
    where votes are visible, or (None, reason)."""
    if len(L_d) < 5:
        return None, "fewer than 5 launches"
    ranked = L_d[L_d.daily_rank.notna()]
    if len(ranked) < RANK_COVER * len(L_d):
        return None, f"ranks not final ({len(ranked)} of {len(L_d)})"
    if P is None or P.reindex(ranked.id).notna().mean() < INPUT_COVER:
        return None, "no honest prior" if P is None else "honest prior covers < 90%"
    if X is None or X.reindex(ranked.id).notna().any(axis=1).mean() < INPUT_COVER:
        return None, "no popscore" if X is None else "popscore covers < 90%"
    D = pd.DataFrame({"id": ranked.id.values, "day": d, "rank": ranked.daily_rank.astype(float).values,
                      "y": np.log1p(ranked.votes.astype(float).values)})
    D["p"] = P.reindex(D.id).values
    D = D[D.p.notna()].reset_index(drop=True)
    D = D.join(X.reindex(D.id).reset_index(drop=True))
    usable = []
    for h in CUTOFFS:
        v = snap_at(S_d, h)
        if v is None or v.votes.reindex(D.id).notna().mean() < COVER:
            continue
        v = v.reindex(D.id)
        D[f"m{h}"] = np.log1p(v.comments.values)
        if (v.votes.fillna(0) > 0).mean() >= VISIBLE:   # Product Hunt shows 0 votes for everyone while counts are hidden
            D[f"e{h}"] = np.log1p(v.votes.values)
        usable.append(h)
    if not all(h in usable for h in CUTOFFS if h <= READY_H and h not in READY_SKIP):
        return None, f"snapshots missing or thin before hour {READY_H} (usable: {usable})"
    return D, "clean"


def _ols(X, y):
    X = np.column_stack([np.ones(len(X)), X]) if X.size else np.ones((len(y), 1))
    ok = np.isfinite(X).all(1) & np.isfinite(y)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    return beta


def _pred(X, beta):
    X = np.column_stack([np.ones(len(X)), X]) if X.size else np.ones((len(X), 1))
    return X @ beta


def _pop_matrix(T, cols, fill):
    return T[cols].astype(float).fillna(fill).values


def scores(train, test, e, use_pop):
    """Leave-one-day-out shock model on signal column `e` (votes or comments at a cutoff): fit on `train`, score `test`."""
    cols = ["p"] + (POP if use_pop else [])
    fill = train[POP].astype(float).median() if use_pop else None
    Xtr = train[["p"]].values if not use_pop else np.column_stack([train[["p"]].values, _pop_matrix(train, POP, fill)])
    Xte = test[["p"]].values if not use_pop else np.column_stack([test[["p"]].values, _pop_matrix(test, POP, fill)])
    b = _ols(Xtr, train[e].values)
    s_tr = train[e].values - _pred(Xtr, b)
    c = _ols(np.nan_to_num(s_tr)[:, None], (train.y - train.p).values)[1]
    s_te = test[e].values - _pred(Xte, b)
    return test.p.values + c * np.nan_to_num(s_te), {"c": float(c), "beta": [float(x) for x in b], "cols": cols}


def recall(day_df, score, k):
    real = set(day_df.id[day_df["rank"] <= k])
    if not real:
        return np.nan
    order = day_df.assign(s=score + np.random.default_rng(0).random(len(day_df)) * 1e-9).sort_values("s", ascending=False)
    return len(set(order.id[:k]) & real) / k


def boot(a, b, n=2000):
    d = np.asarray(a) - np.asarray(b); d = d[np.isfinite(d)]
    if not len(d):
        return [np.nan, np.nan, np.nan]
    rng = np.random.default_rng(1)
    m = rng.choice(d, (n, len(d))).mean(1)
    return [round(100 * d.mean(), 1), round(100 * np.percentile(m, 2.5), 1), round(100 * np.percentile(m, 97.5), 1)]


def collect():
    """All candidate days since EARLY_FROM: the clean frames and the reason each other day is excluded."""
    L = finals(EARLY_FROM); S = snapshots(EARLY_FROM)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    frames, excluded = {}, {}
    for d in sorted(set(L.day.astype(str))):
        if d >= today:
            continue
        D, why = day_frame(d, L[L.day.astype(str) == d], S[S.day.astype(str) == d], prior(d), popscore(d))
        if D is None:
            excluded[d] = why
        else:
            frames[d] = D
    return frames, excluded


def run(frames):
    days = sorted(frames)
    res = {}
    for h in CUTOFFS:
        hd = [d for d in days if f"m{h}" in frames[d]]          # days with a usable snapshot at h
        if len(hd) < 3:
            continue
        per = {m: {k: {} for k in KS} for m in MODELS}          # model -> k -> {day: recall}
        coef = {}
        for d in hd:
            test = frames[d]
            sc = {"prior": test.p.values}
            if f"e{h}" in test:
                sc["votes alone"] = np.nan_to_num(test[f"e{h}"].values, nan=-1) + 1e-6 * test.p.values
            for m, (sig, pop) in ARMS.items():
                col = f"{sig}{h}"
                others = [x for x in hd if x != d and col in frames[x]]
                if col not in test or len(others) < 2:
                    continue
                train = pd.concat([frames[x] for x in others], ignore_index=True)
                sc[m], coef[m] = scores(train, test, col, pop)
            for m, v in sc.items():
                for k in KS:
                    per[m][k][d] = recall(test, v, k)
        def mean(m, k):
            x = list(per[m][k].values())
            return round(100 * float(np.nanmean(x)), 1) if x else None
        def delta(a, b, k):
            both = sorted(set(per[a][k]) & set(per[b][k]))
            return boot([per[a][k][d] for d in both], [per[b][k][d] for d in both]) + [len(both)] if len(both) >= 3 else None
        res[h] = {"days": len(hd), "days_by_model": {m: len(per[m][KS[0]]) for m in MODELS},
                  "recall": {m: {k: mean(m, k) for k in KS} for m in MODELS},
                  "delta": {f"{a} - {b}": {k: delta(a, b, k) for k in KS} for a, b in DELTAS},
                  "coef_last": coef}
    return res


def report(status, res):
    fmt = lambda v: "n/a" if v is None else str(v)
    L = [f"# Early-vote shock correction ({status['run_on']}; {status['clean_days']} clean days, "
         f"{status['first']} to {status['last']}; leave-one-day-out)", "",
         "Daily top 3 / 5 / 10. Δ with 95% CI (paired bootstrap over the days both arms cover). Vote arms are n/a where "
         "Product Hunt still hides vote counts (about the first 4 hours).", ""]
    for h, r in res.items():
        L += [f"## Hour {h} ({r['days']} days)", "", "| Model | Days | Top 3 / 5 / 10 |", "|---|---|---|"]
        L += [f"| {m} | {r['days_by_model'][m]} | {' / '.join(fmt(r['recall'][m][k]) for k in KS)} |" for m in MODELS]
        L += ["", "| Δ | Days | Top 3 | Top 5 | Top 10 |", "|---|---|---|---|---|"]
        for n, by_k in r["delta"].items():
            if by_k[KS[0]] is None:
                continue
            L.append(f"| {n} | {by_k[KS[0]][3]} | " + " | ".join(f"{v[0]:+} ({v[1]:+} to {v[2]:+})" for v in (by_k[k] for k in KS)) + " |")
        L.append("")
    if status["excluded"]:
        L += ["## Excluded days", ""] + [f"- {d}: {w}" for d, w in status["excluded"].items()]
    return "\n".join(L) + "\n"


def main(argv):
    frames, excluded = collect()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    status = {"run_on": today, "ready": len(frames) >= MIN_DAYS, "clean_days": len(frames), "needed": MIN_DAYS,
              "first": min(frames) if frames else None, "last": max(frames) if frames else None, "excluded": excluded}
    print(json.dumps({"early_shock": status}), flush=True)
    if not status["ready"] and "--force" not in argv:
        return status
    res = run(frames) if len(frames) >= 3 else {}
    os.makedirs(OUT, exist_ok=True)
    tag = today + ("_forced" if not status["ready"] else "")
    json.dump({"status": status, "results": res}, open(os.path.join(OUT, f"early_shock_{tag}.json"), "w"), indent=1, default=str)
    open(os.path.join(OUT, f"early_shock_{tag}.md"), "w").write(report(status, res))
    print(report(status, res), flush=True)
    if "--write" in argv and status["ready"] and res:
        from pipeline import warehouse as W
        rows = [{"run_file": f"early_shock_{today}", "run_on": today, "variant": f"{m} H{h}", "list": f"day@{k}",
                 "recall": r["recall"][m][k], "seeds": 0, "months": f"{status['first']}..{status['last']}",
                 "lists": r["days_by_model"][m]}
                for h, r in res.items() for m in MODELS for k in KS if r["recall"][m][k] is not None]
        W.write("backtests", pd.DataFrame(rows))
    status["results"] = len(res)
    return status


if __name__ == "__main__":
    main(sys.argv[1:])
