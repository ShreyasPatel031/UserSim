"""PRE-REGISTERED test of off-HN traction (written and committed 2026-11-04 ~16:40 UTC, before any backfill row exists).

Data (Data Feeder backfill): for each HN story with a URL, Jul 1 - Oct 14 2026, same-URL items on Reddit (Arctic Shift) and
Bluesky with created_at in [HN post - 72 h, HN post + 60 min]. Path: env OFFHN_PATH (a bucket prefix of jsonl files);
expected fields per item: post_id (HN), source ("reddit" | "bluesky"), created_at (UTC), and counts when present
(reddit: score, num_comments, subreddit; bluesky: like_count, repost_count).

Inputs, fixed now (only items created strictly before the checkpoint time; nothing after can enter):
  at posting (t < HN post time):  pre_reddit_n, pre_bsky_n, pre_any, pre_subreddits, pre_reddit_score_max,
                                  pre_reddit_comments_sum, pre_bsky_engagement (likes + reposts), pre_first_h (hours
                                  from the first outside item to the HN post; -1 if none)
  at 15 min (t <= HN post + 15 min): the same eight, window extended to post + 15 min (suffix _15)

Endpoints, fixed now:
  PRIMARY: Caught at posting on Oct 2 - 14 (scored once): the headline 3-way blend (Jul-Aug model + 2025+ history +
    content large; equal weights) vs the same with the Jul-Aug model given the at-posting inputs. Paired by day.
  SECONDARY: (a) the same on Sep 1 - Oct 14; (b) 15 min: the light model (2025 + 2026 rows + content, forward daily
    retrain) + the _15 inputs, Oct 2 - 14, vs the light model and vs the 29.6% headline; (c) counts of late risers and
    re-ups caught; (d) coverage: share of test posts / winners with any outside item before posting.
Decision rule, fixed now: adopt if the PRIMARY paired interval's lower bound is above 0; otherwise drop (the secondary
endpoints are reported, not used to decide). The 2025 rows have no backfill, so the 15-min light model sees NaN for them.

    OFFHN_PATH=usersim_sim/raw/<backfill prefix>/ python offhn_test.py
"""
import io
import os
import sys

import numpy as np
import pandas as pd

import caught as C
import content_ft as CF
import store as S
import top100 as H
import wb_caught as W

PRE = ["pre_reddit_n", "pre_bsky_n", "pre_any", "pre_subreddits", "pre_reddit_score_max", "pre_reddit_comments_sum",
       "pre_bsky_engagement", "pre_first_h"]


def load_items():
    path = os.environ.get("OFFHN_PATH")
    if not path:
        sys.exit("set OFFHN_PATH to the backfill's bucket prefix (pre-registered test; data not landed yet)")
    parts = []
    for x in S._bucket().list_blobs(prefix=path):
        if x.name.endswith(".jsonl"):
            parts.append(pd.read_json(io.StringIO(x.download_as_text()), lines=True))
    if not parts:
        sys.exit(f"no jsonl under {path}")
    A = pd.concat(parts, ignore_index=True)
    A["t"] = (pd.to_datetime(A.created_at, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    return A


def feats(A, born, cutoff_s, suffix=""):
    """The eight inputs per HN post from items created strictly before born + cutoff_s."""
    A = A[A.post_id.isin(born.index)].copy()
    A = A[A.t < A.post_id.map(born) + cutoff_s]
    r, bs = A[A.source == "reddit"], A[A.source == "bluesky"]
    F = pd.DataFrame(index=born.index)
    F["pre_reddit_n"] = r.groupby("post_id").size()
    F["pre_bsky_n"] = bs.groupby("post_id").size()
    F["pre_subreddits"] = r.groupby("post_id").subreddit.nunique() if "subreddit" in r else np.nan
    F["pre_reddit_score_max"] = r.groupby("post_id").score.max() if "score" in r else np.nan
    F["pre_reddit_comments_sum"] = r.groupby("post_id").num_comments.sum() if "num_comments" in r else np.nan
    eng = bs.get("like_count", 0) + bs.get("repost_count", 0) if len(bs) else pd.Series(dtype=float)
    F["pre_bsky_engagement"] = bs.assign(e=eng).groupby("post_id").e.sum() if len(bs) else np.nan
    first = A.groupby("post_id").t.min()
    F["pre_first_h"] = ((born - first.reindex(born.index)) / 3600).where(first.reindex(born.index).notna(), -1)
    for c in ["pre_reddit_n", "pre_bsky_n", "pre_subreddits", "pre_reddit_comments_sum", "pre_bsky_engagement"]:
        F[c] = F[c].fillna(0)
    F["pre_any"] = ((F.pre_reddit_n + F.pre_bsky_n) > 0).astype(int)
    return F[PRE].add_suffix(suffix)


def main():
    A = load_items()
    Q = C.Q
    born = Q.set_index("post_id").created_at_i
    F0 = feats(A, born, 0).reindex(Q.post_id).reset_index(drop=True)
    rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    kind = CF.kinds(Q)[C.te]
    w = T.y.to_numpy() == 1
    anyp = F0.pre_any.to_numpy()[C.te] == 1
    print(f"(d) coverage: test posts with an outside item before posting {anyp.mean():.1%}, winners {anyp[w].mean():.1%}; "
          + ", ".join(f"{t} {int((anyp & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup")), flush=True)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    ca = T.post_id.map(pd.read_parquet(os.path.join(H.CACHE, "content_scores_large_aug30.parquet")).drop_duplicates("post_id").set_index("post_id").s).fillna(-99).to_numpy()
    base = C.model(C.POST + C.KNN + C.EMB + C.CROWD)
    withx = C.model(C.POST + C.KNN + C.EMB + C.CROWD, extra=F0)
    s0, s1 = (rk(base) + rk(h) + rk(ca)) / 3, (rk(withx) + rk(h) + rk(ca)) / 3
    oct_ = (T.day >= "2026-10-02").to_numpy()
    d0, d1 = C.caught(s0, oct_), C.caught(s1, oct_)
    print(f"PRIMARY  at posting, Oct 2 - 14: {W.ci2(d0)} -> {W.ci2(d1)}, paired {W.ci2(d1, d0)}", flush=True)
    c0, c1 = C.caught(s0), C.caught(s1)
    print(f"(a) at posting, Sep 1 - Oct 14: {W.ci2(c0)} -> {W.ci2(c1)}, paired {W.ci2(c1, c0)}", flush=True)
    k = int(T.y.sum())
    for name, s in (("headline", s0), ("+ off-HN", s1)):
        fl = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
        print(f"(c) {name}: late risers {int((fl & (kind == 'late')).sum())}/{int((kind == 'late').sum())}, "
              f"re-ups {int((fl & (kind == 'reup')).sum())}/{int((kind == 'reup').sum())}", flush=True)
    F15 = feats(A, born, 900, "_15")
    F15.reset_index().rename(columns={"index": "post_id"}).to_parquet(os.path.join(H.CACHE, "offhn_feats15.parquet"), index=False)
    print("(b) 15-min inputs saved to offhn_feats15.parquet; run wb25_train.py with OFFHN=1 for the 15-min endpoint", flush=True)


if __name__ == "__main__":
    main()
