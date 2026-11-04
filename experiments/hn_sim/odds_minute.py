"""Odds every 5 minutes on the per-minute recorder (Shreyas via the orchestrator, 2026-11-04: predict every minute, not
hourly). For every live post of the last 3 hours: P(daily top 30) and P(top 10) at posting, at 15 min, at 1 h and now,
from the odds tool's models (odds_live_content_large.pkl: at-posting inputs + content model + front-page rank so far).

Inputs:
  - at-posting feature rows from the x cache (odds_live.py xcache, every 15 min; each post computed once);
  - front-page position from hn_minute (both recorders, unioned): rank now = the post's position in the last front
    read at or before posting + age (91 if not on pages 1-3), best rank = best position over reads since posting.
    These replace the Quality News 10-minute ranks the models were trained on (same quantities, finer clock).
Output: odds_minute/<day>/<HHMM>.parquet in the bucket, one row per live post per run (post_id, made_at, age_min,
inputs at 15 min / now, probabilities at posting / 15 min / 1 h / now); score_live scores each post's trajectory when
its lists settle.

    python odds_minute.py            # loop every 5 minutes (CADENCE_S to change)
    python odds_minute.py once
"""
import io
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

os.environ.setdefault("ODDS_CONTENT", "1")
os.environ.setdefault("CONTENT_MODEL", "large")
import odds_live as OL  # noqa: E402
import store as S  # noqa: E402

CADENCE_S = int(os.environ.get("CADENCE_S", "300"))
SOURCES = ["usersim_sim/hn_jobs/cache/feeder/vm/hn_minute/", "usersim_sim/hn_jobs/cache/feeder/hn_minute/"]
OUT = "usersim_sim/hn_jobs/cache/odds_minute/"
b = S._bucket()
_lines = {}           # (source, day) -> lines already parsed
_front = []           # parsed front rows (id, t, pos)


def read_minute(now):
    """Front-page reads (id, t, pos) for the last two UTC days from both recorders; only new lines are parsed."""
    days = {time.strftime("%Y-%m-%d", time.gmtime(now - k * 86400)) for k in (0, 1)}
    for pre in SOURCES:
        for d in sorted(days):
            x = b.get_blob(f"{pre}{d}.jsonl")
            if x is None:
                continue
            text = x.download_as_text().splitlines()
            k = (pre, d)
            for line in text[_lines.get(k, 0):]:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("list") == "front":
                    t = int(pd.Timestamp(r["fetched_at"]).timestamp())
                    _front.append((int(r["id"]), t, (int(r["page"]) - 1) * 30 + int(r["rank"])))
            _lines[k] = len(text)
    F = pd.DataFrame(_front, columns=["id", "t", "pos"])
    return F[F.t >= now - 2 * 86400]


def ranks_at(F, reads, post_ids, born, at):
    """rank now and best rank for each post at absolute times `at` (seconds)."""
    g = {pid: grp for pid, grp in F[F.id.isin(set(post_ids))].groupby("id")}
    rn, br = np.full(len(post_ids), 91.0), np.full(len(post_ids), 91.0)
    for i, (pid, b0, t) in enumerate(zip(post_ids, born, at)):
        j = np.searchsorted(reads, t, side="right") - 1
        last = reads[j] if j >= 0 else None
        x = g.get(pid)
        if x is None:
            continue
        seen = x[(x.t >= b0) & (x.t <= t)]
        if len(seen):
            br[i] = seen.pos.min()
        if last is not None and t - last <= 600:
            cur = x[(x.t // 60) == (last // 60)]
            if len(cur):
                rn[i] = cur.pos.min()
    return rn, br


def run_once(M):
    t0 = time.time()
    now = t0
    xb = b.get_blob(OL.XCACHE)
    if xb is None:
        print("no x cache yet", flush=True)
        return
    X = pd.read_parquet(io.BytesIO(xb.download_as_bytes()))
    X = X[X.created_at_i >= now - 3 * 3600].reset_index(drop=True)
    F = read_minute(now)
    reads = np.sort(F.t.unique())
    age = (now - X.created_at_i.to_numpy()) / 60
    out = pd.DataFrame({"post_id": X.post_id.astype("int64"), "made_at": int(now), "age_min": age.round(1)})
    ages = OL.AGES                                      # name -> minutes

    def prob(a, Xa):
        res = {}
        for top in (30, 10):
            m, iso, cols = M["models"][(a, top)]
            res[top] = iso.predict(m.predict_proba(Xa[cols])[:, 1])
        res[10] = np.minimum(res[10], res[30])          # a top-10 post is a top-30 post
        return res

    p0 = prob(0, X)
    out["p30_post"], out["p10_post"] = p0[30], p0[10]
    for a, tag in ((15, "15"), (60, "60")):
        ok = age >= a
        out[f"p30_{tag}"], out[f"p10_{tag}"] = np.nan, np.nan
        if ok.any():
            Xa = X[ok].copy()
            Xa["rank_now"], Xa["best_rank"] = ranks_at(F, reads, Xa.post_id.to_numpy(), Xa.created_at_i.to_numpy(),
                                                       Xa.created_at_i.to_numpy() + a * 60)
            p = prob(a, Xa)
            out.loc[ok, f"p30_{tag}"], out.loc[ok, f"p10_{tag}"] = p[30], p[10]
            if a == 15:
                out.loc[ok, "rank_now_15"], out.loc[ok, "best_rank_15"] = Xa.rank_now.to_numpy(), Xa.best_rank.to_numpy()
    # now: the model for the largest age reached, inputs as of now
    reached = np.array([max([v for v in ages.values() if v <= m_] or [0]) for m_ in age])
    out["model_age_now"] = reached
    rn, br = ranks_at(F, reads, X.post_id.to_numpy(), X.created_at_i.to_numpy(), np.full(len(X), now))
    out["rank_now"], out["best_rank"] = rn, br
    out["p30_now"], out["p10_now"] = np.nan, np.nan
    for a in np.unique(reached):
        sel = reached == a
        Xa = X[sel].copy()
        Xa["rank_now"], Xa["best_rank"] = rn[sel], br[sel]
        p = prob(int(a), Xa)
        out.loc[sel, "p30_now"], out.loc[sel, "p10_now"] = p[30], p[10]
    day, hm = time.strftime("%Y-%m-%d", time.gmtime(now)), time.strftime("%H%M", time.gmtime(now))
    buf = io.BytesIO()
    out.to_parquet(buf, index=False)
    b.blob(f"{OUT}{day}/{hm}.parquet").upload_from_string(buf.getvalue())
    last_read = time.strftime("%H:%M", time.gmtime(reads[-1])) if len(reads) else "none"
    print(f"{time.strftime('%H:%MZ', time.gmtime(now))} {len(out)} posts -> {OUT}{day}/{hm}.parquet in "
          f"{time.time() - t0:.0f}s (last front read {last_read})", flush=True)


def main():
    M = pickle.load(open(OL.MODEL, "rb"))
    if sys.argv[1:] == ["once"]:
        return run_once(M)
    while True:
        t = time.time()
        try:
            run_once(M)
        except Exception as e:                          # keep the loop alive; the next run retries
            print("run failed:", repr(e), flush=True)
        time.sleep(max(5, CADENCE_S - (time.time() - t)))


if __name__ == "__main__":
    main()
