"""Quality check for Data Feeder's continuous launch-day capture (spec: mailbox/to_grokbot/20261103T1945_ph_live_capture_spec.md).
Reads raw/ph_at_launch/<day>/live/{posts,comments,board,people,products,coverage}_ts.jsonl (local dir or gs://) and checks:
  schema       required columns per file (missing file = FAIL for posts / coverage, WARN for the others)
  clock        every row: |fetched_at - snapshot_ts| <= 5 min (FETCH_TOL_MIN)
  coverage     per snapshot: >= 95% of the day's launches fetched with status 200 (expected = coverage_ts
               launches_expected, else the distinct launch_ids seen that day)
  votes        votes_at_fetch non-decreasing per launch across snapshots; drops are listed (WARN: PH removes votes)
  comments     usernames present and parseable; created_at <= fetched_at (+1 min) and on/after the day start - 1 day
  board        every snapshot's board lists every launch fetched in that snapshot, each with a position
  gaps         consecutive snapshot_ts more than 20 min apart (GAP_MIN), listed
Output: one line "PASS|FAIL live capture <day>: ..." with counts, and a JSON status (STATUS_OUT, default per day
results/live_capture_status_<day>.json). No usernames are printed or written: counts only.
usage: python live_capture_check.py <day> [<live dir, default gs://.../raw/ph_at_launch/<day>/live>]"""
import glob, json, os, re, subprocess, sys, tempfile
import pandas as pd

BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim"
FETCH_TOL_MIN = float(os.environ.get("FETCH_TOL_MIN", "5"))
GAP_MIN = float(os.environ.get("GAP_MIN", "20"))
COVER = float(os.environ.get("COVER", "0.95"))
FALLBACK = {"box_browser"}   # page-view fallback sources, not the snapshot loop
NEED = {
    "posts": ["snapshot_id", "snapshot_ts", "fetched_at", "day", "launch_id", "slug", "fetch_status", "votes_at_fetch"],
    "comments": ["snapshot_ts", "fetched_at", "launch_id", "comment_id", "username", "created_at"],
    "board": ["snapshot_ts", "fetched_at", "slug"],
    "people": ["snapshot_ts", "fetched_at", "username"],
    "products": ["snapshot_ts", "fetched_at", "slug"],
    "coverage": ["snapshot_id", "snapshot_ts", "launches_expected", "fetched_200"],
}
REQUIRED = {"posts", "coverage"}
USER = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def load(src):
    if src.startswith("gs://"):
        d = tempfile.mkdtemp(prefix="live_")
        for f in NEED:
            subprocess.run(["gsutil", "-q", "cp", f"{src.rstrip('/')}/{f}_ts.jsonl", d], capture_output=True)
        src = d
    out = {}
    for f in NEED:
        p = os.path.join(src, f"{f}_ts.jsonl")
        out[f] = pd.read_json(p, lines=True, dtype=False) if os.path.exists(p) and os.path.getsize(p) else None
    return out


def ts(s):
    return pd.to_datetime(s, utc=True, errors="coerce", format="ISO8601")


def check(day, T):
    fail, warn, n = [], [], {}
    for f, cols in NEED.items():
        D = T[f]
        if D is None:
            (fail if f in REQUIRED else warn).append(f"{f}_ts.jsonl missing"); continue
        miss = [c for c in cols if c not in D.columns]
        if miss:
            (fail if f in REQUIRED else warn).append(f"{f}: missing columns {miss}")
        n[f] = len(D)
        if {"snapshot_ts", "fetched_at"} <= set(D.columns):
            st, fa = ts(D.snapshot_ts), ts(D.fetched_at)
            bad_parse = int((st.isna() | fa.isna()).sum())
            off = ((fa - st).abs() > pd.Timedelta(minutes=FETCH_TOL_MIN)).sum()
            if bad_parse:
                fail.append(f"{f}: {bad_parse} rows with unparseable snapshot_ts/fetched_at")
            if off:
                fail.append(f"{f}: {int(off)} rows with fetched_at more than {FETCH_TOL_MIN:g} min from snapshot_ts")
    P, C, B, V = T["posts"], T["comments"], T["board"], T["coverage"]
    snaps = []
    if P is not None and {"snapshot_ts", "launch_id", "fetch_status"} <= set(P.columns):
        P = P.assign(launch_id=P.launch_id.astype(str), st=ts(P.snapshot_ts), ok=P.fetch_status.astype(str).isin(["200", "ok"]))
        # fallback page views (source box_browser, Nov 4 on) stamp each page with its own snapshot_ts: one launch per
        # "snapshot". Coverage, gaps and board positions are judged on the snapshot loop; fallback rows are counted apart.
        if "source" in P.columns:
            fb = P.source.astype(str).isin(FALLBACK)
            n["fallback_post_rows"] = int(fb.sum()); P = P[~fb]
        exp_n = P.launch_id.nunique()
        expected = {}
        if V is not None and {"snapshot_ts", "launches_expected"} <= set(V.columns):
            expected = dict(zip(ts(V.snapshot_ts), pd.to_numeric(V.launches_expected, errors="coerce")))
        low = []
        for s, g in P.groupby("st"):
            e = expected.get(s) or exp_n
            # launches PH stopped listing (unfeatured: fetch_status absent_from_source) are not expected in that snapshot
            e -= g[g.fetch_status.astype(str) == "absent_from_source"].launch_id.nunique()
            share = g[g.ok].launch_id.nunique() / e if e else 0
            snaps.append(s)
            if share < COVER:
                low.append(f"{s:%H:%M}Z {share:.0%}")
        n["snapshots"] = len(snaps); n["launches"] = exp_n
        key = ["snapshot_ts", "launch_id"] + (["source"] if "source" in P.columns else [])
        dup = int(P.duplicated(key).sum())
        if dup:
            warn.append(f"posts: {dup} duplicate rows per (snapshot, launch, source)")
        if "hide_votes_count" in P.columns and P.hide_votes_count.isna().all():
            warn.append("posts: hide_votes_count empty on every row")
        if low:
            fail.append(f"{len(low)} snapshots under {COVER:.0%} fetched 200: {', '.join(low[:6])}")
        if "votes_at_fetch" in P.columns:
            Q = P[P.ok].assign(v=pd.to_numeric(P.votes_at_fetch, errors="coerce")).sort_values("st")
            if "hide_votes_count" in Q.columns:   # hidden counts show 0: only compare visible ones
                Q = Q[~Q.hide_votes_count.fillna(False).astype(bool)]
            drops = Q.groupby("launch_id").v.apply(lambda s: int((s.diff() < 0).sum()))
            if drops.sum():
                warn.append(f"votes dropped between snapshots: {int(drops.sum())} times on {int((drops > 0).sum())} launches")
            n["vote_drops"] = int(drops.sum())
        snaps = sorted(set(snaps))
        gaps = [f"{a:%H:%M}-{b:%H:%M}Z" for a, b in zip(snaps, snaps[1:]) if (b - a) > pd.Timedelta(minutes=GAP_MIN)]
        if gaps:
            fail.append(f"{len(gaps)} snapshot gaps > {GAP_MIN:g} min: {', '.join(gaps[:6])}")
        # trailing gap (orchestrator, Nov 5 01:34Z: capture stopped at 00:30Z and the between-snapshot check missed it):
        # while the day's capture should be running (launch day + 7 days), the newest snapshot must be <= GAP_MIN old
        now = pd.Timestamp.now(tz="UTC")
        end = pd.Timestamp(f"{day} 00:00", tz="America/Los_Angeles").tz_convert("UTC") + pd.Timedelta(days=8)
        if snaps and now < end and (now - snaps[-1]) > pd.Timedelta(minutes=GAP_MIN):
            fail.append(f"capture stale: no snapshot since {snaps[-1]:%H:%M}Z ({(now - snaps[-1]).total_seconds() / 60:.0f} min)")
        if B is not None and {"snapshot_ts", "slug"} <= set(B.columns):
            pos = next((c for c in ("position", "board_position", "homepage_position") if c in B.columns), None)
            if pos is None:
                fail.append("board: no position column")
            Bt = B.assign(st=ts(B.snapshot_ts))
            if "is_page_view" in Bt.columns:   # page=api_v2_ranking is the API's order, not what visitors see
                n["board_api_rows"] = int((~Bt.is_page_view.fillna(False).astype(bool)).sum())
                Bt = Bt[Bt.is_page_view.fillna(False).astype(bool)]
                if not len(Bt):
                    fail.append("board: no homepage / leaderboard page views (only the API ranking)")
            missing_board = 0
            for s, g in (P[P.ok].groupby("st") if len(Bt) else []):
                b = Bt[Bt.st == s]
                have = set(b.slug.astype(str)) if pos is None else set(b[b[pos].notna()].slug.astype(str))
                missing_board += len(set(g.slug.astype(str)) - have)
            n["board_missing"] = missing_board
            if missing_board:
                fail.append(f"board: {missing_board} launch-snapshots without a board position")
    if C is not None and {"username", "created_at", "fetched_at"} <= set(C.columns):
        u = C.username.astype(str)
        bad_u = int((~u.str.match(USER) | u.str.lower().isin(["", "nan", "none", "[redacted]"])).sum())
        ca, fa = ts(C.created_at), ts(C.fetched_at)
        future = int((ca > fa + pd.Timedelta(minutes=1)).sum()); unparsed = int(ca.isna().sum())
        early = int((ca < pd.Timestamp(day, tz="America/Los_Angeles").tz_convert("UTC") - pd.Timedelta(days=1)).sum())
        n["comments"] = len(C)
        for k, v, msg in (("bad_username", bad_u, "comments: usernames missing or unparseable"), ("created_after_fetch", future, "comments: created_at after fetched_at"),
                          ("created_unparsed", unparsed, "comments: created_at unparseable (relative times?)")):
            n[k] = v
            if v:
                fail.append(f"{msg}: {v}")
        if early:
            warn.append(f"comments: {early} created more than a day before the launch day (old threads?)")
    A = T.get("api_comments")
    if A is not None and len(A):   # API comment pulls (raw/ph_at_launch/<day>/api_comments/): ids, exact times
        n["api_comments"] = int(A.drop_duplicates(["post_id", "comment_id"]).shape[0]) if {"post_id", "comment_id"} <= set(A.columns) else len(A)
        miss = [c for c in ("post_id", "comment_id", "commenter_user_id", "createdAt", "snapshot_at") if c not in A.columns]
        if miss:
            fail.append(f"api_comments: missing columns {miss}")
        else:
            uid = A.commenter_user_id.astype(str)
            no_id = int((~uid.str.fullmatch(r"\d+")).sum())
            late = int((ts(A.createdAt) > ts(A.snapshot_at) + pd.Timedelta(minutes=1)).sum())
            n["api_comments_no_user_id"] = no_id; n["api_comments_created_after_pull"] = late
            if no_id:
                fail.append(f"api_comments: {no_id} rows without a numeric commenter_user_id")
            if late:
                fail.append(f"api_comments: {late} rows created after their pull")
    elif T.get("api_comments") is None:
        warn.append("api_comments/ missing")
    status = "FAIL" if fail else "PASS"
    line = f"{status} live capture {day}: " + ", ".join(f"{k} {v}" for k, v in n.items()) + ("" if not fail else " | FAIL: " + "; ".join(fail)) + ("" if not warn else " | WARN: " + "; ".join(warn))
    return status, line, {"day": day, "status": status, "counts": n, "fail": fail, "warn": warn,
                          "checked_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")}


def load_api_comments(day, src=None):
    """raw/ph_at_launch/<day>/api_comments/*.jsonl (outside live/), or <src>/../api_comments for a local copy."""
    if src and not src.startswith("gs://"):
        files = sorted(glob.glob(os.path.join(os.path.dirname(src.rstrip("/")), "api_comments", "*.jsonl")))
    else:
        d = tempfile.mkdtemp(prefix="apic_")
        subprocess.run(["gsutil", "-q", "-m", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/api_comments/*.jsonl", d], capture_output=True)
        files = sorted(glob.glob(os.path.join(d, "*.jsonl")))
    parts = [pd.read_json(f, lines=True, dtype=False) for f in files if os.path.getsize(f)]
    return pd.concat(parts, ignore_index=True) if parts else None


def main(day, src=None):
    T = load(src or f"{BUCKET}/raw/ph_at_launch/{day}/live")
    T["api_comments"] = load_api_comments(day, src)
    status, line, res = check(day, T)
    out = os.environ.get("STATUS_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", f"live_capture_status_{day}.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, "w"), indent=1)
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(0 if main(*sys.argv[1:3]) == "PASS" else 1)
